const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({console}); context.window=context;
for (const file of ['js/core/namespace.js','js/core/diagnostics.js','js/fds/fds-exporter.js','js/fds/namelist-parser.js','js/fds/fds-geometry-adapter.js'])
    vm.runInContext(fs.readFileSync(file,'utf8'),context,{filename:file});
const exporter=new context.IfcFds.fds.FdsExporter();
const vertices=[[593000,1198000,0],[593001,1198000,0],[593000,1198001,0],[593000,1198000,0.0000001]];
const faces=[[0,2,1],[0,1,3],[1,2,3],[2,0,3],[0,0,1]];
const element={name:'Basic Wall:AR-Wall-220',stepId:2106,globalId:'guid-2106',ifcType:'IFCWALL',convertible:true,
    mesh:{vertices,faces},bounds:{xmin:593000,xmax:593001,ymin:1198000,ymax:1198001,zmin:0,zmax:.0000001}};
const text=exporter.exportFromIfcScene({elements:[element]},{mode:'geom'});
assert.match(text,/,\n\s+FACES=/,'GEOM array fields must have an explicit comma separator');
assert.match(text,/1e-7/,'GEOM coordinates must survive binary64 round trip');
const records=new context.IfcFds.fds.FdsNamelistParser().parse(text);
assert.equal(records.geoms.length,1);
const record=records.geoms[0];
assert.doesNotMatch(record.id,/[<>:"/\\|?*]/,'GEOM ID must be a legal bingeom filename on Windows');
assert.equal(record.faces.length,4*4,'Only exactly zero-area triangles should be removed');
assert.ok(text.includes("NAME='Basic Wall:AR-Wall-220'"),'Original IFC name must remain in provenance');
const broken={...element,mesh:{vertices,faces:[[0,1,100]]}};
assert.throws(() => exporter.exportFromIfcScene({elements:[broken]},{mode:'geom'}),
    {name:'ExportGeometryInputError', stage:'serialization', entityId:2106, message:/valid integer vertex indices/});
assert.throws(() => exporter.exportFromIfcScene({elements:[{...element,mesh:{vertices,faces:[[0,0,1]]}}]},{mode:'geom'}),
    {name:'ExportGeometryInputError', stage:'serialization', entityId:2106, message:/no nondegenerate triangles/});
const rebased="! IFC_COORDINATE_REBASE X_OFFSET=593000 Y_OFFSET=1198000 Z_OFFSET=10 /\n"+
    "&MESH IJK=2,2,2, XB=0,2,0,2,0,2 /\n&OBST ID='wall', XB=0,1,0,1,0,1 /\n"+
    "&GEOM ID='triangle', VERTS=0,0,0,1,0,0,0,1,0, FACES=1,2,3,1 /";
const parsed=new context.IfcFds.fds.FdsNamelistParser().parse(rebased);
const displayed=new context.IfcFds.fds.FdsGeometryAdapter().toSceneModel(parsed);
assert.equal(displayed.obsts[0].xb[0],593000);
assert.equal(displayed.geoms[0].vertices[0][1],1198000);
assert.equal(displayed.bounds.zmin,10);
assert.equal(parsed.obsts[0].xb[0],0,'Display alignment must not modify solver coordinates');
console.log('Legacy GEOM commas, precision, Windows filenames, provenance and zero-area faces passed.');
