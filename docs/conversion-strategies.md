# Conversion Strategies

The right-hand panel exposes two in-browser conversion options. Both use the
original parsed IFC meshes, not the Three.js display objects. By default, they keep
`IfcSpace` room volumes, window and door fill solids, furnishings, MEP parts,
and other review-only objects out of FDS export. These objects remain available
in the IFC review layer, and the IFC Mapping panel reports what will be exported.

## Option 1: OBST + GEOM

Option 1 uses `OBST` for axis-aligned walls, slabs, rectangular columns, doors,
windows, simple furnishings, and simple building-element proxies. Hosts with
IFC openings are stair-stepped onto a shared axis-aligned voxel grid so the
apertures can be carved. Adjacent occupied cells are merged where the resulting
union is equivalent.

Curved facades, complex stairs, irregular terrain, vehicles, imported CAD
shapes, and objects that cannot reasonably become axis-aligned boxes remain
`GEOM` triangle meshes.

`FDS cell size` is a separate control. It determines the generated
`&MESH IJK=...` resolution used by the FDS simulation. `Voxel size` determines
the temporary grid used to convert IFC surfaces into stair-stepped `OBST`
cuboids before export. They default to `0.10 m` but can be changed independently.

Conversion updates the FDS viewer immediately without starting a download. Use
the toolbar save icon after reviewing the result when the converted `.fds` file
is ready to keep.

Use this when the FDS case benefits from traditional OBST geometry without
flattening every irregular object into an oversized bounding box. Host opening volumes carve voxel
cells before adjacent cells are merged, so rectangular and round windows remain
open. The opening margin control thickens each opening along its penetration
axis before carving, following the same practical safeguard exposed by PyroSim
for BIM window and door holes. Smaller voxels improve fidelity but increase
export time and OBST count.

Use the optional closed-fill checkbox only when a window or door should be
modeled as closed. Use the review-object checkbox when furnishings or MEP parts
really should block flow; it is deliberately off by default.

## Option 2: GEOM FDS

Every FDS-ready IFC element is exported as one `&GEOM VERTS=..., FACES=... /`.

Use this when geometric fidelity matters. It preserves tessellated IFC surfaces,
but can produce larger FDS files and needs stronger downstream validation.

## IFC Provenance

Generated `OBST` and `GEOM` items are preceded by structured `IFC_SOURCE`
comments. The comments retain source IFC type, GlobalId, STEP id, name, output
kind, and generated FDS item id. They remain valid FDS comments and are restored
into the browser inspector when the generated FDS is re-imported.

## Blender/BFDS Route

[BFDS](https://firetools.org/bfds/) is an external Blender add-on for creating
and managing NIST FDS models. Its current source is at
[firetools/bfds](https://github.com/firetools/bfds), and the older
[firetools/blenderfds](https://github.com/firetools/blenderfds) repository now
points users to BFDS.

Option 1 follows BFDS's documented
[`Voxels` XB transformation](https://github-wiki-see.page/m/firetools/blenderfds/wiki/Geometries):
many axis-aligned OBST boxes form a stair-stepped approximation of a source
mesh, controlled by a voxel-size setting. BFDS source also uses a shared
world-origin voxel grid by default and merges neighboring boxes. This workbench
uses the same two ideas in its browser exporter.

The semantic defaults follow BFDS's
[BIM workflow guide](https://github.com/firetools/bfds/wiki/Use-BIM-files):
clean up non-essential objects, map structural elements deliberately, and treat
window and door elements as openings unless a closed state is intended.

[PyroSim's BIM conversion documentation](https://www.thunderheadeng.com/docs/2026-1/pyrosim/geometry/creating-geometry-cad/)
also influenced the opening margin control: PyroSim provides a setting to
thicken window and door holes so they pass fully through their host walls.

It is not embedded in this static browser app. The practical workflow is:

1. Import IFC into Blender/Bonsai or another IFC-capable Blender workflow.
2. Clean, simplify, and classify geometry visually.
3. Use BFDS to author or adapt FDS entities.
4. Reopen the resulting `.fds` in this browser workbench for geometry checks.

This is best for manual cleanup and engineering judgement. The browser exporter
is better for fast repeatable conversion tests.
