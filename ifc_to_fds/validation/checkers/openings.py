"""Architectural openings, voids subtraction, and air passage validation checker."""

from typing import Any, Dict, List
from ifc_to_fds.domain.mapping.enums import MappingStrategy
from ifc_to_fds.domain.scope.model import ScopeDecision
from ifc_to_fds.domain.validation.checkers.base import CheckerOutcome
from ifc_to_fds.domain.validation.model import Finding, GateResult, GateStatus, Severity, ValidationContext
from ifc_to_fds.geometry.mesh import as_trimesh, valid_solid
from ifc_to_fds.mapping.boundary import target_mesh
from ifc_to_fds.validation.effective import check_opening_grid_alignment
from ifc_to_fds.validation.metrics import SolidCandidateIndex, opening_residual, passage_metrics


class OpeningsChecker:
    name = "openings"

    def check(self, context: ValidationContext, parsed: Any = None) -> CheckerOutcome:
        parsed = parsed if parsed is not None else context.parsed
        model = context.model
        if parsed is None or model is None:
            return CheckerOutcome(
                gate_name="openings",
                result=GateResult(
                    status=GateStatus.INCONCLUSIVE,
                    reason="Incomplete diagnostic artifact: FDS text missing",
                ),
                findings=[],
            )
        config = context.config
        findings: List[Finding] = []
        element_statuses: Dict[str, str] = {}
        metrics: Dict[str, Any] = {}
        status = GateStatus.PASS
        reasons = []

        # Map emitted primitives by entity key
        primitives: Dict[str, List[Any]] = {}
        for p in parsed.primitives:
            key = p.source.get("entity_key", "")
            if key and p.kind in ("OBST", "GEOM"):
                try:
                    primitives.setdefault(key, []).append(p.mesh())
                except ValueError:
                    pass

        opening_count = sum(
            len(e.openings)
            for e in model.elements
            if e.scope_decision != ScopeDecision.OUT_OF_SCOPE
            and e.mapping_strategy in (MappingStrategy.OBST, MappingStrategy.GEOM)
        )

        if opening_count == 0:
            return CheckerOutcome(
                gate_name="openings",
                result=GateResult(
                    status=GateStatus.NOT_APPLICABLE,
                    reason="No mapped host has source openings",
                ),
                findings=[],
                metrics={"opening_count": 0},
            )

        reference_solids = SolidCandidateIndex(
            target_mesh(x)
            for x in model.elements
            if x.mesh
            and x.role == "PHYSICAL"
            and x.mapping_strategy in (MappingStrategy.OBST, MappingStrategy.GEOM)
            and x.scope_decision in (ScopeDecision.IN_SCOPE, ScopeDecision.BOUNDARY_RETAINED)
        )
        exported_solids = SolidCandidateIndex(
            mesh for group in primitives.values() for mesh in group
        )

        for e in model.elements:
            key = e.entity_key
            if e.scope_decision == ScopeDecision.OUT_OF_SCOPE:
                continue

            if e.mapping_strategy == MappingStrategy.NONE:
                if e.role == "PHYSICAL" and (not e.mesh or not valid_solid(e.mesh)):
                    if e.openings:
                        if status != GateStatus.FAIL:
                            status = GateStatus.INCONCLUSIVE
                        reasons.append(f"Host geometry unavailable for opening proof: {key}")
                elif any(not o.mesh or not valid_solid(o.mesh) for o in e.openings):
                    if status != GateStatus.FAIL:
                        status = GateStatus.INCONCLUSIVE
                    reasons.append(f"Host {key}: incomplete source opening extraction")
                continue

            meshes = primitives.get(key, [])
            if not meshes:
                continue

            for opening in e.openings:
                try:
                    source_residual = opening_residual([e.mesh], opening.mesh) if e.mesh else 0.0
                    output_residual = opening_residual(meshes, opening.mesh)
                    opening_solid = as_trimesh(opening.mesh)
                    surface_tol = config.surface_tolerance_m if config else 0.001
                    opening_tolerance = max(
                        1e-6,
                        surface_tol
                        * opening_solid.area
                        / max(opening_solid.volume, 1e-12),
                    )
                    if source_residual > opening_tolerance:
                        if status != GateStatus.FAIL:
                            status = GateStatus.INCONCLUSIVE
                        reasons.append(f"Source opening subtraction not proven: {opening.opening_global_id}")
                    elif output_residual > opening_tolerance:
                        status = GateStatus.FAIL
                        reasons.append(
                            f"Opening blocked in emitted host: {opening.opening_global_id} "
                            f"(output_residual={output_residual:.6e} > tolerance={opening_tolerance:.6e})"
                        )
                        findings.append(
                            Finding(
                                id=f"FND-{len(findings) + 1:04}",
                                severity=Severity.P1,
                                category="openings",
                                title=f"Opening blocked in emitted host: {opening.opening_global_id}",
                                detail=f"Opening blocked in emitted host: {opening.opening_global_id}",
                                element_id=key,
                            )
                        )

                    passage = (
                        passage_metrics(reference_solids, exported_solids, opening.mesh)
                        if reference_solids is not None and exported_solids is not None
                        else {}
                    )
                    if passage and (
                        passage["normalized_symmetric_difference"] > opening_tolerance
                        or passage["source_free_components"] != passage["output_free_components"]
                    ):
                        status = GateStatus.FAIL
                        reasons.append(
                            f"Opening passage altered: {opening.opening_global_id} "
                            f"(normalized_symmetric_difference={passage.get('normalized_symmetric_difference', 0.0):.6e}, "
                            f"free_components source={passage.get('source_free_components')} vs output={passage.get('output_free_components')})"
                        )
                        findings.append(
                            Finding(
                                id=f"FND-{len(findings) + 1:04}",
                                severity=Severity.P1,
                                category="openings",
                                title=f"Opening passage changed, including fills/blockers: {opening.opening_global_id}",
                                detail=f"Opening passage changed, including fills/blockers: {opening.opening_global_id}",
                                element_id=key,
                            )
                        )

                    align_info = check_opening_grid_alignment(
                        opening.mesh, e.bounding_box, parsed,
                    )

                    metrics.setdefault(key, {})[f"opening:{opening.opening_global_id}"] = dict(
                        source_residual=source_residual,
                        output_residual=output_residual,
                        passage=passage,
                        grid_alignment=align_info,
                    )
                except Exception as exc:
                    if status != GateStatus.FAIL:
                        status = GateStatus.INCONCLUSIVE
                    reasons.append(f"{opening.opening_global_id}: {exc}")

        reason_str = "; ".join(reasons) if reasons else (
            "All host openings verified successfully"
            if status == GateStatus.PASS
            else "Openings validation inconclusive"
        )
        evidence = {
            "findings_count": len(findings),
            "element_statuses": element_statuses,
            "metrics": metrics,
        }
        return CheckerOutcome(
            gate_name="openings",
            result=GateResult(
                status=status,
                reason=reason_str,
                evidence=evidence,
            ),
            findings=findings,
            metrics=metrics,
            element_statuses=element_statuses,
        )
