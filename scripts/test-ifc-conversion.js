const fs = require('fs');
const path = require('path');
const vm = require('vm');

// Keep the file:// inline bundles in sync with the live source on every test run.
// Anyone reading this app from file:// uses the *-inline.js bundles as the source of truth;
// if they lag behind the live JS the page silently runs the old behavior even after a hard
// reload.
require('./generate-inline-export-worker.js');
require('./generate-inline-parse-worker.js');

const root = path.resolve(__dirname, '..');
const ctx = { window: {}, console, FileReader: function () {} };
ctx.window = ctx;

[
    'js/vendor/earcut.min.js',
    'js/core/namespace.js',
    'js/core/diagnostics.js',
    'js/ifc/ifc-adapter.js',
    'js/fds/fds-exporter.js',
    'js/fds/namelist-parser.js',
    'js/fds/fds-geometry-adapter.js',
    'js/compare/checks.js'
].forEach((file) => {
    vm.runInNewContext(
        fs.readFileSync(path.join(root, file), 'utf8'),
        ctx,
        { filename: file }
    );
});

const examples = [
    'AC20-FZK-Haus.ifc',
    'AC20-Institute-Var-2.ifc',
    'IfcOpenShell-Duplex.ifc'
];
const requiredClosedElements = {
    'AC20-FZK-Haus.ifc': [
        'Wand-Ext-OG-1',
        'Wand-Ext-OG-2',
        'Wand-Ext-OG-3',
        'Wand-Ext-OG-4'
    ]
};
const requiredSlabShafts = {
    'AC20-FZK-Haus.ifc': [
        {
            slab: 'Slab-033',
            solidPoint: [1, 1],
            shaftPoint: [9, 2],
            topZ: 2.7
        }
    ]
};

const ifcAdapter = new ctx.IfcFds.ifc.IfcAdapter();
const exporter = new ctx.IfcFds.fds.FdsExporter();
const parser = new ctx.IfcFds.fds.FdsNamelistParser();
const fdsAdapter = new ctx.IfcFds.fds.FdsGeometryAdapter();
const meshCellSize = 0.4;
const voxelSize = 0.25;
const openingThickening = 0.05;
const rows = [];
const failures = [];

