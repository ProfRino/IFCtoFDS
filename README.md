# IFCtoFDS

[![Latest release](https://img.shields.io/github/v/release/ProfRino/IFCtoFDS?label=latest&color=blue)](https://github.com/ProfRino/IFCtoFDS/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/ProfRino/IFCtoFDS/total?label=downloads&color=brightgreen)](https://github.com/ProfRino/IFCtoFDS/releases)
[![License: AGPL-3.0](https://img.shields.io/github/license/ProfRino/IFCtoFDS?label=License&color=yellow)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/ProfRino/IFCtoFDS?style=flat&color=lightgrey)](https://github.com/ProfRino/IFCtoFDS/stargazers)

IFCtoFDS turns an **IFC** building model — the format every modern BIM tool
exports — into a ready-to-run **Fire Dynamics Simulator (FDS)** input file,
so fire-safety engineers can move from architectural geometry to a simulation
mesh without rebuilding the model by hand.

The whole workbench runs **entirely in your web browser**. There is no
installation, no backend, no Python environment, and no build step.

![Demo](demo/demo.gif)

> **Project Lead:** Prof Rino Lovreglio, PhD — Massey University
>
> **Disclaimer:** No responsibility is taken for the use or output of this tool.
> All results must be independently verified by a qualified fire safety engineer
> before use in any design or regulatory context.

---

## Features

Pure client-side — no installation, no build step, no backend. The entire
workbench runs from a single `index.html` and a folder of static `.js` modules.

* **Native IFC parser.** Handles `IfcExtrudedAreaSolid`, `IfcFacetedBrep`,
  `IfcTriangulatedFaceSet`, `IfcFaceBasedSurfaceModel`, planar
  `IfcBooleanClippingResult` cuts, and `IfcRelVoidsElement` openings. Non-convex
  outlines (L / U / T floor plates) are re-triangulated with earcut.
* **Two opening strategies.** **HOLE** emits one continuous `&OBST` per
  axis-aligned wall/slab plus rectangular `&HOLE` cutouts — cleaner FDS file,
  exact opening rectangles. **Voxelization** stair-steps small `&OBST`s around
  each opening; use it for arched or curved openings that `&HOLE` cannot
  represent.
* **Optional closed window/door fills** in window-blue and door-brown
  `SURF`s. With the HOLE strategy, closures are deferred to the end of the
  namelist so wall `&HOLE`s cannot carve the glass.
* **Auto-extruded flat slabs.** Floors whose IFC representation the parser
  couldn't extrude (some Revit-exported slabs and tapered insulation roofs) are
  auto-inflated to a default thickness so their L / U outline is preserved
  rather than collapsing to a zero-volume polygon.
* **Three view modes** (Overlay / FDS / IFC) with independent opacity sliders,
  per-layer toggles (OBST / HOLE / VENT / GEOM / IFC structure / fills / other),
  and a six-slider clip box that hides FDS primitives outside the kept volume.
* **First-person walk mode.** Click any floor or stair surface to place
  yourself, then WASD + mouselook to walk through the building. Door closures
  and `&HOLE` volumes are passable so you can step through doorways.
* **Keyboard navigation.** Number keys `1`–`6` and `0` snap to canonical views.
  Arrow keys orbit; Shift+arrows dolly or strafe.
* **Background conversion** runs in a Web Worker so the interface stays
  responsive while a 5 000-product IFC is being processed. A live progress
  banner shows the current element.
* **Saved provenance.** Every emitted `&OBST` / `&GEOM` / `&HOLE` carries an
  `! IFC_SOURCE` comment with IFC type, GlobalId, STEP id, and source name so
  the link to the source model survives a save-and-reload round trip.

## Download / Try it live

> **👉 [Run it now in your browser — profrino.github.io/IFCtoFDS](https://profrino.github.io/IFCtoFDS/)**
>
> No installation, no local server, no account. Just click *Open IFC* and load
> an `.ifc` model. The hosted page and a local clone are byte-identical — both
> are fully offline-capable once the page has loaded.

For a versioned snapshot, download the latest release ZIP / tarball from the
[Releases page](https://github.com/ProfRino/IFCtoFDS/releases/latest), unzip
it, and double-click `index.html`.

## Quick Start

### A. Hosted version (recommended)

Open **https://profrino.github.io/IFCtoFDS/** in any modern browser. Click
*Open IFC*, pick an `.ifc` file (or drag-drop one onto the page), choose an
**Opening approach** in the right-hand panel, then click **Convert to FDS**.
Use the save icon to download the generated `.fds`.

### B. Open directly from a clone

Download or clone the repo, then double-click `index.html`. The workbench runs
straight from `file://` — no local server needed. Use the *Open IFC* button to
load a model.

### C. Local web server

Serving the folder over loopback enables the parallel worker path and is the
recommended way to run on big IFCs:

```powershell
python -m http.server 8765
```

Then open `http://127.0.0.1:8765/index.html`.

### D. Convert from the command line

The conversion pipeline also runs under Node — handy for batch jobs or CI:

```powershell
node scripts/test-ifc-conversion.js
```

## Bundled examples

The `examples/` folder ships with three open BIM models so the workbench can be
exercised end-to-end without any external download. See
[`examples/SOURCES.md`](examples/SOURCES.md) for original URLs and attribution.

| File | Source | License |
|---|---|---|
| [`AC20-FZK-Haus.ifc`](examples/AC20-FZK-Haus.ifc) | Karlsruhe Institute of Technology (KIT), distributed by [STEP Tools](https://steptools.com/docs/stpfiles/ifc/) | Freely available IFC test model |
| [`AC20-Institute-Var-2.ifc`](examples/AC20-Institute-Var-2.ifc) | Karlsruhe Institute of Technology (KIT), distributed by [STEP Tools](https://steptools.com/docs/stpfiles/ifc/) | Freely available IFC test model |
| [`IfcOpenShell-Duplex.ifc`](examples/IfcOpenShell-Duplex.ifc) | [IfcOpenShell voxelization toolkit](https://github.com/IfcOpenShell/voxelization_toolkit) | LGPL-3.0 |

## Repository layout

```text
index.html              Entry page, wires the workbench together
guide.html              Single-column docs page (linked from the ? icon)
css/                    app.css + guide.css
js/
  core/                 namespace + diagnostics
  ifc/                  IFC parser + meta builder + display loader
  fds/                  Namelist parser, geometry adapter, FDS exporter
  workers/              Background conversion worker + inline bundle
  viewer/               Three.js scene viewer
  vendor/               earcut.min.js
  compare/              Conversion sanity checks
  app-controller.js     UI wiring, conversion orchestration
examples/               Three open IFC test models
scripts/                Node test harness + bundle generators
demo/                   Demo video + sibling reference viewer
```

## Dependencies

CDN-loaded at runtime, no build pipeline:

* **[three.js](https://threejs.org/)** r128 — WebGL renderer, `OrbitControls`,
  `PointerLockControls`
* **[Mapbox earcut](https://github.com/mapbox/earcut)** — non-convex polygon
  triangulation (vendored at `js/vendor/earcut.min.js`, ISC licence at
  `js/vendor/EARCUT-LICENSE.txt`)
* **[Lucide](https://lucide.dev/)** icons

## License

**GNU Affero General Public License v3.0** — see [`LICENSE`](LICENSE).

In plain terms: you can use, study, and modify this software freely. **If you
integrate it into another product or run it as a network-accessible service,
you must release your entire derivative or service codebase under the same
AGPL-3.0 licence.** This is a deliberate choice to keep the tool open for the
research community while preventing closed commercial integration. Commercial
use is not forbidden, but it can only happen under AGPL terms.

## Citation

If you reference this work, please cite:

> Lovreglio, R. *IFCtoFDS*. Massey University.
> https://github.com/ProfRino/IFCtoFDS
