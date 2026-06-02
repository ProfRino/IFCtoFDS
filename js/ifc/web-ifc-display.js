(function (ns) {
    // Display-only IFC geometry loader. Preferred path is a module Web Worker hosting the
    // web-ifc WASM kernel off the main thread. Falls back to a same-page main-thread engine
    // when the worker can't start (e.g. file:// origins, which Chrome blocks from spinning
    // up module workers). Either way the WASM kernel natively applies IfcRelVoidsElement
    // boolean subtractions so walls come out with their window/door openings cut.

    var WEB_IFC_CDN = 'https://cdn.jsdelivr.net/npm/web-ifc@0.0.77/';

    // -------- worker path ----------------------------------------------------

    var worker = null;
    var workerFailed = false;
    var nextId = 1;
    var pending = {};

    function ensureWorker() {
        if (workerFailed) return null;
        if (worker) return worker;
        try {
            worker = new Worker('js/workers/web-ifc-display-worker.js', { type: 'module' });
        } catch (err) {
            console.warn('web-ifc worker init failed, falling back to main thread:', err);
            workerFailed = true;
            return null;
        }
        worker.onmessage = function (event) {
            var msg = event.data || {};
            var cb = pending[msg.id];
            if (!cb) return;
            delete pending[msg.id];
            if (msg.type === 'meshes') cb.resolve(msg.meshes);
            else cb.reject(new Error(msg.message || 'web-ifc worker error'));
        };
        worker.onerror = function (event) {
            console.warn('web-ifc worker fatal error, falling back to main thread:', event.message || event);
            workerFailed = true;
            try { worker.terminate(); } catch (_) { /* ignore */ }
            worker = null;
            Object.keys(pending).forEach(function (key) {
                pending[key].reject(new Error('worker terminated'));
                delete pending[key];
            });
        };
        return worker;
    }

    function loadViaWorker(arrayBuffer) {
        var w = ensureWorker();
        if (!w) return Promise.reject(new Error('worker unavailable'));
        return new Promise(function (resolve, reject) {
            var id = nextId += 1;
            pending[id] = { resolve: resolve, reject: reject };
            try {
                var clone = arrayBuffer.slice(0);
                w.postMessage({ id: id, type: 'load', buffer: clone }, [clone]);
            } catch (err) {
                delete pending[id];
                reject(err);
            }
        });
    }

    // -------- main-thread fallback path --------------------------------------

    var mainApiPromise = null;

    function ensureMainThreadApi() {
        if (mainApiPromise) return mainApiPromise;
        mainApiPromise = (async function () {
            // Use the spec-compliant ES module form via dynamic import. Note we cannot use
            // a bare `import` statement here because this file ships as a classic script,
            // so we go through Function('return import(url)') to dodge the parser.
            var importer = new Function('url', 'return import(url)');
            var WebIFC = await importer(WEB_IFC_CDN + 'web-ifc-api.js');
            var api = new WebIFC.IfcAPI();
            api.SetWasmPath(WEB_IFC_CDN);
            await api.Init();
            return api;
        })().catch(function (err) {
            console.warn('web-ifc main-thread engine unavailable:', err);
            mainApiPromise = null; // allow another attempt later
            return null;
        });
        return mainApiPromise;
    }

    function loadViaMainThread(arrayBuffer) {
        return ensureMainThreadApi().then(function (api) {
            if (!api) return null;
            var bytes = new Uint8Array(arrayBuffer);
            var modelID = api.OpenModel(bytes);
            var meshes = [];
            try {
                api.StreamAllMeshes(modelID, function (flatMesh) {
                    var expressID = flatMesh.expressID;
                    var placed = flatMesh.geometries;
                    var count = placed.size();
                    for (var i = 0; i < count; i += 1) {
                        var entry = readPlacedGeometry(api, modelID, placed.get(i));
                        if (!entry) continue;
                        entry.expressID = expressID;
                        meshes.push(entry);
                    }
                });
            } finally {
                try { api.CloseModel(modelID); } catch (_) { /* ignore */ }
            }
            return meshes;
        });
    }

    function readPlacedGeometry(api, modelID, placed) {
        var geom = null;
        try {
            geom = api.GetGeometry(modelID, placed.geometryExpressID);
            var raw = api.GetVertexArray(geom.GetVertexData(), geom.GetVertexDataSize());
            var idx = api.GetIndexArray(geom.GetIndexData(), geom.GetIndexDataSize());
            var vc = raw.length / 6;
            var positions = new Float32Array(vc * 3);
            var normals = new Float32Array(vc * 3);
            for (var v = 0; v < vc; v += 1) {
                var r = v * 6;
                var w = v * 3;
                positions[w] = raw[r];
                positions[w + 1] = raw[r + 1];
                positions[w + 2] = raw[r + 2];
                normals[w] = raw[r + 3];
                normals[w + 1] = raw[r + 4];
                normals[w + 2] = raw[r + 5];
            }
            var indices = new Uint32Array(idx.length);
            indices.set(idx);
            return {
                positions: positions,
                normals: normals,
                indices: indices,
                color: { r: placed.color.x, g: placed.color.y, b: placed.color.z, a: placed.color.w },
                matrix: Array.prototype.slice.call(placed.flatTransformation)
            };
        } catch (err) {
            console.warn('web-ifc geometry read failed:', err);
            return null;
        } finally {
            if (geom && typeof geom.delete === 'function') {
                try { geom.delete(); } catch (_) { /* ignore */ }
            }
        }
    }

    // -------- public API ------------------------------------------------------

    function WebIfcDisplay() {}

    WebIfcDisplay.prototype.load = function (arrayBuffer) {
        return loadViaWorker(arrayBuffer)
            .catch(function (workerErr) {
                if (!workerFailed) {
                    console.warn('web-ifc worker run failed, retrying on main thread:', workerErr);
                }
                return loadViaMainThread(arrayBuffer);
            })
            .catch(function (err) {
                console.warn('web-ifc display load failed:', err);
                return null;
            });
    };

    ns.WebIfcDisplay = WebIfcDisplay;
})(window.IfcFds.ifc);
