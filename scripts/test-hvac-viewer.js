const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ctx = vm.createContext({console}); ctx.window = ctx;
for (const file of ['js/core/namespace.js', 'js/core/diagnostics.js', 'js/fds/namelist-parser.js', 'js/fds/fds-geometry-adapter.js']) {
    vm.runInContext(fs.readFileSync(file, 'utf8'), ctx, {filename: file});
}
const text = `! IFC_COORDINATE_REBASE X_OFFSET=1000 Y_OFFSET=2000 Z_OFFSET=10 /
&HEAD CHID='network' /
&MESH IJK=10,10,10, XB=0,1,0,1,0,1 /
&VENT ID='V1', XB=0,0,0,1,0,1, SURF_ID='HVAC' /
&HVAC TYPE_ID='NODE', ID='A', VENT_ID='V1', DUCT_ID='D' /
&HVAC TYPE_ID='NODE', ID='B', XYZ=1,0.5,0.5, DUCT_ID='D', AMBIENT=.TRUE. /
&HVAC TYPE_ID='DUCT', ID='D', NODE_ID='A','B', DIAMETER=0.2, LENGTH=1 /
&TAIL /`;
const parsed = new ctx.IfcFds.fds.FdsNamelistParser().parse(text);
const scene = new ctx.IfcFds.fds.FdsGeometryAdapter().toSceneModel(parsed);
assert.equal(parsed.hvac.length, 3);
assert.equal(scene.hvac.length, 1);
assert.equal(scene.obsts.length, 0, 'Network must not become solid obstructions');
assert.deepEqual(Array.from(scene.hvac[0].vertices[0]), [1000,2000.5,10.5]);
assert.deepEqual(Array.from(scene.hvac[0].vertices[1]), [1001,2000.5,10.5]);
assert.deepEqual(Array.from(parsed.hvac[1].XYZ), [1,0.5,0.5], 'Display must not mutate solver coordinates');
for (const file of ['js/vendor/three.min.js','js/viewer/scene-viewer.js']) {
    vm.runInContext(fs.readFileSync(file,'utf8'),ctx,{filename:file});
}
const viewer = Object.create(ctx.IfcFds.viewer.SceneViewer.prototype);
viewer.opacity = 0.7;
const line = viewer.makeHvacDuct(scene.hvac[0]);
assert.equal(line.isLine,true);
assert.deepEqual(Array.from(line.geometry.attributes.position.array), [1000,10.5,2000.5,1001,10.5,2000.5]);
line.geometry.dispose(); line.material.dispose();
console.log('HVAC parser/display preserves graph identity, vent positions and coordinate rebase without adding solids.');
