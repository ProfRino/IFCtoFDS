// Generate FDS files from the bundled examples in both modes (HOLE + voxel) so we can
// feed them into FDS and see whether the namelist parses and the geometry is consistent.
// Outputs land under scripts/out/ so they're easy to pick up.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const ctx = { window: {}, console, FileReader: function () {} };
ctx.window = ctx;

[
    'js/vendor/earcut.min.js',
    'js/core/namespace.js',
    'js/core/diagnostics.js',
    'js/ifc/ifc-adapter.js',
    'js/fds/fds-exporter.js'
].forEach((file) => {
    vm.runInNewContext(
        fs.readFileSync(path.join(root, file), 'utf8'),
        ctx,
        { filename: file }
    );
});

const ifcAdapter = new ctx.IfcFds.ifc.IfcAdapter();
const exporter = new ctx.IfcFds.fds.FdsExporter();

const outDir = path.join(root, 'scripts', 'out');
if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });

const baseOpts = {
    mode: 'hybrid',
    cellSize: 0.1,
    voxelSize: 0.1,
    openingThickening: 0.05,
    openingVoxelPolicy: 'smaller',
    boxFriendlyThreshold: 0.8,
    includeFillSolids: false,
    includeReviewSolids: false
};

const cases = [
    { ifc: 'AC20-FZK-Haus.ifc', name: 'fzk' },
    { ifc: 'AC20-Institute-Var-2.ifc', name: 'inst' }
];

const variants = [
    { suffix: '_hole', opts: { useObstHoles: true, includeFillSolids: false } },
    { suffix: '_hole_closed', opts: { useObstHoles: true, includeFillSolids: true } },
    { suffix: '_voxel', opts: { useObstHoles: false, includeFillSolids: false } },
    { suffix: '_voxel_closed', opts: { useObstHoles: false, includeFillSolids: true } }
];

cases.forEach(c => {
    const ifcText = fs.readFileSync(path.join(root, 'examples', c.ifc), 'utf8');
    const model = ifcAdapter.parse(ifcText);
    variants.forEach(v => {
        const text = exporter.exportFromIfcScene(model, Object.assign({}, baseOpts, v.opts));
        const base = c.name + v.suffix;
        const target = path.join(outDir, base + '.fds');
        // Give each variant its own CHID so .out files don't overwrite each other.
        const tagged = text.replace("CHID='ifc_conversion'", "CHID='" + base + "'");
        fs.writeFileSync(target, tagged);
        const obstCount = (tagged.match(/&OBST /g) || []).length;
        const holeCount = (tagged.match(/&HOLE /g) || []).length;
        const geomCount = (tagged.match(/&GEOM /g) || []).length;
        console.log(base + ':', obstCount, 'OBST,', holeCount, 'HOLE,', geomCount, 'GEOM —', tagged.length, 'bytes');
    });
});
