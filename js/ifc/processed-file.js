(function (ns) {
    // Serialize a parsed IFC model + web-ifc display meshes to a single .ifcfds payload
    // so subsequent opens of the same model skip the parse entirely. Same browser, another
    // browser, another machine — doesn't matter, the file is self-contained.

    var MAGIC = 'IFCFDS';
    var VERSION = 1;

    function typedReplacer(key, value) {
        if (value instanceof Float32Array) return { __typed: 'f32', data: Array.prototype.slice.call(value) };
        if (value instanceof Uint32Array)  return { __typed: 'u32', data: Array.prototype.slice.call(value) };
        if (value instanceof Uint16Array)  return { __typed: 'u16', data: Array.prototype.slice.call(value) };
        return value;
    }

    function typedReviver(key, value) {
        if (value && typeof value === 'object' && value.__typed) {
            if (value.__typed === 'f32') return new Float32Array(value.data);
            if (value.__typed === 'u32') return new Uint32Array(value.data);
            if (value.__typed === 'u16') return new Uint16Array(value.data);
        }
        return value;
    }

    function serialize(model, displayMeshes) {
        var payload = {
            magic: MAGIC,
            version: VERSION,
            savedAt: new Date().toISOString(),
            sourceName: model && model.fileName,
            model: model,
            displayMeshes: displayMeshes || null
        };
        return JSON.stringify(payload, typedReplacer);
    }

    function deserialize(text) {
        var payload = JSON.parse(text, typedReviver);
        if (!payload || payload.magic !== MAGIC) {
            throw new Error('Not a processed IFC file (missing IFCFDS header).');
        }
        if (typeof payload.version !== 'number' || payload.version > VERSION) {
            throw new Error('Processed file version ' + payload.version + ' is newer than supported (' + VERSION + ').');
        }
        return { model: payload.model, displayMeshes: payload.displayMeshes };
    }

    function looksLikeProcessed(fileName) {
        if (!fileName) return false;
        return /\.ifcfds$/i.test(fileName);
    }

    ns.ProcessedFile = {
        EXTENSION: '.ifcfds',
        MIME: 'application/x-ifcfds+json',
        serialize: serialize,
        deserialize: deserialize,
        looksLikeProcessed: looksLikeProcessed
    };
})(window.IfcFds.ifc);
