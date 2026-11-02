(function (ns) {
    function FdsGeometryAdapter() {}

    FdsGeometryAdapter.prototype.toSceneModel = function (fdsData) {
        var diagnostics = (fdsData.diagnostics || []).slice();
        var model = {
            meshes: [],
            obsts: [],
            vents: [],
            holes: [],
            geoms: [],
            hvac: [],
            bounds: null,
            triangleCount: 0,
            diagnostics: diagnostics
        };

        model.meshes = (fdsData.meshes || []).filter(hasValidXb).map(function (item) { return copyBox(item, fdsData.surfs); });
        model.obsts = (fdsData.obsts || []).filter(hasValidXb).map(function (item) { return copyBox(item, fdsData.surfs); });
        model.vents = (fdsData.vents || []).filter(hasValidXb).map(function (item) { return copyBox(item, fdsData.surfs); });
        model.holes = (fdsData.holes || []).filter(hasValidXb).map(function (item) { return copyBox(item, fdsData.surfs); });

        (fdsData.geoms || []).forEach(function (geom) {
            var converted = convertGeom(geom, diagnostics, fdsData.surfs);
            if (converted) {
                model.triangleCount += converted.faces.length;
                model.geoms.push(converted);
            }
        });

        var hvacNodes = Object.create(null);
        (fdsData.hvac || []).forEach(function (record) {
            if (record.TYPE_ID !== 'NODE') return;
            var xyz = record.XYZ;
            if (record.VENT_ID) {
                var vent = model.vents.filter(function (v) { return v.id === record.VENT_ID; })[0];
                if (vent) xyz = [0, 1, 2].map(function (a) { return (vent.xb[2*a] + vent.xb[2*a+1]) / 2; });
            }
            if (Array.isArray(xyz) && xyz.length === 3 && xyz.every(Number.isFinite)) hvacNodes[record.ID] = xyz.slice();
        });
        (fdsData.hvac || []).forEach(function (record) {
            if (record.TYPE_ID !== 'DUCT') return;
            var ids = record.NODE_ID || [];
            if (ids.length === 2 && hvacNodes[ids[0]] && hvacNodes[ids[1]]) {
                model.hvac.push({id: record.ID, vertices: [hvacNodes[ids[0]].slice(), hvacNodes[ids[1]].slice()],
                    ifcSource: record.__ifcSource || null, raw: record});
            } else {
                ns.core.addDiagnostic(diagnostics, 'warning', 'HVAC duct not displayed', record.ID + ': missing node coordinates or vent');
            }
        });

        // Restore the IFC world frame for display only. The saved FDS remains
        // rebased for the solver; IFC/FDS overlays and clipping share one frame.
        var offset = fdsData.coordinateRebase || [0, 0, 0];
        model.coordinateRebase = offset.slice();
        if (offset.some(function (value) { return value !== 0; })) {
            ['meshes', 'obsts', 'vents', 'holes'].forEach(function (key) {
                model[key].forEach(function (item) {
                    item.xb = item.xb.map(function (value, axis) { return value + offset[Math.floor(axis / 2)]; });
                });
            });
            model.hvac.forEach(function (duct) { duct.vertices = duct.vertices.map(function (p) { return p.map(function (v, a) { return v + offset[a]; }); }); });
            model.geoms.forEach(function (geom) {
                geom.vertices = geom.vertices.map(function (vertex) { return vertex.map(function (value, axis) { return value + offset[axis]; }); });
                if (geom.origin) geom.origin = geom.origin.map(function (value, axis) { return value + offset[axis]; });
            });
        }
        model.bounds = computeBounds(model);

        if (!model.obsts.length && !model.geoms.length && !model.vents.length && !model.hvac.length) {
            ns.core.addDiagnostic(
                diagnostics,
                'info',
                'No solid FDS geometry yet',
                'Load an FDS file containing OBST, VENT, or GEOM records to inspect conversion geometry.'
            );
        }

        return model;
    };

    function hasValidXb(item) {
        return item.xb && item.xb.length === 6 && item.xb.every(Number.isFinite);
    }

    function copyBox(item, surfs) {
        return {
            id: item.id,
            xb: normalizeXb(item.xb),
            ijk: item.ijk || [],
            surf_id: item.surf_id,
            color: resolveColor(item, surfs),
            ifcSource: item.ifcSource || null,
            raw: item.raw || item
        };
    }

    function normalizeXb(xb) {
        return [
            Math.min(xb[0], xb[1]),
            Math.max(xb[0], xb[1]),
            Math.min(xb[2], xb[3]),
            Math.max(xb[2], xb[3]),
            Math.min(xb[4], xb[5]),
            Math.max(xb[4], xb[5])
        ];
    }

    function normalizeRgb(rgb) {
        if (!rgb || rgb.length < 3) return null;
        return rgb.slice(0, 3).map(function (value) {
            return Math.max(0, Math.min(255, Math.round(value)));
        });
    }

    function resolveColor(item, surfs) {
        var direct = normalizeRgb(item.color);
        if (direct) return direct;
        var surface = item.surf_id && surfs ? surfs[item.surf_id] : null;
        return normalizeRgb(surface && surface.RGB);
    }

    function convertGeom(geom, diagnostics, surfs) {
        if (geom.verts && geom.verts.length >= 9 && geom.faces && geom.faces.length >= 3) {
            var vertices = [];
            for (var i = 0; i < geom.verts.length; i += 3) {
                vertices.push([geom.verts[i], geom.verts[i + 1], geom.verts[i + 2]]);
            }

            var faces = [];
            var stride = geom.faces.length % 4 === 0 ? 4 : 3;
            for (var f = 0; f + 2 < geom.faces.length; f += stride) {
                var a = geom.faces[f] - 1;
                var b = geom.faces[f + 1] - 1;
                var c = geom.faces[f + 2] - 1;
                if (vertices[a] && vertices[b] && vertices[c]) {
                    faces.push([a, b, c]);
                } else {
                    ns.core.addDiagnostic(
                        diagnostics,
                        'warning',
                        'GEOM face index out of range',
                        geom.id + ' contains a face referencing a missing vertex.'
                    );
                }
            }

            return {
                id: geom.id,
                type: 'trimesh',
                vertices: vertices,
                faces: faces,
                surf_id: geom.surf_id,
                color: resolveColor(geom, surfs),
                ifcSource: geom.ifcSource || null,
                raw: geom.raw || geom
            };
        }

        if (Number.isFinite(geom.sphere_radius) && geom.sphere_radius > 0) {
            return {
                id: geom.id,
                type: 'sphere',
                origin: geom.sphere_origin && geom.sphere_origin.length >= 3 ? geom.sphere_origin.slice(0, 3) : [0, 0, 0],
                radius: geom.sphere_radius,
                faces: [],
                vertices: [],
                surf_id: geom.surf_id,
                color: resolveColor(geom, surfs),
                ifcSource: geom.ifcSource || null,
                raw: geom.raw || geom
            };
        }

        ns.core.addDiagnostic(
            diagnostics,
            'warning',
            'Unsupported GEOM record',
            geom.id + ' is present, but this first workbench milestone only renders VERTS/FACES and sphere GEOM.'
        );
        return null;
    }

    function computeBounds(model) {
        var bounds = null;

        function include(x, y, z) {
            if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) return;
            if (!bounds) {
                bounds = { xmin: x, xmax: x, ymin: y, ymax: y, zmin: z, zmax: z };
                return;
            }
            bounds.xmin = Math.min(bounds.xmin, x);
            bounds.xmax = Math.max(bounds.xmax, x);
            bounds.ymin = Math.min(bounds.ymin, y);
            bounds.ymax = Math.max(bounds.ymax, y);
            bounds.zmin = Math.min(bounds.zmin, z);
            bounds.zmax = Math.max(bounds.zmax, z);
        }

        ['meshes', 'obsts', 'vents', 'holes'].forEach(function (key) {
            model[key].forEach(function (box) {
                include(box.xb[0], box.xb[2], box.xb[4]);
                include(box.xb[1], box.xb[3], box.xb[5]);
            });
        });

        model.geoms.forEach(function (geom) {
            if (geom.type === 'sphere') {
                include(geom.origin[0] - geom.radius, geom.origin[1] - geom.radius, geom.origin[2] - geom.radius);
                include(geom.origin[0] + geom.radius, geom.origin[1] + geom.radius, geom.origin[2] + geom.radius);
            } else {
                geom.vertices.forEach(function (v) { include(v[0], v[1], v[2]); });
            }
        });

        model.hvac.forEach(function (duct) { duct.vertices.forEach(function (p) { include(p[0], p[1], p[2]); }); });
        return bounds;
    }

    ns.fds.FdsGeometryAdapter = FdsGeometryAdapter;
})(window.IfcFds);
