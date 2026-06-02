(function (ns) {
    function FdsNamelistParser() {}

    FdsNamelistParser.prototype.parse = function (text) {
        var records = extractRecords(String(text || ''));
        var data = {
            head: {},
            meshes: [],
            obsts: [],
            vents: [],
            holes: [],
            geoms: [],
            surfs: {},
            rawRecords: records,
            diagnostics: []
        };

        var pendingIfcSource = null;
        records.forEach(function (record, index) {
            var params = parseBody(record.body);
            params.__recordIndex = index + 1;
            params.__group = record.group;

            if (record.group === 'IFC_SOURCE') {
                pendingIfcSource = normalizeIfcSource(params);
                return;
            }
            if (pendingIfcSource && (record.group === 'OBST' || record.group === 'GEOM')) {
                params.__ifcSource = pendingIfcSource;
                pendingIfcSource = null;
            }

            if (record.group === 'HEAD') data.head = params;
            else if (record.group === 'MESH') data.meshes.push(normalizeBoxRecord(params, 'MESH'));
            else if (record.group === 'OBST') data.obsts.push(normalizeBoxRecord(params, 'OBST'));
            else if (record.group === 'VENT') data.vents.push(normalizeBoxRecord(params, 'VENT'));
            else if (record.group === 'HOLE') data.holes.push(normalizeBoxRecord(params, 'HOLE'));
            else if (record.group === 'GEOM') data.geoms.push(normalizeGeomRecord(params));
            else if (record.group === 'SURF' && params.ID) data.surfs[params.ID] = params;
        });

        if (!data.meshes.length) {
            ns.core.addDiagnostic(
                data.diagnostics,
                'warning',
                'No MESH records found',
                'The viewer can render free geometry, but FDS needs at least one computational mesh.'
            );
        }

        return data;
    };

    function extractRecords(text) {
        var normalized = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
        var clean = removeComments(preserveIfcSourceComments(normalized));
        var records = [];
        var i = 0;

        while (i < clean.length) {
            var start = clean.indexOf('&', i);
            if (start < 0) break;

            var nameStart = start + 1;
            var nameEnd = nameStart;
            while (nameEnd < clean.length && /[A-Za-z0-9_]/.test(clean.charAt(nameEnd))) {
                nameEnd += 1;
            }

            var group = clean.slice(nameStart, nameEnd).trim().toUpperCase();
            if (!group) {
                i = nameEnd + 1;
                continue;
            }

            var end = findRecordEnd(clean, nameEnd);
            if (end < 0) break;

            if (group !== 'TAIL') {
                records.push({
                    group: group,
                    body: clean.slice(nameEnd, end).trim()
                });
            }
            i = end + 1;
        }

        return records;
    }

    function preserveIfcSourceComments(text) {
        return text.replace(/!\s*IFC_SOURCE\s*,?\s*([^\n]*)/gi, function (_, body) {
            return '&IFC_SOURCE ' + body + ' /';
        });
    }

    function removeComments(text) {
        var out = '';
        var inSingle = false;
        var inDouble = false;

        for (var i = 0; i < text.length; i += 1) {
            var ch = text.charAt(i);
            if (ch === "'" && !inDouble) inSingle = !inSingle;
            if (ch === '"' && !inSingle) inDouble = !inDouble;
            if (ch === '!' && !inSingle && !inDouble) {
                while (i < text.length && text.charAt(i) !== '\n') i += 1;
                out += '\n';
                continue;
            }
            out += ch;
        }

        return out;
    }

    function findRecordEnd(text, fromIndex) {
        var inSingle = false;
        var inDouble = false;

        for (var i = fromIndex; i < text.length; i += 1) {
            var ch = text.charAt(i);
            if (ch === "'" && !inDouble) inSingle = !inSingle;
            else if (ch === '"' && !inSingle) inDouble = !inDouble;
            else if (ch === '/' && !inSingle && !inDouble) return i;
        }

        return -1;
    }

    function parseBody(body) {
        var params = {};
        var tokens = splitOutsideQuotes(body);
        var key = null;
        var values = [];

        function commit() {
            if (!key) return;
            params[key] = values.length === 1 ? values[0] : values.slice();
            key = null;
            values = [];
        }

        tokens.forEach(function (token) {
            if (!token) return;
            var eqIndex = findEqualsOutsideQuotes(token);
            if (eqIndex >= 0) {
                commit();
                key = token.slice(0, eqIndex).trim().toUpperCase();
                values = parseValues(token.slice(eqIndex + 1));
            } else if (key) {
                values = values.concat(parseValues(token));
            }
        });

        commit();
        return params;
    }

    function splitOutsideQuotes(body) {
        var tokens = [];
        var current = '';
        var inSingle = false;
        var inDouble = false;

        for (var i = 0; i < body.length; i += 1) {
            var ch = body.charAt(i);
            if (ch === "'" && !inDouble) inSingle = !inSingle;
            if (ch === '"' && !inSingle) inDouble = !inDouble;

            if ((ch === ',' || /\s/.test(ch)) && !inSingle && !inDouble) {
                if (current.trim()) tokens.push(current.trim());
                current = '';
            } else {
                current += ch;
            }
        }

        if (current.trim()) tokens.push(current.trim());
        return tokens;
    }

    function findEqualsOutsideQuotes(token) {
        var inSingle = false;
        var inDouble = false;

        for (var i = 0; i < token.length; i += 1) {
            var ch = token.charAt(i);
            if (ch === "'" && !inDouble) inSingle = !inSingle;
            else if (ch === '"' && !inSingle) inDouble = !inDouble;
            else if (ch === '=' && !inSingle && !inDouble) return i;
        }

        return -1;
    }

    function parseValues(valueText) {
        var raw = String(valueText || '').trim();
        if (!raw) return [];

        var repetition = raw.match(/^(\d+)\*(.+)$/);
        if (repetition) {
            var count = parseInt(repetition[1], 10);
            var value = parseScalar(repetition[2]);
            var repeated = [];
            for (var i = 0; i < count; i += 1) repeated.push(value);
            return repeated;
        }

        return [parseScalar(raw)];
    }

    function parseScalar(raw) {
        var value = String(raw).trim();
        if ((value.charAt(0) === "'" && value.charAt(value.length - 1) === "'") ||
            (value.charAt(0) === '"' && value.charAt(value.length - 1) === '"')) {
            return value.slice(1, -1);
        }

        var upper = value.toUpperCase();
        if (upper === '.TRUE.' || upper === 'T') return true;
        if (upper === '.FALSE.' || upper === 'F') return false;

        var numeric = Number(value);
        return Number.isFinite(numeric) ? numeric : value;
    }

    function normalizeBoxRecord(params, fallbackPrefix) {
        return {
            id: params.ID || fallbackPrefix + '_' + params.__recordIndex,
            xb: toNumberArray(params.XB),
            ijk: toNumberArray(params.IJK),
            surf_id: params.SURF_ID || null,
            mult_id: params.MULT_ID || null,
            color: toNumberArray(params.RGB),
            ifcSource: params.__ifcSource || null,
            raw: params
        };
    }

    function normalizeGeomRecord(params) {
        return {
            id: params.ID || 'GEOM_' + params.__recordIndex,
            verts: toNumberArray(params.VERTS),
            faces: toNumberArray(params.FACES),
            poly: toNumberArray(params.POLY),
            surf_id: params.SURF_ID || null,
            sphere_radius: Number(params.SPHERE_RADIUS),
            sphere_origin: toNumberArray(params.SPHERE_ORIGIN),
            ifcSource: params.__ifcSource || null,
            raw: params
        };
    }

    function normalizeIfcSource(params) {
        return {
            outputType: params.OUTPUT || null,
            itemId: params.ITEM_ID || null,
            ifcType: params.IFC_TYPE || null,
            globalId: params.GLOBAL_ID || null,
            stepId: params.STEP_ID || null,
            name: params.NAME || null
        };
    }

    function toNumberArray(value) {
        if (value === undefined || value === null) return [];
        var arr = Array.isArray(value) ? value : [value];
        return arr
            .map(function (item) { return Number(item); })
            .filter(function (item) { return Number.isFinite(item); });
    }

    ns.fds.FdsNamelistParser = FdsNamelistParser;
    ns.fds._parseBody = parseBody;
})(window.IfcFds);
