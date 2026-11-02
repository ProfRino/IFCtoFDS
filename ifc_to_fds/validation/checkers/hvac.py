"""Compare operational records from disk text with independently rebuilt intent."""

from ifc_to_fds.domain.validation.checkers.base import CheckerOutcome
from ifc_to_fds.domain.validation import Finding, GateResult, GateStatus, Severity
from ifc_to_fds.mep.network import build_hvac_network
from ifc_to_fds.mep.fds_records import network_records


class HvacNetworkChecker:
    name = "hvac"

    def check(self, context):
        if context.parsed is None or context.model is None:
            return CheckerOutcome(self.name, GateResult(status=GateStatus.INCONCLUSIVE, reason="FDS text/source missing"))
        try:
            plan = build_hvac_network(context.model)
            expected = {(kind, tuple(values.get("TYPE_ID", [])), values["ID"][0]): (values, keys)
                        for kind, values, keys in network_records(plan)}
            actual = {(r.kind, tuple(r.values.get("TYPE_ID", [])), r.id): r
                      for r in context.parsed.operational_records}
            if set(expected) != set(actual):
                raise ValueError("Serialized HVAC record set differs from reviewed source network")
            for identity, (values, keys) in expected.items():
                r = actual[identity]
                if r.values != values or sorted(r.source.get("entity_keys", [])) != sorted(keys):
                    raise ValueError(f"HVAC parameters, topology or provenance changed: {identity}")
            if context.manifest:
                expected_assignments = plan.assignments()
                for record in context.manifest.records:
                    if record.entity_key in expected_assignments and sorted(record.fds_primitive_ids) != sorted(expected_assignments[record.entity_key]):
                        raise ValueError(f"Manifest HVAC assignments changed: {record.entity_key}")
            return CheckerOutcome(self.name, GateResult(
                status=GateStatus.PASS if expected else GateStatus.NOT_APPLICABLE,
                reason="Operational HVAC network independently reconstructed" if expected else "No operational HVAC network requested",
            ), metrics={"hvac_nodes": len(plan.nodes), "hvac_ducts": len(plan.ducts)})
        except (ValueError, KeyError, TypeError) as exc:
            finding = Finding(id="HVAC-001", severity=Severity.P1, category=self.name,
                              title="HVAC network differs from source intent", detail=str(exc))
            return CheckerOutcome(self.name, GateResult(status=GateStatus.FAIL, reason=str(exc)), [finding])
