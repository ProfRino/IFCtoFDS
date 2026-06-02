# IFC to FDS Workbench Architecture

This project starts as a static browser app that can be opened from `file://`.
It uses classic script tags and a shared `window.IfcFds` namespace so each module
stays separate without requiring a local server or bundler.

## Current modules

- `js/fds/namelist-parser.js` parses FDS namelist records and structured
  `IFC_SOURCE` comments.
- `js/fds/fds-geometry-adapter.js` turns parsed FDS records into a viewer-ready
  geometry model, resolving surface colors and IFC provenance.
- `js/viewer/scene-viewer.js` renders FDS geometry with Three.js.
- `js/compare/checks.js` runs lightweight bounds, OBST, and BFDS-inspired GEOM
  manifold checks.
- `js/ifc/ifc-adapter.js` reads a first native IFC STEP geometry subset,
  applies supported direct opening voids, retains host opening meshes for voxel
  carving, and assigns semantic FDS roles.
- `js/fds/fds-exporter.js` exports original IFC meshes to mixed `OBST + GEOM`
  or all-`GEOM` FDS. It reports type-to-role mapping, emits colored door and
  window surfaces, and writes source metadata beside generated items.

## Relationship to ProfRino/fds-viewer

`ProfRino/fds-viewer` is the mature FDS visualization reference. This workbench
keeps a smaller first layer so IFC parsing and conversion can be developed
independently, then selected FDS viewer code can be reused or extracted once the
interface between modules is stable.

## Next milestones

1. Add general CSG subtraction for wall openings in the `GEOM` path.
2. Add Web-IFC as an optional full-geometry backend.
3. Add finer IFC element filtering by type and GlobalId.
4. Add conversion settings for coordinate recentering and per-element voxel
   size overrides.
5. Add overlay comparison checks for bounds, unit scale, origin shift, and skipped elements.

## Building Sample Status

The main `examples/` folder contains three complete building IFC models:

1. `AC20-FZK-Haus.ifc`
2. `AC20-Institute-Var-2.ifc`
3. `IfcOpenShell-Duplex.ifc`

The native importer currently exports 22, 151, and 77 FDS-ready solid elements
from those models respectively. Window and door fill meshes, furnishings, and
other review objects remain visible in the IFC layer but do not become FDS
obstructions unless their optional export controls are enabled.
