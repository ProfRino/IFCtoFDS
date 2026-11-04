"""AcceptanceEvaluator: aggregates gate checker outcomes into a detached, finalized AcceptanceReport."""

from typing import List
from copy import deepcopy
from .checkers.base import CheckerOutcome
from .model import AcceptanceReport, GateResult, GateStatus, ValidationContext


class AcceptanceEvaluator:
    """Evaluates checker outcomes and constructs finalized AcceptanceReport."""

    def evaluate(
        self, context: ValidationContext, outcomes: List[CheckerOutcome]
    ) -> AcceptanceReport:
        model = context.model
        config = context.config
        report = AcceptanceReport(
            total_elements_checked=len(model.elements) if model else 0,
            configuration=config.model_dump() if config else {},
        )

        # Initialize default gates
        default_gate_names = (
            "syntax",
            "source_inventory",
            "traceability",
            "scope",
            "geometry",
            "structural_completeness",
            "air_path",
            "openings",
            "mep",
            "representation",
            "boundary",
            "domain",
        )
        report.gates = {
            name: GateResult(status=GateStatus.NOT_RUN) for name in default_gate_names
        }

        # Apply outcomes from checkers
        for outcome in outcomes:
            report.gates[outcome.gate_name] = outcome.result.model_copy(deep=True)
            report.gates.update({k: v.model_copy(deep=True) for k, v in outcome.additional_gates.items()})
            report.findings.extend(f.model_copy(deep=True) for f in outcome.findings)
            report.metrics.update(deepcopy(outcome.metrics))
            report.element_statuses.update(deepcopy(outcome.element_statuses))
            for key, value in outcome.coverage.items():
                if key in report.coverage and report.coverage[key] != value:
                    raise ValueError(f"Conflicting audit coverage: {key}")
                report.coverage[key] = deepcopy(value)

        # Update summary counts
        statuses = report.element_statuses
        report.matched_count = sum(s == "MATCHED" for s in statuses.values())
        report.deviated_count = sum(s == "DEVIATED" for s in statuses.values())
        report.missing_count = sum(s == "MISSING" for s in statuses.values())
        report.excluded_count = sum(
            s in ("EXCLUDED_SCOPE", "EXCLUDED_APPROVED") for s in statuses.values()
        )
        report.semantic_only_count = sum(s == "SEMANTIC_ONLY" for s in statuses.values())

        return report.finalize()
