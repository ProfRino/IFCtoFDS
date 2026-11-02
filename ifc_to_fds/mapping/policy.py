"""Versioned decisions; no implicit approval of generic/review objects."""

from ifc_to_fds.core.canonical import MappingStrategy, MappingStatus, ScopeDecision, GeometryStatus
from ifc_to_fds.geometry.mesh import is_axis_aligned_box, valid_solid
from ifc_to_fds.diagnostics import operation
from ifc_to_fds.mep.classifier import MEP_TYPES

MEP_PREFIXES = (
    "IFCDUCT",
    "IFCPIPE",
    "IFCFAN",
    "IFCVALVE",
    "IFCAIRTERMINAL",
    "IFCDAMPER",
    "IFCFLOW",
    "IFCPUMP",
)

NON_OBSTACLE_TYPES = {
    "IFCSPACE",
    "IFCANNOTATION",
    "IFCSITE",
    "IFCVIRTUALELEMENT",
    "IFCBUILDING",
    "IFCBUILDINGSTOREY",
    "IFCPROJECT",
    "IFCOPENINGELEMENT",
    "IFCDISTRIBUTIONPORT",
    "IFCGRID",
    "IFCGRIDAXIS",
    "IFCPOSITIONINGELEMENT",
    "IFCREFERENCINGELEMENT",
    "IFCELEMENTASSEMBLY",
}
REVIEW_TYPES = {"IFCFURNISHINGELEMENT", "IFCBUILDINGELEMENTPROXY", "IFCRAILING"}
PROMOTION_FACTORS = {
    "ifc_type",
    "mesh_scale",
    "domain_position",
    "airflow_clearance",
    "system",
    "future_operational_role",
    "golden_policy",
}


def validate_decisions(decisions):
    if not isinstance(decisions, dict):
        raise ValueError("decisions must map entity keys to explicit decisions")
    for key, decision in decisions.items():
        if not isinstance(decision, dict) or set(decision) - {
            "action",
            "policy_version",
            "rationale",
            "reviewer",
            "evidence",
            "factors",
            "hvac",
        }:
            raise ValueError(f"Invalid decision: {key}")
        if decision.get("action") not in (
            "EXCLUDE",
            "REFERENCE_GEOMETRY",
            "PASSIVE_OBSTACLE",
            "HVAC",
        ):
            raise ValueError(f"Invalid decision action: {key}")
        if not all(
            decision.get(k)
            for k in ("policy_version", "rationale", "reviewer", "evidence")
        ):
            raise ValueError(
                f"Decision requires policy version, rationale, reviewer and evidence: {key}"
            )
        if "hvac" in decision:
            if decision["action"] != "HVAC":
                raise ValueError("hvac parameters require action=HVAC")
            from ifc_to_fds.domain.mep.hvac import DuctSpec
            DuctSpec.model_validate(decision["hvac"])
        if decision["action"] == "PASSIVE_OBSTACLE" and (
            not isinstance(decision.get("factors"), dict)
            or set(decision["factors"]) != PROMOTION_FACTORS
            or not all(
                isinstance(v, str) and v.strip() for v in decision["factors"].values()
            )
        ):
            raise ValueError(
                f"Promotion requires all simulation relevance factors: {key}"
            )


def determine_element_strategy(
    element, force_all_geom=False, include_review_solids=False
):
    if element.scope_decision == ScopeDecision.OUT_OF_SCOPE:
        return MappingStrategy.EXCLUDED_SCOPE
    if element.ifc_type.upper() in NON_OBSTACLE_TYPES or element.role != "PHYSICAL":
        return MappingStrategy.SEMANTIC_ONLY
    if element.ifc_type.upper() == "IFCCOVERING" and (
        not element.mesh
        or not valid_solid(element.mesh)
        or (
            element.bounding_box
            and min(element.bounding_box.dx, element.bounding_box.dy, element.bounding_box.dz) < 0.02
        )
    ):
        return MappingStrategy.SEMANTIC_ONLY
    if element.review_status == "EXCLUDED_APPROVED":
        return MappingStrategy.EXCLUDED_APPROVED
    if element.simulation_role == "HVAC":
        return MappingStrategy.HVAC
    ifc_type_upper = (element.ifc_type or "").upper()
    type_class_upper = (getattr(element, "type_class", None) or "").upper()
    is_mep_type = (
        ifc_type_upper in MEP_TYPES
        or type_class_upper in MEP_TYPES
        or ifc_type_upper.startswith(MEP_PREFIXES)
        or type_class_upper.startswith(MEP_PREFIXES)
    )
    is_mep_obstacle = (
        (element.mapping_planned and element.simulation_role == "PASSIVE_OBSTACLE")
        or bool(element.decision and element.decision.get("action") == "PASSIVE_OBSTACLE")
    )
    if (
        element.simulation_role == "REFERENCE_GEOMETRY"
        or (is_mep_type and not is_mep_obstacle)
        or (
            element.boundary_treatment == "PENDING_VALIDATION"
            and element.representation_bounds is None
        )
    ):
        return MappingStrategy.NONE
    if not element.mesh or not valid_solid(element.mesh):
        return MappingStrategy.NONE
    if (
        not force_all_geom
        and element.boundary_policy != "SOURCE_SOLID_DOMAIN_INTERSECTION"
        and not element.openings
        and is_axis_aligned_box(element.mesh)
    ):
        return MappingStrategy.OBST
    return MappingStrategy.GEOM


