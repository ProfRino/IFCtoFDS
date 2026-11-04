"""FDS Serializer and Syntax Emitter.

Converts Canonical BIM Model elements into standard FDS 6+ input namelists
(&HEAD, &TIME, &MESH, &SURF, &OBST, &HOLE, &GEOM) with full IFC source provenance.
"""

from typing import List, Optional, Tuple
from pathlib import Path
import math
import re
from dataclasses import dataclass
from ifc_to_fds.diagnostics import operation

from ifc_to_fds.core.canonical import (
    BoundingBox,
    CanonicalElement,
    CanonicalModel,
    MappingStrategy,
)
from ifc_to_fds.domain.mapping import MappingPlan
from .manifest import MappingManifest, build_manifest
from ifc_to_fds.geometry.mesh import (
    bounds_for_vertices,
    valid_solid,
    is_axis_aligned_box,
)
from ifc_to_fds.core.canonical import ScopeDecision
import json


@dataclass(frozen=True)
class SerializationResult:
    """Output of rendering; primitive assignments are not mapping intent."""

    fds_text: str
    manifest: MappingManifest
    primitive_assignments: dict[str, list[str]]
    exported_bounds: Optional[BoundingBox]
    domain: Optional[BoundingBox]


def clean_fds_id(name: str, fallback: str = "ID") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name or "")
    cleaned = cleaned.strip("._-")
    if not cleaned:
        cleaned = fallback
    return cleaned[:30]


def format_xb(xb: List[float]) -> str:
    # Shortest binary64 round trip; keep integral bounds readable for legacy callers.
    return ",".join(
        str(int(v)) if float(v).is_integer() else repr(float(v)) for v in xb
    )


def format_source_comment(elem: CanonicalElement) -> str:
    return "! IFC_SOURCE " + json.dumps(
        dict(
            entity_key=elem.entity_key,
            source_id=elem.source_id,
            global_id=elem.global_id,
            step_id=elem.step_id,
            ifc_type=elem.ifc_type,
        ),
        ensure_ascii=True,
    )


def surface_for_element(elem: CanonicalElement) -> str:
    ifc_type = (elem.ifc_type or "").upper()
    type_class = (getattr(elem, "type_class", None) or "").upper()
    name = (elem.name or "").upper()
    from ifc_to_fds.mep.classifier import MEP_TYPES
    from ifc_to_fds.mapping.policy import MEP_PREFIXES

    if ifc_type in ("IFCWINDOW", "IFCDOOR") or "GLASS" in ifc_type:
        return "GLASS"
    if (
        ifc_type in MEP_TYPES
        or type_class in MEP_TYPES
        or ifc_type.startswith(MEP_PREFIXES)
        or type_class.startswith(MEP_PREFIXES)
        or "STEEL" in name
        or "METAL" in name
    ):
        return "STEEL"
    return "CONCRETE"



def compute_mesh_grid(
    bounds: BoundingBox, cell_size: float = 0.2, max_total_cells: int = 50_000_000
) -> Tuple[List[int], List[float]]:
    if not math.isfinite(cell_size) or cell_size <= 0:
        raise ValueError("cell_size must be finite and positive")
    xb = bounds.to_xb()
    ijk = [
        max(1, math.ceil((xb[1] - xb[0]) / cell_size)),
        max(1, math.ceil((xb[3] - xb[2]) / cell_size)),
        max(1, math.ceil((xb[5] - xb[4]) / cell_size)),
    ]
    total_cells = ijk[0] * ijk[1] * ijk[2]
    if total_cells > max_total_cells:
        raise ValueError(
            f"Total mesh cells ({total_cells:,}) exceeds maximum safety limit of {max_total_cells:,}. "
            f"Increase cell_size (current: {cell_size}m) or restrict simulation domain."
        )
    return ijk, xb


