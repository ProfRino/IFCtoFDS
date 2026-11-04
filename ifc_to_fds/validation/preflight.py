"""Shared source topology eligibility and policy for both audit entry points."""

from ifc_to_fds.domain.scope.model import ScopeDecision
from ifc_to_fds.geometry.mesh import valid_solid


def invalid_source_solids(model):
    return [
        element.entity_key
        for element in model.elements if element.role == "PHYSICAL"
        and element.scope_decision in (ScopeDecision.IN_SCOPE, ScopeDecision.BOUNDARY_RETAINED)
        and element.mesh and not valid_solid(element.mesh)
    ]


def comparison_summary(parsed, solids, invalid, *, mode, verified, attempted, completed,
                       skipped, failed, inconclusive, deviated):
    """Use one accounting contract for attempted, measured and withheld solids."""
    primitives = parsed.primitives
    return (
        dict(mode=mode, attempted_entities=sorted(attempted), completed_entities=sorted(completed),
             skipped_for_source_errors=sorted(skipped), failed_entities=sorted(failed),
             inconclusive_entities=sorted(inconclusive)),
        dict(entities=len(solids), primitives=len(primitives),
             obst=sum(p.kind == "OBST" for p in primitives), geom=sum(p.kind == "GEOM" for p in primitives),
             verified_entities=verified, comparisons_skipped_for_source_errors=bool(skipped),
             comparison_mode=mode, attempted_entities=len(attempted), compared_entities=len(completed),
             deviated_entities=len(deviated), failed_comparison_entities=len(failed),
             inconclusive_comparison_entities=len(inconclusive), not_compared_entities=len(set(solids) - completed),
             skipped_for_source_errors=len(skipped), source_invalid_entities=len(invalid)),
    )