@operation("MAPPING")
def plan_mapping(
    model,
    force_all_geom=False,
    include_review_solids=False,
    decisions=None,
    boundary_policy=None,
    geometry_fidelity=False,
    system_decisions=None,
):
    if include_review_solids:
        raise ValueError(
            "include_review=True is not supported without explicit reviewed decisions; "
            "provide decisions with action='PASSIVE_OBSTACLE' and required promotion factors"
        )
    decisions = decisions or {}
    validate_decisions(decisions)
    system_decisions = system_decisions or {}
    validate_decisions(system_decisions)
    unknown_systems = set(system_decisions) - {
        s.system_id for s in model.mep_graph.systems
    }
    if unknown_systems:
        raise ValueError(
            f"Decisions refer to unknown systems: {sorted(unknown_systems)}"
        )
    unknown = set(decisions) - {e.entity_key for e in model.elements}
    if unknown:
        raise ValueError(f"Decisions refer to unknown entities: {sorted(unknown)}")
    for e in model.elements:
        e.fds_primitive_ids = []
        e.decision = decisions.get(e.entity_key, {})
        inherited = [system_decisions[s] for s in e.system_ids if s in system_decisions]
        if inherited and not e.decision:
            if len({d["action"] for d in inherited}) > 1:
                raise ValueError(
                    f"Conflicting system decisions require an entity decision: {e.entity_key}"
                )
            e.decision = inherited[0]
        e.review_status = "NOT_REQUIRED"
        is_review = e.ifc_type.upper() in REVIEW_TYPES
        ifc_type_upper = (e.ifc_type or "").upper()
        type_class_upper = (e.type_class or "").upper()
        is_mep = bool(
            e.classification_evidence
            or e.system_ids
            or e.ports
            or ifc_type_upper in MEP_TYPES
            or type_class_upper in MEP_TYPES
            or ifc_type_upper.startswith(MEP_PREFIXES)
            or type_class_upper.startswith(MEP_PREFIXES)
        )
        is_thin_covering = (
            e.ifc_type.upper() == "IFCCOVERING"
            and (
                not e.mesh
                or not valid_solid(e.mesh)
                or (
                    e.bounding_box
                    and min(e.bounding_box.dx, e.bounding_box.dy, e.bounding_box.dz) < 0.02
                )
            )
        )
        if e.simulation_role != "HVAC":
            e.simulation_role = (
                "REFERENCE_GEOMETRY"
                if is_thin_covering
                or (is_review and not (is_mep and geometry_fidelity))
                or (is_mep and not geometry_fidelity)
                else "PASSIVE_OBSTACLE"
            )
        e.operational_status = (
            "CONFIGURED"
            if e.simulation_role == "HVAC"
            else "NOT_CONFIGURED"
            if is_mep or e.simulation_role == "REFERENCE_GEOMETRY"
            else "NOT_APPLICABLE"
        )
        if is_review:
            e.review_status = "REVIEW_REQUIRED"
        if e.decision:
            e.review_status = (
                "EXCLUDED_APPROVED" if e.decision["action"] == "EXCLUDE" else "APPROVED"
            )
            if e.decision["action"] != "EXCLUDE":
                e.simulation_role = e.decision["action"]
                e.operational_status = (
                    "CONFIGURED"
                    if e.simulation_role == "HVAC"
                    else "NOT_CONFIGURED"
                    if is_mep or e.simulation_role == "REFERENCE_GEOMETRY"
                    else "NOT_APPLICABLE"
                )
        e.boundary_treatment = "NOT_APPLICABLE"
        e.boundary_policy = None
        e.boundary_evidence = {}
        e.representation_bounds = None
        if (
            e.scope_decision
            in (ScopeDecision.IN_SCOPE, ScopeDecision.BOUNDARY_RETAINED)
            and e.role == "PHYSICAL"
            and e.simulation_role != "HVAC"
            and e.bounding_box
            and model.simulation_domain
        ):
            b, d = e.bounding_box.to_xb(), model.simulation_domain.to_xb()
            if any(
                b[i] < d[i] - 1e-8 if i % 2 == 0 else b[i] > d[i] + 1e-8
                for i in range(6)
            ):
                e.boundary_treatment = "PENDING_VALIDATION"
                from .boundary import POLICY, eligible_bounds

                if boundary_policy == POLICY:
                    bounds = eligible_bounds(e, model, force_all_geom)
                    if bounds:
                        e.boundary_policy = POLICY
                        e.representation_bounds = bounds
                from .boundary import EXACT_POLICY, exact_bounds

                if boundary_policy == EXACT_POLICY:
                    try:
                        bounds = exact_bounds(e, model)
                        if bounds:
                            e.boundary_policy = EXACT_POLICY
                            e.representation_bounds = bounds
                    except (ValueError, RuntimeError) as exc:
                        e.boundary_evidence = {"intersection_error": str(exc)}
        e.mapping_planned = True
        e.mapping_strategy = determine_element_strategy(
            e, force_all_geom, include_review_solids
        )
        e.fds_representation = (
            e.mapping_strategy.value
            if e.mapping_strategy in (MappingStrategy.OBST, MappingStrategy.GEOM, MappingStrategy.HVAC)
            else "NONE"
        )
        e.geometry_preservation = "NOT_RUN"
        e.mapping_status = MappingStatus.INCONCLUSIVE
        e.mapping_rationale = e.decision.get(
            "rationale",
            "Geometry fidelity: preserve source MEP solid as passive geometry; operational behavior NOT_CONFIGURED"
            if geometry_fidelity and is_mep
            else "Policy 0.4: independently audit geometry, role and scope",
        )
        if e.boundary_policy == "SOURCE_SOLID_DOMAIN_INTERSECTION":
            e.mapping_rationale += "; source solid intersected with explicit domain; solver-effective boundary verification pending"
        if e.mapping_strategy == MappingStrategy.EXCLUDED_SCOPE:
            e.mapping_status = MappingStatus.EXCLUDED_SCOPE
            e.mapping_rationale = e.scope_rationale
        elif e.mapping_strategy == MappingStrategy.EXCLUDED_APPROVED:
            e.mapping_status = MappingStatus.EXCLUDED_APPROVED
        elif e.mapping_strategy == MappingStrategy.SEMANTIC_ONLY:
            e.mapping_status = MappingStatus.SEMANTIC_ONLY
            if is_thin_covering:
                e.mapping_rationale = "Thin/decorative covering classified as semantic reference; excluded from solid obstacles"
        elif getattr(e, "geometry_status", None) == GeometryStatus.APPROXIMATED:
            e.geometry_preservation = "APPROXIMATED"
            if e.review_status == "APPROVED":
                e.mapping_status = MappingStatus.DEVIATED
                e.mapping_rationale += "; non-manifold leaf geometry approximated as bounding box solid barrier (decision approved)"
            else:
                e.mapping_status = MappingStatus.REVIEW_REQUIRED
                e.mapping_rationale += "; non-manifold leaf geometry approximated as bounding box solid barrier; explicit review REQUIRED"
        elif e.role == "PHYSICAL" and (not e.mesh or not valid_solid(e.mesh)):
            e.mapping_status = MappingStatus.UNSUPPORTED
            e.geometry_preservation = (
                "FAILED" if e.mesh and not valid_solid(e.mesh) else "INCONCLUSIVE"
            )
            details = list(e.validation_notes)
            details.extend(
                f"Opening STEP {o.opening_step_id}: {getattr(o, 'extraction_diagnostic', None) or 'missing or invalid opening solid'}"
                for o in e.openings
                if not o.mesh or not valid_solid(o.mesh)
            )
            suffix = "; ".join(details)
            e.mapping_rationale = (
                f"Source physical geometry is missing or invalid; no FDS representation authorized. {suffix}"
                if suffix
                else "Source physical geometry is missing or invalid; no FDS representation authorized."
            )
        elif e.review_status == "REVIEW_REQUIRED":
            e.mapping_status = MappingStatus.REVIEW_REQUIRED
            if geometry_fidelity and is_mep:
                e.mapping_rationale += "; generic MEP source shape included for fidelity; simulation relevance review REQUIRED"
        elif e.openings and any(
            not o.mesh or not valid_solid(o.mesh) for o in e.openings
        ):
            e.mapping_rationale += (
                "; valid IFC host solid retained, including kernel-applied voids; "
                "opening evidence incomplete, opening verification INCONCLUSIVE"
            )
    from ifc_to_fds.mep.network import build_hvac_network
    model.hvac_network = build_hvac_network(model)  # Validated independently of serialization.
    return model