for (const fileName of examples) {
    const filePath = path.join(root, 'examples', fileName);
    if (!fs.existsSync(filePath)) {
        failures.push(`${fileName}: missing example file`);
        continue;
    }

    const ifcText = fs.readFileSync(filePath, 'utf8');
    const model = ifcAdapter.parse(ifcText, fileName);
    const exportOptions = { cellSize: meshCellSize, voxelSize, openingThickening };
    const convertible = exporter.getExportableElements(model, exportOptions);
    const sourceTriangles = convertible.reduce((sum, element) => sum + element.mesh.faces.length, 0);

    const obstText = exporter.exportFromIfcScene(model, { ...exportOptions, mode: 'obst' });
    const hybridText = exporter.exportFromIfcScene(model, { ...exportOptions, mode: 'hybrid' });
    const geomText = exporter.exportFromIfcScene(model, { ...exportOptions, mode: 'geom' });
    if (!hybridText.includes('! Hole voxel policy: smaller.')) {
        failures.push(`${fileName}: hybrid export did not default to the smaller-hole policy`);
    }
    const obstScene = fdsAdapter.toSceneModel(parser.parse(obstText));
    const hybridScene = fdsAdapter.toSceneModel(parser.parse(hybridText));
    const geomScene = fdsAdapter.toSceneModel(parser.parse(geomText));
    const hybridSummary = exporter.summarizeStrategy(model, { ...exportOptions, mode: 'hybrid' });

    const row = {
        file: fileName,
        entities: model.stats.entities,
        imported: model.elements.length,
        fdsReady: convertible.length,
        sourceTriangles: sourceTriangles,
        exportedObsts: obstScene.obsts.length,
        hybridObsts: hybridScene.obsts.length,
        hybridGeoms: hybridScene.geoms.length,
        hybridTriangles: hybridScene.triangleCount,
        exportedGeoms: geomScene.geoms.length,
        exportedTriangles: geomScene.triangleCount
    };
    rows.push(row);

    if (row.exportedObsts < row.fdsReady) {
        failures.push(`${fileName}: expected at least ${row.fdsReady} voxel OBST records, got ${row.exportedObsts}`);
    }
    if (row.exportedGeoms !== row.fdsReady) {
        failures.push(`${fileName}: expected ${row.fdsReady} GEOM records, got ${row.exportedGeoms}`);
    }
    if (row.hybridObsts !== hybridSummary.obsts || row.hybridGeoms !== hybridSummary.geoms) {
        failures.push(`${fileName}: hybrid summary mismatch`);
    }
    if (row.hybridTriangles !== hybridSummary.triangles) {
        failures.push(`${fileName}: expected ${hybridSummary.triangles} hybrid triangles, got ${row.hybridTriangles}`);
    }
    if (row.exportedTriangles !== row.sourceTriangles) {
        failures.push(`${fileName}: expected ${row.sourceTriangles} GEOM triangles, got ${row.exportedTriangles}`);
    }
    if (!obstScene.obsts.every((obst) => obst.ifcSource && obst.ifcSource.ifcType && obst.ifcSource.globalId)) {
        failures.push(`${fileName}: voxel OBST records lost IFC source metadata`);
    }
    if (!hybridScene.obsts.every((obst) => obst.ifcSource && obst.ifcSource.ifcType && obst.ifcSource.globalId) ||
        !hybridScene.geoms.every((geom) => geom.ifcSource && geom.ifcSource.ifcType && geom.ifcSource.globalId)) {
        failures.push(`${fileName}: Option 1 records lost IFC source metadata`);
    }
    if (!geomScene.geoms.every((geom) => geom.ifcSource && geom.ifcSource.ifcType && geom.ifcSource.globalId)) {
        failures.push(`${fileName}: GEOM records lost IFC source metadata`);
    }
    if (!obstText.includes('Opening depth margin: 0.05 m')) {
        failures.push(`${fileName}: voxel export did not record the opening depth margin`);
    }
    if (!obstText.includes('FDS mesh target cell size: 0.4 m') ||
        !obstText.includes('Voxel size: 0.25 m')) {
        failures.push(`${fileName}: FDS mesh and voxel resolutions were not recorded independently`);
    }

    const furnishingElements = model.elements.filter((element) => element.ifcType === 'IFCFURNISHINGELEMENT');
    if (furnishingElements.length) {
        if (convertible.some((element) => element.ifcType === 'IFCFURNISHINGELEMENT')) {
            failures.push(`${fileName}: furnishings should remain review-only by default`);
        }
        const withReviewObjects = exporter.getExportableElements(model, { ...exportOptions, includeReviewSolids: true });
        if (!withReviewObjects.some((element) => element.ifcType === 'IFCFURNISHINGELEMENT')) {
            failures.push(`${fileName}: review object option did not include furnishings`);
        }
    }

    (requiredClosedElements[fileName] || []).forEach((name) => {
        const element = model.elements.find((candidate) => candidate.name === name);
        if (!element) {
            failures.push(`${fileName}: missing required clipped element ${name}`);
            return;
        }
        const openEdges = countOpenEdges(element.mesh);
        if (openEdges) {
            failures.push(`${fileName}: clipped element ${name} has ${openEdges} open mesh edge(s)`);
        }
    });

    (requiredSlabShafts[fileName] || []).forEach((check) => {
        const slab = model.elements.find((candidate) => candidate.name === check.slab);
        if (!slab) {
            failures.push(`${fileName}: missing shaft host slab ${check.slab}`);
            return;
        }
        const openEdges = countOpenEdges(slab.mesh);
        if (openEdges) {
            failures.push(`${fileName}: shaft host slab ${check.slab} has ${openEdges} open mesh edge(s)`);
        }
        if (!hasHorizontalTriangleAtPoint(slab.mesh, check.solidPoint, check.topZ)) {
            failures.push(`${fileName}: shaft host slab ${check.slab} lost solid floor coverage`);
        }
        if (hasHorizontalTriangleAtPoint(slab.mesh, check.shaftPoint, check.topZ)) {
            failures.push(`${fileName}: shaft host slab ${check.slab} still covers the spiral stair shaft`);
        }

        const voxelSlab = obstScene.obsts.filter((obst) => obst.id.startsWith(`${check.slab}_v`));
        if (voxelSlab.length < 2) {
            failures.push(`${fileName}: voxel OBST did not split shaft host ${check.slab} around its opening`);
        }
        if (voxelSlab.some((obst) => obstContainsPoint(obst, [...check.shaftPoint, check.topZ - 0.1]))) {
            failures.push(`${fileName}: voxel OBST still covers the spiral stair shaft`);
        }

        const hybridSlab = hybridScene.obsts.filter((obst) => obst.id.startsWith(`${check.slab}_v`));
        if (hybridSlab.some((obst) => obstContainsPoint(obst, [...check.shaftPoint, check.topZ - 0.1]))) {
            failures.push(`${fileName}: hybrid FDS voxel host still covers the spiral stair shaft`);
        }
    });

    if (fileName === 'AC20-FZK-Haus.ifc') {
        const voxelRoof = obstScene.obsts.filter((obst) => obst.id.startsWith('Dach-1_v'));
        if (voxelRoof.length < 3) {
            failures.push(`${fileName}: voxel OBST did not stair-step the sloped Dach-1 roof`);
        }

        const fineHybridText = exporter.exportFromIfcScene(model, {
            ...exportOptions,
            mode: 'hybrid',
            voxelSize: 0.1,
            openingVoxelPolicy: 'larger'
        });
        const fineHybridScene = fdsAdapter.toSceneModel(parser.parse(fineHybridText));
        const smallerHoleText = exporter.exportFromIfcScene(model, {
            ...exportOptions,
            mode: 'hybrid',
            voxelSize: 0.1,
            openingVoxelPolicy: 'smaller'
        });
        const smallerHoleScene = fdsAdapter.toSceneModel(parser.parse(smallerHoleText));
        const edgeOfWindow = [0.15, 6.45, 1.4];
        if (fineHybridScene.obsts.some((obst) => obstContainsPoint(obst, edgeOfWindow))) {
            failures.push(`${fileName}: larger-hole policy did not clear the edge voxel beside EG-Fenster-6`);
        }
        if (!smallerHoleScene.obsts.some((obst) => obstContainsPoint(obst, edgeOfWindow))) {
            failures.push(`${fileName}: smaller-hole policy did not retain the edge voxel beside EG-Fenster-6`);
        }
        model.elements
            .filter((element) => element.ifcType === 'IFCDOOR' || element.ifcType === 'IFCWINDOW')
            .forEach((fill) => {
                const bounds = fill.bounds;
                const center = [
                    (bounds.xmin + bounds.xmax) / 2,
                    (bounds.ymin + bounds.ymax) / 2,
                    (bounds.zmin + bounds.zmax) / 2
                ];
                if (fineHybridScene.obsts.some((obst) => obstContainsPoint(obst, center))) {
                    failures.push(`${fileName}: fine hybrid FDS still covers door/window opening ${fill.name}`);
                }
            });

        [
            { name: 'EG-Fenster-6', point: [0.15, 7.5, 1.4] },
            { name: 'OG-Fenster-2', point: [0.15, 5, 4] }
        ].forEach((opening) => {
            if (obstScene.obsts.some((obst) => obstContainsPoint(obst, opening.point))) {
                failures.push(`${fileName}: voxel OBST still covers window opening ${opening.name}`);
            }
            if (obstScene.obsts.some((obst) => obst.id.startsWith(opening.name))) {
                failures.push(`${fileName}: window fill ${opening.name} was exported as a solid OBST`);
            }
            if (hybridScene.obsts.some((obst) => obstContainsPoint(obst, opening.point))) {
                failures.push(`${fileName}: hybrid FDS still covers window opening ${opening.name}`);
            }
        });

    const closedFillText = exporter.exportFromIfcScene(model, {
        ...exportOptions,
        mode: 'obst',
        voxelSize: 0.1,
        includeFillSolids: true
    });
        const closedFillScene = fdsAdapter.toSceneModel(parser.parse(closedFillText));
        const closedWindow = closedFillScene.obsts.find((obst) => obst.id === 'EG-Fenster-6');
        const closedDoor = closedFillScene.obsts.find((obst) => obst.ifcSource && obst.ifcSource.ifcType === 'IFCDOOR');
        const closedFillObsts = closedFillScene.obsts.filter((obst) =>
            obst.ifcSource && (obst.ifcSource.ifcType === 'IFCDOOR' || obst.ifcSource.ifcType === 'IFCWINDOW'));
        const closedFillGeoms = closedFillScene.geoms.filter((geom) =>
            geom.ifcSource && (geom.ifcSource.ifcType === 'IFCDOOR' || geom.ifcSource.ifcType === 'IFCWINDOW'));
        if (!closedWindow) {
            failures.push(`${fileName}: closed-fill option did not export EG-Fenster-6 as a solid`);
        }
        if (!closedWindow || !closedWindow.ifcSource || closedWindow.ifcSource.ifcType !== 'IFCWINDOW' ||
            !closedWindow.color || closedWindow.color.join(',') !== '92,178,214') {
            failures.push(`${fileName}: closed window fill did not retain glass-blue IFC source styling`);
        }
        if (!closedDoor || !closedDoor.color || closedDoor.color.join(',') !== '150,88,46') {
            failures.push(`${fileName}: closed door fill did not retain brown IFC source styling`);
        }
        if (closedFillObsts.length !== 16 || closedFillGeoms.length) {
            failures.push(`${fileName}: closed-fill option should export all 16 door/window closures as OBST and none as GEOM`);
        }
        if (!closedWindow || closedWindow.xb[0] !== 0 || closedWindow.xb[1] !== 0.3) {
            failures.push(`${fileName}: closed window OBST did not align to the voxelized host wall depth`);
        }
        if (ctx.IfcFds.compare.assessClosedFillPerimeters(closedFillScene).some((assessment) => assessment.missingEdges.length)) {
            failures.push(`${fileName}: closed-fill perimeter assessment reported unsupported generated closures`);
        }

        const spiralStair = model.elements.find((element) => element.name === 'Wendeltreppe');
        const overrideText = exporter.exportFromIfcScene(model, {
            ...exportOptions,
            mode: 'hybrid',
            forceObstStepIds: [String(spiralStair.stepId)]
        });
        const overrideScene = fdsAdapter.toSceneModel(parser.parse(overrideText));
        if (!overrideScene.obsts.some((obst) => obst.ifcSource && obst.ifcSource.stepId === `#${spiralStair.stepId}`) ||
            overrideScene.geoms.some((geom) => geom.ifcSource && geom.ifcSource.stepId === `#${spiralStair.stepId}`)) {
            failures.push(`${fileName}: manual GEOM-to-OBST override did not reroute Wendeltreppe`);
        }

        const windowMapping = exporter.summarizeIfcMapping(model, exportOptions)
            .find((row) => row.ifcType === 'IFCWINDOW');
        const closedWindowMapping = exporter.summarizeIfcMapping(model, { ...exportOptions, includeFillSolids: true })
            .find((row) => row.ifcType === 'IFCWINDOW');
        if (!windowMapping || windowMapping.role !== 'opening' || windowMapping.exported !== 0) {
            failures.push(`${fileName}: default IFCWINDOW mapping should remain an unexported opening`);
        }
        if (!closedWindowMapping || closedWindowMapping.exported !== closedWindowMapping.imported) {
            failures.push(`${fileName}: closed-fill IFCWINDOW mapping did not include all windows`);
        }
    }

    if (fileName === 'IfcOpenShell-Duplex.ifc') {
        const stairFlights = model.elements.filter((element) => element.ifcType === 'IFCSTAIRFLIGHT');
        const stairMembers = model.elements.filter((element) => element.ifcType === 'IFCMEMBER');
        const stairRailings = model.elements.filter((element) => element.ifcType === 'IFCRAILING');
        const exportedStairGeoms = hybridScene.geoms.filter((geom) => {
            return geom.ifcSource &&
                (geom.ifcSource.ifcType === 'IFCSTAIRFLIGHT' || geom.ifcSource.ifcType === 'IFCMEMBER');
        });
        const exportedRailings = hybridScene.geoms.filter((geom) => {
            return geom.ifcSource && geom.ifcSource.ifcType === 'IFCRAILING';
        });
        if (stairFlights.length !== 2 || stairMembers.length !== 4) {
            failures.push(`${fileName}: expected 2 stair flights and 4 stair stringers from decomposed IFC stair assemblies`);
        }
        if (stairRailings.length !== 4 || stairRailings.some((railing) => !railing.mesh.faces.length || railing.reference === true)) {
            failures.push(`${fileName}: expected 4 visible stair railings from IfcFaceBasedSurfaceModel geometry`);
        }
        if (exportedStairGeoms.length !== 6) {
            failures.push(`${fileName}: expected decomposed stair geometry to export as 6 detailed GEOM records`);
        }
        if (exportedRailings.length) {
            failures.push(`${fileName}: review-only stair railings should stay out of the default FDS export`);
        }
    }
}