def partition_simulation_domain(
    bounds: BoundingBox,
    cell_size: float = 0.2,
    max_cells_per_mesh: int = 500_000,
) -> List[Tuple[List[int], List[float]]]:
    """Partitions simulation domain into one or more meshes conforming to FDS MPI limits.
    Each submesh has at most max_cells_per_mesh cells.
    Submesh boundaries align strictly with cell_size multiples.
    """
    ijk, xb = compute_mesh_grid(bounds, cell_size=cell_size)
    total_cells = ijk[0] * ijk[1] * ijk[2]

    if total_cells <= max_cells_per_mesh:
        return [(ijk, xb)]

    # Partition along X and Y first to preserve vertical stratification;
    # if vertical cell count ijk[2] exceeds max_cells_per_mesh, partition Z as well.
    nx_parts = 1
    ny_parts = 1
    nz_parts = 1
    while (
        math.ceil(ijk[0] / nx_parts)
        * math.ceil(ijk[1] / ny_parts)
        * math.ceil(ijk[2] / nz_parts)
    ) > max_cells_per_mesh:
        cx = math.ceil(ijk[0] / nx_parts)
        cy = math.ceil(ijk[1] / ny_parts)
        cz = math.ceil(ijk[2] / nz_parts)
        if cx >= cy and cx > 1 and nx_parts < ijk[0]:
            nx_parts += 1
        elif cy > 1 and ny_parts < ijk[1]:
            ny_parts += 1
        elif cz > 1 and nz_parts < ijk[2]:
            nz_parts += 1
        else:
            break

    meshes = []
    total_x_cells = ijk[0]
    total_y_cells = ijk[1]
    total_z_cells = ijk[2]

    base_x_cells = total_x_cells // nx_parts
    rem_x_cells = total_x_cells % nx_parts

    base_y_cells = total_y_cells // ny_parts
    rem_y_cells = total_y_cells % ny_parts

    base_z_cells = total_z_cells // nz_parts
    rem_z_cells = total_z_cells % nz_parts

    dx = (xb[1] - xb[0]) / total_x_cells
    dy = (xb[3] - xb[2]) / total_y_cells
    dz = (xb[5] - xb[4]) / total_z_cells

    curr_x_cell = 0
    for px in range(nx_parts):
        count_x = base_x_cells + (1 if px < rem_x_cells else 0)
        sub_xmin = round(xb[0] + curr_x_cell * dx, 6)
        sub_xmax = round(xb[0] + (curr_x_cell + count_x) * dx, 6) if px < nx_parts - 1 else round(xb[1], 6)
        curr_x_cell += count_x

        curr_y_cell = 0
        for py in range(ny_parts):
            count_y = base_y_cells + (1 if py < rem_y_cells else 0)
            sub_ymin = round(xb[2] + curr_y_cell * dy, 6)
            sub_ymax = round(xb[2] + (curr_y_cell + count_y) * dy, 6) if py < ny_parts - 1 else round(xb[3], 6)
            curr_y_cell += count_y

            curr_z_cell = 0
            for pz in range(nz_parts):
                count_z = base_z_cells + (1 if pz < rem_z_cells else 0)
                sub_zmin = round(xb[4] + curr_z_cell * dz, 6)
                sub_zmax = round(xb[4] + (curr_z_cell + count_z) * dz, 6) if pz < nz_parts - 1 else round(xb[5], 6)
                curr_z_cell += count_z

                sub_ijk = [count_x, count_y, count_z]
                sub_xb = [sub_xmin, sub_xmax, sub_ymin, sub_ymax, sub_zmin, sub_zmax]
                meshes.append((sub_ijk, sub_xb))

    return meshes


def serialize_fds(
    model: CanonicalModel,
    cell_size: Optional[float] = None,
    mapping_plan: Optional[MappingPlan] = None,
) -> Tuple[str, MappingManifest]:
    """Legacy tuple API; mirrors only primitive IDs and exported bounds as outputs."""
    result = serialize_mapping(model, cell_size, mapping_plan)
    for element in model.elements:
        element.fds_primitive_ids = list(
            result.primitive_assignments[element.entity_key]
        )
    model.exported_bounds = result.exported_bounds
    return result.fds_text, result.manifest


@operation("SERIALIZATION")
def serialize_mapping(model, cell_size=None, mapping_plan=None) -> SerializationResult:
    """Render a validated plan without modifying the source model or plan."""
    from ifc_to_fds.domain.mapping import build_mapping_plan
    from .plan_validation import planned_model
    from ifc_to_fds.mep.network import build_hvac_network

    if cell_size is not None and (not math.isfinite(cell_size) or cell_size <= 0):
        raise ValueError("cell_size must be finite and positive")
    if mapping_plan is None:
        mapping_plan = build_mapping_plan(
            model, cell_size=0.2 if cell_size is None else cell_size,
            hvac_network=build_hvac_network(model)
        )
    elif cell_size is not None and cell_size != mapping_plan.cell_size:
        raise ValueError("cell_size conflicts with MappingPlan")
    view = planned_model(model, mapping_plan)
    text, manifest = _serialize_planned_model(view, mapping_plan.cell_size, mapping_plan.hvac_network)
    return SerializationResult(
        text,
        manifest.model_copy(deep=True),
        {e.entity_key: list(e.fds_primitive_ids) for e in view.elements},
        view.exported_bounds.model_copy(deep=True) if view.exported_bounds else None,
        view.simulation_domain.model_copy(deep=True)
        if view.simulation_domain
        else None,
    )


