"""Validate serialization intent against source authorization and geometry."""

from ifc_to_fds.domain.mapping import MappingPlan, MappingStrategy
from ifc_to_fds.domain.scope import ScopeDecision
from ifc_to_fds.geometry.mesh import (
    bounds_for_vertices,
    is_axis_aligned_box,
    valid_solid,
)
from .boundary import POLICY, EXACT_POLICY, eligible_bounds, exact_bounds
from .policy import NON_OBSTACLE_TYPES, validate_decisions


def planned_model(model, plan):
    # Validate even if a caller mutated a Pydantic instance after construction.
    plan = MappingPlan.model_validate(plan.model_dump())
    if not all(e.mapping_planned for e in model.elements):
        raise ValueError("Call plan_mapping before serialization")
    from ifc_to_fds.mep.network import build_hvac_network
    expected_network = build_hvac_network(model)
    if plan.hvac_network != expected_network:
        raise ValueError("MappingPlan HVAC network differs from reviewed source topology/parameters")
    known = {e.entity_key: e for e in model.elements}
    keys = [d.entity_key for d in plan.decisions]
    if (
        len(known) != len(model.elements)
        or len(keys) != len(set(keys))
        or set(keys) != set(known)
    ):
        raise ValueError(
            "MappingPlan must contain exactly one decision per source entity"
        )
    view = model.model_copy(
        update={
            "simulation_domain": plan.simulation_domain,
            "domain_origin": plan.domain_origin,
        }
    )
    elements = []
    for d in plan.decisions:
        e = known[d.entity_key]

        def reject(reason):
            raise ValueError(f"Invalid MappingPlan for {d.entity_key}: {reason}")

        if d.scope_decision != e.scope_decision:
            reject("source scope decision cannot be changed by serializer")
        if (
            d.simulation_role != e.simulation_role
            or d.decision != e.decision
            or d.review_status != e.review_status
        ):
            reject("role/review authorization differs from source policy")
        if d.decision:
            validate_decisions({d.entity_key: d.decision})
        if d.strategy in (MappingStrategy.VOXEL, MappingStrategy.OBST_HOLE):
            reject("unverified representation strategy")
        emits = d.strategy in (MappingStrategy.OBST, MappingStrategy.GEOM)
        source_requires_representation = e.mapping_strategy in (
            MappingStrategy.OBST,
            MappingStrategy.GEOM,
        )
        if source_requires_representation and not emits:
            reject(
                "required source representation cannot be suppressed; authorize disposition through source policy first"
            )
        if not emits and d.strategy != e.mapping_strategy:
            reject("non-emitting disposition differs from source policy")
        if d.strategy != e.mapping_strategy:
            reject(
                "strategy differs from source policy; build a new plan through policy"
            )
        if d.fds_representation != (d.strategy.value if emits or d.strategy == MappingStrategy.HVAC else "NONE"):
            reject("strategy and FDS representation conflict")
        if (
            d.strategy == MappingStrategy.EXCLUDED_APPROVED
            and e.review_status != "EXCLUDED_APPROVED"
        ):
            reject("exclusion lacks approval")
        if emits and (
            e.scope_decision
            not in (ScopeDecision.IN_SCOPE, ScopeDecision.BOUNDARY_RETAINED)
            or e.simulation_role != "PASSIVE_OBSTACLE"
            or e.role != "PHYSICAL"
            or e.ifc_type.upper() in NON_OBSTACLE_TYPES
            or e.review_status == "EXCLUDED_APPROVED"
        ):
            reject("entity has no obstacle authorization")
        if (
            d.boundary_policy != e.boundary_policy
            or d.boundary_treatment != e.boundary_treatment
            or d.boundary_evidence != e.boundary_evidence
        ):
            reject("boundary evidence differs from established policy")
        solid = bool(e.mesh and valid_solid(e.mesh))
        if emits and not solid:
            reject("emitting strategy requires valid source solid geometry")
        if emits and solid:
            source_bounds = bounds_for_vertices(e.mesh.vertices)
            if e.bounding_box is None or any(
                abs(a - b) > 1e-8
                for a, b in zip(e.bounding_box.to_xb(), source_bounds.to_xb())
            ):
                reject("source bounds do not match source mesh")
            if d.strategy == MappingStrategy.OBST and (
                e.openings or not is_axis_aligned_box(e.mesh)
            ):
                reject("OBST requires an opening-free axis-aligned source solid")
            expected = source_bounds
            domain = plan.simulation_domain
            crosses = domain and any(
                v < domain.to_xb()[i] - 1e-8
                if i % 2 == 0
                else v > domain.to_xb()[i] + 1e-8
                for i, v in enumerate(source_bounds.to_xb())
            )
            if crosses:
                if d.boundary_policy == EXACT_POLICY:
                    expected = exact_bounds(e, view)
                    if d.strategy != MappingStrategy.GEOM or not expected:
                        reject("exact domain intersection requires valid GEOM solid")
                elif (
                    d.strategy != MappingStrategy.OBST
                    or d.boundary_policy != POLICY
                    or not (expected := eligible_bounds(e, view))
                ):
                    reject("crossing requires eligible boundary OBST policy")
            elif d.boundary_policy:
                reject("boundary policy does not match plan domain")
            actual = d.representation_bounds or source_bounds
            if any(abs(a - b) > 1e-8 for a, b in zip(actual.to_xb(), expected.to_xb())):
                reject("representation bounds differ from source/domain intersection")
        elif d.representation_bounds is not None:
            reject("representation bounds lack valid source geometry")
        elements.append(
            e.model_copy(
                update={
                    "mapping_strategy": d.strategy,
                    "simulation_role": d.simulation_role,
                    "fds_representation": d.fds_representation,
                    "representation_bounds": d.representation_bounds,
                    "mapping_rationale": d.rationale,
                    "scope_rationale": d.scope_rationale,
                    "fds_primitive_ids": [],
                }
            )
        )
    return view.model_copy(update={"elements": elements})
