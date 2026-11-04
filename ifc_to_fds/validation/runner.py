"""ValidationRunner orchestrates execution of independent gate checkers."""

from typing import Any, List, Optional
from ifc_to_fds.domain.validation.checkers.base import CheckerOutcome, GateChecker
from ifc_to_fds.domain.validation.evaluator import AcceptanceEvaluator
from ifc_to_fds.domain.validation.model import AcceptanceReport, AuditConfig, GateResult, GateStatus, ValidationContext
from ifc_to_fds.validation.parser import parse_fds
from ifc_to_fds.validation.checkers.syntax import FdsSyntaxChecker
from ifc_to_fds.validation.checkers.domain import DomainChecker
from ifc_to_fds.validation.checkers.traceability import TraceabilityChecker
from ifc_to_fds.validation.checkers.scope import ScopeChecker
from ifc_to_fds.validation.checkers.geometry import GeometryChecker
from ifc_to_fds.validation.checkers.structural import StructuralCompletenessChecker
from ifc_to_fds.validation.checkers.air_path import AirPathTopologyChecker
from ifc_to_fds.validation.checkers.openings import OpeningsChecker
from ifc_to_fds.validation.checkers.mep import MepChecker
from ifc_to_fds.validation.checkers.representation import RepresentationChecker
from ifc_to_fds.validation.checkers.boundary import BoundaryChecker
from ifc_to_fds.validation.checkers.mesh_resolution import MeshResolutionChecker
from ifc_to_fds.validation.checkers.solver import SolverChecker
from ifc_to_fds.validation.checkers.hvac import HvacNetworkChecker
from ifc_to_fds.validation.preflight import invalid_source_solids


class ValidationRunner:
    """Orchestrates independent gate checkers against a validation context."""

    def __init__(self, checkers: Optional[List[GateChecker]] = None):
        self.checkers = checkers or self._default_checkers()
        self.evaluator = AcceptanceEvaluator()

    @staticmethod
    def _default_checkers() -> List[GateChecker]:
        return [
            FdsSyntaxChecker(),
            DomainChecker(),
            TraceabilityChecker(),
            ScopeChecker(),
            GeometryChecker(),
            StructuralCompletenessChecker(),
            AirPathTopologyChecker(),
            OpeningsChecker(),
            MepChecker(),
            HvacNetworkChecker(),
            RepresentationChecker(),
            BoundaryChecker(),
            MeshResolutionChecker(),
            SolverChecker(),
        ]

    def create_context(
        self, model: Any, fds_text: str, manifest: Any = None, config: Optional[AuditConfig] = None
    ) -> ValidationContext:
        config = config or AuditConfig()
        parsed_fds = parse_fds(fds_text) if fds_text else None
        if parsed_fds and model and getattr(model, "elements", None):
            for p in parsed_fds.primitives:
                if not p.source.get("entity_key") and p.source.get("legacy"):
                    candidates = [
                        e
                        for e in model.elements
                        if e.global_id == p.source.get("global_id")
                        and e.step_id == p.source.get("step_id")
                    ]
                    if len(candidates) == 1:
                        p.source["entity_key"] = candidates[0].entity_key
        return ValidationContext(
            model=model,
            fds_text=fds_text,
            manifest=manifest,
            config=config,
            parsed_fds=parsed_fds,
        )

    def validate(
        self,
        model: Any,
        fds_text: str,
        manifest: Any = None,
        config: Optional[AuditConfig] = None,
    ) -> AcceptanceReport:
        context = self.create_context(model, fds_text, manifest, config)
        outcomes: List[CheckerOutcome] = []
        syntax_passed = True
        mesh_passed = True
        invalid = invalid_source_solids(model) if model is not None else []
        blocked = bool(context.config.fail_fast_on_source_errors and invalid)
        for checker in self.checkers:
            if blocked and checker.name in ("air_path", "openings", "solver"):
                def blocked_gate(required=True):
                    return GateResult(status=GateStatus.NOT_RUN, required=required,
                                      reason="Source topology preflight rejected")
                solver = checker.name == "solver"
                outcome = CheckerOutcome(
                    gate_name=checker.name, result=blocked_gate(required=not solver),
                    additional_gates={"effective_geometry": blocked_gate(False)} if solver else {},
                )
            elif isinstance(checker, GeometryChecker):
                outcome = checker.check(context, invalid_source=invalid)
            elif isinstance(checker, SolverChecker):
                outcome = checker.check(
                    context, syntax_passed=syntax_passed, mesh_passed=mesh_passed
                )
            else:
                outcome = checker.check(context)
                if checker.name == "syntax" and outcome.result.status != GateStatus.PASS:
                    syntax_passed = False
                elif checker.name == "mesh_resolution" and outcome.result.status not in (
                    GateStatus.PASS,
                    GateStatus.NOT_APPLICABLE,
                ):
                    mesh_passed = False
            outcomes.append(outcome)
        report = self.evaluator.evaluate(context, outcomes)
        if blocked:
            report.metrics["source_topology_preflight_rejected"] = invalid
        return report
