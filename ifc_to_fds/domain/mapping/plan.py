"""MappingPlan builder and inspection utilities."""

from __future__ import annotations
from typing import Any
from .model import MappingDecision, MappingPlan


def build_mapping_plan(model: Any, cell_size: float = 0.2, hvac_network=None) -> MappingPlan:
    """Snapshot mapping intent without sharing mutable policy evidence with the model."""
    decisions = []
    for e in model.elements:
        decisions.append(
            MappingDecision(
                entity_key=e.entity_key,
                strategy=e.mapping_strategy,
                simulation_role=e.simulation_role,
                fds_representation=e.fds_representation,
                representation_bounds=e.representation_bounds,
                element_bounds=e.bounding_box,
                rationale=e.mapping_rationale,
                boundary_treatment=e.boundary_treatment,
                scope_decision=e.scope_decision,
                scope_rationale=e.scope_rationale,
                boundary_policy=e.boundary_policy,
                boundary_evidence=e.boundary_evidence.copy(),
                decision=e.decision.copy(),
                review_status=e.review_status,
            )
        )
    return MappingPlan(
        decisions=decisions,
        hvac_network=hvac_network if hvac_network is not None else model.hvac_network,
        simulation_domain=model.simulation_domain
        or (
            model.model_bounds
            if not model.requested_scope.get("storeys")
            and not model.requested_scope.get("bounding_box")
            else None
        ),
        domain_origin=(
            "FULL_MODEL"
            if model.simulation_domain is None
            and model.model_bounds
            and not model.requested_scope.get("storeys")
            and not model.requested_scope.get("bounding_box")
            else model.domain_origin
        ),
        cell_size=cell_size,
        metadata={
            "source_id": model.source.source_id,
            "filename": model.source.filename,
            "total_elements": len(model.elements),
        },
    ).model_copy(deep=True)
