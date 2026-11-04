"""Geometric fidelity and 3D solid preservation validation checker."""

from typing import Any, Dict, List
from ifc_to_fds.domain.mapping.enums import MappingStrategy
from ifc_to_fds.domain.scope.model import ScopeDecision
from ifc_to_fds.domain.validation.checkers.base import CheckerOutcome
from ifc_to_fds.domain.validation.model import Finding, GateResult, GateStatus, Severity, ValidationContext
from ifc_to_fds.geometry.mesh import bounds_for_vertices, valid_solid
from ifc_to_fds.mapping.boundary import target_mesh
from ifc_to_fds.validation.metrics import compare_solids
from ifc_to_fds.validation.preflight import comparison_summary, invalid_source_solids


class GeometryChecker:
    name = "geometry"

    def check(self, context: ValidationContext, parsed: Any = None, *, invalid_source=None) -> CheckerOutcome:
        parsed = parsed if parsed is not None else context.parsed
        model = context.model
        if parsed is None or model is None:
            return CheckerOutcome(
                gate_name="geometry",
                result=GateResult(
                    status=GateStatus.INCONCLUSIVE,
                    reason="Incomplete diagnostic artifact: FDS text missing",
                ),
                findings=[],
            )
        config = context.config
        findings: List[Finding] = []
        element_statuses: Dict[str, str] = {}
        metrics_dict: Dict[str, Any] = {}
        invalid = invalid_source_solids(model) if invalid_source is None else invalid_source
        blocked = bool(config and config.fail_fast_on_source_errors and invalid)
        skip = blocked and not config.collect_partial_geometry_evidence
        status = GateStatus.FAIL if blocked else GateStatus.PASS
        reasons = ["Source topology preflight rejected"] if blocked else []
        attempted, completed, skipped, failed, inconclusive, deviated = (set() for _ in range(6))

        domains = [r.values.get("XB") for r in parsed.records if r.kind == "MESH"]
        primitives: Dict[str, List[Any]] = {}

        for p in parsed.primitives:
            key = p.source.get("entity_key", "")
            if p.kind in ("OBST", "GEOM"):
                try:
                    solid = p.mesh()
                    bounds = bounds_for_vertices(solid.vertices)
                    if bounds and len(domains) == 1:
                        xb = domains[0]
                        coordinates = bounds.to_xb()
                        if any(
                            coordinates[i] < xb[i] - 1e-6
                            if i % 2 == 0
                            else coordinates[i] > xb[i] + 1e-6
                            for i in range(6)
                        ):
                            status = GateStatus.FAIL
                            findings.append(
                                Finding(
                                    id=f"FND-{len(findings) + 1:04}",
                                    severity=Severity.P1,
                                    category="geometry",
                                    title=f"Primitive outside computational mesh: {p.id}",
                                    detail=f"Primitive outside computational mesh: {p.id}",
                                    element_id=key,
                                )
                            )
                    primitives.setdefault(key, []).append(solid)
                except ValueError as exc:
                    status = GateStatus.FAIL
                    findings.append(
                        Finding(
                            id=f"FND-{len(findings) + 1:04}",
                            severity=Severity.P1,
                            category="syntax",
                            title=str(exc),
                            detail=str(exc),
                            element_id=key,
                        )
                    )
            else:
                if status != GateStatus.FAIL:
                    status = GateStatus.INCONCLUSIVE
                reasons.append(f"{p.kind} effective semantics not supported")

        for e in model.elements:
            key = e.entity_key
            if e.scope_decision == ScopeDecision.OUT_OF_SCOPE:
                continue

            strategy = e.mapping_strategy
            if strategy in (MappingStrategy.EXCLUDED_SCOPE, MappingStrategy.EXCLUDED_APPROVED):
                element_statuses[key] = strategy.value
                continue
            if strategy == MappingStrategy.SEMANTIC_ONLY:
                element_statuses[key] = "SEMANTIC_ONLY"
                continue
            if strategy == MappingStrategy.HVAC:
                element_statuses[key] = "OPERATIONAL_MAPPED"
                continue
            if strategy == MappingStrategy.NONE:
                if e.role == "PHYSICAL" and (not e.mesh or not valid_solid(e.mesh)):
                    detail = (
                        f"Unsupported source geometry: entity={key}, STEP={e.step_id}, "
                        f"GlobalId={e.global_id}, IFC type={e.ifc_type}; {e.mapping_rationale}"
                    )
                    element_statuses[key] = "UNSUPPORTED"
                    if e.mesh:
                        status = GateStatus.FAIL
                        findings.append(
                            Finding(
                                id=f"FND-{len(findings) + 1:04}",
                                severity=Severity.P1,
                                category="geometry",
                                title=detail[:100],
                                detail=detail,
                                element_id=key,
                            )
                        )
                    else:
                        if status != GateStatus.FAIL:
                            status = GateStatus.INCONCLUSIVE
                        reasons.append(detail)
                continue

            meshes = primitives.get(key, [])
            if not meshes:
                element_statuses[key] = "MISSING"
                continue

            if not e.mesh or not valid_solid(e.mesh):
                element_statuses[key] = "UNSUPPORTED"
                status = GateStatus.FAIL
                findings.append(
                    Finding(
                        id=f"FND-{len(findings) + 1:04}",
                        severity=Severity.P1,
                        category="geometry",
                        title=f"Source physical solid missing or invalid: {e.global_id}",
                        detail=f"Source physical solid missing or invalid: {e.global_id}",
                        element_id=key,
                    )
                )
                continue

            if skip:
                element_statuses[key] = "INCONCLUSIVE"
                skipped.add(key)
                continue
            attempted.add(key)
            try:
                m = compare_solids(target_mesh(e), meshes)
                completed.add(key)
                metrics_dict[key] = m
                surface_tol = config.surface_tolerance_m if config else 0.001
                vol_tol = config.relative_volume_tolerance if config else 0.001
                iou_tol = config.min_solid_iou if config else 0.999

                fail = (
                    float(m["surface_distance_m"]) > surface_tol
                    or float(m["relative_volume_error"]) > vol_tol
                    or float(m["solid_iou"]) < iou_tol
                    or m["reference_components"] != m["output_components"]
                )
                if fail:
                    deviated.add(key)
                    status = GateStatus.FAIL
                    findings.append(
                        Finding(
                            id=f"FND-{len(findings) + 1:04}",
                            severity=Severity.P1,
                            category="geometry",
                            title=f"Geometric deviation: {m}",
                            detail=f"Geometric deviation: {m}",
                            element_id=key,
                        )
                    )
                    element_statuses[key] = "DEVIATED"
                elif not m["surface_proven"]:
                    inconclusive.add(key)
                    if status != GateStatus.FAIL:
                        status = GateStatus.INCONCLUSIVE
                    reasons.append(f"Full surface distance not proven for {key}")
                    element_statuses[key] = "INCONCLUSIVE"
                else:
                    element_statuses[key] = "MATCHED"
            except ValueError as exc:
                failed.add(key)
                status = GateStatus.FAIL
                findings.append(
                    Finding(
                        id=f"FND-{len(findings) + 1:04}",
                        severity=Severity.P1,
                        category="geometry",
                        title=f"{key}: invalid solid comparison: {exc}",
                        detail=f"{key}: invalid solid comparison: {exc}",
                        element_id=key,
                    )
                )
                element_statuses[key] = "DEVIATED"
            except Exception as exc:
                inconclusive.add(key)
                if status != GateStatus.FAIL:
                    status = GateStatus.INCONCLUSIVE
                reasons.append(f"{key}: solid comparison failed: {exc}")
                element_statuses[key] = "INCONCLUSIVE"

        mode = "FAIL_FAST" if skip else "PARTIAL" if blocked else "FULL"
        summary, export_coverage = comparison_summary(
            parsed, primitives, invalid, mode=mode,
            verified=sum(value == "MATCHED" for value in element_statuses.values()),
            attempted=attempted, completed=completed, skipped=skipped,
            failed=failed, inconclusive=inconclusive, deviated=deviated,
        )
        metrics_dict["geometry_comparison"] = summary
        final_reason = "; ".join(reasons)
        if not final_reason:
            if status == GateStatus.PASS:
                final_reason = (
                    f"All {len(completed)} physical solid elements verified within tolerance"
                    if completed
                    else "No physical solid elements to verify"
                )
            elif status == GateStatus.NOT_RUN:
                final_reason = "Geometry comparison not run"
        return CheckerOutcome(
            gate_name="geometry",
            result=GateResult(status=status, reason=final_reason),
            findings=findings,
            metrics=metrics_dict,
            element_statuses=element_statuses,
            coverage={"fds_export": export_coverage},
        )
