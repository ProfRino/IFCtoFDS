(function (ns) {
    function runChecks(fdsModel, ifcModel) {
        var diagnostics = [];

        if (fdsModel && fdsModel.diagnostics) {
            diagnostics = diagnostics.concat(fdsModel.diagnostics);
        }
        if (ifcModel && ifcModel.diagnostics) {
            diagnostics = diagnostics.concat(ifcModel.diagnostics);
        }

        if (fdsModel && fdsModel.bounds) {
            var b = fdsModel.bounds;
            var spanX = b.xmax - b.xmin;
            var spanY = b.ymax - b.ymin;
            var spanZ = b.zmax - b.zmin;
            if (spanX <= 0 || spanY <= 0 || spanZ <= 0) {
                ns.core.addDiagnostic(diagnostics, 'warning', 'Flat FDS bounds', 'The visible FDS geometry has a zero domain span in at least one axis.');
            }
            if (Math.max(Math.abs(b.xmin), Math.abs(b.xmax), Math.abs(b.ymin), Math.abs(b.ymax)) > 10000) {
                ns.core.addDiagnostic(diagnostics, 'warning', 'Large coordinate offset', 'The FDS geometry is far from the origin. IFC models often need recentering before FDS export.');
            }
        }

        if (fdsModel) {
            fdsModel.obsts.forEach(function (obst) {
                var sx = obst.xb[1] - obst.xb[0];
                var sy = obst.xb[3] - obst.xb[2];
                var sz = obst.xb[5] - obst.xb[4];
                if (sx <= 0 || sy <= 0 || sz <= 0) {
                    ns.core.addDiagnostic(diagnostics, 'warning', 'Thin or degenerate OBST', obst.id + ' has zero thickness in one direction.');
                }
            });

            var closedFillAssessments = assessClosedFillPerimeters(fdsModel);
            closedFillAssessments.forEach(function (assessment) {
                if (assessment.missingEdges.length) {
                    ns.core.addDiagnostic(
                        diagnostics,
                        'warning',
                        'Closed fill perimeter gap',
                        assessment.id + ' has unsupported ' + assessment.missingEdges.join(', ') +
                        ' perimeter contact. Smoke may leak around this generated ' + assessment.kind.toLowerCase() +
                        ' closure; reduce the voxel size or review the opening geometry.'
                    );
                }
            });

            if (closedFillAssessments.length && !closedFillAssessments.some(function (assessment) {
                return assessment.missingEdges.length;
            })) {
                ns.core.addDiagnostic(
                    diagnostics,
                    'success',
                    'Closed fill perimeters sealed',
                    closedFillAssessments.length + ' generated door/window closure(s) touch surrounding wall OBST geometry on every required edge.'
                );
            }

            fdsModel.geoms.forEach(function (geom) {
                if (geom.type !== 'trimesh') return;
                var quality = inspectGeom(geom);
                if (quality.degenerateFaces) {
                    ns.core.addDiagnostic(diagnostics, 'warning', 'Degenerate GEOM triangles', geom.id + ' contains ' + quality.degenerateFaces + ' near-zero-area triangle(s).');
                }
                if (quality.openEdges) {
                    ns.core.addDiagnostic(diagnostics, 'warning', 'Open GEOM mesh', geom.id + ' contains ' + quality.openEdges + ' boundary edge(s). FDS GEOM solids should be closed manifolds.');
                }
                if (quality.nonManifoldEdges) {
                    ns.core.addDiagnostic(diagnostics, 'warning', 'Non-manifold GEOM mesh', geom.id + ' contains ' + quality.nonManifoldEdges + ' edge(s) shared by more than two faces.');
                }
                if (quality.inconsistentEdges) {
                    ns.core.addDiagnostic(diagnostics, 'warning', 'Inconsistent GEOM normals', geom.id + ' contains ' + quality.inconsistentEdges + ' edge(s) whose adjacent faces have inconsistent orientation.');
                }
            });
        }

        if (!diagnostics.length) {
            ns.core.addDiagnostic(diagnostics, 'success', 'No obvious geometry issues', 'The loaded FDS geometry passed the first lightweight browser checks.');
        }

        return diagnostics;
    }

    function assessClosedFillPerimeters(fdsModel) {
        var obsts = fdsModel && fdsModel.obsts || [];
        var fills = obsts.filter(isClosedFillObst);
        var supports = obsts.filter(function (obst) { return !isClosedFillObst(obst); });

        return fills.map(function (fill) {
            var penetrationAxis = thinnestAxis(fill.xb);
            var tangentialAxes = [0, 1, 2].filter(function (axis) { return axis !== penetrationAxis; });
            var kind = fill.ifcSource.ifcType === 'IFCDOOR' ? 'Door' : 'Window';
            var edges = [];

            tangentialAxes.forEach(function (axis) {
                if (kind === 'Door' && axis === 2) {
                    edges.push({ axis: axis, side: 'max', label: 'top' });
                    return;
                }
                edges.push({ axis: axis, side: 'min', label: axis === 2 ? 'bottom' : 'side' });
                edges.push({ axis: axis, side: 'max', label: axis === 2 ? 'top' : 'side' });
            });

            var sideCount = 0;
            return {
                id: fill.id || kind + ' closure',
                kind: kind,
                fill: fill,
                missingEdges: edges.filter(function (edge) {
                    if (edge.label === 'side') {
                        sideCount += 1;
                        edge.label = sideCount === 1 ? 'left side' : 'right side';
                    }
                    return edgeSupportRatio(fill.xb, edge.axis, edge.side, supports) < 0.6;
                }).map(function (edge) { return edge.label; })
            };
        });
    }

    function edgeSupportRatio(fillXb, edgeAxis, side, supports) {
        var penetrationAxis = thinnestAxis(fillXb);
        var alongAxis = [0, 1, 2].filter(function (axis) {
            return axis !== penetrationAxis && axis !== edgeAxis;
        })[0];
        var fractions = [0.1, 0.5, 0.9];
        var boundary = fillXb[edgeAxis * 2 + (side === 'max' ? 1 : 0)];
        var direction = side === 'max' ? 1 : -1;
        var epsilon = Math.max(1e-5, axisSpan(fillXb, edgeAxis) * 1e-5);
        var tested = 0;
        var supported = 0;

        fractions.forEach(function (depthFraction) {
            fractions.forEach(function (alongFraction) {
                var point = [0, 0, 0];
                point[penetrationAxis] = axisValue(fillXb, penetrationAxis, depthFraction);
                point[alongAxis] = axisValue(fillXb, alongAxis, alongFraction);
                point[edgeAxis] = boundary + direction * epsilon;
                tested += 1;
                if (supports.some(function (obst) { return pointInsideXb(point, obst.xb); })) supported += 1;
            });
        });

        return tested ? supported / tested : 0;
    }

    function isClosedFillObst(obst) {
        var type = obst && obst.ifcSource && obst.ifcSource.ifcType;
        return type === 'IFCDOOR' || type === 'IFCWINDOW';
    }

    function thinnestAxis(xb) {
        var axis = 0;
        if (axisSpan(xb, 1) < axisSpan(xb, axis)) axis = 1;
        if (axisSpan(xb, 2) < axisSpan(xb, axis)) axis = 2;
        return axis;
    }

    function axisSpan(xb, axis) {
        return xb[axis * 2 + 1] - xb[axis * 2];
    }

    function axisValue(xb, axis, fraction) {
        return xb[axis * 2] + axisSpan(xb, axis) * fraction;
    }

    function pointInsideXb(point, xb) {
        if (!xb || xb.length !== 6) return false;
        return point[0] >= xb[0] && point[0] <= xb[1] &&
            point[1] >= xb[2] && point[1] <= xb[3] &&
            point[2] >= xb[4] && point[2] <= xb[5];
    }

    function triangleArea(a, b, c) {
        if (!a || !b || !c) return 0;
        var ab = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
        var ac = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
        var cross = [
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0]
        ];
        return 0.5 * Math.sqrt(cross[0] * cross[0] + cross[1] * cross[1] + cross[2] * cross[2]);
    }

    function inspectGeom(geom) {
        var edges = {};
        var degenerateFaces = 0;

        geom.faces.forEach(function (face) {
            var vertices = face.map(function (index) { return geom.vertices[index]; });
            if (triangleArea(vertices[0], vertices[1], vertices[2]) < 1e-8) {
                degenerateFaces += 1;
            }
            addEdge(edges, vertices[0], vertices[1]);
            addEdge(edges, vertices[1], vertices[2]);
            addEdge(edges, vertices[2], vertices[0]);
        });

        return Object.keys(edges).reduce(function (quality, key) {
            var edge = edges[key];
            if (edge.count === 1) quality.openEdges += 1;
            if (edge.count > 2) quality.nonManifoldEdges += 1;
            if (edge.count === 2 && edge.balance !== 0) quality.inconsistentEdges += 1;
            return quality;
        }, {
            degenerateFaces: degenerateFaces,
            openEdges: 0,
            nonManifoldEdges: 0,
            inconsistentEdges: 0
        });
    }

    function addEdge(edges, a, b) {
        var aKey = pointKey(a);
        var bKey = pointKey(b);
        var key = aKey < bKey ? aKey + '|' + bKey : bKey + '|' + aKey;
        var direction = aKey < bKey ? 1 : -1;
        edges[key] = edges[key] || { count: 0, balance: 0 };
        edges[key].count += 1;
        edges[key].balance += direction;
    }

    function pointKey(point) {
        return point.map(function (value) { return Number(value).toFixed(8); }).join(',');
    }

    ns.compare.runChecks = runChecks;
    ns.compare.assessClosedFillPerimeters = assessClosedFillPerimeters;
})(window.IfcFds);