const malformedGeomScene = {
    diagnostics: [],
    bounds: { xmin: 0, xmax: 1, ymin: 0, ymax: 1, zmin: 0, zmax: 1 },
    obsts: [],
    geoms: [
        {
            id: 'Open-test',
            type: 'trimesh',
            vertices: [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
            faces: [[0, 1, 2]]
        }
    ]
};
const malformedDiagnostics = ctx.IfcFds.compare.runChecks(malformedGeomScene, null);
if (!malformedDiagnostics.some((diagnostic) => diagnostic.title === 'Open GEOM mesh')) {
    failures.push('GEOM diagnostics: open synthetic mesh was not reported');
}

const sealedClosedFillScene = {
    obsts: [
        { id: 'Window closure', xb: [0, 0.2, 1, 2, 1, 2], ifcSource: { ifcType: 'IFCWINDOW' } },
        { id: 'Wall left', xb: [0, 0.2, 0.9, 1, 0.9, 2.1] },
        { id: 'Wall right', xb: [0, 0.2, 2, 2.1, 0.9, 2.1] },
        { id: 'Wall bottom', xb: [0, 0.2, 1, 2, 0.9, 1] },
        { id: 'Wall top', xb: [0, 0.2, 1, 2, 2, 2.1] }
    ]
};
if (ctx.IfcFds.compare.assessClosedFillPerimeters(sealedClosedFillScene)[0].missingEdges.length) {
    failures.push('Closed-fill diagnostics: sealed synthetic window was reported as leaking');
}
const leakingClosedFillScene = {
    obsts: sealedClosedFillScene.obsts.filter((obst) => obst.id !== 'Wall top')
};
if (!ctx.IfcFds.compare.assessClosedFillPerimeters(leakingClosedFillScene)[0].missingEdges.includes('top')) {
    failures.push('Closed-fill diagnostics: synthetic missing top wall contact was not reported');
}

const optionOneSummary = exporter.summarizeStrategy({
    elements: [
        {
            ifcType: 'IFCFURNISHINGELEMENT',
            fdsRole: 'review',
            convertible: false,
            canExportAsSolid: true,
            exportAsSolid: false,
            bounds: { xmin: 0, xmax: 1, ymin: 0, ymax: 1, zmin: 0, zmax: 1 },
            mesh: boxMesh(0, 1, 0, 1, 0, 1)
        },
        {
            stepId: 77,
            ifcType: 'IFCSTAIR',
            fdsRole: 'solid',
            convertible: true,
            exportAsSolid: true,
            bounds: { xmin: 0, xmax: 1, ymin: 0, ymax: 1, zmin: 0, zmax: 1 },
            mesh: {
                vertices: [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0.5, 0.5, 1]],
                faces: [[0, 1, 2], [0, 1, 3], [1, 2, 3], [2, 0, 3]]
            }
        }
    ]
}, { mode: 'hybrid', includeReviewSolids: true });
if (optionOneSummary.obsts !== 1 || optionOneSummary.geoms !== 1) {
    failures.push('Option 1 routing: expected a simple furnishing block as OBST and an irregular stair as GEOM');
}
const forcedOptionOneSummary = exporter.summarizeStrategy({
    elements: [
        {
            stepId: 77,
            ifcType: 'IFCSTAIR',
            fdsRole: 'solid',
            convertible: true,
            exportAsSolid: true,
            bounds: { xmin: 0, xmax: 1, ymin: 0, ymax: 1, zmin: 0, zmax: 1 },
            mesh: {
                vertices: [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0.5, 0.5, 1]],
                faces: [[0, 1, 2], [0, 1, 3], [1, 2, 3], [2, 0, 3]]
            }
        }
    ]
}, { mode: 'hybrid', forceObstStepIds: ['77'] });
if (forcedOptionOneSummary.obsts < 1 || forcedOptionOneSummary.geoms !== 0) {
    failures.push('Manual override routing: expected selected irregular stair to become voxel OBST');
}

