(function (ns) {
    var PRODUCT_TYPES = {
        IFCWALL: true,
        IFCWALLSTANDARDCASE: true,
        IFCSLAB: true,
        IFCDOOR: true,
        IFCWINDOW: true,
        IFCSTAIR: true,
        IFCSTAIRFLIGHT: true,
        IFCMEMBER: true,
        IFCRAILING: true,
        IFCROOF: true,
        IFCCOLUMN: true,
        IFCBEAM: true,
        IFCBUILDINGELEMENTPROXY: true,
        IFCFURNISHINGELEMENT: true,
        IFCFLOWSEGMENT: true,
        IFCFLOWFITTING: true,
        IFCFLOWTERMINAL: true,
        IFCDUCTSEGMENT: true,
        IFCPIPESEGMENT: true,
        IFCAIRTERMINAL: true,
        IFCELEMENTASSEMBLY: true,
        IFCSPACE: true
    };
    var REVIEW_TYPES = {
        IFCBUILDINGELEMENTPROXY: 'Building element proxy',
        IFCFURNISHINGELEMENT: 'Furnishing element',
        IFCFLOWSEGMENT: 'Flow segment',
        IFCFLOWFITTING: 'Flow fitting',
        IFCFLOWTERMINAL: 'Flow terminal',
        IFCDUCTSEGMENT: 'Duct segment',
        IFCPIPESEGMENT: 'Pipe segment',
        IFCAIRTERMINAL: 'Air terminal',
        IFCELEMENTASSEMBLY: 'Element assembly',
        IFCRAILING: 'Railing'
    };

    function IfcAdapter() {}

    IfcAdapter.prototype.readFile = function (file, onProgress, options) {
        var self = this;
        return readText(file).then(function (text) {
            var fileName = file ? file.name : 'IFC model';
            return (onProgress || options)
                ? self.parseAsync(text, fileName, onProgress, options)
                : self.parse(text, fileName, options);
        });
    };

    IfcAdapter.prototype.parse = function (text, fileName, options) {
        var ctx = beginParse(text, options);
        ctx.step.entities.forEach(function (entity) { processEntity(ctx, entity); });
        return finishParse(ctx, fileName);
    };

    // Shards the entity list across N worker scripts, each running the same beginParse +
    // processEntity pipeline on its slice. Returns a merged model identical to parseAsync.
    // Falls back to a single worker / serial parse cleanly via the existing parseAsync if the
    // worker can't start.
    IfcAdapter.prototype.parseAsyncParallel = function (text, fileName, onProgress, options, workerCount) {
        var self = this;
        var factory = window.IfcFds && window.IfcFds.workers && window.IfcFds.workers.createParseShardWorker;
        if (!factory) return self.parseAsync(text, fileName, onProgress, options);

        var ctx = beginParse(text, options);
        var entities = ctx.step.entities;
        var total = entities.length;
        var shards = Math.max(1, Math.min(workerCount || (navigator.hardwareConcurrency || 4), 8));
        if (total < 50000) {
            // Sharding overhead (each worker re-parses STEP text + builds indexes) only pays
            // off on big models; small models like FZK (44k entities) and Duplex (27k) are
            // measurably faster on the main-thread async path.
            return self.parseAsync(text, fileName, onProgress, options);
        }
        var shardSize = Math.ceil(total / shards);
        var completed = 0;

        function runShard(shardIndex) {
            var startIndex = shardIndex * shardSize;
            var endIndex = Math.min(startIndex + shardSize, total);
            return new Promise(function (resolve, reject) {
                var handle;
                try { handle = factory(); } catch (err) { reject(err); return; }
                var worker = handle.worker;
                worker.onmessage = function (event) {
                    var data = event.data || {};
                    if (data.type === 'error') {
                        cleanup();
                        reject(new Error(data.message || 'parse shard failed'));
                        return;
                    }
                    if (data.type !== 'parse-shard-result') return;
                    cleanup();
                    completed += 1;
                    if (onProgress) onProgress(completed / shards);
                    resolve(data);
                };
                worker.onerror = function (event) {
                    cleanup();
                    reject(new Error(event.message || 'parse shard worker error'));
                };
                worker.postMessage({
                    type: 'parse-shard',
                    requestId: shardIndex,
                    shardIndex: shardIndex,
                    text: text,
                    startIndex: startIndex,
                    endIndex: endIndex
                });
                function cleanup() {
                    try { worker.terminate(); } catch (_) { /* ignore */ }
                    if (handle.url) {
                        try { URL.revokeObjectURL(handle.url); } catch (_) { /* ignore */ }
                    }
                }
            });
        }

        var jobs = [];
        for (var i = 0; i < shards; i += 1) jobs.push(runShard(i));

        return Promise.all(jobs).then(function (results) {
            // Merge each shard's partial state back into the main context, then finish.
            results.forEach(function (r) {
                if (Array.isArray(r.elements)) {
                    r.elements.forEach(function (el) { ctx.elements.push(el); });
                }
                if (r.unsupported) {
                    Object.keys(r.unsupported).forEach(function (k) {
                        ctx.unsupported[k] = (ctx.unsupported[k] || 0) + r.unsupported[k];
                    });
                }
                if (Array.isArray(r.diagnostics)) {
                    r.diagnostics.forEach(function (d) { ctx.diagnostics.push(d); });
                }
                if (r.voidStatsApplied) {
                    Object.keys(r.voidStatsApplied).forEach(function (k) { ctx.voidStats.applied[k] = true; });
                }
                if (typeof r.openingMaskCount === 'number') ctx.openingMaskCount += r.openingMaskCount;
            });
            return finishParse(ctx, fileName);
        }).catch(function (err) {
            console.warn('parallel parse failed, falling back to serial:', err);
            return self.parseAsync(text, fileName, onProgress, options);
        });
    };

    // Same work as parse() but with cooperative yields every CHUNK entities so a large
    // IFC doesn't freeze the main thread. onProgress(fraction) is called between chunks.
    IfcAdapter.prototype.parseAsync = function (text, fileName, onProgress, options) {
        var ctx = beginParse(text, options);
        var entities = ctx.step.entities;
        var total = entities.length;
        var CHUNK = 800;
        var idx = 0;

        function processChunk() {
            var end = Math.min(idx + CHUNK, total);
            for (; idx < end; idx += 1) processEntity(ctx, entities[idx]);
            if (onProgress) onProgress(total ? idx / total : 1);
            if (idx < total) {
                return new Promise(function (resolve) { setTimeout(resolve, 0); }).then(processChunk);
            }
            return finishParse(ctx, fileName);
        }

        return Promise.resolve().then(processChunk);
    };

    function beginParse(text, options) {
        var diagnostics = [];
        var step = new StepModel(text);
        var scale = detectLengthScale(step, diagnostics);
        var voidsByHost = indexVoidsByHost(step);
        return {
            step: step,
            diagnostics: diagnostics,
            scale: scale,
            elements: [],
            unsupported: {},
            stairChildIds: indexStairChildIds(step),
            voidsByHost: voidsByHost,
            hostIdsByOpening: indexHostIdsByOpening(voidsByHost),
            openingsByFill: indexOpeningsByFill(step),
            voidStats: { applied: {}, total: countIndexedVoids(voidsByHost) },
            openingMaskCount: 0,
            skipBoxOpenings: !!(options && options.skipBoxOpenings)
        };
    }

    function processEntity(ctx, entity) {
        if (!isSupportedProduct(entity, ctx.stairChildIds)) return;
        var step = ctx.step;

        var placement = step.transformForLocalPlacement(entity.args[5]);
        var representation = step.ref(entity.args[6]);
        var items = representationItems(step, representation);
        var mesh = emptyMesh();
        var hostOpenings = ctx.voidsByHost[entity.id] || [];
        var openingExtrusions = extrusionsForOpenings(
            step,
            hostOpenings,
            ctx.diagnostics,
            ctx.unsupported
        );
        var openings = meshesForOpenings(step, hostOpenings, ctx.diagnostics, ctx.unsupported);
        var fillOpenings = meshesForOpenings(step, ctx.openingsByFill[entity.id] || [], ctx.diagnostics, ctx.unsupported);
        ctx.openingMaskCount += openings.length;
        var displayMesh = openingExtrusions.length ? emptyMesh() : null;
        var displayDiffers = false;

        items.forEach(function (item) {
            var itemMesh = meshForRepresentationItem(step, item, placement, ctx.diagnostics, ctx.unsupported);
            if (displayMesh) {
                var carved = carveItemOpenings(itemMesh, openingExtrusions, ctx.diagnostics, ctx.voidStats, { skipBoxOpenings: ctx.skipBoxOpenings });
                appendMesh(mesh, carved.exportMesh);
                appendMesh(displayMesh, carved.displayMesh);
                if (carved.displayMesh !== carved.exportMesh) displayDiffers = true;
            } else {
                appendMesh(mesh, itemMesh);
            }
        });

        scaleMesh(mesh, ctx.scale);
        if (displayMesh && displayDiffers) scaleMesh(displayMesh, ctx.scale);
        openings.forEach(function (opening) {
            scaleMesh(opening.mesh, ctx.scale);
        });
        fillOpenings.forEach(function (opening) {
            scaleMesh(opening.mesh, ctx.scale);
        });
        if (!mesh.vertices.length || !mesh.faces.length) {
            ns.core.addDiagnostic(
                ctx.diagnostics,
                'warning',
                'IFC element skipped',
                labelForEntity(entity) + ' has no supported Body geometry yet.'
            );
            return;
        }

        var bounds = boundsForVertices(mesh.vertices);
        var classification = classifyElement(entity, bounds);
        ctx.elements.push({
            stepId: entity.id,
            ifcType: entity.type,
            globalId: asText(entity.args[0]),
            name: asText(entity.args[2]) || entity.type + ' #' + entity.id,
            convertible: classification.convertible,
            reference: classification.reference,
            exportAsSolid: classification.exportAsSolid !== false,
            canExportAsSolid: classification.canExportAsSolid !== false,
            fdsRole: classification.fdsRole,
            conversionNote: classification.note,
            openings: openings,
            fillOpeningBounds: boundsForOpeningMeshes(fillOpenings),
            fillHostStepIds: fillOpenings.map(function (opening) {
                return ctx.hostIdsByOpening[opening.stepId];
            }).filter(Boolean),
            mesh: mesh,
            displayMesh: (displayMesh && displayDiffers) ? displayMesh : undefined,
            bounds: bounds,
            raw: {
                id: '#' + entity.id,
                type: entity.type,
                globalId: asText(entity.args[0]),
                name: asText(entity.args[2]),
                convertible: classification.convertible,
                exportAsSolid: classification.exportAsSolid !== false,
                canExportAsSolid: classification.canExportAsSolid !== false,
                fdsRole: classification.fdsRole,
                conversionNote: classification.note
            }
        });
    }

    function finishParse(ctx, fileName) {
        attachFillHostBounds(ctx.elements);

        Object.keys(ctx.unsupported).forEach(function (type) {
            ns.core.addDiagnostic(
                ctx.diagnostics,
                'info',
                'Unsupported IFC geometry: ' + type,
                ctx.unsupported[type] + ' representation item(s) were skipped in this first importer milestone.'
            );
        });

        var appliedVoidCount = Object.keys(ctx.voidStats.applied).length;
        if (appliedVoidCount) {
            ns.core.addDiagnostic(
                ctx.diagnostics,
                'success',
                'IFC voids applied',
                appliedVoidCount + ' opening void(s) were subtracted from directly extruded host geometry.'
            );
        }
        if (ctx.voidStats.total > appliedVoidCount) {
            ns.core.addDiagnostic(
                ctx.diagnostics,
                'info',
                'IFC voids awaiting broader CSG support',
                (ctx.voidStats.total - appliedVoidCount) + ' opening void(s) could not yet be subtracted from their host representation.'
            );
        }
        if (ctx.openingMaskCount) {
            ns.core.addDiagnostic(
                ctx.diagnostics,
                'success',
                'IFC voxel opening masks ready',
                ctx.openingMaskCount + ' host opening volume(s) will carve window, door, and shaft apertures from voxel OBST export.'
            );
        }

        if (!ctx.elements.length) {
            ns.core.addDiagnostic(
                ctx.diagnostics,
                'warning',
                'No convertible IFC elements',
                'This importer currently supports IfcExtrudedAreaSolid with rectangle/polyline profiles and IfcFacetedBrep.'
            );
        } else {
            ns.core.addDiagnostic(
                ctx.diagnostics,
                'success',
                'IFC import ready',
                ctx.elements.length + ' element(s) were converted to browser geometry in metres.'
            );
        }

        return {
            fileName: fileName,
            schema: ctx.step.schema,
            unitScale: ctx.scale,
            elements: ctx.elements,
            meshes: ctx.elements.map(function (element) { return element.mesh; }),
            bounds: boundsForElements(ctx.elements),
            convertibleBounds: boundsForElements(ctx.elements.filter(function (element) { return element.convertible !== false; })),
            diagnostics: ctx.diagnostics,
            stats: {
                entities: ctx.step.entities.length,
                elements: ctx.elements.length
            }
        };
    }

    function StepModel(text) {
        this.entities = parseEntities(text);
        this.byId = {};
        this.schema = detectSchema(text);
        this._placementCache = {};
        this._axisCache = {};

        for (var i = 0; i < this.entities.length; i += 1) {
            this.byId[this.entities[i].id] = this.entities[i];
        }
    }

    StepModel.prototype.each = function (callback) {
        this.entities.forEach(callback);
    };

    StepModel.prototype.ref = function (value) {
        var id = refId(value);
        return id ? this.byId[id] : null;
    };

    StepModel.prototype.point = function (value) {
        var entity = this.ref(value) || (value && value.type === 'IFCCARTESIANPOINT' ? value : null);
        if (!entity || entity.type !== 'IFCCARTESIANPOINT') return [0, 0, 0];
        var coords = Array.isArray(entity.args[0]) ? entity.args[0] : [];
        return [
            numberOr(coords[0], 0),
            numberOr(coords[1], 0),
            numberOr(coords[2], 0)
        ];
    };

    StepModel.prototype.direction = function (value, fallback) {
        var entity = this.ref(value) || (value && value.type === 'IFCDIRECTION' ? value : null);
        if (!entity || entity.type !== 'IFCDIRECTION') return fallback.slice();
        var ratios = Array.isArray(entity.args[0]) ? entity.args[0] : [];
        return normalize([
            numberOr(ratios[0], fallback[0]),
            numberOr(ratios[1], fallback[1]),
            numberOr(ratios[2], fallback[2])
        ], fallback);
    };

    StepModel.prototype.transformForAxisPlacement = function (value) {
        if (!value) return identityTransform();
        var id = refId(value) || (value.id || null);
        if (id && this._axisCache[id]) return this._axisCache[id];

        var entity = this.ref(value) || value;
        if (!entity) return identityTransform();

        var tx = identityTransform();
        if (entity.type === 'IFCAXIS2PLACEMENT3D') {
            var origin3 = this.point(entity.args[0]);
            var z3 = this.direction(entity.args[1], [0, 0, 1]);
            var x3 = this.direction(entity.args[2], [1, 0, 0]);
            tx = axesTransform(origin3, x3, z3);
        } else if (entity.type === 'IFCAXIS2PLACEMENT2D') {
            var origin2 = this.point(entity.args[0]);
            var x2 = this.direction(entity.args[1], [1, 0, 0]);
            tx = axesTransform(origin2, x2, [0, 0, 1]);
        }

        if (id) this._axisCache[id] = tx;
        return tx;
    };

    StepModel.prototype.transformForLocalPlacement = function (value) {
        var id = refId(value);
        if (!id) return identityTransform();
        if (this._placementCache[id]) return this._placementCache[id];

        var entity = this.byId[id];
        if (!entity || entity.type !== 'IFCLOCALPLACEMENT') return identityTransform();

        var parent = this.transformForLocalPlacement(entity.args[0]);
        var local = this.transformForAxisPlacement(entity.args[1]);
        var result = composeTransform(parent, local);
        this._placementCache[id] = result;
        return result;
    };

    function parseEntities(text) {
        var entities = [];
        var i = 0;

        while (i < text.length) {
            var hash = text.indexOf('#', i);
            if (hash < 0) break;
            var eq = text.indexOf('=', hash);
            if (eq < 0) break;
            var idText = text.slice(hash + 1, eq).trim();
            if (!/^\d+$/.test(idText)) {
                i = hash + 1;
                continue;
            }

            var end = findStatementEnd(text, eq + 1);
            if (end < 0) break;
            var statement = text.slice(hash, end).trim();
            var match = statement.match(/^#(\d+)\s*=\s*([A-Z0-9_]+)\s*\(([\s\S]*)\)$/i);
            if (match) {
                entities.push({
                    id: parseInt(match[1], 10),
                    type: match[2].toUpperCase(),
                    args: splitTopLevel(match[3], ',').map(parseArg),
                    raw: statement
                });
            }
            i = end + 1;
        }

        return entities;
    }

    function findStatementEnd(text, from) {
        var inString = false;
        for (var i = from; i < text.length; i += 1) {
            var ch = text.charAt(i);
            if (ch === "'") {
                if (text.charAt(i + 1) === "'") {
                    i += 1;
                } else {
                    inString = !inString;
                }
            } else if (ch === ';' && !inString) {
                return i;
            }
        }
        return -1;
    }

    function splitTopLevel(text, delimiter) {
        var parts = [];
        var current = '';
        var depth = 0;
        var inString = false;

        for (var i = 0; i < text.length; i += 1) {
            var ch = text.charAt(i);
            if (ch === "'") {
                current += ch;
                if (text.charAt(i + 1) === "'") {
                    current += text.charAt(i + 1);
                    i += 1;
                } else {
                    inString = !inString;
                }
                continue;
            }

            if (!inString) {
                if (ch === '(') depth += 1;
                if (ch === ')') depth -= 1;
                if (ch === delimiter && depth === 0) {
                    parts.push(current.trim());
                    current = '';
                    continue;
                }
            }
            current += ch;
        }

        if (current.trim() || text.length === 0) parts.push(current.trim());
        return parts;
    }

    function parseArg(token) {
        var value = String(token || '').trim();
        if (!value || value === '$' || value === '*') return null;
        if (/^#\d+$/.test(value)) return value;
        if (value.charAt(0) === '(' && value.charAt(value.length - 1) === ')') {
            var inner = value.slice(1, -1).trim();
            return inner ? splitTopLevel(inner, ',').map(parseArg) : [];
        }
        if (value.charAt(0) === "'" && value.charAt(value.length - 1) === "'") {
            return value.slice(1, -1).replace(/''/g, "'");
        }

        var typed = value.match(/^([A-Z0-9_]+)\s*\(([\s\S]*)\)$/i);
        if (typed) {
            return {
                type: typed[1].toUpperCase(),
                args: splitTopLevel(typed[2], ',').map(parseArg)
            };
        }

        var numberText = value.replace(/D/i, 'E');
        var numeric = Number(numberText);
        return Number.isFinite(numeric) ? numeric : value.toUpperCase();
    }

    function detectSchema(text) {
        var match = text.match(/FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'/i);
        return match ? match[1] : 'IFC';
    }

    function detectLengthScale(step, diagnostics) {
        var scale = 1;
        step.each(function (entity) {
            if (entity.type !== 'IFCSIUNIT') return;
            var unitType = String(entity.args[1] || '').toUpperCase();
            var prefix = String(entity.args[2] || '').toUpperCase();
            var name = String(entity.args[3] || '').toUpperCase();
            if (unitType !== '.LENGTHUNIT.' || name !== '.METRE.') return;
            scale = prefixScale(prefix);
        });

        if (scale !== 1) {
            ns.core.addDiagnostic(
                diagnostics,
                'info',
                'IFC units converted',
                'Length coordinates were scaled by ' + scale + ' to metres.'
            );
        }
        return scale;
    }

    function prefixScale(prefix) {
        if (prefix === '.MILLI.') return 0.001;
        if (prefix === '.CENTI.') return 0.01;
        if (prefix === '.DECI.') return 0.1;
        if (prefix === '.KILO.') return 1000;
        return 1;
    }

    function representationItems(step, productDefinitionShape) {
        if (!productDefinitionShape || productDefinitionShape.type !== 'IFCPRODUCTDEFINITIONSHAPE') return [];
        var representations = Array.isArray(productDefinitionShape.args[2]) ? productDefinitionShape.args[2] : [];
        var resolved = representations.map(function (repRef) { return step.ref(repRef); }).filter(function (representation) {
            return representation && representation.type === 'IFCSHAPEREPRESENTATION';
        });
        var bodies = resolved.filter(function (representation) {
            return String(representation.args[1] || '').toUpperCase() === 'BODY';
        });
        var items = [];

        (bodies.length ? bodies : resolved).forEach(function (representation) {
            var repItems = Array.isArray(representation.args[3]) ? representation.args[3] : [];
            repItems.forEach(function (itemRef) {
                var item = step.ref(itemRef);
                if (item) items.push(item);
            });
        });

        return items;
    }

    function indexStairChildIds(step) {
        var ids = {};

        step.each(function (entity) {
            if (entity.type !== 'IFCRELAGGREGATES') return;
            var parent = step.ref(entity.args[4]);
            if (!parent || parent.type !== 'IFCSTAIR') return;
            var children = Array.isArray(entity.args[5]) ? entity.args[5] : [];
            children.forEach(function (child) {
                var childId = refId(child);
                if (childId) ids[childId] = true;
            });
        });

        return ids;
    }

    function isSupportedProduct(entity, stairChildIds) {
        if (entity.type === 'IFCMEMBER') return !!stairChildIds[entity.id];
        return !!PRODUCT_TYPES[entity.type];
    }

    function indexVoidsByHost(step) {
        var byHost = {};

        step.each(function (entity) {
            if (entity.type !== 'IFCRELVOIDSELEMENT') return;
            var hostId = refId(entity.args[4]);
            var opening = step.ref(entity.args[5]);
            if (!hostId || !opening || opening.type !== 'IFCOPENINGELEMENT') return;
            byHost[hostId] = byHost[hostId] || [];
            byHost[hostId].push(opening);
        });

        return byHost;
    }

    function indexOpeningsByFill(step) {
        var byFill = {};

        step.each(function (entity) {
            if (entity.type !== 'IFCRELFILLSELEMENT') return;
            var opening = step.ref(entity.args[4]);
            var fillId = refId(entity.args[5]);
            if (!fillId || !opening || opening.type !== 'IFCOPENINGELEMENT') return;
            byFill[fillId] = byFill[fillId] || [];
            byFill[fillId].push(opening);
        });

        return byFill;
    }

    function indexHostIdsByOpening(voidsByHost) {
        var byOpening = {};
        Object.keys(voidsByHost).forEach(function (hostId) {
            voidsByHost[hostId].forEach(function (opening) {
                byOpening[opening.id] = Number(hostId);
            });
        });
        return byOpening;
    }

    function countIndexedVoids(voidsByHost) {
        return Object.keys(voidsByHost).reduce(function (count, hostId) {
            return count + voidsByHost[hostId].length;
        }, 0);
    }

    function extrusionsForOpenings(step, openings, diagnostics, unsupported) {
        var extrusions = [];

        openings.forEach(function (opening) {
            var placement = step.transformForLocalPlacement(opening.args[5]);
            var representation = step.ref(opening.args[6]);
            representationItems(step, representation).forEach(function (item) {
                var mesh = meshForRepresentationItem(step, item, placement, diagnostics, unsupported);
                if (mesh.extrusion) {
                    extrusions.push({
                        openingId: opening.id,
                        openingName: asText(opening.args[2]) || 'Opening #' + opening.id,
                        extrusion: mesh.extrusion
                    });
                }
            });
        });

        return extrusions;
    }

    function meshesForOpenings(step, openings, diagnostics, unsupported) {
        return openings.map(function (opening) {
            var placement = step.transformForLocalPlacement(opening.args[5]);
            var representation = step.ref(opening.args[6]);
            var mesh = emptyMesh();

            representationItems(step, representation).forEach(function (item) {
                appendMesh(mesh, meshForRepresentationItem(step, item, placement, diagnostics, unsupported));
            });

            if (!mesh.faces.length) return null;
            return {
                stepId: opening.id,
                name: asText(opening.args[2]) || 'Opening #' + opening.id,
                mesh: mesh
            };
        }).filter(Boolean);
    }

    function boundsForOpeningMeshes(openings) {
        var vertices = [];
        openings.forEach(function (opening) {
            vertices = vertices.concat(opening.mesh.vertices);
        });
        return vertices.length ? boundsForVertices(vertices) : null;
    }

    function attachFillHostBounds(elements) {
        var byStepId = {};
        elements.forEach(function (element) {
            byStepId[element.stepId] = element;
        });

        elements.forEach(function (element) {
            var hosts = (element.fillHostStepIds || []).map(function (stepId) {
                return byStepId[stepId];
            }).filter(Boolean);
            if (hosts.length) element.fillHostBounds = boundsForElements(hosts);
        });
    }

    // Carve an item's openings, returning separate export and display meshes.
    // Profile holes that run parallel to and span the host extrusion (e.g. a shaft through a
    // slab) are subtracted from both meshes, exactly as before. Openings that cut across the
    // host (windows/doors in a wall) are boolean-subtracted into the display mesh only, so the
    // preview shows the void while the FDS export keeps the watertight solid that the
    // voxel/HOLE pipeline depends on.
    function carveItemOpenings(mesh, openings, diagnostics, voidStats, options) {
        if (!openings.length || !mesh.faces.length) {
            return { exportMesh: mesh, displayMesh: mesh };
        }
        if (!earcutFunction()) {
            addDiagnosticOnce(
                diagnostics,
                'warning',
                'IFC void triangulation unavailable',
                'Earcut was not loaded, so opening voids could not be triangulated.'
            );
            return { exportMesh: mesh, displayMesh: mesh };
        }

        var profileHoles = [];
        var boxOpenings = [];
        if (mesh.extrusion) {
            openings.forEach(function (opening) {
                var hole = holeForOpeningExtrusion(mesh.extrusion, opening.extrusion);
                if (hole) profileHoles.push({ opening: opening, hole: hole });
                else boxOpenings.push(opening);
            });
        } else {
            boxOpenings = openings.slice();
        }

        var exportMesh = mesh;
        if (profileHoles.length) {
            var extrusion = cloneExtrusion(mesh.extrusion);
            profileHoles.forEach(function (item) {
                extrusion.holes.push(item.hole);
                voidStats.applied[item.opening.openingId] = true;
            });
            exportMesh = meshForExtrusionWithHoles(extrusion);
        }

        var displayMesh = exportMesh;
        // The box-subtraction is by far the heaviest per-wall work. Skip it when the
        // caller is going to render through another path (e.g. web-ifc) — the export
        // mesh stays watertight either way because boxOpenings only touch displayMesh.
        if (!(options && options.skipBoxOpenings)) {
            boxOpenings.forEach(function (opening) {
                var box = boxFromExtrusion(opening.extrusion);
                if (!box) return;
                var carved = subtractBoxFromMesh(displayMesh, box);
                if (carved.faces.length) {
                    displayMesh = carved;
                    voidStats.applied[opening.openingId] = true;
                }
            });
        }

        return { exportMesh: exportMesh, displayMesh: displayMesh };
    }

    // Tight oriented box for an opening extrusion: an orthonormal frame (two base edges plus
    // the extrusion direction) with the min/max extent of the opening along each axis. A small
    // relative pad guarantees the box pokes through coincident host faces (no z-fighting caps).
    function boxFromExtrusion(extrusion) {
        var base = removeDuplicateLoopPoints(extrusion.base);
        if (base.length < 3 || vectorLength(extrusion.offset) < 1e-8) return null;

        var basis = basisForExtrusion(extrusion);
        var axes = [basis.uAxis, basis.vAxis, basis.normal];
        var corners = base.concat(base.map(function (point) {
            return addVector(point, extrusion.offset);
        }));

        var mins = [Infinity, Infinity, Infinity];
        var maxs = [-Infinity, -Infinity, -Infinity];
        corners.forEach(function (point) {
            for (var i = 0; i < 3; i += 1) {
                var distance = dot(subtractVector(point, basis.origin), axes[i]);
                if (distance < mins[i]) mins[i] = distance;
                if (distance > maxs[i]) maxs[i] = distance;
            }
        });

        for (var axis = 0; axis < 3; axis += 1) {
            var pad = (maxs[axis] - mins[axis]) * 0.005;
            if (pad < 1e-9) return null;
            mins[axis] -= pad;
            maxs[axis] += pad;
        }
        return { origin: basis.origin.slice(), axes: axes, mins: mins, maxs: maxs };
    }

    // host solid minus box, built by partitioning the host into the six capped regions that
    // surround the box and unioning them. Reuses the half-space mesh clipper, so it works for
    // any host shape and for openings at any orientation (parallel or across the extrusion).
    function subtractBoxFromMesh(mesh, box) {
        function planeAt(axisIndex, value, keepPositive) {
            return {
                origin: addVector(box.origin, scaleVector(box.axes[axisIndex], value)),
                normal: box.axes[axisIndex].slice(),
                keepPositive: keepPositive
            };
        }

        var insideA = [planeAt(0, box.mins[0], true), planeAt(0, box.maxs[0], false)];
        var insideB = [planeAt(1, box.mins[1], true), planeAt(1, box.maxs[1], false)];
        var regions = [
            [planeAt(0, box.mins[0], false)],
            [planeAt(0, box.maxs[0], true)],
            insideA.concat([planeAt(1, box.mins[1], false)]),
            insideA.concat([planeAt(1, box.maxs[1], true)]),
            insideA.concat(insideB, [planeAt(2, box.mins[2], false)]),
            insideA.concat(insideB, [planeAt(2, box.maxs[2], true)])
        ];

        var result = emptyMesh();
        regions.forEach(function (planes) {
            var piece = mesh;
            for (var k = 0; k < planes.length && piece.faces.length; k += 1) {
                piece = clipMeshByPlane(piece, planes[k]);
            }
            if (piece.faces.length) appendMesh(result, piece);
        });
        return result;
    }

    function holeForOpeningExtrusion(host, opening) {
        var hostLength = vectorLength(host.offset);
        var openingLength = vectorLength(opening.offset);
        if (hostLength < 1e-8 || openingLength < 1e-8) return null;

        var basis = basisForExtrusion(host);
        var openingNormal = normalize(opening.offset, [0, 0, 1]);
        if (Math.abs(dot(basis.normal, openingNormal)) < 0.9999) return null;

        var allOpeningPoints = opening.base.concat(opening.base.map(function (point) {
            return addVector(point, opening.offset);
        }));
        var heights = allOpeningPoints.map(function (point) {
            return dot(subtractVector(point, basis.origin), basis.normal);
        });
        var minHeight = Math.min.apply(Math, heights);
        var maxHeight = Math.max.apply(Math, heights);
        if (minHeight > 1e-7 || maxHeight < hostLength - 1e-7) return null;

        var outer2d = host.base.map(function (point) { return projectToBasis2d(point, basis); });
        var hole = removeDuplicateLoopPoints(opening.base).map(function (point) {
            var projected = projectToBasis2d(point, basis);
            return {
                point: pointFromBasis2d(projected, basis),
                projected: projected
            };
        });

        if (hole.length < 3 || !hole.every(function (item) {
            return pointStrictlyInsidePolygon(item.projected, outer2d);
        })) {
            return null;
        }

        return hole.map(function (item) { return item.point; });
    }

    function cloneExtrusion(extrusion) {
        return {
            base: extrusion.base.map(function (point) { return point.slice(); }),
            offset: extrusion.offset.slice(),
            holes: (extrusion.holes || []).map(function (hole) {
                return hole.map(function (point) { return point.slice(); });
            })
        };
    }

    function meshForRepresentationItem(step, item, productTransform, diagnostics, unsupported) {
        if (!item) return emptyMesh();
        if (item.type === 'IFCEXTRUDEDAREASOLID') {
            return meshForExtrudedAreaSolid(step, item, productTransform, diagnostics);
        }
        if (item.type === 'IFCFACETEDBREP') {
            return meshForFacetedBrep(step, item, productTransform, diagnostics);
        }
        if (item.type === 'IFCFACEBASEDSURFACEMODEL') {
            return meshForFaceBasedSurfaceModel(step, item, productTransform, diagnostics);
        }
        if (item.type === 'IFCTRIANGULATEDFACESET') {
            return meshForTriangulatedFaceSet(step, item, productTransform, diagnostics);
        }
        if (item.type === 'IFCMAPPEDITEM') {
            return meshForMappedItem(step, item, productTransform, diagnostics, unsupported);
        }
        if (item.type === 'IFCBOOLEANCLIPPINGRESULT') {
            return meshForBooleanClippingResult(step, item, productTransform, diagnostics, unsupported);
        }

        unsupported[item.type] = (unsupported[item.type] || 0) + 1;
        return emptyMesh();
    }

    function meshForMappedItem(step, item, productTransform, diagnostics, unsupported) {
        var source = step.ref(item.args[0]);
        var target = transformForCartesianOperator(step, step.ref(item.args[1]));
        var mesh = emptyMesh();

        if (!source || source.type !== 'IFCREPRESENTATIONMAP') {
            unsupported.IFCMAPPEDITEM = (unsupported.IFCMAPPEDITEM || 0) + 1;
            return mesh;
        }

        var origin = step.transformForAxisPlacement(source.args[0]);
        if (!isIdentityish(origin)) {
            ns.core.addDiagnostic(
                diagnostics,
                'info',
                'IFC mapped origin approximated',
                'A non-identity IfcRepresentationMap origin was detected. Geometry may need a later precision pass.'
            );
        }

        var mappedRepresentation = step.ref(source.args[1]);
        var items = [];
        if (mappedRepresentation && mappedRepresentation.type === 'IFCSHAPEREPRESENTATION') {
            var refs = Array.isArray(mappedRepresentation.args[3]) ? mappedRepresentation.args[3] : [];
            refs.forEach(function (ref) {
                var mapped = step.ref(ref);
                if (mapped) items.push(mapped);
            });
        }

        var mappedTransform = composeTransform(productTransform, target);
        items.forEach(function (mappedItem) {
            appendMesh(mesh, meshForRepresentationItem(step, mappedItem, mappedTransform, diagnostics, unsupported));
        });
        return mesh;
    }

    function meshForBooleanClippingResult(step, item, productTransform, diagnostics, unsupported) {
        if (String(item.args[0] || '').toUpperCase() !== '.DIFFERENCE.') {
            unsupported.IFCBOOLEANCLIPPINGRESULT = (unsupported.IFCBOOLEANCLIPPINGRESULT || 0) + 1;
            return emptyMesh();
        }

        var source = step.ref(item.args[1]);
        var halfSpace = step.ref(item.args[2]);
        var mesh = meshForRepresentationItem(step, source, productTransform, diagnostics, unsupported);
        var plane = clippingPlaneForHalfSpace(step, halfSpace, productTransform);

        if (!mesh.faces.length || !plane) {
            unsupported.IFCBOOLEANCLIPPINGRESULT = (unsupported.IFCBOOLEANCLIPPINGRESULT || 0) + 1;
            return emptyMesh();
        }

        if (halfSpace.type === 'IFCPOLYGONALBOUNDEDHALFSPACE') {
            addDiagnosticOnce(
                diagnostics,
                'info',
                'Polygonal clipping boundary approximated',
                'IfcPolygonalBoundedHalfSpace roof cuts are currently applied as planar cuts. This preserves the supported building walls, but a later precision pass should also limit the cut to the polygon boundary.'
            );
        }

        return clipMeshByPlane(mesh, plane);
    }

    function clippingPlaneForHalfSpace(step, halfSpace, productTransform) {
        if (!halfSpace ||
            (halfSpace.type !== 'IFCHALFSPACESOLID' && halfSpace.type !== 'IFCPOLYGONALBOUNDEDHALFSPACE')) {
            return null;
        }

        var surface = step.ref(halfSpace.args[0]);
        if (!surface || surface.type !== 'IFCPLANE') return null;

        var surfaceTransform = step.transformForAxisPlacement(surface.args[0]);
        var worldTransform = composeTransform(productTransform, surfaceTransform);
        return {
            origin: worldTransform.origin,
            normal: normalize(worldTransform.zAxis, [0, 0, 1]),
            keepPositive: String(halfSpace.args[1] || '').toUpperCase() === '.T.'
        };
    }

    function meshForExtrudedAreaSolid(step, solid, productTransform, diagnostics) {
        var profile = step.ref(solid.args[0]);
        var solidPosition = step.transformForAxisPlacement(solid.args[1]);
        var direction = step.direction(solid.args[2], [0, 0, 1]);
        var depth = numberOr(solid.args[3], 0);
        var profilePoints = profilePoints2d(step, profile, diagnostics);

        if (!profilePoints.length || depth <= 0) return emptyMesh();

        profilePoints = removeDuplicateLoopPoints(profilePoints);
        var localMesh = extrudeProfile(profilePoints, direction, depth);
        var transform = composeTransform(productTransform, solidPosition);
        transformMesh(localMesh, transform);
        localMesh.extrusion = {
            base: profilePoints.map(function (point) { return transformPoint(transform, point); }),
            offset: transformVector(transform, scaleVector(normalize(direction, [0, 0, 1]), depth)),
            holes: []
        };
        return localMesh;
    }

    function meshForExtrusionWithHoles(extrusion) {
        var mesh = emptyMesh();
        var rings = [removeDuplicateLoopPoints(extrusion.base)].concat(
            extrusion.holes.map(removeDuplicateLoopPoints)
        );
        var basis = basisForExtrusion(extrusion);
        var flat = [];
        var holeIndices = [];
        var ringStarts = [];
        var vertexCount = 0;

        rings.forEach(function (ring, index) {
            ringStarts.push(vertexCount);
            if (index > 0) holeIndices.push(vertexCount);
            ring.forEach(function (point) {
                var projected = projectToBasis2d(point, basis);
                flat.push(projected[0], projected[1]);
                mesh.vertices.push(point.slice());
                vertexCount += 1;
            });
        });

        var triangles = earcutFunction()(flat, holeIndices, 2);
        var baseCount = mesh.vertices.length;
        mesh.vertices.slice().forEach(function (point) {
            mesh.vertices.push(addVector(point, extrusion.offset));
        });

        for (var i = 0; i < triangles.length; i += 3) {
            mesh.faces.push([triangles[i], triangles[i + 2], triangles[i + 1]]);
            mesh.faces.push([
                baseCount + triangles[i],
                baseCount + triangles[i + 1],
                baseCount + triangles[i + 2]
            ]);
        }

        rings.forEach(function (ring, ringIndex) {
            var start = ringStarts[ringIndex];
            for (var j = 0; j < ring.length; j += 1) {
                var current = start + j;
                var next = start + (j + 1) % ring.length;
                if (ringIndex === 0) {
                    mesh.faces.push([current, next, baseCount + next]);
                    mesh.faces.push([current, baseCount + next, baseCount + current]);
                } else {
                    mesh.faces.push([current, baseCount + next, next]);
                    mesh.faces.push([current, baseCount + current, baseCount + next]);
                }
            }
        });

        mesh.extrusion = cloneExtrusion(extrusion);
        return mesh;
    }

    function clipMeshByPlane(source, plane) {
        var mesh = emptyMesh();
        var vertexMap = {};
        var cutSegments = [];

        source.faces.forEach(function (face) {
            var triangle = face.map(function (index) { return source.vertices[index]; });
            var clipped = clipPolygonByPlane(triangle, plane);
            var cutPoints = intersectionPointsForTriangle(triangle, plane);

            if (cutPoints.length === 2) cutSegments.push(cutPoints);
            if (clipped.length < 3) return;

            var indices = clipped.map(function (point) {
                return addUniqueVertex(mesh, vertexMap, point);
            });
            for (var i = 1; i < indices.length - 1; i += 1) {
                mesh.faces.push([indices[0], indices[i], indices[i + 1]]);
            }
        });

        addClipCaps(mesh, vertexMap, cutSegments, plane);
        return mesh;
    }

    function clipPolygonByPlane(points, plane) {
        var result = [];

        for (var i = 0; i < points.length; i += 1) {
            var current = points[i];
            var next = points[(i + 1) % points.length];
            var currentDistance = signedDistanceToPlane(current, plane);
            var nextDistance = signedDistanceToPlane(next, plane);
            var currentInside = isInsideClip(currentDistance, plane);
            var nextInside = isInsideClip(nextDistance, plane);

            if (currentInside) result.push(current.slice());
            if (currentInside !== nextInside) {
                result.push(intersectionPoint(current, next, currentDistance, nextDistance));
            }
        }

        return removeDuplicateLoopPoints(result);
    }

    function intersectionPointsForTriangle(points, plane) {
        var intersections = [];

        for (var i = 0; i < points.length; i += 1) {
            var current = points[i];
            var next = points[(i + 1) % points.length];
            var currentDistance = signedDistanceToPlane(current, plane);
            var nextDistance = signedDistanceToPlane(next, plane);

            if (Math.abs(currentDistance) < 1e-8) intersections.push(current.slice());
            if (isInsideClip(currentDistance, plane) !== isInsideClip(nextDistance, plane)) {
                intersections.push(intersectionPoint(current, next, currentDistance, nextDistance));
            }
        }

        return uniquePoints(intersections);
    }

    function addClipCaps(mesh, vertexMap, segments, plane) {
        var unused = {};
        var adjacency = {};

        segments.forEach(function (segment) {
            var a = pointKey(segment[0]);
            var b = pointKey(segment[1]);
            if (a === b) return;
            var edgeKey = a < b ? a + '|' + b : b + '|' + a;
            if (unused[edgeKey]) return;
            unused[edgeKey] = { a: a, b: b, points: {} };
            unused[edgeKey].points[a] = segment[0];
            unused[edgeKey].points[b] = segment[1];
            adjacency[a] = adjacency[a] || [];
            adjacency[b] = adjacency[b] || [];
            adjacency[a].push(edgeKey);
            adjacency[b].push(edgeKey);
        });

        Object.keys(unused).forEach(function (startEdgeKey) {
            if (!unused[startEdgeKey]) return;
            var edge = unused[startEdgeKey];
            var startKey = edge.a;
            var currentKey = edge.b;
            var loop = [edge.points[startKey], edge.points[currentKey]];
            delete unused[startEdgeKey];

            while (currentKey !== startKey) {
                var nextEdgeKey = (adjacency[currentKey] || []).find(function (candidate) {
                    return !!unused[candidate];
                });
                if (!nextEdgeKey) break;

                var nextEdge = unused[nextEdgeKey];
                var nextKey = nextEdge.a === currentKey ? nextEdge.b : nextEdge.a;
                loop.push(nextEdge.points[nextKey]);
                delete unused[nextEdgeKey];
                currentKey = nextKey;
            }

            if (currentKey !== startKey || loop.length < 4) return;
            loop.pop();
            addCapLoop(mesh, vertexMap, loop, plane);
        });
    }

    function addCapLoop(mesh, vertexMap, loop, plane) {
        var desiredNormal = plane.keepPositive ? scaleVector(plane.normal, -1) : plane.normal;
        if (dot(polygonNormal(loop), desiredNormal) < 0) loop.reverse();

        var center = [0, 0, 0];
        loop.forEach(function (point) { center = addVector(center, point); });
        center = scaleVector(center, 1 / loop.length);

        var centerIndex = addUniqueVertex(mesh, vertexMap, center);
        var indices = loop.map(function (point) { return addUniqueVertex(mesh, vertexMap, point); });
        for (var i = 0; i < indices.length; i += 1) {
            mesh.faces.push([centerIndex, indices[i], indices[(i + 1) % indices.length]]);
        }
    }

    function polygonNormal(points) {
        var normal = [0, 0, 0];
        for (var i = 0; i < points.length; i += 1) {
            var current = points[i];
            var next = points[(i + 1) % points.length];
            normal[0] += (current[1] - next[1]) * (current[2] + next[2]);
            normal[1] += (current[2] - next[2]) * (current[0] + next[0]);
            normal[2] += (current[0] - next[0]) * (current[1] + next[1]);
        }
        return normal;
    }

    function signedDistanceToPlane(point, plane) {
        return dot(subtractVector(point, plane.origin), plane.normal);
    }

    function isInsideClip(distance, plane) {
        return plane.keepPositive ? distance >= -1e-8 : distance <= 1e-8;
    }

    function intersectionPoint(a, b, aDistance, bDistance) {
        var denominator = aDistance - bDistance;
        var t = Math.abs(denominator) < 1e-12 ? 0 : aDistance / denominator;
        return [
            a[0] + (b[0] - a[0]) * t,
            a[1] + (b[1] - a[1]) * t,
            a[2] + (b[2] - a[2]) * t
        ];
    }

    function removeDuplicateLoopPoints(points) {
        var result = [];
        points.forEach(function (point) {
            if (!result.length || pointKey(result[result.length - 1]) !== pointKey(point)) result.push(point);
        });
        if (result.length > 1 && pointKey(result[0]) === pointKey(result[result.length - 1])) result.pop();
        return result;
    }

    function uniquePoints(points) {
        var seen = {};
        return points.filter(function (point) {
            var key = pointKey(point);
            if (seen[key]) return false;
            seen[key] = true;
            return true;
        });
    }

    function addUniqueVertex(mesh, vertexMap, point) {
        var key = pointKey(point);
        if (vertexMap[key] === undefined) {
            vertexMap[key] = mesh.vertices.length;
            mesh.vertices.push(point.slice());
        }
        return vertexMap[key];
    }

    function pointKey(point) {
        return point.map(function (value) { return Number(value).toFixed(8); }).join(',');
    }

    function basisForExtrusion(extrusion) {
        var origin = extrusion.base[0];
        var normal = normalize(extrusion.offset, [0, 0, 1]);
        var uAxis = null;

        for (var i = 1; i < extrusion.base.length; i += 1) {
            var edge = subtractVector(extrusion.base[i], origin);
            if (vectorLength(edge) > 1e-8) {
                uAxis = normalize(edge, [1, 0, 0]);
                break;
            }
        }

        uAxis = uAxis || perpendicularVector(normal);
        var vAxis = normalize(cross(normal, uAxis), [0, 1, 0]);
        uAxis = normalize(cross(vAxis, normal), [1, 0, 0]);
        return { origin: origin.slice(), normal: normal, uAxis: uAxis, vAxis: vAxis };
    }

    function perpendicularVector(normal) {
        var candidate = Math.abs(normal[0]) < 0.8 ? [1, 0, 0] : [0, 1, 0];
        return normalize(cross(candidate, normal), [0, 0, 1]);
    }

    function projectToBasis2d(point, basis) {
        var relative = subtractVector(point, basis.origin);
        return [dot(relative, basis.uAxis), dot(relative, basis.vAxis)];
    }

    function pointFromBasis2d(point, basis) {
        return addVector(
            basis.origin,
            addVector(scaleVector(basis.uAxis, point[0]), scaleVector(basis.vAxis, point[1]))
        );
    }

    function pointStrictlyInsidePolygon(point, polygon) {
        var inside = false;

        for (var i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
            if (pointOnSegment2d(point, polygon[j], polygon[i])) return false;
            if ((polygon[i][1] > point[1]) !== (polygon[j][1] > point[1]) &&
                point[0] < (polygon[j][0] - polygon[i][0]) * (point[1] - polygon[i][1]) /
                (polygon[j][1] - polygon[i][1]) + polygon[i][0]) {
                inside = !inside;
            }
        }

        return inside;
    }

    function pointOnSegment2d(point, a, b) {
        var crossValue = (point[1] - a[1]) * (b[0] - a[0]) - (point[0] - a[0]) * (b[1] - a[1]);
        if (Math.abs(crossValue) > 1e-8) return false;
        return point[0] >= Math.min(a[0], b[0]) - 1e-8 &&
            point[0] <= Math.max(a[0], b[0]) + 1e-8 &&
            point[1] >= Math.min(a[1], b[1]) - 1e-8 &&
            point[1] <= Math.max(a[1], b[1]) + 1e-8;
    }

    function earcutFunction() {
        if (!window.earcut) return null;
        return window.earcut.default || window.earcut;
    }

    function profilePoints2d(step, profile, diagnostics) {
        if (!profile) return [];
        var transform = step.transformForAxisPlacement(profile.args[2]);

        if (profile.type === 'IFCRECTANGLEPROFILEDEF') {
            var xDim = numberOr(profile.args[3], 0);
            var yDim = numberOr(profile.args[4], 0);
            var points = [
                [-xDim / 2, -yDim / 2, 0],
                [xDim / 2, -yDim / 2, 0],
                [xDim / 2, yDim / 2, 0],
                [-xDim / 2, yDim / 2, 0]
            ];
            return points.map(function (point) { return transformPoint(transform, point); });
        }

        if (profile.type === 'IFCARBITRARYCLOSEDPROFILEDEF') {
            var curve = step.ref(profile.args[2]);
            var curvePoints = pointsForCurve(step, curve);
            return curvePoints.map(function (point) { return transformPoint(transform, point); });
        }

        ns.core.addDiagnostic(
            diagnostics,
            'info',
            'Unsupported IFC profile: ' + profile.type,
            'Only rectangle and arbitrary closed polyline profiles are converted in this milestone.'
        );
        return [];
    }

    function pointsForCurve(step, curve) {
        if (!curve || curve.type !== 'IFCPOLYLINE') return [];
        var refs = Array.isArray(curve.args[0]) ? curve.args[0] : [];
        return refs.map(function (ref) { return step.point(ref); });
    }

    function extrudeProfile(profilePoints, direction, depth) {
        var mesh = emptyMesh();
        var n = profilePoints.length;
        if (n < 3) return mesh;

        var offset = scaleVector(normalize(direction, [0, 0, 1]), depth);
        for (var i = 0; i < n; i += 1) {
            mesh.vertices.push(profilePoints[i].slice());
        }
        for (var j = 0; j < n; j += 1) {
            mesh.vertices.push(addVector(profilePoints[j], offset));
        }

        for (var b = 1; b < n - 1; b += 1) {
            mesh.faces.push([0, b + 1, b]);
            mesh.faces.push([n, n + b, n + b + 1]);
        }
        for (var s = 0; s < n; s += 1) {
            var next = (s + 1) % n;
            mesh.faces.push([s, next, n + next]);
            mesh.faces.push([s, n + next, n + s]);
        }

        return mesh;
    }

    function meshForFacetedBrep(step, brep, productTransform, diagnostics) {
        var mesh = emptyMesh();
        var shell = step.ref(brep.args[0]);
        if (!shell || shell.type !== 'IFCCLOSEDSHELL') return mesh;

        var faceRefs = Array.isArray(shell.args[0]) ? shell.args[0] : [];
        appendFaceRefsToMesh(step, faceRefs, productTransform, mesh);

        if (!mesh.faces.length) {
            ns.core.addDiagnostic(diagnostics, 'warning', 'Faceted BREP skipped', 'A BREP was found but no triangulated outer faces could be read.');
        }
        return mesh;
    }

    function meshForFaceBasedSurfaceModel(step, surfaceModel, productTransform, diagnostics) {
        var mesh = emptyMesh();
        var vertexMap = {};
        var connectedFaceSetRefs = Array.isArray(surfaceModel.args[0]) ? surfaceModel.args[0] : [];

        connectedFaceSetRefs.forEach(function (connectedFaceSetRef) {
            var connectedFaceSet = step.ref(connectedFaceSetRef);
            if (!connectedFaceSet || connectedFaceSet.type !== 'IFCCONNECTEDFACESET') return;
            var faceRefs = Array.isArray(connectedFaceSet.args[0]) ? connectedFaceSet.args[0] : [];
            appendFaceRefsToMesh(step, faceRefs, productTransform, mesh, vertexMap);
        });

        if (!mesh.faces.length) {
            ns.core.addDiagnostic(
                diagnostics,
                'warning',
                'Face-based surface model skipped',
                'An IfcFaceBasedSurfaceModel was found but no triangulated outer faces could be read.'
            );
        }
        return mesh;
    }

    function appendFaceRefsToMesh(step, faceRefs, productTransform, mesh, vertexMap) {
        vertexMap = vertexMap || {};

        faceRefs.forEach(function (faceRef) {
            var face = step.ref(faceRef);
            if (!face || face.type !== 'IFCFACE') return;
            var bounds = Array.isArray(face.args[0]) ? face.args[0] : [];
            var outer = null;
            bounds.forEach(function (boundRef) {
                var bound = step.ref(boundRef);
                if (bound && bound.type === 'IFCFACEOUTERBOUND') outer = bound;
            });
            if (!outer) return;

            var loop = step.ref(outer.args[0]);
            if (!loop || loop.type !== 'IFCPOLYLOOP') return;
            var pointRefs = Array.isArray(loop.args[0]) ? loop.args[0] : [];
            var indices = [];

            pointRefs.forEach(function (pointRef) {
                var point = transformPoint(productTransform, step.point(pointRef));
                var key = point.map(function (value) { return value.toFixed(8); }).join(',');
                if (vertexMap[key] === undefined) {
                    vertexMap[key] = mesh.vertices.length;
                    mesh.vertices.push(point);
                }
                indices.push(vertexMap[key]);
            });

            if (indices.length < 3) return;
            triangulatePlanarPolygon(mesh, indices);
        });
        return mesh;
    }

    // Fan-triangulate from the first vertex works only for CONVEX polygons. Real BREP
    // outlines from BIM models are routinely L / U / T shaped — a fan turns those into
    // triangles that lie outside the polygon, and downstream voxelization treats the
    // mesh as if it covered the whole bounding rectangle (which is what we saw on the
    // school slab). Earcut handles non-convex shapes correctly; falls back to the fan
    // only when earcut is unavailable or the polygon is degenerate.
    function triangulatePlanarPolygon(mesh, indices) {
        if (indices.length === 3) {
            mesh.faces.push([indices[0], indices[1], indices[2]]);
            return;
        }
        var earcut = earcutFunction();
        if (earcut) {
            var points3d = indices.map(function (idx) { return mesh.vertices[idx]; });
            var basis = basisFromPlanarPoints(points3d);
            if (basis) {
                var flat = [];
                points3d.forEach(function (p) {
                    var proj = projectToBasis2d(p, basis);
                    flat.push(proj[0], proj[1]);
                });
                var triangles = earcut(flat, null, 2);
                if (triangles && triangles.length >= 3) {
                    for (var t = 0; t < triangles.length; t += 3) {
                        mesh.faces.push([
                            indices[triangles[t]],
                            indices[triangles[t + 1]],
                            indices[triangles[t + 2]]
                        ]);
                    }
                    return;
                }
            }
        }
        // Last-resort fan triangulation (only correct for convex polygons).
        for (var i = 1; i < indices.length - 1; i += 1) {
            mesh.faces.push([indices[0], indices[i], indices[i + 1]]);
        }
    }

    // Builds a u/v basis for a set of co-planar 3-D points. Picks the polygon normal via
    // the first two non-degenerate edge cross product, then a perpendicular u axis on the
    // plane. Returns null if the points are colinear or degenerate.
    function basisFromPlanarPoints(points) {
        if (!points || points.length < 3) return null;
        var origin = points[0];
        var normal = null;
        for (var i = 1; i < points.length - 1; i += 1) {
            var e1 = subtractVector(points[i], origin);
            var e2 = subtractVector(points[i + 1], origin);
            var n = cross(e1, e2);
            if (vectorLength(n) > 1e-10) { normal = normalize(n, [0, 0, 1]); break; }
        }
        if (!normal) return null;
        var uAxis = null;
        for (var j = 1; j < points.length; j += 1) {
            var edge = subtractVector(points[j], origin);
            if (vectorLength(edge) > 1e-8) { uAxis = normalize(edge, [1, 0, 0]); break; }
        }
        if (!uAxis) return null;
        var vAxis = normalize(cross(normal, uAxis), [0, 1, 0]);
        uAxis = normalize(cross(vAxis, normal), [1, 0, 0]);
        return { origin: origin.slice(), normal: normal, uAxis: uAxis, vAxis: vAxis };
    }

    function meshForTriangulatedFaceSet(step, faceSet, productTransform, diagnostics) {
        var mesh = emptyMesh();
        var pointList = step.ref(faceSet.args[0]);
        var coords = pointList3d(pointList);
        var indices = Array.isArray(faceSet.args[3]) ? faceSet.args[3] : [];

        if (!coords.length || !indices.length) {
            ns.core.addDiagnostic(
                diagnostics,
                'warning',
                'Triangulated face set skipped',
                'An IfcTriangulatedFaceSet did not contain readable coordinates and triangle indices.'
            );
            return mesh;
        }

        coords.forEach(function (point) {
            mesh.vertices.push(transformPoint(productTransform, point));
        });

        indices.forEach(function (face) {
            if (!Array.isArray(face) || face.length < 3) return;
            var a = numberOr(face[0], 0) - 1;
            var b = numberOr(face[1], 0) - 1;
            var c = numberOr(face[2], 0) - 1;
            if (mesh.vertices[a] && mesh.vertices[b] && mesh.vertices[c]) {
                mesh.faces.push([a, b, c]);
            }
        });

        return mesh;
    }

    function pointList3d(entity) {
        if (!entity || entity.type !== 'IFCCARTESIANPOINTLIST3D') return [];
        var coords = Array.isArray(entity.args[0]) ? entity.args[0] : [];
        return coords
            .filter(function (point) { return Array.isArray(point) && point.length >= 3; })
            .map(function (point) {
                return [
                    numberOr(point[0], 0),
                    numberOr(point[1], 0),
                    numberOr(point[2], 0)
                ];
            });
    }

    function transformForCartesianOperator(step, entity) {
        if (!entity || entity.type !== 'IFCCARTESIANTRANSFORMATIONOPERATOR3D') return identityTransform();
        var x = step.direction(entity.args[0], [1, 0, 0]);
        var y = step.direction(entity.args[1], [0, 1, 0]);
        var origin = step.point(entity.args[2]);
        var scale = numberOr(entity.args[3], 1);
        var z = step.direction(entity.args[4], [0, 0, 1]);
        return {
            origin: origin,
            xAxis: scaleVector(x, scale),
            yAxis: scaleVector(y, scale),
            zAxis: scaleVector(z, scale)
        };
    }

    function readText(file) {
        return new Promise(function (resolve, reject) {
            var reader = new FileReader();
            reader.onload = function () { resolve(String(reader.result || '')); };
            reader.onerror = function () { reject(reader.error); };
            reader.readAsText(file);
        });
    }

    function emptyMesh() {
        return { vertices: [], faces: [] };
    }

    function appendMesh(target, source) {
        if (!source || !source.vertices.length) return target;
        var offset = target.vertices.length;
        source.vertices.forEach(function (vertex) { target.vertices.push(vertex); });
        source.faces.forEach(function (face) {
            target.faces.push([face[0] + offset, face[1] + offset, face[2] + offset]);
        });
        return target;
    }

    function transformMesh(mesh, transform) {
        mesh.vertices = mesh.vertices.map(function (vertex) { return transformPoint(transform, vertex); });
        return mesh;
    }

    function scaleMesh(mesh, scale) {
        if (scale === 1) return mesh;
        mesh.vertices = mesh.vertices.map(function (vertex) {
            return [vertex[0] * scale, vertex[1] * scale, vertex[2] * scale];
        });
        return mesh;
    }

    function boundsForVertices(vertices) {
        var bounds = null;
        vertices.forEach(function (v) {
            if (!bounds) {
                bounds = { xmin: v[0], xmax: v[0], ymin: v[1], ymax: v[1], zmin: v[2], zmax: v[2] };
            } else {
                bounds.xmin = Math.min(bounds.xmin, v[0]);
                bounds.xmax = Math.max(bounds.xmax, v[0]);
                bounds.ymin = Math.min(bounds.ymin, v[1]);
                bounds.ymax = Math.max(bounds.ymax, v[1]);
                bounds.zmin = Math.min(bounds.zmin, v[2]);
                bounds.zmax = Math.max(bounds.zmax, v[2]);
            }
        });
        return bounds;
    }

    function boundsForElements(elements) {
        var bounds = null;
        elements.forEach(function (element) {
            var b = element.bounds;
            if (!b) return;
            if (!bounds) {
                bounds = { xmin: b.xmin, xmax: b.xmax, ymin: b.ymin, ymax: b.ymax, zmin: b.zmin, zmax: b.zmax };
            } else {
                bounds.xmin = Math.min(bounds.xmin, b.xmin);
                bounds.xmax = Math.max(bounds.xmax, b.xmax);
                bounds.ymin = Math.min(bounds.ymin, b.ymin);
                bounds.ymax = Math.max(bounds.ymax, b.ymax);
                bounds.zmin = Math.min(bounds.zmin, b.zmin);
                bounds.zmax = Math.max(bounds.zmax, b.zmax);
            }
        });
        return bounds;
    }

    function classifyElement(entity) {
        var type = entity.type;

        if (type === 'IFCSPACE') {
            return {
                convertible: false,
                reference: true,
                exportAsSolid: false,
                canExportAsSolid: false,
                fdsRole: 'ignore',
                note: 'IfcSpace is a room volume. It is useful for checking layout, but should not become an FDS obstruction.'
            };
        }

        if (type === 'IFCRAILING') {
            return {
                convertible: false,
                reference: false,
                exportAsSolid: false,
                canExportAsSolid: true,
                fdsRole: 'review',
                note: 'Railing is visible in the IFC building preview and excluded from FDS by default. Enable review objects only when it should block the flow.'
            };
        }

        if (REVIEW_TYPES[type]) {
            return {
                convertible: false,
                reference: false,
                exportAsSolid: false,
                canExportAsSolid: true,
                fdsRole: 'review',
                note: REVIEW_TYPES[type] + ' is shown in the IFC preview and excluded from FDS by default. Enable review objects only when it should block the flow.'
            };
        }

        if (type === 'IFCWINDOW' || type === 'IFCDOOR') {
            return {
                convertible: true,
                reference: false,
                exportAsSolid: false,
                canExportAsSolid: true,
                fdsRole: 'opening',
                note: 'Window and door fills remain visible for IFC review but are excluded from FDS obstructions; their host openings are carved during voxel export.'
            };
        }

        return {
            convertible: true,
            reference: false,
            exportAsSolid: true,
            canExportAsSolid: true,
            fdsRole: 'solid',
            note: 'Converted by default.'
        };
    }

    function identityTransform() {
        return {
            origin: [0, 0, 0],
            xAxis: [1, 0, 0],
            yAxis: [0, 1, 0],
            zAxis: [0, 0, 1]
        };
    }

    function axesTransform(origin, xAxis, zAxis) {
        var z = normalize(zAxis, [0, 0, 1]);
        var x = normalize(xAxis, [1, 0, 0]);
        var y = normalize(cross(z, x), [0, 1, 0]);
        x = normalize(cross(y, z), [1, 0, 0]);
        return { origin: origin.slice(), xAxis: x, yAxis: y, zAxis: z };
    }

    function composeTransform(a, b) {
        return {
            origin: transformPoint(a, b.origin),
            xAxis: transformVector(a, b.xAxis),
            yAxis: transformVector(a, b.yAxis),
            zAxis: transformVector(a, b.zAxis)
        };
    }

    function transformPoint(transform, point) {
        return addVector(transform.origin, transformVector(transform, point));
    }

    function transformVector(transform, vector) {
        return [
            transform.xAxis[0] * vector[0] + transform.yAxis[0] * vector[1] + transform.zAxis[0] * vector[2],
            transform.xAxis[1] * vector[0] + transform.yAxis[1] * vector[1] + transform.zAxis[1] * vector[2],
            transform.xAxis[2] * vector[0] + transform.yAxis[2] * vector[1] + transform.zAxis[2] * vector[2]
        ];
    }

    function cross(a, b) {
        return [
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]
        ];
    }

    function normalize(vector, fallback) {
        var len = Math.sqrt(vector[0] * vector[0] + vector[1] * vector[1] + vector[2] * vector[2]);
        if (len < 1e-12) return fallback.slice();
        return [vector[0] / len, vector[1] / len, vector[2] / len];
    }

    function addVector(a, b) {
        return [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
    }

    function subtractVector(a, b) {
        return [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
    }

    function scaleVector(vector, scale) {
        return [vector[0] * scale, vector[1] * scale, vector[2] * scale];
    }

    function vectorLength(vector) {
        return Math.sqrt(dot(vector, vector));
    }

    function dot(a, b) {
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    }

    function numberOr(value, fallback) {
        return Number.isFinite(value) ? value : fallback;
    }

    function refId(value) {
        if (typeof value === 'string') {
            var match = value.match(/^#(\d+)$/);
            return match ? parseInt(match[1], 10) : null;
        }
        return null;
    }

    function asText(value) {
        return typeof value === 'string' && value.charAt(0) !== '#' ? value : '';
    }

    function labelForEntity(entity) {
        return entity.type + ' #' + entity.id + (asText(entity.args[2]) ? ' (' + asText(entity.args[2]) + ')' : '');
    }

    function isIdentityish(transform) {
        var id = identityTransform();
        return vectorClose(transform.origin, id.origin) &&
            vectorClose(transform.xAxis, id.xAxis) &&
            vectorClose(transform.yAxis, id.yAxis) &&
            vectorClose(transform.zAxis, id.zAxis);
    }

    function vectorClose(a, b) {
        return Math.abs(a[0] - b[0]) < 1e-8 &&
            Math.abs(a[1] - b[1]) < 1e-8 &&
            Math.abs(a[2] - b[2]) < 1e-8;
    }

    function addDiagnosticOnce(diagnostics, level, title, detail) {
        var exists = diagnostics.some(function (diagnostic) {
            return diagnostic.title === title;
        });
        if (!exists) ns.core.addDiagnostic(diagnostics, level, title, detail);
    }

    // Exposed for the parallel parse-shard worker so it can drive the same parse pipeline
    // on a slice of entities without duplicating the per-entity body.
    IfcAdapter.beginParse = beginParse;
    IfcAdapter.processEntity = processEntity;
    IfcAdapter.finishParse = finishParse;

    ns.ifc.IfcAdapter = IfcAdapter;
})(window.IfcFds);
