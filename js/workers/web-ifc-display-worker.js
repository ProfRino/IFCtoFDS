// Display-only IFC geometry worker. Hosts ThatOpen's web-ifc WASM kernel off the main
// thread so the parse and StreamAllMeshes loop don't freeze the page on large models.
// Returns one entry per placedGeometry with positions/normals/indices/color/matrix/expressID.
// Typed-array buffers are transferred (not copied) back to the main thread.

let api = null;
let initPromise = null;

async function ensureInit() {
    if (initPromise) return initPromise;
    initPromise = (async () => {
        const WebIFC = await import('https://cdn.jsdelivr.net/npm/web-ifc@0.0.77/web-ifc-api.js');
        api = new WebIFC.IfcAPI();
        api.SetWasmPath('https://cdn.jsdelivr.net/npm/web-ifc@0.0.77/');
        await api.Init();
        return api;
    })();
    return initPromise;
}

self.onmessage = async (event) => {
    const msg = event.data || {};
    const id = msg.id;
    if (msg.type !== 'load') return;

    try {
        await ensureInit();
        const bytes = new Uint8Array(msg.buffer);
        const modelID = api.OpenModel(bytes);
        const meshes = [];
        const transferables = [];
        try {
            api.StreamAllMeshes(modelID, (flatMesh) => {
                const expressID = flatMesh.expressID;
                const placed = flatMesh.geometries;
                const placedCount = placed.size();
                for (let i = 0; i < placedCount; i += 1) {
                    const pg = placed.get(i);
                    let geom = null;
                    try {
                        geom = api.GetGeometry(modelID, pg.geometryExpressID);
                        const raw = api.GetVertexArray(geom.GetVertexData(), geom.GetVertexDataSize());
                        const idx = api.GetIndexArray(geom.GetIndexData(), geom.GetIndexDataSize());
                        const vc = raw.length / 6;
                        const positions = new Float32Array(vc * 3);
                        const normals = new Float32Array(vc * 3);
                        for (let v = 0; v < vc; v += 1) {
                            const r = v * 6;
                            const w = v * 3;
                            positions[w] = raw[r];
                            positions[w + 1] = raw[r + 1];
                            positions[w + 2] = raw[r + 2];
                            normals[w] = raw[r + 3];
                            normals[w + 1] = raw[r + 4];
                            normals[w + 2] = raw[r + 5];
                        }
                        const indices = new Uint32Array(idx.length);
                        indices.set(idx);
                        meshes.push({
                            expressID,
                            positions,
                            normals,
                            indices,
                            color: { r: pg.color.x, g: pg.color.y, b: pg.color.z, a: pg.color.w },
                            matrix: Array.from(pg.flatTransformation)
                        });
                        transferables.push(positions.buffer, normals.buffer, indices.buffer);
                    } finally {
                        if (geom && typeof geom.delete === 'function') {
                            try { geom.delete(); } catch (_) { /* ignore */ }
                        }
                    }
                }
            });
        } finally {
            try { api.CloseModel(modelID); } catch (_) { /* ignore */ }
        }
        self.postMessage({ id, type: 'meshes', meshes }, transferables);
    } catch (err) {
        self.postMessage({ id, type: 'error', message: String((err && err.message) || err) });
    }
};