console.table(rows);

if (failures.length) {
    console.error('\nConversion test failures:');
    failures.forEach((failure) => console.error(`- ${failure}`));
    process.exit(1);
}

console.log('\nAll IFC conversion tests passed.');

function countOpenEdges(mesh) {
    const edges = new Map();

    mesh.faces.forEach((face) => {
        [
            [face[0], face[1]],
            [face[1], face[2]],
            [face[2], face[0]]
        ].forEach(([a, b]) => {
            const aKey = pointKey(mesh.vertices[a]);
            const bKey = pointKey(mesh.vertices[b]);
            const edgeKey = aKey < bKey ? `${aKey}|${bKey}` : `${bKey}|${aKey}`;
            edges.set(edgeKey, (edges.get(edgeKey) || 0) + 1);
        });
    });

    return [...edges.values()].filter((count) => count === 1).length;
}

function pointKey(point) {
    return point.map((value) => Number(value).toFixed(8)).join(',');
}

function hasHorizontalTriangleAtPoint(mesh, point, z) {
    return mesh.faces.some((face) => {
        const triangle = face.map((index) => mesh.vertices[index]);
        if (!triangle.every((vertex) => Math.abs(vertex[2] - z) < 1e-8)) return false;
        return pointInTriangle2d(point, triangle);
    });
}

