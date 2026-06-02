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

const sourceName = 'AC20-FZK-Haus.ifc';
const sourcePath = path.join(root, 'examples', sourceName);
const outputPath = path.join(root, 'examples', 'AC20-FZK-Haus_obst-geom.fds');
const ifcAdapter = new ctx.IfcFds.ifc.IfcAdapter();
const exporter = new ctx.IfcFds.fds.FdsExporter();
const model = ifcAdapter.parse(fs.readFileSync(sourcePath, 'utf8'), sourceName);

const text = exporter.exportFromIfcScene(model, {
    mode: 'hybrid',
    cellSize: 0.1,
    voxelSize: 0.1,
    openingThickening: 0.05
});

fs.writeFileSync(outputPath, text);
console.log(`Generated ${path.relative(root, outputPath)} (${text.length} characters).`);
