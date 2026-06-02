# IFC Conversion Test Results

Run from the project root:

```powershell
node scripts/test-ifc-conversion.js
```

The script imports each IFC example, exercises voxel FDS `OBST`, Option 1 mixed
`OBST + GEOM`, and Option 2 all-`GEOM`, parses the generated strings back into
the browser model, and checks that record counts and triangle counts are
consistent. Regression runs deliberately use `0.25 m` voxels and a different
`0.4 m` FDS cell size for speed and to confirm that computational mesh
resolution and voxel geometry resolution remain independent. Browser defaults
are `0.10 m`, `0.10 m`, and a `0.05 m` opening margin.

## Current Samples

| IFC file | Imported | FDS-ready | Voxel OBST export | Hybrid export | GEOM export |
| --- | ---: | ---: | ---: | ---: | ---: |
| `AC20-FZK-Haus.ifc` | 45 | 22 | 223 `OBST` | 124 `OBST`, 6 `GEOM` | 22 `GEOM`, 2972 triangles |
| `AC20-Institute-Var-2.ifc` | 769 | 151 | 1620 `OBST` | 1127 `OBST`, 50 `GEOM` | 151 `GEOM`, 5140 triangles |
| `IfcOpenShell-Duplex.ifc` | 148 | 77 | 163 `OBST` | 117 `OBST`, 16 `GEOM` | 77 `GEOM`, 1346 triangles |

Option 1 is intentionally conservative. It emits exact `OBST` boxes when a
box-friendly IFC mesh matches its axis-aligned bounds, voxel-carved `OBST`
cuboids for hosts with IFC openings, and `GEOM` otherwise.

The FZK Haus check also requires all four roof-clipped upper exterior walls to
exist and verifies that their reconstructed meshes have no open edges. It also
checks that the upper slab remains closed, covers the ordinary floor area, and
does not cover the spiral stair shaft. The voxel regression also checks that the
sloped roof becomes multiple stair-stepped `OBST` cuboids, that voxelized slab
cuboids leave the stair shaft open, and that rectangular and round window
apertures remain open without solid window-fill `OBST` records. Optional
closed-fill export is checked separately. Furnishings stay review-only by
default, and a synthetic open GEOM mesh must produce a manifold diagnostic.
All generated solids must preserve their IFC source metadata after re-import.
Closed windows must round-trip as glass blue and closed doors as brown.
