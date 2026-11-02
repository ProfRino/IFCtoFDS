(function (ns) {
    var parser = new ns.fds.FdsNamelistParser();
    var adapter = new ns.fds.FdsGeometryAdapter();
    var ifcAdapter = new ns.ifc.IfcAdapter();
    var webIfcDisplay = ns.ifc.WebIfcDisplay ? new ns.ifc.WebIfcDisplay() : null;
    var exporter = new ns.fds.FdsExporter();
    var state = {
        fdsModel: null,
        ifcModel: null,             // currently displayed (meta until conversion)
        ifcSourceText: null,        // cached decoded STEP text, reused by deferred parse
        ifcFileName: null,
        fullModel: null,            // ifc-adapter heavy parse, lazy
        lastDisplayMeshes: null,
        generatedFdsText: null,
        generatedFdsName: null,
        forceObstStepIds: {},
        excludedStepIds: {},        // IFC elements the user has removed (cascades to all their OBST/GEOM)
        excludedItemIds: {},        // individual OBST/GEOM primitives the user has removed
        undoStack: [],              // history of voxelize/delete actions for Ctrl+Z reversal
        selection: [],
        exportEnabled: false,
        exportBusy: false,
        exportAction: null,
        exportRequestId: 0,
        exportWorker: null,
        exportWorkerUrl: null,
        helpTrigger: null,
        lastAuditReport: null,
        lastManifest: null,
        backendOnline: false,
        currentIfcFile: null
    };

    var els = {};
    var viewer = null;
    var currentTheme = 'light';
    var VIEW_KEY_TO_DIRECTION = {
        '1': 'front',
        '2': 'back',
        '3': 'left',
        '4': 'right',
        '5': 'top',
        '6': 'bottom',
        '0': 'iso'
    };

    document.addEventListener('DOMContentLoaded', function () {
        cacheElements();
        viewer = new ns.viewer.SceneViewer(els.viewer, showSelection);
        viewer.setNavigationModeChangeHandler(updateWalkModeButton);
        applyTheme(readSavedTheme());
        if (window.lucide) window.lucide.createIcons();
        if (ns.ui && ns.ui.domainPanel) ns.ui.domainPanel.init(els);
        if (ns.workbench && ns.workbench.inspector && ns.workbench.inspector.inspectorController) {
            ns.workbench.inspector.inspectorController.init(els, viewer);
        } else if (ns.ui && ns.ui.inspectorPanel) {
            ns.ui.inspectorPanel.init(els, viewer);
        }
        if (ns.workbench && ns.workbench.state && ns.workbench.state.selectionStore) {
            ns.workbench.state.selectionStore.subscribe(function (payload) {
                if (payload.source !== 'viewer' && viewer && typeof viewer.selectByEntityKeys === 'function') {
                    viewer.selectByEntityKeys(payload.keys);
                }
            });
        }
        if (ns.workbench && ns.workbench.state && ns.workbench.state.visibilityStore) {
            ns.workbench.state.visibilityStore.subscribe(function () {
                if (viewer && typeof viewer.applyVisibilityState === 'function') {
                    viewer.applyVisibilityState(ns.workbench.state.visibilityStore);
                }
            });
        }
        if (ns.workbench && ns.workbench.navigation) {
            if (ns.workbench.navigation.colorOverlay) ns.workbench.navigation.colorOverlay.setViewer(viewer);
            if (ns.workbench.navigation.sectionBox) ns.workbench.navigation.sectionBox.setViewer(viewer);
            if (ns.workbench.navigation.modelTree) ns.workbench.navigation.modelTree.init();
        }
        if (ns.ui && ns.ui.auditDrawer) ns.ui.auditDrawer.init(els, viewer);
        bindEvents();
        ns.verified.init();
        clearFdsModel();
        checkBackendHealth();
        window.addEventListener('focus', checkBackendHealth);
    });

    function cacheElements() {
        if (ns.ui && ns.ui.domCache) {
            els = ns.ui.domCache.init();
        }
    }

    function applyClip(id, value) {
        var slider = els.clipSliders[id];
        var input = els.clipInputs[id];
        if (slider) slider.value = String(value);
        if (input) input.value = Number(value).toFixed(2);
        var axisChar = id.charAt(0);
        var side = id.slice(1);
        viewer.setClipPlane(axisChar, side, Number(value));
    }

    function clampClip(id, raw) {
        var slider = els.clipSliders[id];
        if (!slider) return raw;
        var v = Number(raw);
        if (!isFinite(v)) return Number(slider.value);
        return Math.max(Number(slider.min), Math.min(Number(slider.max), v));
    }

    function bindClipSlider(id) {
        var slider = els.clipSliders[id];
        var input = els.clipInputs[id];
        if (!slider) return;
        slider.addEventListener('input', function () { applyClip(id, slider.value); });
        if (input) {
            input.addEventListener('change', function () { applyClip(id, clampClip(id, input.value)); });
            input.addEventListener('keydown', function (event) {
                if (event.key === 'Enter') input.blur();
            });
        }
    }

    function bindClipSteppers() {
        Array.prototype.forEach.call(document.querySelectorAll('.clip-step'), function (btn) {
            btn.addEventListener('click', function () {
                var id = String(btn.getAttribute('data-target') || '').replace(/^clip-/, '');
                var dir = Number(btn.getAttribute('data-dir')) || 0;
                var slider = els.clipSliders[id];
                if (!slider) return;
                var step = Number(slider.step) || 0.1;
                var current = Number(slider.value);
                applyClip(id, clampClip(id, current + dir * step));
            });
        });
    }

    function setupClippingForBounds(bounds) {
        if (!els.clipPanel) return;
        if (!bounds) { els.clipPanel.hidden = true; return; }
        els.clipPanel.hidden = false;
        var pairs = [['xmin', 'xmax', bounds.xmin, bounds.xmax], ['ymin', 'ymax', bounds.ymin, bounds.ymax], ['zmin', 'zmax', bounds.zmin, bounds.zmax]];
        pairs.forEach(function (p) {
            var lo = p[2], hi = p[3];
            var span = Math.max(hi - lo, 0.001);
            // Step granularity: round to a sensible nudge (cm-scale on a metre-scale model)
            // so the ▲/▼ buttons feel like 0.01–0.1 m per click rather than fractional µm.
            var step = Math.max(span / 200, 0.01);
            [[p[0], lo], [p[1], hi]].forEach(function (pair) {
                var id = pair[0], value = pair[1];
                var slider = els.clipSliders[id];
                var input = els.clipInputs[id];
                if (slider) { slider.min = String(lo); slider.max = String(hi); slider.step = String(step); slider.value = String(value); }
                if (input) input.value = Number(value).toFixed(2);
            });
        });
        viewer.setClipBoundsNative(bounds);
    }

    function showLoading(title, stage) {
        if (!els.ifcLoading) return;
        els.ifcLoadingTitle.textContent = title || 'Loading IFC…';
        els.ifcLoadingStage.textContent = stage || '';
        els.ifcLoadingPercent.textContent = '';
        els.ifcLoadingFill.classList.add('is-indeterminate');
        els.ifcLoadingFill.style.width = '';
        els.ifcLoading.hidden = false;
    }

    function setLoadingProgress(fraction, stage) {
        if (!els.ifcLoading || els.ifcLoading.hidden) return;
        if (stage !== undefined) els.ifcLoadingStage.textContent = stage;
        var f = Math.max(0, Math.min(1, fraction || 0));
        els.ifcLoadingFill.classList.remove('is-indeterminate');
        els.ifcLoadingFill.style.width = (f * 100).toFixed(1) + '%';
        els.ifcLoadingPercent.textContent = Math.round(f * 100) + '%';
    }

    function hideLoading() {
        if (!els.ifcLoading) return;
        els.ifcLoading.hidden = true;
        els.ifcLoadingFill.classList.add('is-indeterminate');
        els.ifcLoadingFill.style.width = '';
    }

    function setSaveProcessedEnabled(enabled) {
        if (els.saveProcessed) els.saveProcessed.disabled = !enabled;
    }

    function finishIfcLoad(model, displayMeshes, oversizeNotice) {
        state.ifcModel = model;
        state.lastDisplayMeshes = displayMeshes || null;
        if (oversizeNotice && model && model.diagnostics) model.diagnostics.unshift(oversizeNotice);
        setLoadingProgress(1, 'Rendering…');
        if (ns.workbench && ns.workbench.state && ns.workbench.state.selectionStore) {
            if (model && model.elements) {
                ns.workbench.state.selectionStore.indexElements(
                    model.elements,
                    state.currentIfcFile ? state.currentIfcFile.name : 'ifc'
                );
            }
        }
        viewer.sourceId = state.currentIfcFile ? state.currentIfcFile.name : 'ifc';
        if (!model.backendPreview) viewer.loadIfcModel(model, displayMeshes);
        else ns.verified.usePreviewInventory(model.inventorySummary, state.currentIfcFile);
        viewer.setIfcOpacity(Number(els.ifcOpacity.value));
        updateIfcMetrics(model);
        updateSourcePill(state.currentIfcFile, model);
        setExportEnabled(!model.backendPreview && countConvertibleIfc(model) > 0);
        setSaveProcessedEnabled(!!(model && !model.backendPreview && model.elements && model.elements.length));
        setupClippingForBounds(boundsForClipping());
        if (ns.workbench && ns.workbench.navigation) {
            if (ns.workbench.navigation.sectionBox) {
                ns.workbench.navigation.sectionBox.setNativeExtents(boundsForClipping());
            }
            if (ns.workbench.navigation.modelTree) {
                ns.workbench.navigation.modelTree.render();
            }
            var clipStoreySelect = document.getElementById('clip-storey-select');
            if (clipStoreySelect && model && model.storeys) {
                clipStoreySelect.innerHTML = '<option value="" selected>Full Height</option>';
                model.storeys.forEach(function (st) {
                    var opt = document.createElement('option');
                    var name = typeof st === 'string' ? st : (st.name || st.storey_id || 'Storey');
                    opt.value = name;
                    opt.textContent = name;
                    clipStoreySelect.appendChild(opt);
                });
            }
        }
        renderDiagnostics();
        hideLoading();
    }

    // Prefers the lightweight meta model's expressIDs (when web-ifc rendered) by reading the
    // viewer's world Box3, then falls back to the parsed model's bounds. Returns IFC-native
    // coordinates because the clipping API speaks in those.
    function boundsForClipping() {
        var model = state.ifcModel;
        if (model && (model.convertibleBounds || model.bounds)) return model.convertibleBounds || model.bounds;
        // Meta-only model — compute world box from the IFC group, then unswap to native.
        if (!viewer || !viewer.ifcGroup) return null;
        viewer.ifcGroup.updateMatrixWorld(true);
        var box = new THREE.Box3().expandByObject(viewer.ifcGroup);
        if (box.isEmpty()) return null;
        // toThree(x, y, z) = (x, z, y) — so to invert: native (x, z_three, y_three).
        return {
            xmin: box.min.x, xmax: box.max.x,
            ymin: box.min.z, ymax: box.max.z,
            zmin: box.min.y, zmax: box.max.y
        };
    }

    function failIfcLoad(fileName, error) {
        hideLoading();
        state.ifcModel = {
            fileName: fileName,
            elements: [],
            diagnostics: [
                new ns.core.Diagnostic('error', 'IFC import failed', error && error.message ? error.message : String(error), ns.core.failure(error, {stage: 'ifc_read'}))
            ]
        };
        state.lastDisplayMeshes = null;
        updateIfcMetrics(state.ifcModel);
        setExportEnabled(false);
        setSaveProcessedEnabled(false);
        renderDiagnostics();
    }

    function bindEvents() {
        var viewBus = ns.workbench.commands.commandBus;
        var undoView = document.getElementById('undo-view');
        var resetVisibility = document.getElementById('reset-visibility');
        if (undoView) {
            undoView.addEventListener('click', function () { viewBus.undo(); });
            viewBus.subscribe(function () { undoView.disabled = !viewBus.canUndo(); });
        }
        if (resetVisibility) resetVisibility.addEventListener('click', function () {
            viewBus.execute(new ns.workbench.commands.ResetVisibilityCommand());
        });
        var cancelTask = document.getElementById('cancel-task');
        function cancelUiTask() {
            state.ifcLoadRequestId = (state.ifcLoadRequestId || 0) + 1;
            ns.ifc.backendPreview.cancel();
            cancelPendingExport();
            hideLoading();
            document.getElementById('verified-progress').textContent = 'Cancelled';
        }
        if (cancelTask) cancelTask.addEventListener('click', cancelUiTask);
        var verifiedCancel = document.getElementById('verified-cancel');
        if (verifiedCancel) verifiedCancel.addEventListener('click', cancelUiTask);
        els.toggleTheme.addEventListener('click', function () {
            var theme = currentTheme === 'dark' ? 'light' : 'dark';
            applyTheme(theme);
            try {
                localStorage.setItem('ifc-fds-theme', theme);
            } catch (error) {
                // Theme switching still works when storage is unavailable.
            }
        });

        els.toggleWalk.addEventListener('click', function () {
            viewer.setNavigationMode(viewer.navigationMode === 'walk' ? 'orbit' : 'walk');
        });

        // Both the toolbar help button and the footer "Guide" link now open the standalone
        // single-column guide.html page in a new tab instead of layering a modal over the
        // viewer. The old modal markup is left in place as a fallback for any environment
        // where window.open is blocked.
        [els.openHelp, els.footerHelp].forEach(function (button) {
            if (!button) return;
            button.addEventListener('click', function (event) {
                event.preventDefault();
                var opened = window.open('guide.html', '_blank', 'noopener');
                if (!opened) openHelp();
            });
        });

        if (els.closeHelp) els.closeHelp.addEventListener('click', closeHelp);
        if (els.helpModal) {
            var backdrop = els.helpModal.querySelector('[data-close-help]');
            if (backdrop) backdrop.addEventListener('click', closeHelp);
        }

        if (els.openCredits) els.openCredits.addEventListener('click', openCredits);
        if (els.closeCredits) els.closeCredits.addEventListener('click', closeCredits);
        if (els.creditsModal) els.creditsModal.querySelector('[data-close-credits]').addEventListener('click', closeCredits);

        if (els.openAudit) els.openAudit.addEventListener('click', openAudit);
        if (els.closeAudit) els.closeAudit.addEventListener('click', closeAudit);
        if (els.auditModal) {
            var auditBackdrop = els.auditModal.querySelector('[data-close-audit]');
            if (auditBackdrop) auditBackdrop.addEventListener('click', closeAudit);
        }

        window.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && !els.helpModal.hidden) closeHelp();
            if (event.key === 'Escape' && els.creditsModal && !els.creditsModal.hidden) closeCredits();
            if (event.key === 'Escape' && els.auditModal && !els.auditModal.hidden) closeAudit();
        });

        els.ifcFile.addEventListener('change', function (event) {
            var file = event.target.files[0];
            if (!file) return;
            var loadGeneration = state.ifcLoadRequestId = (state.ifcLoadRequestId || 0) + 1;
            function currentLoad() { return state.currentIfcFile === file && state.ifcLoadRequestId === loadGeneration; }
            ns.ifc.backendPreview.cancel();
            state.currentIfcFile = file;
            ns.verified.setFallback(file);
            cancelPendingExport();
            clearGeneratedFds();
            clearFdsModel();
            state.forceObstStepIds = {};
            state.excludedStepIds = {};
            state.excludedItemIds = {};
            state.undoStack = [];
            viewBus.clear();
            ns.workbench.state.visibilityStore.resetVisibility('source-change');
            state.fullModel = null;
            state.ifcSourceText = null;
            state.ifcFileName = file.name;
            // The previous file's reveal animation may have left the IFC slider at 0.3 so
            // the new model would render as a barely-visible ghost. Reset to full opacity
            // before showing the new file.
            if (els.ifcOpacity) {
                els.ifcOpacity.value = '1';
                viewer.setIfcOpacity(1);
            }
            setExportEnabled(false);
            setSaveProcessedEnabled(false);
            els.ifcSourceName.textContent = file.name;
            showLoading('Loading ' + file.name, 'Reading file…');

            // Large sources go directly to an isolated backend worker. Never
            // decode their entire STEP content or send them to the legacy parser.
            var WEB_IFC_MAX_BYTES = 8 * 1024 * 1024;
            if (file.size > WEB_IFC_MAX_BYTES) {
                ns.ifc.backendPreview.load(file, viewer, function (fraction, message) {
                    if (currentLoad()) setLoadingProgress(fraction, message);
                }).then(function (model) {
                    if (currentLoad()) finishIfcLoad(model, null, null);
                }).catch(function (error) {
                    if (currentLoad() && error.name !== 'AbortError') failIfcLoad(file.name, error);
                });
                return;
            }
            var useWebIfcDisplay = webIfcDisplay && file.size <= WEB_IFC_MAX_BYTES;
            var oversizeNotice = null;

            file.arrayBuffer().then(function (buffer) {
                if (!currentLoad()) return;
                setLoadingProgress(0.1, 'Indexing entities…');
                var text = new TextDecoder().decode(new Uint8Array(buffer));
                state.ifcSourceText = text;
                var meta = ns.ifc.IfcMeta.buildModel(text, file.name);
                setLoadingProgress(0.5, useWebIfcDisplay ? 'Rendering geometry…' : 'Building legacy mesh…');
                var displayPromise = useWebIfcDisplay
                    ? webIfcDisplay.load(buffer).catch(function (err) {
                        console.warn('web-ifc display load failed:', err);
                        return null;
                    })
                    : Promise.resolve(null);
                return displayPromise.then(function (displayMeshes) {
                    if (!currentLoad()) return;
                    if (displayMeshes && displayMeshes.length) {
                        finishIfcLoad(meta, displayMeshes, oversizeNotice);
                        return;
                    }
                    // No WASM display available — fall back to the legacy parser so the viewer
                    // has geometry to draw. Caches it as state.fullModel so Convert won't reparse.
                    return ifcAdapter.parseAsync(text, file.name, function (fraction) {
                        setLoadingProgress(fraction, 'Parsing legacy mesh…');
                    }).then(function (fullModel) {
                        if (!currentLoad()) return;
                        state.fullModel = fullModel;
                        finishIfcLoad(fullModel, null, oversizeNotice);
                    });
                });
            }).catch(function (error) {
                if (!currentLoad()) return;
                failIfcLoad(file.name, error);
            });
        });

        els.resetCamera.addEventListener('click', function () {
            viewer.resetCamera();
        });

        els.convertIfc.addEventListener('click', function () {
            exportIfc('convert');
        });

        if (els.convertVerified) {
            els.convertVerified.addEventListener('click', function () {
                exportVerified();
            });
        }

        els.convertSelectedObst.addEventListener('click', function () {
            var stepIds = selectedGeneratedGeomStepIds(state.selection);
            if (!stepIds.length) return;
            var added = stepIds.filter(function (id) { return !state.forceObstStepIds[id]; });
            stepIds.forEach(function (stepId) {
                state.forceObstStepIds[stepId] = true;
            });
            if (added.length) pushUndo({ kind: 'voxelize', stepIds: added });
            exportIfc('voxelize');
        });

        if (els.deleteSelected) {
            els.deleteSelected.addEventListener('click', function () {
                var split = splitSelectionForDelete(state.selection);
                if (!split.stepIds.length && !split.itemIds.length) return;
                var addedStepIds = split.stepIds.filter(function (id) { return !state.excludedStepIds[id]; });
                var addedItemIds = split.itemIds.filter(function (id) { return !state.excludedItemIds[id]; });
                addedStepIds.forEach(function (id) { state.excludedStepIds[id] = true; });
                addedItemIds.forEach(function (id) { state.excludedItemIds[id] = true; });
                if (addedStepIds.length || addedItemIds.length) {
                    pushUndo({ kind: 'delete', stepIds: addedStepIds, itemIds: addedItemIds });
                }
                viewer.setSelectedObjects([]);
                showSelection(null);
                viewer.setExclusions(state.excludedStepIds, state.excludedItemIds);
                updateIfcMetrics(state.ifcModel);
                setExportEnabled(countConvertibleIfc(state.ifcModel) > 0);
            });
        }

        if (els.undoLast) {
            els.undoLast.addEventListener('click', undoLastChange);
        }

        ['xmin', 'xmax', 'ymin', 'ymax', 'zmin', 'zmax'].forEach(bindClipSlider);
        bindClipSteppers();
        if (els.obstThreshold && els.obstThresholdVal) {
            els.obstThreshold.addEventListener('input', function () {
                els.obstThresholdVal.value = Number(els.obstThreshold.value).toFixed(2);
            });
            els.obstThresholdVal.addEventListener('change', function () {
                var v = Number(els.obstThresholdVal.value);
                if (!isFinite(v)) { els.obstThresholdVal.value = Number(els.obstThreshold.value).toFixed(2); return; }
                v = Math.max(Number(els.obstThreshold.min), Math.min(Number(els.obstThreshold.max), v));
                els.obstThreshold.value = String(v);
                els.obstThresholdVal.value = v.toFixed(2);
            });
            els.obstThresholdVal.addEventListener('keydown', function (event) {
                if (event.key === 'Enter') els.obstThresholdVal.blur();
            });
        }
        if (els.clipReset) {
            els.clipReset.addEventListener('click', function () {
                viewer.resetClipping();
                if (state.ifcModel) setupClippingForBounds(boundsForClipping());
            });
        }

        window.addEventListener('keydown', function (event) {
            var key = event.key && event.key.toLowerCase();
            var tag = (event.target && event.target.tagName) || '';
            var typing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
            if (key === 'z' && (event.ctrlKey || event.metaKey) && !event.shiftKey) {
                if (typing) return;
                if (viewBus.canUndo()) { event.preventDefault(); viewBus.undo(); return; }
                if (els.undoLast && !els.undoLast.disabled) {
                    event.preventDefault();
                    undoLastChange();
                }
                return;
            }
            // Number-key view shortcuts (mirrors ProfRino/fds-viewer). Skipped while typing
            // in inputs, walking, or with any non-Shift modifier held.
            if (typing) return;
            if (viewer.navigationMode === 'walk') return;
            if (event.ctrlKey || event.metaKey || event.altKey) return;

            // Arrow-key orbit/dolly: left/right yaw, up/down pitch; Shift + arrows dollies
            // or strafes. Mirrors ProfRino/fds-viewer's keyboard navigation.
            var arrowMap = { ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down' };
            if (arrowMap[event.key] && viewer.orbitByKey) {
                event.preventDefault();
                viewer.orbitByKey(arrowMap[event.key], { shift: event.shiftKey });
                return;
            }

            if (event.shiftKey) return;
            var viewKey = VIEW_KEY_TO_DIRECTION[event.key];
            if (viewKey) {
                event.preventDefault();
                viewer.setView(viewKey);
            }
        });

        els.saveFds.addEventListener('click', function () {
            if (!state.generatedFdsText || !state.generatedFdsName) return;
            downloadText(state.generatedFdsName, state.generatedFdsText);
        });

        if (els.saveManifest) {
            els.saveManifest.addEventListener('click', function (e) {
                e.preventDefault();
                if (state.lastManifest) {
                    var base = ((state.lastManifest || {}).source_filename || state.ifcFileName || 'ifc_model').replace(/\.[^.]+$/, '').replace(/[^\w.-]+/g, '_');
                    downloadText(base + '_manifest.json', JSON.stringify(state.lastManifest, null, 2));
                    return;
                }
                if (state.lastArtifactLinks && state.lastArtifactLinks.manifest && state.lastArtifactLinks.manifest.url) {
                    var authH = (ns.verified && typeof ns.verified.getAuthHeaders === 'function') ? ns.verified.getAuthHeaders() : {};
                    fetch(state.lastArtifactLinks.manifest.url, { headers: authH })
                        .then(function (r) { return r.ok ? r.json() : null; })
                        .then(function (data) {
                            if (data) {
                                state.lastManifest = data;
                                var base = (data.source_filename || state.ifcFileName || 'ifc_model').replace(/\.[^.]+$/, '').replace(/[^\w.-]+/g, '_');
                                downloadText(base + '_manifest.json', JSON.stringify(data, null, 2));
                            }
                        })
                        .catch(function (err) { console.error('Download Manifest failed:', err); });
                }
            });
        }

        if (els.saveProcessed) {
            els.saveProcessed.addEventListener('click', function () {
                var processed = ns.ifc.ProcessedFile;
                if (!processed || !state.ifcModel || !state.ifcModel.elements || !state.ifcModel.elements.length) return;
                showLoading('Saving processed file', 'Serializing…');
                // Defer to next tick so the bar paints before the (potentially long)
                // JSON.stringify pass on the structured-clone payload.
                setTimeout(function () {
                    try {
                        var text = processed.serialize(state.ifcModel, state.lastDisplayMeshes);
                        var base = (state.ifcModel.fileName || 'ifc_model').replace(/\.[^.]+$/, '').replace(/[^\w.-]+/g, '_');
                        downloadText(base + processed.EXTENSION, text);
                    } catch (err) {
                        console.warn('processed-file save failed:', err);
                    }
                    hideLoading();
                }, 0);
            });
        }

        Array.prototype.forEach.call(document.querySelectorAll('[data-view-mode]'), function (button) {
            button.addEventListener('click', function () {
                Array.prototype.forEach.call(document.querySelectorAll('[data-view-mode]'), function (other) {
                    other.classList.toggle('active', other === button);
                });
                viewer.setViewMode(button.getAttribute('data-view-mode'));
            });
        });

        els.fdsOpacity.addEventListener('input', function () {
            viewer.setFdsOpacity(Number(els.fdsOpacity.value));
        });

        els.ifcOpacity.addEventListener('input', function () {
            viewer.setIfcOpacity(Number(els.ifcOpacity.value));
        });

        [els.includeFillSolids, els.includeReviewSolids].forEach(function (input) {
            input.addEventListener('change', function () {
                updateIfcMetrics(state.ifcModel);
                setExportEnabled(countConvertibleIfc(state.ifcModel) > 0);
            });
        });

        if (els.showIfcEdges) {
            els.showIfcEdges.addEventListener('change', function (event) {
                viewer.setIfcEdgesVisible(event.target.checked);
            });
        }
        bindToggle('show-grid', 'groundGrid');
        bindToggle('show-obst', 'obsts');
        bindToggle('show-hole', 'holes');
        bindToggle('show-geom', 'geoms');
        bindToggle('show-hvac', 'hvac');
        if (els.showStructure) {
            els.showStructure.addEventListener('change', function (event) {
                viewer.setIfcCategoryVisible('structure', event.target.checked);
            });
        }
        if (els.showFills) {
            els.showFills.addEventListener('change', function (event) {
                viewer.setIfcCategoryVisible('fills', event.target.checked);
            });
        }
        if (els.showOther) {
            els.showOther.addEventListener('change', function (event) {
                viewer.setIfcCategoryVisible('other', event.target.checked);
            });
        }

        // Workflow Mode Switcher
        if (els.modeTabVerified) {
            els.modeTabVerified.addEventListener('click', function () { setWorkflowMode('verified'); });
        }
        if (els.modeTabQuick) {
            els.modeTabQuick.addEventListener('click', function () { setWorkflowMode('quick'); });
        }

        // Viewport Floating Toolbar Popovers
        var btnLayers = document.getElementById('toggle-layers-popover');
        var popLayers = document.getElementById('layers-popover');
        var btnCamera = document.getElementById('toggle-camera-views');
        var popCamera = document.getElementById('camera-popover');
        if (btnLayers && popLayers) {
            btnLayers.addEventListener('click', function (e) {
                e.stopPropagation();
                popLayers.style.display = popLayers.style.display === 'none' ? 'flex' : 'none';
                if (popCamera) popCamera.style.display = 'none';
            });
        }
        if (btnCamera && popCamera) {
            btnCamera.addEventListener('click', function (e) {
                e.stopPropagation();
                popCamera.style.display = popCamera.style.display === 'none' ? 'flex' : 'none';
                if (popLayers) popLayers.style.display = 'none';
            });
        }
        document.addEventListener('click', function () {
            if (popLayers) popLayers.style.display = 'none';
            if (popCamera) popCamera.style.display = 'none';
        });

        var btnClip = document.getElementById('toggle-clip');
        if (btnClip && els.clipPanel) {
            btnClip.addEventListener('click', function () {
                els.clipPanel.hidden = !els.clipPanel.hidden;
            });
        }

        Array.prototype.forEach.call(document.querySelectorAll('[data-cam]'), function (btn) {
            btn.addEventListener('click', function () {
                var dir = btn.getAttribute('data-cam');
                if (dir && viewer && viewer.setView) viewer.setView(dir);
            });
        });

        // Sidebar Nav Switcher (Workflow vs Model Tree vs EV Scenario Batch)
        var tabWorkflow = document.getElementById('sidebar-tab-workflow');
        var tabTree = document.getElementById('sidebar-tab-tree');
        var tabEv = document.getElementById('sidebar-tab-ev');
        var panelWorkflow = document.getElementById('sidebar-panel-workflow');
        var panelTree = document.getElementById('sidebar-panel-tree');
        var panelEv = document.getElementById('sidebar-panel-ev');

        if (tabWorkflow && tabTree && panelWorkflow && panelTree) {
            tabWorkflow.addEventListener('click', function () {
                tabWorkflow.classList.add('active');
                tabWorkflow.setAttribute('aria-selected', 'true');
                tabTree.classList.remove('active');
                tabTree.setAttribute('aria-selected', 'false');
                if (tabEv) {
                    tabEv.classList.remove('active');
                    tabEv.setAttribute('aria-selected', 'false');
                }
                panelWorkflow.style.display = 'block';
                panelTree.style.display = 'none';
                if (panelEv) panelEv.style.display = 'none';
            });
            tabTree.addEventListener('click', function () {
                tabTree.classList.add('active');
                tabTree.setAttribute('aria-selected', 'true');
                tabWorkflow.classList.remove('active');
                tabWorkflow.setAttribute('aria-selected', 'false');
                if (tabEv) {
                    tabEv.classList.remove('active');
                    tabEv.setAttribute('aria-selected', 'false');
                }
                panelWorkflow.style.display = 'none';
                panelTree.style.display = 'flex';
                if (panelEv) panelEv.style.display = 'none';
                if (ns.workbench && ns.workbench.navigation && ns.workbench.navigation.modelTree) {
                    ns.workbench.navigation.modelTree.render();
                }
            });
            if (tabEv && panelEv) {
                tabEv.addEventListener('click', function () {
                    tabEv.classList.add('active');
                    tabEv.setAttribute('aria-selected', 'true');
                    tabWorkflow.classList.remove('active');
                    tabWorkflow.setAttribute('aria-selected', 'false');
                    tabTree.classList.remove('active');
                    tabTree.setAttribute('aria-selected', 'false');
                    panelWorkflow.style.display = 'none';
                    panelTree.style.display = 'none';
                    panelEv.style.display = 'flex';

                    var evPanel = (ns.workbench && ns.workbench.panels && ns.workbench.panels.evScenarioPanel) || (ns.ui && ns.ui.evScenarioPanel);
                    if (evPanel && !panelEv.dataset.mounted) {
                        panelEv.dataset.mounted = 'true';
                        evPanel.mount(panelEv, {
                            scenarioStore: ns.workbench && ns.workbench.state && ns.workbench.state.scenarioStore,
                            getBaseBundleSha: function () {
                                return (state.lastVerifiedResult && state.lastVerifiedResult.bundle_sha256) ||
                                    (ns.workbench && ns.workbench.state && ns.workbench.state.scenarioStore && ns.workbench.state.scenarioStore.getBaseMappingSha && ns.workbench.state.scenarioStore.getBaseMappingSha()) ||
                                    '';
                            }
                        });
                    }
                });
            }
        }

        // Semantic Tree Group & Search
        var treeGroupBy = document.getElementById('tree-group-by');
        if (treeGroupBy) {
            treeGroupBy.addEventListener('change', function () {
                if (ns.workbench && ns.workbench.navigation && ns.workbench.navigation.modelTree) {
                    ns.workbench.navigation.modelTree.setGroupBy(treeGroupBy.value);
                }
            });
        }
        var treeSearch = document.getElementById('tree-search-input');
        if (treeSearch) {
            treeSearch.addEventListener('input', function () {
                if (ns.workbench && ns.workbench.navigation && ns.workbench.navigation.modelTree) {
                    ns.workbench.navigation.modelTree.setSearchQuery(treeSearch.value);
                }
            });
        }

        // Color Mode Selector
        var colorSelect = document.getElementById('color-mode-select');
        if (colorSelect) {
            colorSelect.addEventListener('change', function () {
                updateColorModeLegend(colorSelect.value);
                if (ns.workbench && ns.workbench.navigation && ns.workbench.navigation.colorOverlay) {
                    ns.workbench.navigation.colorOverlay.applyColorMode(colorSelect.value);
                }
            });
        }

        // Section Box Storey Cut & Reset
        var clipStoreySelect = document.getElementById('clip-storey-select');
        if (clipStoreySelect) {
            clipStoreySelect.addEventListener('change', function () {
                if (ns.workbench && ns.workbench.navigation && ns.workbench.navigation.sectionBox) {
                    if (!clipStoreySelect.value) {
                        ns.workbench.navigation.sectionBox.reset();
                    } else {
                        ns.workbench.navigation.sectionBox.cutToStorey(clipStoreySelect.value);
                    }
                }
            });
        }
        var clipReset = document.getElementById('clip-reset');
        if (clipReset) {
            clipReset.addEventListener('click', function () {
                if (ns.workbench && ns.workbench.navigation && ns.workbench.navigation.sectionBox) {
                    ns.workbench.navigation.sectionBox.reset();
                }
                if (clipStoreySelect) clipStoreySelect.value = '';
                setupClippingForBounds(boundsForClipping());
            });
        }

        // Domain Estimates & Preflight Scoped Domain Warning
        ['xmin', 'xmax', 'ymin', 'ymax', 'zmin', 'zmax'].forEach(function (axis) {
            var input = document.getElementById('verified-domain-' + axis);
            if (input) input.addEventListener('input', updateDomainEstimates);
        });
        if (els.verifiedCellSize) {
            els.verifiedCellSize.addEventListener('input', updateDomainEstimates);
        }
        if (els.verifiedStoreys) {
            els.verifiedStoreys.addEventListener('change', checkScopedDomainPreflight);
        }
        if (els.verifiedUseDomain) {
            els.verifiedUseDomain.addEventListener('change', function () {
                var box = document.getElementById('verified-domain-box');
                if (box) box.style.display = els.verifiedUseDomain.checked ? 'grid' : 'none';
                checkScopedDomainPreflight();
            });
        }
        var useBoundsCheck = document.getElementById('verified-use-bounds');
        var boundsBox = document.getElementById('verified-bounds-box');
        if (useBoundsCheck && boundsBox) {
            useBoundsCheck.addEventListener('change', function () {
                boundsBox.style.display = useBoundsCheck.checked ? 'grid' : 'none';
            });
        }

        // Reviewed Decisions Upload Summary Preview
        var decisionsInput = document.getElementById('verified-decisions');
        var decisionsChip = document.getElementById('decisions-summary-chip');
        if (decisionsInput && decisionsChip) {
            decisionsInput.addEventListener('change', async function () {
                if (!decisionsInput.files || !decisionsInput.files.length) {
                    decisionsChip.style.display = 'none';
                    return;
                }
                try {
                    var data = JSON.parse(await decisionsInput.files[0].text());
                    var keys = Object.keys(data);
                    var passive = keys.filter(function (k) { return data[k].action === 'PASSIVE_OBSTACLE'; }).length;
                    var ref = keys.filter(function (k) { return data[k].action === 'REFERENCE_GEOMETRY'; }).length;
                    var excl = keys.filter(function (k) { return data[k].action === 'EXCLUDE'; }).length;
                    decisionsChip.style.display = 'flex';
                    decisionsChip.textContent = '✓ ' + keys.length + ' decisions loaded (' + passive + ' Obstacle, ' + ref + ' Reference, ' + excl + ' Excluded)';
                } catch (e) {
                    decisionsChip.style.display = 'flex';
                    decisionsChip.textContent = '⚠️ Malformed decisions JSON';
                }
            });
        }

        // Inspector Tabs
        ['id', 'map', 'geom', 'mep'].forEach(function (tab) {
            var btn = document.getElementById('inspect-tab-' + tab);
            if (btn) {
                btn.addEventListener('click', function () {
                    activeInspectorTab = tab;
                    ['id', 'map', 'geom', 'mep'].forEach(function (t) {
                        var b = document.getElementById('inspect-tab-' + t);
                        if (b) b.classList.toggle('active', t === tab);
                    });
                    if (state.selection && state.selection.length) {
                        renderStructuredInspector(state.selection[0]);
                    }
                });
            }
        });

        // Bottom Audit Drawer Toggle & Tabs
        if (els.toggleDrawer && els.auditDrawer) {
            els.toggleDrawer.addEventListener('click', function (e) {
                e.stopPropagation();
                toggleAuditDrawer();
            });
            var drawerHeader = document.querySelector('.audit-drawer-header');
            if (drawerHeader) {
                drawerHeader.addEventListener('click', function (e) {
                    if (e.target.closest('.audit-tab-btn')) return;
                    toggleAuditDrawer();
                });
            }
        }
        ['gates', 'findings', 'artifacts'].forEach(function (tab) {
            var btn = document.getElementById('drawer-tab-' + tab);
            var panel = document.getElementById('panel-' + tab);
            if (btn && panel) {
                btn.addEventListener('click', function (e) {
                    e.stopPropagation();
                    if (els.auditDrawer && els.auditDrawer.classList.contains('minimized')) {
                        els.auditDrawer.classList.remove('minimized');
                        var icon = document.getElementById('drawer-toggle-icon');
                        if (icon) icon.setAttribute('data-lucide', 'chevron-down');
                        if (window.lucide) window.lucide.createIcons();
                    }
                    ['gates', 'findings', 'artifacts'].forEach(function (t) {
                        var b = document.getElementById('drawer-tab-' + t);
                        var p = document.getElementById('panel-' + t);
                        if (b) b.classList.toggle('active', t === tab);
                        if (p) p.style.display = t === tab ? (t === 'artifacts' || t === 'gates' ? 'grid' : 'block') : 'none';
                    });
                });
            }
        });
    }

    function bindToggle(id, layer) {
        var el = document.getElementById(id);
        if (!el) return;
        el.addEventListener('change', function (event) {
            viewer.setLayerVisible(layer, event.target.checked);
        });
    }

    function openHelp(event) {
        viewer.setNavigationMode('orbit');
        state.helpTrigger = event && event.currentTarget ? event.currentTarget : els.openHelp;
        els.helpModal.hidden = false;
        els.helpModal.querySelector('.help-body').scrollTop = 0;
        els.closeHelp.focus();
    }

    function closeHelp() {
        els.helpModal.hidden = true;
        (state.helpTrigger || els.openHelp).focus();
    }

    function openCredits() {
        els.creditsModal.hidden = false;
        els.closeCredits.focus();
    }

    function closeCredits() {
        els.creditsModal.hidden = true;
        if (els.openCredits) els.openCredits.focus();
    }

    function readSavedTheme() {
        try {
            return localStorage.getItem('ifc-fds-theme') || 'light';
        } catch (error) {
            return 'light';
        }
    }

    function applyTheme(theme) {
        currentTheme = theme === 'dark' ? 'dark' : 'light';
        document.documentElement.setAttribute('data-theme', currentTheme);
        if (viewer) viewer.setTheme(currentTheme);
        if (!els.toggleTheme) return;

        var nextTheme = currentTheme === 'dark' ? 'light' : 'dark';
        els.toggleTheme.title = 'Switch to ' + nextTheme + ' theme';
        els.toggleTheme.setAttribute('aria-label', els.toggleTheme.title);
        els.toggleTheme.innerHTML = '<i data-lucide="' + (currentTheme === 'dark' ? 'sun' : 'moon') + '"></i>';
        if (window.lucide) window.lucide.createIcons();
    }

    function updateWalkModeButton(mode) {
        var walking = mode === 'walk';
        els.toggleWalk.classList.toggle('active', walking);
        els.toggleWalk.setAttribute('aria-pressed', walking ? 'true' : 'false');
        els.toggleWalk.title = walking
            ? 'Exit walk mode'
            : 'Enter walk mode';
        els.toggleWalk.setAttribute('aria-label', walking ? 'Exit walk mode' : 'Enter walk mode');
    }

    function loadFdsText(text, sourceName, preparedModel) {
        var parsed = preparedModel ? null : ns.core.atStage('fds_parse', function () { return parser.parse(text); });
        var model = preparedModel || ns.core.atStage('scene_model', function () { return adapter.toSceneModel(parsed); });
        state.fdsModel = model;
        els.fdsSourceName.textContent = sourceName;
        if (ns.workbench && ns.workbench.state) {
            var sceneItems = [].concat(model.obsts || [], model.geoms || [], model.vents || [], model.holes || []);
            ns.workbench.state.selectionStore.indexElements(sceneItems, sourceName || 'fds');
        }
        ns.core.atStage('viewer', function () { viewer.loadFdsModel(model); });
        viewer.setFdsOpacity(Number(els.fdsOpacity.value));
        viewer.setExclusions(state.excludedStepIds, state.excludedItemIds);
        updateMetrics(model);
        renderDiagnostics();
        showSelection(null);
        if (ns.workbench && ns.workbench.navigation) {
            if (ns.workbench.navigation.colorOverlay) {
                var currentMode = ns.workbench.navigation.colorOverlay.currentMode || 'mapping';
                ns.workbench.navigation.colorOverlay.applyColorMode(currentMode);
            }
            if (ns.workbench.navigation.modelTree) {
                ns.workbench.navigation.modelTree.render();
            }
        }
    }

    function clearFdsModel() {
        var model = {
            meshes: [],
            obsts: [],
            vents: [],
            holes: [],
            geoms: [],
            triangleCount: 0,
            bounds: null,
            diagnostics: []
        };
        state.fdsModel = model;
        els.fdsSourceName.textContent = 'No conversion';
        viewer.loadFdsModel(model);
        if (ns.workbench && ns.workbench.state && ns.workbench.state.workbenchStore) {
            ns.workbench.state.workbenchStore.resetAll();
        }
        updateMetrics(model);
        renderDiagnostics();
        showSelection(null);
    }

    function readText(file) {
        return new Promise(function (resolve, reject) {
            var reader = new FileReader();
            reader.onload = function () { resolve(String(reader.result || '')); };
            reader.onerror = function () { reject(reader.error); };
            reader.readAsText(file);
        });
    }

    function updateMetrics(model) {
        els.countMeshes.textContent = model.meshes.length;
        els.countObsts.textContent = model.obsts.length;
        els.countVents.textContent = model.vents.length;
        els.countGeoms.textContent = model.geoms.length;
        els.countTriangles.textContent = model.triangleCount;
        els.countIfc.textContent = state.ifcModel && state.ifcModel.elements ? state.ifcModel.elements.length : 0;
        els.countIfcConvertible.textContent = countConvertibleIfc(state.ifcModel);
        renderIfcMapping(state.ifcModel);
    }

    function updateIfcMetrics(model) {
        els.countIfc.textContent = model && model.elements ? model.elements.length : 0;
        els.countIfcConvertible.textContent = countConvertibleIfc(model);
        renderIfcMapping(model);
    }

    function renderIfcMapping(model) {
        var rows = exporter.summarizeIfcMapping(model, currentExportOptions());
        els.ifcMapping.innerHTML = '';

        if (!rows.length) {
            els.ifcMapping.innerHTML = '<p class="empty-state">Open an IFC model to review its FDS mapping.</p>';
            return;
        }

        rows.forEach(function (row) {
            var item = document.createElement('div');
            var exported = row.exported ? row.exported + ' exported' : 'not exported';
            item.className = 'mapping-row';
            item.innerHTML = '<span class="mapping-type"></span><span class="mapping-status"><strong></strong><span></span></span>';
            item.querySelector('.mapping-type').textContent = row.ifcType.replace(/^IFC/, '');
            item.querySelector('strong').textContent = row.imported;
            item.querySelector('.mapping-status span').textContent = row.role + ' - ' + exported;
            els.ifcMapping.appendChild(item);
        });
    }

    function renderDiagnostics() {
        var diagnostics = ns.compare.runChecks(state.fdsModel, state.ifcModel);
        els.diagnostics.innerHTML = '';
        diagnostics.forEach(function (diag) {
            var item = document.createElement('li');
            item.className = diag.level || 'info';
            item.innerHTML = '<strong></strong><span></span>';
            item.querySelector('strong').textContent = diag.title;
            item.querySelector('span').textContent = diag.detail;
            els.diagnostics.appendChild(item);
            if (diag.ref && diag.ref.kind === 'conversion-failure') {
                var download = document.createElement('button');
                download.type = 'button'; download.textContent = 'Download diagnostic';
                download.addEventListener('click', function () {
                    var url = URL.createObjectURL(new Blob([JSON.stringify(diag.ref, null, 2)], {type: 'application/json'}));
                    var link = document.createElement('a'); link.href = url; link.download = 'conversion-diagnostic.json';
                    link.click(); setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
                });
                item.appendChild(download);
            }
        });
    }

    function showSelection(data) {
        var selection = normalizeSelection(data);
        state.selection = selection;
        refreshConversionActions();
        if (ns.workbench && ns.workbench.state && ns.workbench.state.selectionStore) {
            ns.workbench.state.selectionStore.setSelection(selection, 'viewer');
        } else {
            if (!selection.length) {
                els.inspectCard.hidden = true;
                return;
            }
            els.inspectCard.hidden = false;
            if (selection.length === 1) {
                els.inspectTitle.textContent = selection[0].type + (selection[0].id ? ': ' + selection[0].id : '');
                renderStructuredInspector(selection[0]);
                els.inspectBody.textContent = JSON.stringify(selectionDetails(selection[0]), null, 2);
                return;
            }
            els.inspectTitle.textContent = 'Selected objects: ' + selection.length;
            renderStructuredInspector(null);
            els.inspectBody.textContent = JSON.stringify(selection.map(selectionDetails), null, 2);
        }
    }

    function selectionDetails(data) {
        return {
            surf_id: data.surf_id,
            ifcType: data.ifcType,
            globalId: data.globalId,
            convertible: data.convertible,
            fdsRole: data.fdsRole,
            canExportAsSolid: data.canExportAsSolid,
            conversionNote: data.conversionNote,
            ifcSource: data.ifcSource,
            xb: data.xb,
            bounds: data.bounds,
            raw: data.raw
        };
    }

    function setExportEnabled(enabled) {
        state.exportEnabled = !!enabled;
        refreshConversionActions();
    }

    function refreshConversionActions() {
        els.convertIfc.disabled = state.exportBusy || !state.exportEnabled;
        if (els.convertVerified) {
            els.convertVerified.disabled = state.exportBusy || (!state.exportEnabled && !ns.verified.hasFiles());
        }
        els.convertSelectedObst.disabled = state.exportBusy || !selectedGeneratedGeomStepIds(state.selection).length;
        if (els.deleteSelected) {
            var split = splitSelectionForDelete(state.selection);
            els.deleteSelected.disabled = state.exportBusy || (!split.stepIds.length && !split.itemIds.length);
        }
        if (els.undoLast) {
            els.undoLast.disabled = state.exportBusy || !state.undoStack.length;
        }
        if (els.openAudit) {
            els.openAudit.disabled = !state.lastAuditReport;
        }
        if (els.saveManifest) {
            els.saveManifest.disabled = !state.lastManifest && !state.lastArtifactLinks;
        }
    }

    function pushUndo(entry) {
        state.undoStack.push(entry);
        refreshConversionActions();
    }

    function undoLastChange() {
        var entry = state.undoStack.pop();
        if (!entry) return;
        if (entry.kind === 'voxelize') {
            entry.stepIds.forEach(function (id) { delete state.forceObstStepIds[id]; });
            // The voxelize action ran an export; undoing it has to re-run the export to
            // get the original GEOM triangles back on screen.
            if (state.ifcModel && state.ifcModel.elements && state.ifcModel.elements.length) {
                exportIfc('convert');
            }
        } else if (entry.kind === 'delete') {
            (entry.stepIds || []).forEach(function (id) { delete state.excludedStepIds[id]; });
            (entry.itemIds || []).forEach(function (id) { delete state.excludedItemIds[id]; });
            viewer.setExclusions(state.excludedStepIds, state.excludedItemIds);
            updateIfcMetrics(state.ifcModel);
            setExportEnabled(countConvertibleIfc(state.ifcModel) > 0);
        }
        refreshConversionActions();
    }

    function setExportBusy(busy, action) {
        state.exportBusy = !!busy;
        state.exportAction = state.exportBusy ? action : null;
        els.convertIfc.classList.toggle('is-busy', state.exportBusy && action === 'convert');
        if (els.convertVerified) {
            els.convertVerified.classList.toggle('is-busy', state.exportBusy && action === 'convert-verified');
            els.convertVerified.setAttribute('aria-busy', state.exportBusy && action === 'convert-verified' ? 'true' : 'false');
            var span = els.convertVerified.querySelector('span');
            if (span) {
                span.textContent = (state.exportBusy && action === 'convert-verified')
                    ? 'Verifying...'
                    : 'Verified Conversion (Audit)';
            }
        }
        els.convertSelectedObst.classList.toggle('is-busy', state.exportBusy && action === 'voxelize');
        els.convertIfc.setAttribute('aria-busy', state.exportBusy && action === 'convert' ? 'true' : 'false');
        els.convertSelectedObst.setAttribute('aria-busy', state.exportBusy && action === 'voxelize' ? 'true' : 'false');
        var spanIfc = els.convertIfc ? els.convertIfc.querySelector('span') : null;
        if (spanIfc) {
            spanIfc.textContent = state.exportBusy && action === 'convert'
                ? 'Converting...'
                : 'Run Quick Preview (Legacy)';
        }
        var spanObst = els.convertSelectedObst ? els.convertSelectedObst.querySelector('span') : null;
        if (spanObst) {
            spanObst.textContent = state.exportBusy && action === 'voxelize'
                ? 'Voxelizing selected GEOM...'
                : 'Voxelize selected GEOM to OBST';
        }
        refreshConversionActions();
    }

    function exportIfc(action) {
        if (state.exportBusy) return;
        if (!state.ifcModel || !state.ifcModel.elements || !state.ifcModel.elements.length) return;
        var generation = state.exportRequestId;
        setExportBusy(true, action || 'convert');
        ensureFullModel().then(function (fullModel) {
            if (generation !== state.exportRequestId) return;
            runExportWithModel(fullModel, action);
        }).catch(function (err) {
            if (generation !== state.exportRequestId) return;
            hideLoading(); setExportBusy(false);
            addExportDiagnostic(err, {stage: 'ifc_parse'});
        });
    }

    // The meta model is enough for browse/select/preview, but FDS export needs the full
    // ifc-adapter parse (placements, void carving, classifications). We do it on demand
    // the first time the user clicks Convert, and cache the result for repeated exports.
    function ensureFullModel() {
        if (state.fullModel && !state.fullModel.elements.some(function (e) { return e.exportGeometryComplete === false; })) return Promise.resolve(state.fullModel);
        if (state.ifcModel && state.ifcModel.backendPreview) {
            return Promise.resolve(state.ifcModel);
        }
        if (!state.ifcSourceText) {
            return Promise.reject(new Error('IFC source not in memory — please reopen the file.'));
        }
        showLoading('Preparing FDS conversion', 'Parsing entities…');
        var generation = state.exportRequestId;
        // Export completes openings independently of the preview source.
        var parseOptions = { skipBoxOpenings: false };
        var parsePromise = ns.core.atStage('ifc_parse', function () { return ifcAdapter.parseAsync(state.ifcSourceText, state.ifcFileName, function (fraction) {
            setLoadingProgress(fraction, 'Parsing entities…');
        }, parseOptions); });
        return parsePromise.then(function (model) {
            if (generation !== state.exportRequestId) { var aborted = new Error('Conversion cancelled'); aborted.name = 'AbortError'; throw aborted; }
            state.fullModel = model;
            // Swap the displayed model to the precise one so sidebar counts and the IFC
            // mapping reflect the actual parser output instead of the meta heuristic.
            state.ifcModel = model;
            updateIfcMetrics(model);
            renderDiagnostics();
            hideLoading();
            return model;
        }, function (err) {
            hideLoading();
            throw err;
        });
    }

    function runExportWithModel(fullModel, action) {
        var options = currentExportOptions();
        var requestId = state.exportRequestId + 1;
        state.exportRequestId = requestId;
        setExportBusy(true, action || 'convert');
        // The Convert button's "Converting…" busy state runs in parallel with the export
        // worker; surface the same status on the top banner so the user gets the bigger
        // progress affordance during the FDS-text generation phase as well.
        var fileLabel = (state.ifcFileName || (state.ifcModel && state.ifcModel.fileName) || 'IFC model');
        showLoading('Converting ' + fileLabel, 'Generating FDS file…');

        try {
            var workerHandle = ns.workers.createExportWorker();
            var worker = workerHandle.worker;
            state.exportWorker = worker;
            state.exportWorkerUrl = workerHandle.url;
            worker.addEventListener('message', function (event) {
                if (requestId !== state.exportRequestId) return;
                var result = event.data || {};
                if (result.type === 'progress') {
                    var stage = result.stage ? 'Generating FDS: ' + result.stage : 'Generating FDS file…';
                    setLoadingProgress(result.fraction, stage);
                    return;
                }
                if (result.type === 'error') {
                    finishExportWithError(result.error || new Error(result.message || 'Background conversion failed.'));
                    return;
                }
                if (result.type !== 'complete') return;

                cleanupExportWorker();
                try {
                    var base = (fullModel.fileName || 'ifc_model').replace(/\.[^.]+$/, '').replace(/[^\w.-]+/g, '_');
                    var fileName = base + '_quick_preview_legacy.fds';
                    state.generatedFdsText = result.text;
                    state.generatedFdsName = fileName;
                    els.saveFds.disabled = false;
                    var fdsDrawerBtn = document.getElementById('btn-download-fds');
                    if (fdsDrawerBtn && (!state.lastArtifactLinks || !state.lastArtifactLinks.fds)) {
                        fdsDrawerBtn.classList.remove('disabled');
                        fdsDrawerBtn.style.pointerEvents = '';
                        fdsDrawerBtn.style.opacity = '';
                        fdsDrawerBtn.removeAttribute('aria-disabled');
                    }
                    loadFdsText(result.text, fileName, result.model);
                    hideLoading();
                    // The reveal animation clears any partial clip box from before this
                    // convert; mirror that on the UI so the bars sit at the full extent.
                    setupClippingForBounds(boundsForClipping());
                    // Skip the bottom-up reveal for the in-place "voxelize selected GEOM" path
                    // — the user is editing a small subset of an already-converted scene and
                    // doesn't want the whole building to fade-and-rebuild every time they
                    // change a single OBST.
                    if (viewer.playConversionReveal && action !== 'voxelize') viewer.playConversionReveal();
                } catch (error) {
                    addExportDiagnostic(error, {stage: 'viewer', requestId: requestId});
                    hideLoading();
                }
                setExportBusy(false);
            });
            worker.addEventListener('error', function (event) {
                if (requestId !== state.exportRequestId) return;
                finishExportWithError(ns.core.failure(event, {stage: 'worker', requestId: requestId}));
            });
            worker.postMessage({
                type: 'export',
                requestId: requestId,
                ifcModel: fullModel,
                options: options
            });
        } catch (error) {
            finishExportWithError(error);
        }
    }

    function finishExportWithError(message) {
        cleanupExportWorker();
        addExportDiagnostic(message);
        hideLoading();
        setExportBusy(false);
    }

    function addExportDiagnostic(error, context) {
        var failure = ns.core.failure(error, Object.assign({requestId: state.exportRequestId}, context || {}));
        if (!state.ifcModel) state.ifcModel = { diagnostics: [] };
        if (!state.ifcModel.diagnostics) state.ifcModel.diagnostics = [];
        state.ifcModel.diagnostics.push(
            new ns.core.Diagnostic('error', failure.stage === 'viewer' ? 'FDS display failed' : 'FDS export failed',
                failure.message + ' (stage: ' + failure.stage + ')', failure)
        );
        renderDiagnostics();
    }

    function cleanupExportWorker() {
        if (state.fdsParseReject) {
            var reject = state.fdsParseReject;
            state.fdsParseReject = null;
            var error = new Error('FDS display cancelled'); error.name = 'AbortError';
            reject(error);
        }
        if (state.exportWorker) state.exportWorker.terminate();
        if (state.exportWorkerUrl) URL.revokeObjectURL(state.exportWorkerUrl);
        state.exportWorker = null;
        state.exportWorkerUrl = null;
    }

    function parseFdsInWorker(text, requestId) {
        return new Promise(function (resolve, reject) {
            var handle = ns.workers.createExportWorker();
            state.exportWorker = handle.worker; state.exportWorkerUrl = handle.url;
            state.fdsParseReject = reject;
            function finish(error, model) {
                state.fdsParseReject = null;
                cleanupExportWorker();
                if (error) reject(error); else resolve(model);
            }
            handle.worker.addEventListener('message', function (event) {
                if (requestId !== state.exportRequestId) return;
                var result = event.data || {};
                if (result.type === 'complete') finish(null, result.model);
                else if (result.type === 'error') finish(new Error(result.message || 'FDS display parsing failed'));
            });
            handle.worker.addEventListener('error', function (event) {
                if (requestId !== state.exportRequestId) return;
                finish(new Error(event.message || 'FDS display worker failed'));
            });
            handle.worker.postMessage({type:'parse-fds', requestId:requestId, text:text});
        });
    }

    function cancelPendingExport() {
        state.exportRequestId += 1;
        if (ns.verified.cancel) ns.verified.cancel().catch(function () {});
        cleanupExportWorker();
        setExportBusy(false);
    }

    function clearGeneratedFds() {
        state.verifiedJobId = null;
        state.generatedFdsText = null;
        state.generatedFdsName = null;
        if (viewer.cancelVerifiedLoad) viewer.cancelVerifiedLoad();
        state.lastArtifactLinks = null;
        state.lastAuditReport = null;
        state.lastManifest = null;
        if (ns.ui && ns.ui.auditDrawer && ns.ui.auditDrawer.clearArtifacts) ns.ui.auditDrawer.clearArtifacts();
        var scenario = ns.workbench && ns.workbench.state && ns.workbench.state.scenarioStore;
        if (scenario && scenario.setInvalidBaseMapping) {
            var previousBase = scenario.getScenarioSpec ? scenario.getScenarioSpec().mappingBundleSha : null;
            scenario.setInvalidBaseMapping(previousBase, 'Conversion result cleared');
        }
        if (els.saveFds) els.saveFds.disabled = true;
        if (els.openAudit) els.openAudit.disabled = true;
        if (els.saveManifest) els.saveManifest.disabled = true;
        var fdsDrawerBtn = document.getElementById('btn-download-fds');
        if (fdsDrawerBtn && (!state.lastArtifactLinks || !state.lastArtifactLinks.fds)) {
            fdsDrawerBtn.removeAttribute('href');
            fdsDrawerBtn.removeAttribute('download');
            fdsDrawerBtn.classList.add('disabled');
            fdsDrawerBtn.style.pointerEvents = 'none';
            fdsDrawerBtn.style.opacity = '0.5';
            fdsDrawerBtn.setAttribute('aria-disabled', 'true');
        }
    }

    function exportVerified() {
        if (state.exportBusy) return;
        if (!state.ifcSourceText && !state.currentIfcFile && !ns.verified.hasFiles()) {
            addExportDiagnostic('IFC source not in memory — please reopen the file.');
            return;
        }
        clearGeneratedFds();
        // The single background worker should convert immediately instead of
        // waiting for a now-unneeded source preview to finish first.
        ns.ifc.backendPreview.cancel();
        state.ifcLoadRequestId = (state.ifcLoadRequestId || 0) + 1;

        var fileLabel = (state.ifcFileName || (state.ifcModel && state.ifcModel.fileName) || 'IFC model');
        showLoading('Verified Conversion: ' + fileLabel, 'Processing with IfcOpenShell & OpenCASCADE...');
        setExportBusy(true, 'convert-verified');
        var generation = ++state.exportRequestId;
        var cancelButton = document.getElementById('verified-cancel');
        if (cancelButton) cancelButton.disabled = false;

        var blob = state.currentIfcFile || new File([state.ifcSourceText || ''], state.ifcFileName || 'model.ifc');
        var forceGeom = !!(els.verifiedForceGeom && els.verifiedForceGeom.checked);
        var cellSize = Number(els.verifiedCellSize && els.verifiedCellSize.value) || Number(els.meshCellSize && els.meshCellSize.value) || 0.20;
        ns.verified.run(blob, {
            cell_size: cellSize,
            all_geom: forceGeom,
        }, function (message, detail, activeJobId) {
            if (generation !== state.exportRequestId) return;
            state.verifiedJobId = activeJobId;
            if (els.ifcLoadingStage) els.ifcLoadingStage.textContent = message;
        })
        .then(async function (data) {
            if (generation !== state.exportRequestId) return;
            state.verifiedJobId = data && data.job_id;
            setLoadingProgress(0.85, 'Loading conversion artifacts.');
            if (!data || !data.artifacts) throw new Error('Missing conversion artifacts');
            state.lastArtifactLinks = data.artifacts;
            var summary = Object.assign({}, data, {configuration: {}, matched_count: (data.coverage || {}).geometry || 0});
            state.lastAuditReport = summary;
            state.lastManifest = null;
            if (els.openAudit) els.openAudit.disabled = false;
            if (els.saveManifest) els.saveManifest.disabled = false;
            if (viewer.bindVerifiedArtifacts) viewer.bindVerifiedArtifacts(data.artifacts);

            var manifestPromise = (data.artifacts.manifest && data.artifacts.manifest.url)
                ? fetch(data.artifacts.manifest.url, {headers: ns.verified.getAuthHeaders()}).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; })
                : Promise.resolve(null);
            var reportPromise = (data.artifacts.report && data.artifacts.report.url)
                ? fetch(data.artifacts.report.url, {headers: ns.verified.getAuthHeaders()}).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; })
                : Promise.resolve(null);

            var extraArtifacts = await Promise.all([manifestPromise, reportPromise]);
            if (generation !== state.exportRequestId) return;
            var manifestData = extraArtifacts[0];
            var fullReport = Object.assign({}, summary, extraArtifacts[1] || {});
            if (data && data.artifacts) {
                fullReport.artifacts = data.artifacts;
            }
            state.lastManifest = manifestData;
            state.lastAuditReport = fullReport;

            if (ns.workbench && ns.workbench.state && ns.workbench.state.selectionStore && manifestData) {
                var records = manifestData.records || manifestData.elements || [];
                ns.workbench.state.selectionStore.hydrateManifest(records, fullReport);
            }

            renderAuditReport(fullReport); openAudit();
            var authH = (ns.verified && typeof ns.verified.getAuthHeaders === 'function') ? ns.verified.getAuthHeaders() : {};
            var response = await fetch(data.artifacts.fds.url, { headers: authH });
            if (!response.ok) throw new Error('FDS artifact unavailable');
            var text = await response.text();
            if (generation !== state.exportRequestId) return;
            var base = (data.source_filename || state.ifcFileName || 'model').replace(/\.[^.]+$/, '');
            var fileName = base + (data.status === 'MAPPING_VERIFIED' ? '_mapping_verified.fds' : '_diagnostic_unaccepted.fds');
            state.generatedFdsText = text; state.generatedFdsName = fileName;
            if (els.saveFds) els.saveFds.disabled = false;
            setLoadingProgress(0.95, 'Preparing FDS display.');
            var displayModel = await parseFdsInWorker(text, generation);
            if (generation !== state.exportRequestId) return;
            loadFdsText(text, fileName, displayModel);
            if (ns.workbench && ns.workbench.state && ns.workbench.state.scenarioStore) {
                var mSha = (manifestData && (manifestData.bundle_sha256 || manifestData.fds_sha256 || manifestData.source_sha256)) ||
                           (data.artifacts && data.artifacts.manifest && data.artifacts.manifest.sha256) ||
                           (data.artifacts && data.artifacts.fds && data.artifacts.fds.sha256);
                if (mSha) {
                    var isVerified = (data.status === 'MAPPING_VERIFIED' || data.mapping_status === 'MAPPING_VERIFIED');
                    if (isVerified) {
                        ns.workbench.state.scenarioStore.setBaseMapping(mSha);
                    } else if (typeof ns.workbench.state.scenarioStore.setInvalidBaseMapping === 'function') {
                        ns.workbench.state.scenarioStore.setInvalidBaseMapping(mSha, data.status || data.mapping_status);
                    }
                }
            }
            setupClippingForBounds(boundsForClipping());
        })
        .catch(function (err) {
            if (generation !== state.exportRequestId || err.name === 'AbortError') return;
            state.verifiedJobId = err.jobId || state.verifiedJobId;
            hideLoading();
            setExportBusy(false);
            addExportDiagnostic(err, {stage: 'verified_conversion', jobId: state.verifiedJobId});
            updateGlobalStatusBadge('FAILED');
            if (state.verifiedJobId) exposeFailedCheckpoints(state.verifiedJobId);
        }).finally(function () {
            if (generation === state.exportRequestId) { cleanupExportWorker(); hideLoading(); setExportBusy(false); }
        });
    }

    function renderAuditReport(report) {
        if (!report) return;
        updateGlobalStatusBadge(report.status);
        if (!els.auditBody) return;
        if (!report) {
            els.auditBody.innerHTML = '<p>No audit report available. Run <strong>Verified Conversion</strong> to generate a complete 3-tier audit.</p>';
            return;
        }
        els.auditBody.replaceChildren();
        function line(tag, text, parent) {
            var node = document.createElement(tag);
            node.textContent = text;
            (parent || els.auditBody).appendChild(node);
            return node;
        }
        line('h3', 'Acceptance: ' + report.status);
        line('p', 'Mapping: ' + report.mapping_status + '; simulation: ' + report.simulation_status);
        var roles = (report.coverage || {}).representation || {};
        line('p', 'Reference objects: ' + (roles.REFERENCE_GEOMETRY || 0) + '; passive obstacles: ' + (roles.PASSIVE_OBSTACLE || 0) + '; operational objects: ' + (roles.OPERATIONAL_MEP || 0));
        var pending = (report.coverage || {}).boundary_pending || 0;
        line('p', 'Pending boundary treatment: ' + (Array.isArray(pending) ? pending.length : pending));
        if (report.research) line('p', 'Research acceptance: ' + report.research.research_acceptance + '; reference parity: ' + report.research.parity_status);
        var domain = (report.configuration || {}).simulation_domain;
        if (domain) line('p', 'Fixed domain (m): X ' + domain.xmin + ' to ' + domain.xmax + '; Y ' + domain.ymin + ' to ' + domain.ymax + '; Z ' + domain.zmin + ' to ' + domain.zmax);
        if (report.total_elements_checked !== undefined) line('p', 'Matched solids: ' + report.matched_count + ' / accounted entities: ' + report.total_elements_checked);
        var exported = (report.coverage || {}).fds_export;
        if (exported) {
            line('p', 'FDS written: ' + exported.entities + ' entities / ' + exported.primitives + ' primitives (' + exported.obst + ' OBST, ' + exported.geom + ' GEOM). Independently verified: ' + exported.verified_entities + '.');
            if (exported.comparisons_skipped_for_source_errors) line('p', 'Source topology errors stopped the remaining solid comparisons. The FDS download is available as an unaccepted diagnostic artifact.');
        }
        var scope = (report.configuration || {}).scope || {};
        var storeys = (((report.coverage || {}).scope || {}).selected_storeys || []);
        if (!Array.isArray(storeys)) storeys = [String(storeys) + ' selected (see configuration artifact)'];
        line('p', 'Export storeys: ' + (storeys.length ? storeys.join(', ') : 'All storeys'));
        if (scope.bounding_box) line('p', 'Export volume (m): ' + ['xmin','xmax','ymin','ymax','zmin','zmax'].map(function (key) { return key + ': ' + scope.bounding_box[key]; }).join(', '));
        line('p', 'Retained crossing elements: ' + (((report.coverage || {}).scope || {}).BOUNDARY_RETAINED || 0));
        var list = line('ul', '');
        Object.keys(report.gates || {}).forEach(function (name) {
            var gate = report.gates[name];
            line('li', name + ': ' + gate.status + (gate.reason ? ' — ' + gate.reason : ''), list);
        });
        (report.findings || []).forEach(function (f) { line('p', f.severity + ' — ' + f.element_id + ': ' + f.detail); });
        renderAuditDrawer(report);
    }

    function openAudit() {
        if (!els.auditModal) return;
        renderAuditReport(state.lastAuditReport);
        els.auditModal.hidden = false;
    }

    function closeAudit() {
        if (!els.auditModal) return;
        els.auditModal.hidden = true;
    }

    function checkBackendHealth() {
        var apiUrl = (window.location.protocol === 'http:' || window.location.protocol === 'https:')
            ? '/api/health'
            : 'http://127.0.0.1:8000/api/health';

        fetch(apiUrl, { method: 'GET' })
            .then(function (res) {
                if (res.ok) return res.json();
                throw new Error('HTTP ' + res.status);
            })
            .then(function (data) {
                if (data && data.status === 'ok') {
                    state.backendOnline = true;
                    if (els.backendStatusIndicator) {
                        els.backendStatusIndicator.className = 'status-indicator online';
                    }
                    if (els.backendStatusText) {
                        els.backendStatusText.textContent = 'Backend: Online (IfcOpenShell v' + (data.version || '0.2.0') + ')';
                    }
                    refreshConversionActions();
                }
            })
            .catch(function () {
                state.backendOnline = false;
                if (els.backendStatusIndicator) {
                    els.backendStatusIndicator.className = 'status-indicator offline';
                }
                if (els.backendStatusText) {
                    els.backendStatusText.textContent = 'Backend: Offline (Run: python -m ifc_to_fds serve)';
                }
                refreshConversionActions();
            });
    }

    function downloadText(fileName, text) {
        var blob = new Blob([text], { type: 'text/plain' });
        var url = URL.createObjectURL(blob);
        var link = document.createElement('a');
        link.href = url;
        link.download = fileName;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    }

    function countConvertibleIfc(model) {
        return exporter.getExportableElements(model, currentExportOptions()).length;
    }

    function currentExportOptions() {
        var cellSize = Math.max(0.05, Number(els.meshCellSize && els.meshCellSize.value) || 0.1);
        var voxelSize = Math.max(0.05, Number(els.voxelSize && els.voxelSize.value) || 0.1);
        return {
            mode: 'hybrid',
            cellSize: cellSize,
            voxelSize: voxelSize,
            openingThickening: Math.max(0, Number(els.openingThickening && els.openingThickening.value) || 0),
            openingVoxelPolicy: els.openingVoxelPolicy ? els.openingVoxelPolicy.value : 'smaller',
            includeFillSolids: !!(els.includeFillSolids && els.includeFillSolids.checked),
            includeReviewSolids: !!(els.includeReviewSolids && els.includeReviewSolids.checked),
            // Default to HOLE approach (cleaner FDS, exact rectangular cutouts). Voxelization
            // is kept as a fallback for IFCs with non-axis-aligned or curved openings.
            useObstHoles: !els.conversionApproach || els.conversionApproach.value !== 'voxel',
            forceObstStepIds: Object.keys(state.forceObstStepIds),
            excludedStepIds: Object.keys(state.excludedStepIds),
            excludedItemIds: Object.keys(state.excludedItemIds),
            boxFriendlyThreshold: Math.max(0.5, Math.min(1, Number(els.obstThreshold && els.obstThreshold.value) || 0.8))
        };
    }

    function normalizeSelection(data) {
        if (!data) return [];
        return Array.isArray(data) ? data : [data];
    }

    function selectedGeneratedGeomStepIds(data) {
        return normalizeSelection(data).map(function (item) {
            if (!item || String(item.type || '').indexOf('GEOM') !== 0 || !item.ifcSource) return null;
            return String(item.ifcSource.stepId || '').replace(/^#/, '') || null;
        }).filter(Boolean);
    }

    function selectedIfcStepIds(data) {
        return normalizeSelection(data).map(function (item) {
            if (!item || item.type !== 'IFC') return null;
            var raw = item.raw || {};
            var id = raw.id || raw.stepId || raw.STEP_ID || (raw.__ifcSource && raw.__ifcSource.stepId);
            return id ? String(id).replace(/^#/, '') : null;
        }).filter(Boolean);
    }

    // Splits the current selection into source-level deletions (IFC meshes — cascade through
    // all their derived OBST/GEOM) and primitive-level deletions (OBST/GEOM meshes — remove
    // just that one instance, leaving sibling primitives from the same source untouched).
    function splitSelectionForDelete(data) {
        var stepIds = [];
        var itemIds = [];
        normalizeSelection(data).forEach(function (item) {
            if (!item) return;
            if (item.type === 'IFC') {
                var raw = item.raw || {};
                var sid = raw.id || raw.stepId || raw.STEP_ID;
                if (sid) stepIds.push(String(sid).replace(/^#/, ''));
                return;
            }
            // OBST / GEOM primitive — exclude this specific itemId only.
            var primitiveId = item.id || (item.raw && item.raw.ID) || (item.ifcSource && item.ifcSource.itemId);
            if (primitiveId) itemIds.push(String(primitiveId));
        });
        return { stepIds: stepIds, itemIds: itemIds };
    }

    function renderStructuredInspector(item) {
        if (ns.ui && ns.ui.inspectorPanel) {
            ns.ui.inspectorPanel.renderStructuredInspector(item);
        }
    }

    function updateSourcePill(file, model) {
        var nameEl = document.getElementById('ifc-source-name');
        if (nameEl) nameEl.textContent = file ? file.name : ((model && model.fileName) || 'Loaded model');
        var sizeEl = document.getElementById('ifc-size-tag');
        if (sizeEl) sizeEl.textContent = file ? (file.size / (1024 * 1024)).toFixed(1) + ' MB' : '-- MB';
        var schemaEl = document.getElementById('ifc-schema-tag');
        if (schemaEl) schemaEl.textContent = (model && model.schema) || 'IFC';

        var b = model && (model.convertibleBounds || model.bounds);
        if (b) {
            ['xmin', 'xmax', 'ymin', 'ymax', 'zmin', 'zmax'].forEach(function (axis) {
                var domainInput = document.getElementById('verified-domain-' + axis);
                if (domainInput && b[axis] !== undefined) {
                    domainInput.value = Number(b[axis]).toFixed(2);
                }
            });
            updateDomainEstimates();
        }
    }

    function setWorkflowMode(mode) {
        var isVerified = mode === 'verified';
        if (els.modeTabVerified) els.modeTabVerified.classList.toggle('active', isVerified);
        if (els.modeTabQuick) els.modeTabQuick.classList.toggle('active', !isVerified);
        var target = isVerified ? els.containerVerified : els.containerQuick;
        if (target && target.scrollIntoView) {
            target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    }

    function updateDomainEstimates() {
        if (ns.ui && ns.ui.domainPanel) {
            ns.ui.domainPanel.updateDomainEstimates(els);
        }
    }

    function checkScopedDomainPreflight() {
        if (ns.ui && ns.ui.domainPanel) {
            ns.ui.domainPanel.checkScopedDomainPreflight(els);
        }
    }

    function toggleAuditDrawer() {
        if (ns.ui && ns.ui.auditDrawer) {
            ns.ui.auditDrawer.toggleAuditDrawer(els);
        }
    }

    function updateGlobalStatusBadge(status) {
        var badge = document.getElementById('global-run-status');
        var label = document.getElementById('global-status-label');
        if (!badge || !label) return;
        badge.className = 'global-status-badge';
        if (status === 'MAPPING_VERIFIED' || status === 'SIMULATION_VERIFIED') {
            badge.classList.add('verified');
            label.textContent = 'VERIFIED';
        } else if (status === 'INCONCLUSIVE') {
            badge.classList.add('inconclusive');
            label.textContent = 'INCONCLUSIVE';
        } else if (status === 'REJECTED' || status === 'FAILED') {
            badge.classList.add('rejected');
            label.textContent = status;
        } else {
            label.textContent = status || 'NOT RUN';
        }
    }

    function updateColorModeLegend(mode) {
        var container = document.getElementById('legend-swatches');
        if (!container) return;
        if (mode === 'mapping') {
            container.innerHTML = '<div class="legend-swatch-item"><span class="swatch-color" style="background:#3b82f6"></span><span>OBST</span></div>' +
                '<div class="legend-swatch-item"><span class="swatch-color" style="background:#f59e0b"></span><span>GEOM</span></div>' +
                '<div class="legend-swatch-item"><span class="swatch-color" style="background:#64748b"></span><span>Reference</span></div>' +
                '<div class="legend-swatch-item"><span class="swatch-color" style="background:#ef4444"></span><span>Unsupported</span></div>';
        } else if (mode === 'verification') {
            container.innerHTML = '<div class="legend-swatch-item"><span class="swatch-color" style="background:#10b981"></span><span>PASS</span></div>' +
                '<div class="legend-swatch-item"><span class="swatch-color" style="background:#f59e0b"></span><span>INCONCLUSIVE</span></div>' +
                '<div class="legend-swatch-item"><span class="swatch-color" style="background:#ef4444"></span><span>FAIL / REJECT</span></div>' +
                '<div class="legend-swatch-item"><span class="swatch-color" style="background:#64748b"></span><span>NOT RUN</span></div>';
        } else if (mode === 'ifc-type') {
            container.innerHTML = '<div class="legend-swatch-item"><span class="swatch-color" style="background:#60a5fa"></span><span>Wall / Column</span></div>' +
                '<div class="legend-swatch-item"><span class="swatch-color" style="background:#a78bfa"></span><span>Slab / Roof</span></div>' +
                '<div class="legend-swatch-item"><span class="swatch-color" style="background:#34d399"></span><span>Door / Window</span></div>' +
                '<div class="legend-swatch-item"><span class="swatch-color" style="background:#f472b6"></span><span>MEP / Flow</span></div>';
        } else if (mode === 'mep') {
            container.innerHTML = '<div class="legend-swatch-item"><span class="swatch-color" style="background:#ef4444"></span><span>Fire Suppression</span></div>' +
                '<div class="legend-swatch-item"><span class="swatch-color" style="background:#f97316"></span><span>Smoke Extract</span></div>' +
                '<div class="legend-swatch-item"><span class="swatch-color" style="background:#06b6d4"></span><span>Ventilation</span></div>' +
                '<div class="legend-swatch-item"><span class="swatch-color" style="background:#3b82f6"></span><span>Plumbing</span></div>';
        }
    }

    function renderAuditDrawer(report) {
        if (ns.ui && ns.ui.auditDrawer) {
            ns.ui.auditDrawer.renderAuditDrawer(report, viewer);
        }
    }

    function exposeFailedCheckpoints(jobId) {
        if (ns.ui && ns.ui.auditDrawer) {
            ns.ui.auditDrawer.exposeFailedCheckpoints(jobId);
        }
    }

})(window.IfcFds);
