"""Validation domain models for findings, gates, and acceptance reports."""

from enum import Enum
from typing import Any, Callable, ClassVar, Optional
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from ..version import SCHEMA_VERSION


class Severity(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class AcceptanceStatus(str, Enum):
    MAPPING_VERIFIED = "MAPPING_VERIFIED"
    SIMULATION_VERIFIED = "SIMULATION_VERIFIED"
    REJECTED = "REJECTED"
    INCONCLUSIVE = "INCONCLUSIVE"


# Backward compatibility alias
AcceptanceVerdict = AcceptanceStatus


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class GateResult(BaseModel):
    status: GateStatus = GateStatus.NOT_RUN
    required: bool = True
    reason: str = ""
    reason_code: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)


class AuditConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fail_fast_on_source_errors: StrictBool = False
    collect_partial_geometry_evidence: StrictBool = False
    surface_tolerance_m: float = Field(default=0.001, gt=0, allow_inf_nan=False)
    relative_volume_tolerance: float = Field(
        default=0.001, ge=0, lt=1, allow_inf_nan=False
    )
    min_solid_iou: float = Field(default=0.999, gt=0, le=1, allow_inf_nan=False)
    solver_executable: str | None = None
    solver_version: str = "6.11.1"
    solver_evidence_directory: str | None = None
    boundary_fixture_certificate: str | None = None
    solver_timeout_s: float = Field(default=120.0, gt=0, allow_inf_nan=False)
    max_leak_volume_m3: float = Field(default=1e-4, ge=0, allow_inf_nan=False)


class Finding(BaseModel):
    verification_level: str = "mapping"
    id: str
    severity: Severity
    category: str
    title: str
    detail: str
    element_id: str = ""
    remediation: str = ""


