"""Application service for preparing canonical models with spatial scope and mapping plan."""

from time import perf_counter
from typing import Any, Dict, List
from ifc_to_fds.core.federation import load_sources
from ifc_to_fds.domain.bim import BoundingBox, CanonicalModel
from ifc_to_fds.domain.scope import SpatialScope
from ifc_to_fds.mapping.policy import plan_mapping
from ifc_to_fds.mapping.scope import apply_spatial_scope
from ifc_to_fds.application.dto.configuration import validate_configuration


def prepare_model(
    paths: List[str], configuration: Dict[str, Any], reference: bool = False
) -> CanonicalModel:
    """Prepares canonical model with spatial scoping, simulation domain, and mapping plan."""
    configuration = validate_configuration(configuration)
    source_opts = dict(configuration.get("sources") or {})
    for k in ("rebase_vector", "rebase_origin", "auto_rebase_origin"):
        if k in configuration:
            source_opts[k] = configuration[k]
    model = load_sources(paths, source_opts, reference=reference)
    rebase_vec = getattr(model.source, "rebase_vector", None) or [0.0, 0.0, 0.0]
    has_rebase = any(abs(v) > 1e-6 for v in rebase_vec)
    dx, dy, dz = rebase_vec if has_rebase else (0.0, 0.0, 0.0)

    scope_start = perf_counter()
    scope_raw = dict(configuration.get("scope", {}) or {})
    coord_frame = scope_raw.get("coordinate_frame") or configuration.get("coordinate_frame")
    if coord_frame not in (None, "WORLD", "REBASED"):
        raise ValueError(f"Invalid coordinate_frame: {coord_frame!r}, must be 'WORLD' or 'REBASED'")

    if scope_raw.get("bounding_box") and has_rebase:
        if coord_frame is None:
            raise ValueError("scope.coordinate_frame is required for explicit bounds when the IFC model is rebased")
        raw_box = BoundingBox.model_validate(scope_raw["bounding_box"])
        if coord_frame == "WORLD":
            scope_raw["coordinate_frame"] = "REBASED"
            scope_raw["bounding_box"] = BoundingBox(
                xmin=raw_box.xmin - dx,
                xmax=raw_box.xmax - dx,
                ymin=raw_box.ymin - dy,
                ymax=raw_box.ymax - dy,
                zmin=raw_box.zmin - dz,
                zmax=raw_box.zmax - dz,
            ).model_dump()

    scope = SpatialScope.model_validate(scope_raw)
    if scope.storeys or scope.bounding_box:
        apply_spatial_scope(model, scope)
    else:
        model.requested_scope = scope.model_dump(mode="json")
    if configuration.get("simulation_domain"):
        domain_box = BoundingBox.model_validate(configuration["simulation_domain"])
        domain_frame = (
            configuration.get("simulation_domain_coordinate_frame")
            or coord_frame
        )
        if domain_frame not in (None, "WORLD", "REBASED"):
            raise ValueError(
                f"Invalid simulation_domain_coordinate_frame: {domain_frame!r}, must be 'WORLD' or 'REBASED'"
            )
        if has_rebase and domain_frame is None:
            raise ValueError("simulation_domain_coordinate_frame is required when the IFC model is rebased")
        if has_rebase and domain_frame == "WORLD":
            domain_box = BoundingBox(
                xmin=domain_box.xmin - dx,
                xmax=domain_box.xmax - dx,
                ymin=domain_box.ymin - dy,
                ymax=domain_box.ymax - dy,
                zmin=domain_box.zmin - dz,
                zmax=domain_box.zmax - dz,
            )
        model.simulation_domain = domain_box
        model.domain_origin = "EXPLICIT_CONFIGURATION"
    elif not scope.storeys and not scope.bounding_box:
        model.simulation_domain = model.model_bounds
        model.domain_origin = "FULL_MODEL"
    mapping_start = perf_counter()
    plan_mapping(
        model,
        configuration.get("all_geom", False),
        configuration.get("include_review", False),
        configuration.get("decisions", {}),
        configuration.get("boundary_policy"),
        geometry_fidelity=configuration.get("profile") == "geometry-fidelity",
        system_decisions=configuration.get("system_decisions", {}),
    )
    model.timings.update(
        scope_s=mapping_start - scope_start, mapping_s=perf_counter() - mapping_start
    )
    included = {
        e.entity_key
        for e in model.elements
        if e.scope_decision.value in ("IN_SCOPE", "BOUNDARY_RETAINED")
    }
    for edge in model.mep_graph.connections:
        edge.boundary_connection = (edge.source_element_id in included) != (
            edge.target_element_id in included
        )
    return model