def _serialize_planned_model(model, cell_size, hvac_network):
    """Serializes CanonicalModel into valid FDS text and generates MappingManifest."""
    if not all(e.mapping_planned for e in model.elements):
        raise ValueError("Call plan_mapping before serialization")
    lines: List[str] = []

    chid = clean_fds_id(Path(model.source.filename).stem, "IFC_MODEL")
    lines.append(
        f"&HEAD CHID='{chid}', TITLE='IFCtoFDS conversion; see acceptance report' /"
    )
    lines.append("&TIME T_END=0.0 /")
    vec = getattr(model.source, "rebase_vector", [0.0, 0.0, 0.0])
    if vec and any(abs(x) > 1e-6 for x in vec):
        lines.append(
            f"! IFC_COORDINATE_REBASE X_OFFSET={vec[0]} Y_OFFSET={vec[1]} Z_OFFSET={vec[2]} /"
        )

    # MESH calculation
    active = [
        e
        for e in model.elements
        if e.scope_decision in (ScopeDecision.IN_SCOPE, ScopeDecision.BOUNDARY_RETAINED)
        and e.mapping_strategy in (MappingStrategy.GEOM, MappingStrategy.OBST)
        and e.mesh
        and valid_solid(e.mesh)
    ]
    representation_bounds = [e.representation_bounds or e.bounding_box for e in active]
    bounds = bounds_for_vertices(
        [
            v
            for b in representation_bounds
            if b
            for v in (
                [b.xmin, b.ymin, b.zmin],
                [b.xmax, b.ymax, b.zmax],
            )
        ]
    )
    model.exported_bounds = bounds
    if model.simulation_domain:
        multi_mesh_limit = 500_000
        meshes = partition_simulation_domain(
            model.simulation_domain,
            cell_size=cell_size,
            max_cells_per_mesh=multi_mesh_limit,
        )
        for idx, (ijk, mesh_xb) in enumerate(meshes, start=1):
            mesh_id = f"M{idx}" if len(meshes) > 1 else None
            id_clause = f" ID='{mesh_id}'," if mesh_id else ""
            lines.append(f"&MESH{id_clause} IJK={ijk[0]},{ijk[1]},{ijk[2]}, XB={format_xb(mesh_xb)} /")
    else:
        lines.append("! INCOMPLETE: simulation domain has not been declared")
    lines.append("")

    # Default Surfaces
    lines.append("&SURF ID='CONCRETE', COLOR='GRAY', DEFAULT=.TRUE. /")
    lines.append("&SURF ID='GLASS', COLOR='SKY BLUE', TRANSPARENCY=0.5 /")
    lines.append("&SURF ID='STEEL', COLOR='DIM GRAY' /")
    lines.append("&SURF ID='WOOD', COLOR='SANDY BROWN' /")
    lines.append("")

    prim_counter = 0

    for elem in model.elements:
        elem.fds_primitive_ids.clear()
        strategy = elem.mapping_strategy
        if elem.scope_decision in (
            ScopeDecision.OUT_OF_SCOPE,
            ScopeDecision.UNRESOLVED,
        ):
            continue
        if strategy in (MappingStrategy.NONE, MappingStrategy.EXCLUDED_SCOPE):
            continue
        if strategy == MappingStrategy.HVAC:
            # The network adapter emits these elements as operational records.
            continue
        if strategy in (MappingStrategy.GEOM, MappingStrategy.OBST) and (
            not elem.mesh or not valid_solid(elem.mesh)
        ):
            raise ValueError(f"Invalid emitting geometry: {elem.entity_key}")
        if strategy in (MappingStrategy.VOXEL, MappingStrategy.OBST_HOLE):
            raise ValueError(f"Unverified mapping strategy: {strategy.value}")
        if strategy == MappingStrategy.OBST and not is_axis_aligned_box(elem.mesh):
            raise ValueError(f"OBST lacks geometric equivalence: {elem.entity_key}")
        if (
            strategy == MappingStrategy.EXCLUDED_APPROVED
            or strategy == MappingStrategy.SEMANTIC_ONLY
        ):
            continue

        if strategy == MappingStrategy.OBST and elem.bounding_box:
            prim_counter += 1
            prim_id = f"OBST_{prim_counter}_{clean_fds_id(elem.name, 'obs')}"
            elem.fds_primitive_ids.append(prim_id)

            lines.append(format_source_comment(elem))
            lines.append(
                f"&OBST ID='{prim_id}', XB={format_xb((elem.representation_bounds or elem.bounding_box).to_xb())}, SURF_ID='{surface_for_element(elem)}' /"
            )

        elif (
            strategy == MappingStrategy.GEOM
            and elem.mesh
            and elem.mesh.vertices
            and elem.mesh.faces
        ):
            prim_counter += 1
            prim_id = f"GEOM_{prim_counter}_{clean_fds_id(elem.name, 'geom')}"
            elem.fds_primitive_ids.append(prim_id)

            from .boundary import target_mesh

            output_mesh = target_mesh(elem)
            verts_str = ",\n      ".join(
                ",".join(format(x, ".17g") for x in v) for v in output_mesh.vertices
            )
            faces_str = ",\n      ".join(
                f"{f[0] + 1},{f[1] + 1},{f[2] + 1},1" for f in output_mesh.faces
            )

            lines.append(format_source_comment(elem))
            lines.append(f"&GEOM ID='{prim_id}', SURF_ID='{surface_for_element(elem)}',")
            lines.append(f"      VERTS={verts_str},")
            lines.append(f"      FACES={faces_str} /")

    from ifc_to_fds.mep.fds_records import render_network
    lines.extend(render_network(hvac_network, model.elements))
    assignments = hvac_network.assignments()
    for elem in model.elements:
        if elem.entity_key in assignments:
            elem.fds_primitive_ids.extend(assignments[elem.entity_key])

    lines.append("")
    lines.append("&TAIL /")
    lines.append("")

    text = "\n".join(lines)
    manifest = build_manifest(model, text)
    return text, manifest
