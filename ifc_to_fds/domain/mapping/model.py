"""Mapping domain models including MappingDecision and MappingPlan abstractions."""

import csv
import hashlib
import io
import json
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from ..bim.bounding_box import BoundingBox
from ..version import SCHEMA_VERSION
from ..scope.model import ScopeDecision
from .enums import MappingStatus, MappingStrategy
from ..mep.hvac import HvacNetworkPlan

__all__ = [
    "MappingStrategy",
    "MappingStatus",
    "MappingDecision",
    "MappingPlan",
    "ManifestRecord",
    "MappingManifest",
    "_serialize_csv_value",
]


def _serialize_csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, list):
        if not value:
            return ""
        if all(isinstance(item, str) for item in value):
            return ";".join(value)
        return json.dumps(value, sort_keys=True)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return value


class MappingDecision(BaseModel):
    """Explicit mapping decision for a single canonical element."""

    entity_key: str
    strategy: MappingStrategy
    simulation_role: str
    fds_representation: str
    # Legacy read/explicit sync only. New plans do not carry serialization results.
    fds_primitive_ids: List[str] = Field(
        default_factory=list, json_schema_extra={"deprecated": True}
    )
    representation_bounds: Optional[BoundingBox] = None
    element_bounds: Optional[BoundingBox] = None
    rationale: Optional[str] = None
    boundary_treatment: str = "NOT_APPLICABLE"
    scope_decision: ScopeDecision = ScopeDecision.IN_SCOPE
    scope_rationale: str = "Full model"
    boundary_policy: Optional[str] = None
    boundary_evidence: Dict[str, Any] = Field(default_factory=dict)
    decision: Dict[str, Any] = Field(default_factory=dict)
    review_status: str = "NOT_REQUIRED"


class MappingPlan(BaseModel):
    """Intermediate mapping plan decoupled from FDS serialization."""

    decisions: List[MappingDecision] = Field(default_factory=list)
    hvac_network: HvacNetworkPlan = Field(default_factory=HvacNetworkPlan)
    simulation_domain: Optional[BoundingBox] = None
    cell_size: float = Field(0.2, gt=0, allow_inf_nan=False)
    domain_origin: str = "UNRESOLVED"
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def get_decision(self, entity_key: str) -> Optional[MappingDecision]:
        for d in self.decisions:
            if d.entity_key == entity_key:
                return d
        return None

    def sync_primitive_ids(self, model: Any) -> None:
        """Legacy explicit sync; IDs are ignored by serialization authorization."""
        for elem in model.elements:
            decision = self.get_decision(elem.entity_key)
            if decision is not None:
                decision.fds_primitive_ids = list(elem.fds_primitive_ids)


class ManifestRecord(BaseModel):
    system_ids: list[str] = Field(default_factory=list)
    ports: list[dict[str, Any]] = Field(default_factory=list)
    openings: list[dict[str, Any]] = Field(default_factory=list)
    classification_evidence: list[str] = Field(default_factory=list)
    source_presence: str = "CONFIRMED"
    geometry_preservation: str = "NOT_RUN"
    simulation_role: str = "PASSIVE_OBSTACLE"
    operational_status: str = "NOT_APPLICABLE"
    fds_representation: str = "NONE"
    review_status: str = "NOT_REQUIRED"
    boundary_treatment: str = "NOT_APPLICABLE"
    boundary_policy: str | None = None
    boundary_evidence: dict[str, Any] = Field(default_factory=dict)
    representation_bounds: dict[str, float] | None = None
    source_bounds: dict[str, float] | None = None
    placement: dict[str, Any] = Field(default_factory=dict)
    building_id: str | None = None
    type_class: str | None = None
    decision: dict[str, Any] = Field(default_factory=dict)
    entity_key: str
    source_id: str
    global_id: str
    step_id: int
    ifc_type: str
    name: str
    storey: str | None = None
    systems: list[str] = Field(default_factory=list)
    scope_decision: str
    scope_rationale: str
    mapping_strategy: str
    mapping_status: str
    fds_primitive_ids: list[str] = Field(default_factory=list)
    rationale: str | None = None


