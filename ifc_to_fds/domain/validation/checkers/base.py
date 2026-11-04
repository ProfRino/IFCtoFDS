"""Base protocol and outcome models for independent gate checkers."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol, runtime_checkable

from ..model import Finding, GateResult, ValidationContext


@dataclass
class CheckerOutcome:
    gate_name: str
    result: GateResult
    findings: List[Finding] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    additional_gates: Dict[str, GateResult] = field(default_factory=dict)
    element_statuses: Dict[str, str] = field(default_factory=dict)
    coverage: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class GateChecker(Protocol):
    name: str

    def check(self, context: ValidationContext) -> CheckerOutcome:
        ...
