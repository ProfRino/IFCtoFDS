(function (ns) {
    // Lightweight IFC metadata builder. One regex pass over the STEP text yields
    // entity ids, types, and names — enough for the sidebar, selection, and the
    // viewer's userData. No placements, no geometry, no boolean carving. The full
    // ifc-adapter parser only runs when the user clicks Convert to FDS.

    var STATEMENT_PATTERN = /#(\d+)\s*=\s*([A-Z0-9_]+)\s*\(([\s\S]*?)\)\s*;/gi;

    var REVIEW_TYPES = {
        IFCFURNISHINGELEMENT: 'Furnishing',
        IFCBUILDINGELEMENTPROXY: 'Building element proxy',
        IFCFLOWTERMINAL: 'Flow terminal',
        IFCFLOWFITTING: 'Flow fitting',
        IFCFLOWSEGMENT: 'Flow segment',
        IFCFLOWCONTROLLER: 'Flow controller',
        IFCDISTRIBUTIONELEMENT: 'Distribution element',
        IFCSANITARYTERMINAL: 'Sanitary terminal',
        IFCSTACKTERMINAL: 'Stack terminal',
        IFCELECTRICAPPLIANCE: 'Electric appliance',
        IFCLAMP: 'Lamp',
        IFCLIGHTFIXTURE: 'Light fixture',
        IFCSWITCHINGDEVICE: 'Switching device',
        IFCOUTLET: 'Outlet'
    };

    var SUPPORTED_PRODUCT = /^IFC(WALL|WALLSTANDARDCASE|SLAB|ROOF|COLUMN|BEAM|STAIR|STAIRFLIGHT|MEMBER|RAILING|CURTAINWALL|DOOR|WINDOW|SPACE|PLATE|COVERING|FOOTING|PILE|FURNISHINGELEMENT|BUILDINGELEMENTPROXY|FLOWTERMINAL|FLOWFITTING|FLOWSEGMENT|FLOWCONTROLLER|DISTRIBUTIONELEMENT|SANITARYTERMINAL|STACKTERMINAL|ELECTRICAPPLIANCE|LAMP|LIGHTFIXTURE|SWITCHINGDEVICE|OUTLET|RAMP|RAMPFLIGHT|TRANSPORTELEMENT)$/;

    function buildModel(text, fileName) {
        var elements = [];
        var openingHostIds = {};
        var diagnostics = [];
        var match;

        while ((match = STATEMENT_PATTERN.exec(text))) {
            var id = Number(match[1]);
            var type = match[2].toUpperCase();
            var args = splitTopLevel(match[3], ',');

            if (type === 'IFCRELVOIDSELEMENT') {
                var hostId = refId(args[4]);
                if (hostId) openingHostIds[hostId] = true;
                continue;
            }
            if (!SUPPORTED_PRODUCT.test(type)) continue;

            var classification = classifyType(type);
            var globalId = stepString(args[0]);
            var name = stepString(args[2]) || type + ' #' + id;
            elements.push({
                stepId: id,
                ifcType: type,
                globalId: globalId,
                name: name,
                convertible: classification.convertible,
                reference: classification.reference,
                exportAsSolid: classification.exportAsSolid,
                canExportAsSolid: classification.canExportAsSolid,
                fdsRole: classification.fdsRole,
                conversionNote: classification.note,
                openings: [],
                fillOpeningBounds: null,
                fillHostStepIds: [],
                mesh: null,
                displayMesh: undefined,
                bounds: null,
                raw: {
                    id: '#' + id,
                    type: type,
                    globalId: globalId,
                    name: name,
                    convertible: classification.convertible,
                    exportAsSolid: classification.exportAsSolid,
                    canExportAsSolid: classification.canExportAsSolid,
                    fdsRole: classification.fdsRole,
                    conversionNote: classification.note
                }
            });
        }

        return {
            fileName: fileName,
            schema: null,
            unitScale: 1,
            elements: elements,
            meshes: [],
            bounds: null,
            convertibleBounds: null,
            diagnostics: diagnostics,
            meta: true,
            stats: {
                openingHosts: Object.keys(openingHostIds).length,
                elements: elements.length
            }
        };
    }

    function classifyType(type) {
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

    function splitTopLevel(text, delimiter) {
        var parts = [];
        var current = '';
        var depth = 0;
        var inString = false;
        for (var index = 0; index < text.length; index += 1) {
            var c = text.charAt(index);
            if (c === "'") {
                current += c;
                if (text.charAt(index + 1) === "'") {
                    current += "'";
                    index += 1;
                } else {
                    inString = !inString;
                }
                continue;
            }
            if (!inString) {
                if (c === '(') depth += 1;
                if (c === ')') depth -= 1;
                if (c === delimiter && depth === 0) {
                    parts.push(current.trim());
                    current = '';
                    continue;
                }
            }
            current += c;
        }
        parts.push(current.trim());
        return parts;
    }

    function stepString(value) {
        var text = String(value || '').trim();
        if (text.charAt(0) !== "'" || text.charAt(text.length - 1) !== "'") return '';
        return text.slice(1, -1).replace(/''/g, "'");
    }

    function refId(value) {
        var match = String(value || '').trim().match(/^#(\d+)$/);
        return match ? Number(match[1]) : null;
    }

    ns.IfcMeta = {
        buildModel: buildModel
    };
})(window.IfcFds.ifc);