class ValidationContext(BaseModel):
    """Context passed to individual gate checkers."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    model: Any
    fds_text: str
    manifest: Any
    config: AuditConfig | None = None
    geometry_package: Any | None = None
    parsed_fds: Any | None = None

    _parser: ClassVar[Optional[Callable[[str], Any]]] = None

    @classmethod
    def register_parser(cls, parser_fn: Callable[[str], Any]) -> None:
        cls._parser = staticmethod(parser_fn)

    @property
    def parsed(self) -> Any:
        if self.parsed_fds is None and self.fds_text:
            if self._parser is not None:
                self.parsed_fds = self._parser(self.fds_text)
            else:
                raise RuntimeError("No FDS parser registered on ValidationContext")
        return self.parsed_fds


class AcceptanceReport(BaseModel):
    requested_level: str = "mapping"
    mapping_status: AcceptanceStatus = AcceptanceStatus.INCONCLUSIVE
    simulation_status: AcceptanceStatus = AcceptanceStatus.INCONCLUSIVE
    schema_version: str = SCHEMA_VERSION
    status: AcceptanceStatus = AcceptanceStatus.INCONCLUSIVE
    total_elements_checked: int = 0
    matched_count: int = 0
    deviated_count: int = 0
    missing_count: int = 0
    excluded_count: int = 0
    semantic_only_count: int = 0
    findings: list[Finding] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
    gates: dict[str, GateResult] = Field(default_factory=dict)
    element_statuses: dict[str, str] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    configuration: dict[str, Any] = Field(default_factory=dict)
    coverage: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def read_legacy_report(cls, value):
        if isinstance(value, dict) and value.get("schema_version") == "0.3.0":
            value = dict(value)
            value["status"] = "INCONCLUSIVE"
            value["mapping_status"] = "INCONCLUSIVE"
            value["simulation_status"] = "INCONCLUSIVE"
            value["gates"] = {
                **value.get("gates", {}),
                "schema_migration": dict(
                    status="INCONCLUSIVE",
                    reason="Legacy report requires independent audit under schema 0.4",
                ),
            }
        return value

    def finalize(self):
        pass_reasons = {
            "syntax": "Serialized FDS parsed without syntax errors or unsupported records",
            "traceability": "Serialized primitives agree with their source and manifest identities",
            "scope": "Exported primitives comply with the resolved IFC scope",
            "geometry": "Completed solid comparisons meet the configured tolerances",
            "openings": "Checked source openings retain their subtraction and free passage",
            "mep": "Source MEP relationships and the mapping inventory agree",
            "representation": "Exported solids comply with the source representation decisions",
            "boundary": "Required boundary treatments have no unresolved findings",
            "domain": "Declared FDS meshes agree with the resolved simulation domain",
        }
        for name, gate in self.gates.items():
            if not gate.reason.strip() and gate.status == GateStatus.PASS and name in pass_reasons:
                gate.reason = pass_reasons[name]
            if not gate.reason.strip() and gate.status == GateStatus.NOT_RUN:
                gate.reason = f"No result was produced for the {name} check"
            if not gate.reason_code:
                gate.reason_code = f"{name.upper()}_{gate.status.value}"
        # NOTE (M13 contract): SIMULATION_VERIFIED is intentionally never issued
        # here -- simulation_status is only REJECTED or INCONCLUSIVE until the
        # simulation epic defines solver/physics/scenario/mesh gates. The
        # MAPPING_VERIFIED-only checkpoint seal in convert_verified.py relies on
        # this. Pinned by test_finalize_never_issues_simulation_verified.
        simulation = {
            "solver",
            "effective_geometry",
            "physics",
            "scenario",
            "mesh_resolution",
            "operational_model",
        }
        required = [
            g for name, g in self.gates.items() if g.required and name not in simulation
        ]
        failed = any(g.status == GateStatus.FAIL for g in required) or any(
            f.severity in (Severity.P0, Severity.P1)
            and f.verification_level == "mapping"
            for f in self.findings
        )
        if failed:
            self.mapping_status = AcceptanceStatus.REJECTED
        elif required and all(
            g.status in (GateStatus.PASS, GateStatus.NOT_APPLICABLE)
            and (g.status != GateStatus.NOT_APPLICABLE or g.reason)
            for g in required
        ):
            self.mapping_status = AcceptanceStatus.MAPPING_VERIFIED
        else:
            self.mapping_status = AcceptanceStatus.INCONCLUSIVE
        sim_failed = any(
            g.status == GateStatus.FAIL
            for name, g in self.gates.items()
            if name in simulation
        )
        self.simulation_status = (
            AcceptanceStatus.REJECTED
            if sim_failed or failed
            else AcceptanceStatus.INCONCLUSIVE
        )
        self.status = (
            self.simulation_status
            if self.requested_level == "simulation"
            else self.mapping_status
        )
        self.summary = {
            s.value: sum(f.severity == s for f in self.findings) for s in Severity
        }
        return self

    def to_markdown(self):
        def escape(value):
            return str(value).replace("|", r"\|").replace("\n", " ")

        lines = [
            "# IFCtoFDS Conversion Acceptance Report",
            "",
            f"**Overall Verdict:** `{self.status.value}`",
            f"Mapping: `{self.mapping_status.value}`; simulation: `{self.simulation_status.value}`",
            f"Research: `{self.configuration.get('research', {}).get('research_acceptance', 'NOT_RUN')}`",
            "",
            f"Accounted elements: {self.total_elements_checked}; matched solids: {self.matched_count}",
            "",
        ]
        exported = self.coverage.get("fds_export", {})
        if "compared_entities" in exported:
            lines += [
                f"FDS written: {exported['entities']} entities / {exported['primitives']} primitives.",
                f"Geometry comparisons ({exported['comparison_mode']}): "
                f"{exported['compared_entities']} completed / {exported['attempted_entities']} attempted; "
                f"{exported['verified_entities']} verified; {exported['deviated_entities']} deviated; "
                f"{exported['failed_comparison_entities']} invalid comparisons; "
                f"{exported['inconclusive_comparison_entities']} inconclusive; "
                f"{exported['not_compared_entities']} written entities not compared.",
                "",
            ]
            if self.metrics.get("source_topology_preflight_rejected"):
                lines += [
                    "Source topology preflight blocked dependent global checks. "
                    f"{exported['skipped_for_source_errors']} local comparisons skipped. "
                    "Partial results do not accept the diagnostic FDS artifact.",
                    "",
                ]
        lines += ["| Gate | Status | Reason |", "|---|---|---|"]
        lines += [
            f"| {name} | {g.status.value} | {escape(g.reason)} |"
            for name, g in self.gates.items()
        ]
        lines += ["", "| Severity | Element | Detail |", "|---|---|---|"]
        lines += [
            f"| {f.severity.value} | {escape(f.element_id)} | {escape(f.detail)} |"
            for f in self.findings
        ]
        if not self.findings:
            lines += [
                "",
                "No defects reported by completed checks. See gate statuses for unverified requirements.",
            ]
        return "\n".join(lines) + "\n"
