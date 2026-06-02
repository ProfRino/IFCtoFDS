# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-06-02

Initial public release.

### Conversion

- Native IFC parser handling `IfcExtrudedAreaSolid`, `IfcFacetedBrep`,
  `IfcTriangulatedFaceSet`, `IfcFaceBasedSurfaceModel`, planar
  `IfcBooleanClippingResult` cuts, and `IfcRelVoidsElement` openings — no
  server or WASM required.
- Two opening strategies selectable from the UI:
  - **HOLE (recommended)** — one continuous `&OBST` per axis-aligned wall/slab
    plus rectangular `&HOLE` cutouts.
  - **Voxelization (legacy)** — stair-stepped `&OBST` cluster around each
    opening, for arched / curved geometry that `&HOLE` cannot represent.
- Optional closed window/door fills emitted as colored airtight `&OBST`s
  (window blue / door brown). With HOLE, closures are deferred to the end of
  the namelist so wall `&HOLE`s cannot carve the glass.
- Non-convex BREP outlines (L, U, T floor plates) re-triangulated with
  Mapbox earcut, replacing a fan triangulation that used to collapse them to
  their bounding rectangle.
- Flat slabs whose IFC representation the parser couldn't extrude are
  auto-inflated to a default thickness so their outline is preserved through
  voxelization.
- Bbox-based opening carve eliminates the 1-cell "phantom gap" that the
  ray-casting point-in-mesh test left at axis-aligned opening corners.

### Viewer

- Three.js scene with three view modes (Overlay / FDS / IFC), independent
  opacity sliders, and per-layer toggles for OBST, HOLE, VENT, GEOM, and
  IFC categories.
- HOLE markers render as ghost-cyan boxes so the closure colour behind them
  shows through. Window/door closure OBSTs render 12 mm proud of the wall
  plane to avoid z-fight flicker.
- GEOMs render distinctly darker than OBSTs so the two output kinds are easy
  to tell apart.
- Six clip-bar sliders at the bottom of the viewer cut the scene to a
  sub-volume. FDS primitives whose full bbox sits inside the clip stay
  visible; the rest disappear cleanly (no slicing through).
- First-person walk mode (footprint icon) with click-to-place. The click
  raycasts down to find the actual floor under the cursor, not the first
  surface the ray crosses. Door closures and HOLE volumes are passable so
  you can step through doorways.
- Distance-first click pick — clicking a visible front wall lands on that
  wall instead of a HOLE behind it. HOLE/VENT priority still wins as a
  tie-breaker within 0.3 m.
- Marquee multi-selection with **Shift + drag**.
- Conversion reveal animation with linear sweep that scales duration with
  building height (caps at 6 s).
- Keyboard navigation: `1`–`6` / `0` snap to canonical views; arrow keys
  orbit; `Shift` + arrows dolly or strafe; `Ctrl + Z` undo.

### App

- Background Web Worker conversion with per-element progress on the top
  banner so the UI stays responsive on large IFCs.
- Inline worker bundle for `file://` (direct double-click) origin.
- Delete-selected / undo / per-primitive OBST removal.
- Top-banner loading indicator during both IFC parse and FDS export.
- Single-column `guide.html` page linked from the help icon in the toolbar.

### Tooling

- `node scripts/test-ifc-conversion.js` exercises the bundled IFCs through
  the full export pipeline and regenerates the inline worker bundles.

### Bundled examples

- `examples/AC20-FZK-Haus.ifc` (KIT, via STEP Tools)
- `examples/AC20-Institute-Var-2.ifc` (KIT, via STEP Tools)
- `examples/IfcOpenShell-Duplex.ifc` (IfcOpenShell voxelization toolkit)

[0.1.0]: https://github.com/ProfRino/IFCtoFDS/releases/tag/v0.1.0