function pointInTriangle2d(point, triangle) {
    const [a, b, c] = triangle;
    const denominator = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1]);
    if (Math.abs(denominator) < 1e-12) return false;
    const alpha = ((b[1] - c[1]) * (point[0] - c[0]) + (c[0] - b[0]) * (point[1] - c[1])) / denominator;
    const beta = ((c[1] - a[1]) * (point[0] - c[0]) + (a[0] - c[0]) * (point[1] - c[1])) / denominator;
    const gamma = 1 - alpha - beta;
    return alpha >= -1e-8 && beta >= -1e-8 && gamma >= -1e-8;
}

function obstContainsPoint(obst, point) {
    return point[0] > obst.xb[0] + 1e-8 && point[0] < obst.xb[1] - 1e-8 &&
        point[1] > obst.xb[2] + 1e-8 && point[1] < obst.xb[3] - 1e-8 &&
        point[2] > obst.xb[4] + 1e-8 && point[2] < obst.xb[5] - 1e-8;
}

function boxMesh(xmin, xmax, ymin, ymax, zmin, zmax) {
    return {
        vertices: [
            [xmin, ymin, zmin], [xmax, ymin, zmin], [xmax, ymax, zmin], [xmin, ymax, zmin],
            [xmin, ymin, zmax], [xmax, ymin, zmax], [xmax, ymax, zmax], [xmin, ymax, zmax]
        ],
        faces: [
            [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
            [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
            [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]
        ]
    };
}
