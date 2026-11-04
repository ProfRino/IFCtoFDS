(function (ns) {
    'use strict';
    var jobId = null, stopped = false, fallback = null, generation = 0, inventoryGeneration = 0;
    var domainSources = null, domainEdited = false;
    var domainAxes = ['xmin','xmax','ymin','ymax','zmin','zmax'];
    function cancelled() { var error = new Error('Conversion cancelled'); error.name = 'AbortError'; return error; }
    function get(id) { return document.getElementById('verified-' + id); }
    function files() { return Array.prototype.slice.call(get('sources').files || []); }
    function selectedFiles() { return files().length ? files() : (fallback ? [fallback] : []); }
    function progress(text) { get('progress').textContent = text; }
    function synchronizeDomainSources() {
        var chosen = selectedFiles();
        if (domainSources === null) { domainSources = chosen.slice(); return false; }
        if (domainSources.length === chosen.length && domainSources.every(function (file, i) { return file === chosen[i]; })) return false;
        domainSources = chosen.slice();
        domainEdited = false;
        get('use-domain').checked = false;
        domainAxes.forEach(function (axis) { get('domain-' + axis).value = ''; });
        var box = get('domain-box');
        if (box) box.style.display = 'none';
        progress('Sources changed; the previous fixed domain was cleared. Declare a new domain for these sources if needed.');
        return true;
    }
    function readBounds(prefix, label) {
        var bounds = {};
        domainAxes.forEach(function (axis) {
            var value = get(prefix + axis).value;
            if (String(value).trim() === '' || !Number.isFinite(Number(value))) throw new Error(label + ': enter six finite coordinates in metres.');
            bounds[axis] = Number(value);
        });
        ['x','y','z'].forEach(function (axis) {
            if (bounds[axis + 'min'] >= bounds[axis + 'max']) throw new Error(label + ': ' + axis.toUpperCase() + ' minimum must be less than maximum.');
        });
        return bounds;
    }
    function getAuthHeaders(extraHeaders) {
        var headers = Object.assign({}, extraHeaders || {});
        var key = (typeof window !== 'undefined' && window.IFCFDS_API_KEY) || '';
        try { key = (window.localStorage && window.localStorage.getItem('ifcfds_api_key')) || key; } catch (_) { /* Storage may be disabled. */ }
        if (key) {
            headers['x-api-key'] = key;
        }
        return headers;
    }
    function authFetch(url, options) {
        options = options || {};
        options.headers = getAuthHeaders(options.headers);
        return fetch(url, options);
    }
    function response(res) {
        return res.json().then(function (data) {
            if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
            return data;
        });
    }
    function readInventory() {
        var token = ++inventoryGeneration;
        var data = new FormData();
        selectedFiles().forEach(function (file) { data.append('files', file); });
        progress('Reading inventory…');
        return authFetch('/api/inventory', {method: 'POST', body: data}).then(response).then(function (inventory) {
            if (token === inventoryGeneration) applyInventory(inventory);
        }).catch(function (err) { if (token === inventoryGeneration) progress(err.message); });
    }
    function applyInventory(inventory) {
            get('storeys').replaceChildren();
            (inventory.storey_references || []).forEach(function (storey) {
                var option = document.createElement('option');
                option.value = storey.storey_id;
                option.textContent = storey.name + ' [' + storey.source_id.slice(0, 8) + ' / ' + (storey.building_id || 'unassigned').split(':').pop() + ' / #' + storey.storey_id.split(':').pop() + ']';
                get('storeys').appendChild(option);
            });
            progress(inventory.total_elements + ' entities in ' + inventory.sources.length + ' sources');
            get('research-notice').textContent = ((inventory.research || {}).known_cases || []).map(function (c) { return c.name + ' [' + c.source_match + '] — research parity NOT RUN. Choose research profile and reference to compare.'; }).join(' ');
    }
    function transformInputs() {
        get('transforms').replaceChildren();
        if (files().length < 2) return;
        files().forEach(function (file, index) {
            var fieldset = document.createElement('fieldset');
            var legend = document.createElement('legend'); legend.textContent = file.name; fieldset.appendChild(legend);
            ['X (m)', 'Y (m)', 'Z (m)', 'Rotation Z (degrees)'].forEach(function (name, axis) {
                var label = document.createElement('label'); label.textContent = name;
                var input = document.createElement('input'); input.type = 'number'; input.step = 'any'; input.value = '0';
                input.id = 'verified-transform-' + index + '-' + axis;
                label.appendChild(input); fieldset.appendChild(label);
            });
            get('transforms').appendChild(fieldset);
        });
    }
    ns.verified = {
        getAuthHeaders: getAuthHeaders,
        authFetch: authFetch,
        queueScenarioBatch: function (scenarios, dispatchFn) {
            var panel = (ns.workbench && ns.workbench.panels && ns.workbench.panels.evScenarioPanel) || (ns.ui && ns.ui.evScenarioPanel);
            if (!panel) {
                return Promise.reject(new Error('evScenarioPanel module not loaded'));
            }
            return panel.queueScenarioBatch(scenarios, dispatchFn);
        },
        hasFiles: function () { return selectedFiles().length > 0; },
        setFallback: function (file) {
            fallback = file;
            if (synchronizeDomainSources()) { inventoryGeneration++; get('storeys').replaceChildren(); }
            var convertBtn = document.getElementById('convert-verified');
            if (convertBtn && file) convertBtn.disabled = false;
        },
        suggestDomainFromSource: function (file, bounds) {
            synchronizeDomainSources();
            var chosen = selectedFiles();
            // Viewer coordinates cannot define the domain of a different or federated source set.
            if (chosen.length !== 1 || chosen[0] !== file || domainEdited || get('use-domain').checked) return false;
            if (!bounds || !domainAxes.every(function (axis) { return typeof bounds[axis] === 'number' && Number.isFinite(bounds[axis]); }) ||
                !['x','y','z'].every(function (axis) { return bounds[axis + 'min'] < bounds[axis + 'max']; })) return false;
            domainAxes.forEach(function (axis) { get('domain-' + axis).value = String(bounds[axis]); });
            return true;
        },
        usePreviewInventory: function (inventory, file) {
            var chosen = selectedFiles();
            if (chosen.length === 1 && chosen[0] === file) {
                inventoryGeneration++;
                applyInventory(inventory);
                var convertBtn = document.getElementById('convert-verified');
                if (convertBtn) convertBtn.disabled = false;
            }
        },
        cancel: function () {
            stopped = true; generation++;
            var active = jobId; jobId = null; get('cancel').disabled = true;
            return active ? authFetch('/api/jobs/' + active + '/cancel', {method: 'POST'}).then(response) : Promise.resolve();
        },
        init: function () {
            synchronizeDomainSources();
            domainAxes.forEach(function (axis) {
                get('domain-' + axis).addEventListener('input', function () { domainEdited = true; });
            });
            get('use-domain').addEventListener('change', function () { if (get('use-domain').checked) domainEdited = true; });
            authFetch('/api/reference-cases').then(response).then(function (data) {
                data.cases.forEach(function (entry) {
                    var id = entry.id;
                    var option = document.createElement('option'); option.value = id; option.textContent = entry.name + ' (' + entry.approval_status + ')';
                    get('reference-case').appendChild(option);
                });
            }).catch(function () {});
            get('sources').addEventListener('change', function () {
                inventoryGeneration++;
                synchronizeDomainSources();
                ns.verified.cancel().catch(function (err) { progress(err.message); });
                transformInputs(); get('storeys').replaceChildren();
                document.getElementById('convert-verified').disabled = !selectedFiles().length;
            });
            get('inventory').addEventListener('click', readInventory);
            get('cancel').addEventListener('click', function () {
                ns.verified.cancel().then(function () { progress('Cancelled'); }).catch(function (err) { progress(err.message); });
            });
        },
        run: async function (file, configuration, onProgress) {
            fallback = file; stopped = false; jobId = null;
            synchronizeDomainSources();
            var runGeneration = ++generation, localJobId = null;
            if (location.protocol === 'file:') return Promise.reject(new Error('Open http://127.0.0.1:8000 for Verified Conversion'));
            var sources = selectedFiles();
            if (!sources.length) return Promise.reject(new Error('Select IFC sources first'));
            configuration.profile = get('profile').value;
            if (get('boundary-obst').checked) configuration.boundary_policy = 'VALIDATED_BOUNDARY_OBST_SINGLE_MESH';
            if (get('reference-case').value) configuration.reference_case = get('reference-case').value;
            if (get('decisions').files.length) configuration.decisions = JSON.parse(await get('decisions').files[0].text());
            if (get('system-decisions').files.length) configuration.system_decisions = JSON.parse(await get('system-decisions').files[0].text());
            if (get('deltas').files.length) configuration.intentional_deltas = JSON.parse(await get('deltas').files[0].text());
            if (get('use-domain').checked) {
                configuration.simulation_domain = readBounds('domain-', 'Fixed simulation domain');
                configuration.simulation_domain_coordinate_frame = 'WORLD';
            } else {
                delete configuration.simulation_domain;
                delete configuration.simulation_domain_coordinate_frame;
            }
            configuration.scope = {storeys: Array.prototype.filter.call(get('storeys').options, function (o) { return o.selected; }).map(function (o) { return o.value; })};
            if (get('use-bounds').checked) {
                configuration.scope.bounding_box = readBounds('', 'Export scope');
                configuration.scope.coordinate_frame = 'WORLD';
            }
            configuration.sources = {common_coordinates: get('common').checked};
            if (sources.length > 1 && !get('common').checked && !get('transform-confirm').checked) return Promise.reject(new Error('Confirm shared coordinates or confirm the source offsets before converting'));
            if (sources.length > 1 && !get('common').checked) {
                configuration.sources.transforms = {};
                sources.forEach(function (source, index) {
                    var values = [0,1,2,3].map(function (axis) { return Number(document.getElementById('verified-transform-' + index + '-' + axis).value); });
                    if (!values.every(isFinite)) throw new Error('Source offsets must be finite');
                    var theta = values[3] * Math.PI / 180, c = Math.cos(theta), s = Math.sin(theta);
                    configuration.sources.transforms[index] = [c,-s,0,values[0],s,c,0,values[1],0,0,1,values[2],0,0,0,1];
                });
            }
            var data = new FormData(); sources.forEach(function (source) { data.append('files', source); });
            if (runGeneration !== generation) throw cancelled();
            data.append('configuration', JSON.stringify(configuration)); get('cancel').disabled = false;
            progress('Uploading…');
            function poll() {
                if (stopped || runGeneration !== generation) return Promise.reject(cancelled());
                return authFetch('/api/jobs/' + localJobId).then(response).then(function (job) {
                    if (runGeneration !== generation) throw cancelled();
                    var statusText = job.state + (job.progress ? ' - ' + job.progress.stage : '');
                    if (job.progress && job.progress.total) statusText += ' ' + job.progress.completed + '/' + job.progress.total;
                    if (job.started) statusText += ' (' + Math.max(0, Math.floor(Date.now()/1000 - job.started)) + ' s)';
                    progress(statusText);
                    if (onProgress) onProgress(statusText, job.progress || {}, localJobId);
                    if (job.state === 'COMPLETED') return authFetch('/api/jobs/' + localJobId + '/result').then(response);
                    if (['FAILED','TIMED_OUT','CANCELLED'].indexOf(job.state) !== -1) {
                        var error = new Error(job.error || job.state);
                        error.stage = job.progress ? job.progress.stage : 'VALIDATION';
                        if (job.diagnostics_url) {
                            var link = document.createElement('a'); link.href = job.diagnostics_url;
                            link.textContent = 'Download conversion diagnostics'; link.download = '';
                            get('artifacts').replaceChildren(link);
                        }
                        throw error;
                    }
                    return new Promise(function (resolve) { setTimeout(resolve, 700); }).then(poll);
                });
            }
            return authFetch('/api/jobs', {method:'POST',body:data}).then(response).then(function (job) {
                localJobId = job.id;
                if (stopped || runGeneration !== generation) return authFetch('/api/jobs/' + localJobId, {method:'DELETE'}).then(function () { throw cancelled(); });
                jobId = localJobId;
                return poll();
            }).then(function (result) {
                if (runGeneration !== generation) throw cancelled();
                progress(result.status);
                get('artifacts').replaceChildren();
                Object.keys(result.artifacts || {}).forEach(function (name) {
                    var link = document.createElement('a'); link.href = result.artifacts[name].url;
                    link.textContent = 'Download ' + name; link.download = ''; link.style.display = 'block'; get('artifacts').appendChild(link);
                });
                result.job_id = localJobId;
                return result; })
                .catch(function (error) { error.jobId = localJobId; throw error; })
                .finally(function () { if (runGeneration === generation) { jobId = null; get('cancel').disabled = true; } });
        }
    };
})(window.IfcFds);
