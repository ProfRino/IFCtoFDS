"""Traceability and source inventory validation checkers."""

import hashlib
from typing import Any, List
from ifc_to_fds.core.canonical import MappingStrategy, ScopeDecision
from ifc_to_fds.domain.validation.checkers.base import CheckerOutcome
from ifc_to_fds.domain.validation.model import Finding, GateResult, GateStatus, Severity, ValidationContext


SCENARIO_PRIMITIVE_PREFIXES = ("OBST_EV_", "VENT_BURNER_", "BURNER_")


def is_scenario_primitive(pid: str) -> bool:
    return bool(pid and pid.startswith(SCENARIO_PRIMITIVE_PREFIXES))


class TraceabilityChecker:
    name = "traceability"

    def check(self, context: ValidationContext, parsed: Any = None) -> CheckerOutcome:
        parsed = parsed if parsed is not None else context.parsed
        model = context.model
        if parsed is None or model is None:
            return CheckerOutcome(
                gate_name="traceability",
                result=GateResult(
                    status=GateStatus.INCONCLUSIVE,
                    reason="Incomplete diagnostic artifact: FDS text missing",
                ),
                findings=[],
            )
        manifest = context.manifest
        fds_text = context.fds_text
        findings: List[Finding] = []
        status = GateStatus.PASS
        reasons = []

        known = {e.entity_key: e for e in model.elements}
        actual_ids = set()

        for p in parsed.primitives:
            if is_scenario_primitive(p.id):
                continue
            actual_ids.add(p.id)
            key = p.source.get("entity_key", "")
            if not key and p.source.get("legacy"):
                candidates = [
                    e
                    for e in model.elements
                    if e.global_id == p.source.get("global_id")
                    and e.step_id == p.source.get("step_id")
                ]
                if len(candidates) == 1:
                    key = candidates[0].entity_key
                    p.source["entity_key"] = candidates[0].entity_key
            if p.source.get("legacy"):
                if status != GateStatus.FAIL:
                    status = GateStatus.INCONCLUSIVE
                reasons.append(f"Legacy source metadata lacks file hash: {p.id}")

            if key not in known:
                status = GateStatus.FAIL
                findings.append(
                    Finding(
                        id=f"FND-{len(findings) + 1:04}",
                        severity=Severity.P0,
                        category="traceability",
                        title=f"Unexpected primitive {p.id}: source entity {key!r} is not in inventory",
                        detail=f"Unexpected primitive {p.id}: source entity {key!r} is not in inventory",
                        element_id=key,
                    )
                )
                continue

            e = known[key]
            if (
                p.source.get("global_id") != e.global_id
                or p.source.get("step_id") != e.step_id
                or (not p.source.get("legacy") and p.source.get("source_id") != e.source_id)
                or (not p.source.get("legacy") and p.source.get("ifc_type") != e.ifc_type)
            ):
                status = GateStatus.FAIL
                findings.append(
                    Finding(
                        id=f"FND-{len(findings) + 1:04}",
                        severity=Severity.P1,
                        category="traceability",
                        title=f"Conflicting provenance for primitive {p.id}",
                        detail=f"Conflicting provenance for primitive {p.id}",
                        element_id=key,
                    )
                )
            if e.role != "PHYSICAL":
                status = GateStatus.FAIL
                findings.append(
                    Finding(
                        id=f"FND-{len(findings) + 1:04}",
                        severity=Severity.P1,
                        category="traceability",
                        title=f"Nonphysical entity emitted as solid: {p.id}",
                        detail=f"Nonphysical entity emitted as solid: {p.id}",
                        element_id=key,
                    )
                )

        emitted_keys = {
            p.source.get("entity_key")
            for p in parsed.primitives
            if p.source.get("entity_key")
        }
        for e in model.elements:
            key = e.entity_key
            if (
                e.scope_decision in (ScopeDecision.IN_SCOPE, ScopeDecision.BOUNDARY_RETAINED)
                and e.role == "PHYSICAL"
                and e.mapping_strategy in (MappingStrategy.OBST, MappingStrategy.GEOM)
            ):
                if key not in emitted_keys:
                    status = GateStatus.FAIL
                    findings.append(
                        Finding(
                            id=f"FND-{len(findings) + 1:04}",
                            severity=Severity.P0,
                            category="traceability",
                            title=f"Missing required FDS solid: {e.global_id}",
                            detail=f"Missing required FDS solid: {e.global_id}",
                            element_id=key,
                        )
                    )

        if manifest:
            records = manifest.records
            if manifest.fds_sha256 != hashlib.sha256(fds_text.encode()).hexdigest():
                status = GateStatus.FAIL
                findings.append(
                    Finding(
                        id=f"FND-{len(findings) + 1:04}",
                        severity=Severity.P0,
                        category="traceability",
                        title="Serialized FDS hash differs from manifest",
                        detail="Serialized FDS hash differs from manifest",
                        element_id="",
                    )
                )
            actual_ids.update(r.id for r in parsed.operational_records)
            manifest_ids = {p for r in records for p in r.fds_primitive_ids}
            if manifest_ids != actual_ids:
                status = GateStatus.FAIL
                findings.append(
                    Finding(
                        id=f"FND-{len(findings) + 1:04}",
                        severity=Severity.P0,
                        category="traceability",
                        title="Manifest primitive set differs from serialized FDS",
                        detail="Manifest primitive set differs from serialized FDS",
                        element_id="",
                    )
                )
            reverse = {}
            for r in records:
                for pid in r.fds_primitive_ids:
                    reverse.setdefault(pid, []).append(r.entity_key)
            if reverse != manifest.primitive_to_ifc:
                status = GateStatus.FAIL
                findings.append(
                    Finding(
                        id=f"FND-{len(findings) + 1:04}",
                        severity=Severity.P1,
                        category="traceability",
                        title="Manifest reverse mapping conflicts with records",
                        detail="Manifest reverse mapping conflicts with records",
                        element_id="",
                    )
                )
            for p in parsed.primitives:
                if is_scenario_primitive(p.id):
                    continue
                if p.id not in reverse or p.source.get("entity_key") not in reverse[p.id]:
                    status = GateStatus.FAIL
                    findings.append(
                        Finding(
                            id=f"FND-{len(findings) + 1:04}",
                            severity=Severity.P1,
                            category="traceability",
                            title=f"Primitive {p.id} disagrees with manifest source mapping",
                            detail=f"Primitive {p.id} disagrees with manifest source mapping",
                            element_id=p.source.get("entity_key", ""),
                        )
                    )
        else:
            if status != GateStatus.FAIL:
                status = GateStatus.INCONCLUSIVE
            reasons.append("No manifest supplied")

        return CheckerOutcome(
            gate_name="traceability",
            result=GateResult(status=status, reason="; ".join(reasons)),
            findings=findings,
        )