class MappingManifest(BaseModel):
    simulation_domain: dict[str, Any] | None = None
    geometry_package_sha256: str = ""
    bundle_sha256: str = ""
    mapping_acceptance: str = "INCONCLUSIVE"
    simulation_acceptance: str = "INCONCLUSIVE"
    output_complete: bool = False
    schema_version: str = SCHEMA_VERSION
    source_filename: str
    source_sha256: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    total_elements_accounted: int
    total_primitives_emitted: int
    records: list[ManifestRecord] = Field(default_factory=list)
    primitive_to_ifc: dict[str, list[str]] = Field(default_factory=dict)
    auxiliary_primitives: dict[str, str] = Field(default_factory=dict)
    fds_sha256: str = ""
    configuration: dict[str, Any] = Field(default_factory=dict)
    acceptance_status: str = "INCONCLUSIVE"

    def compute_bundle_sha256(self) -> str:
        sources_payload = [
            dict(
                source_id=s.get("source_id"),
                file_hash_sha256=s.get("file_hash_sha256", s.get("source_id")),
            )
            for s in sorted(self.sources, key=lambda x: str(x.get("source_id", "")))
        ] if self.sources else [dict(source_id=self.source_sha256, file_hash_sha256=self.source_sha256)]
        sources_digest = hashlib.sha256(
            json.dumps(sources_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        def _canon_box(box: Any) -> Any:
            if not box:
                return None
            b = box if isinstance(box, dict) else box.model_dump()
            return {k: round(float(b[k]), 6) for k in sorted(b)}

        def _canon_item(item: Any) -> Any:
            if isinstance(item, dict):
                return json.dumps(item, sort_keys=True)
            return str(item)

        records_payload = [
            dict(
                entity_key=r.entity_key,
                source_id=r.source_id,
                global_id=r.global_id,
                step_id=r.step_id,
                ifc_type=r.ifc_type,
                name=r.name,
                storey=r.storey,
                building_id=r.building_id,
                type_class=r.type_class,
                systems=sorted(r.systems),
                system_ids=sorted(r.system_ids),
                ports=sorted([_canon_item(p) for p in r.ports]),
                openings=sorted([_canon_item(o) for o in r.openings]),
                classification_evidence=sorted(r.classification_evidence),
                source_presence=r.source_presence,
                geometry_preservation=r.geometry_preservation,
                simulation_role=r.simulation_role,
                operational_status=r.operational_status,
                fds_representation=r.fds_representation,
                review_status=r.review_status,
                boundary_treatment=r.boundary_treatment,
                boundary_policy=r.boundary_policy,
                boundary_evidence=r.boundary_evidence,
                representation_bounds=_canon_box(r.representation_bounds),
                source_bounds=_canon_box(r.source_bounds),
                placement=r.placement,
                decision=r.decision,
                scope_decision=r.scope_decision,
                scope_rationale=r.scope_rationale,
                mapping_strategy=r.mapping_strategy,
                mapping_status=r.mapping_status,
                fds_primitive_ids=sorted(r.fds_primitive_ids),
                rationale=r.rationale,
            )
            for r in sorted(self.records, key=lambda x: (x.source_id, x.step_id, x.entity_key))
        ]
        records_digest = hashlib.sha256(
            json.dumps(records_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        reverse_payload = {
            k: sorted(v) for k, v in sorted(self.primitive_to_ifc.items())
        }
        reverse_digest = hashlib.sha256(
            json.dumps(reverse_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        bundle_payload = json.dumps(
            {
                "source_sha256": self.source_sha256,
                "sources_digest": sources_digest,
                "fds_sha256": self.fds_sha256,
                "geometry_package_sha256": self.geometry_package_sha256,
                "simulation_domain": self.simulation_domain or {},
                "total_elements": self.total_elements_accounted,
                "total_primitives": self.total_primitives_emitted,
                "records_digest": records_digest,
                "primitive_to_ifc_digest": reverse_digest,
                "configuration": self.configuration or {},
            },
            sort_keys=True,
        )
        return hashlib.sha256(bundle_payload.encode("utf-8")).hexdigest()

    def reseal(self) -> str:
        self.bundle_sha256 = self.compute_bundle_sha256()
        return self.bundle_sha256

    def to_json(self, indent=2):
        return self.model_dump_json(indent=indent)

    def to_csv(self):
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        fields = list(ManifestRecord.model_fields)
        writer.writerow(fields)
        for record in self.records:
            values = record.model_dump()
            writer.writerow([_serialize_csv_value(values[k]) for k in fields])
        return output.getvalue()
