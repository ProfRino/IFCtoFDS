"""Canonical BIM Domain Schema.

Defines the strongly-typed intermediate data structures mediating between
raw IFC STEP entities, the geometric kernel, the MEP topological graph,
and the FDS serialized output.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from ..mep.model import MEPGraph, PortReference
from ..mep.hvac import HvacNetworkPlan
from ..scope.model import ScopeDecision
from ..source.model import SourceMetadata
from .bounding_box import BoundingBox
from ..version import SCHEMA_VERSION
from ..mapping.enums import MappingStatus, MappingStrategy


class GeometryStatus(str, Enum):
    NOT_PROCESSED = "NOT_PROCESSED"
    VALID = "VALID"
    FAILED = "FAILED"
    NO_REPRESENTATION = "NO_REPRESENTATION"
    APPROXIMATED = "APPROXIMATED"


class TriangleMesh(BaseModel):
    vertices: List[List[float]] = Field(default_factory=list)
    faces: List[List[int]] = Field(default_factory=list)
    normals: Optional[List[List[float]]] = None
    is_closed_manifold: Optional[bool] = None
    has_consistent_normals: Optional[bool] = None
    area: Optional[float] = None
    volume: Optional[float] = None


class OpeningReference(BaseModel):
    entity_key: str = ""
    host_entity_key: str = ""
    void_relation_key: str = ""
    filling_entity_keys: List[str] = Field(default_factory=list)
    filling_relation_keys: List[str] = Field(default_factory=list)
    placement: Dict[str, Any] = Field(default_factory=dict)
    opening_global_id: str
    opening_step_id: int
    opening_name: str
    opening_type: str = "IfcOpeningElement"
    bounding_box: Optional[BoundingBox] = None
    filling_global_ids: List[str] = Field(default_factory=list)
    is_subtracted: bool = False
    mesh: Optional[TriangleMesh] = None
    verification_status: str = "NOT_RUN"
    extraction_diagnostic: Optional[str] = None


class StoreyReference(BaseModel):
    building_id: Optional[str] = None
    spatial_ancestry: List[str] = Field(default_factory=list)
    storey_id: str
    source_id: str
    name: str
    elevation_m: Optional[float] = None


class CanonicalElement(BaseModel):
    building_id: Optional[str] = None
    spatial_ancestry: List[str] = Field(default_factory=list)
    type_class: Optional[str] = None
    source_presence: str = "CONFIRMED"
    geometry_preservation: str = "NOT_RUN"
    simulation_role: str = "PASSIVE_OBSTACLE"
    operational_status: str = "NOT_APPLICABLE"
    fds_representation: str = "NONE"
    review_status: str = "NOT_REQUIRED"
    boundary_treatment: str = "NOT_APPLICABLE"
    boundary_policy: str | None = None
    boundary_evidence: Dict[str, Any] = Field(default_factory=dict)
    representation_bounds: Optional[BoundingBox] = None
    decision: Dict[str, Any] = Field(default_factory=dict)
    source_id: str = ""
    entity_key: str = ""
    global_id: str
    step_id: int
    ifc_type: str
    name: str = ""
    tag: Optional[str] = None
    storey: Optional[str] = None
    storey_id: Optional[str] = None
    role: str = "PHYSICAL"
    geometry_status: GeometryStatus = GeometryStatus.NOT_PROCESSED
    scope_decision: ScopeDecision = ScopeDecision.IN_SCOPE
    scope_rationale: str = "Full model"
    mapping_planned: bool = False
    mep_category: str = "OTHER"
    classification_evidence: List[str] = Field(default_factory=list)
    predefined_type: Optional[str] = None
    system_names: List[str] = Field(default_factory=list)
    system_ids: List[str] = Field(default_factory=list)

    # Transform: 4x4 matrix row-major in world coordinates
    transform: Optional[List[float]] = None
    placement: Dict[str, Any] = Field(default_factory=dict)

    # Geometric representation
    bounding_box: Optional[BoundingBox] = None
    mesh: Optional[TriangleMesh] = None
    has_3d_geometry: bool = False
    source_representations: List[Dict[str, Any]] = Field(default_factory=list)
    geometry_diagnostics: Dict[str, Any] = Field(default_factory=dict)

    # Relationships
    host_global_id: Optional[str] = None
    openings: List[OpeningReference] = Field(default_factory=list)
    ports: List[PortReference] = Field(default_factory=list)
    property_sets: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    # Mapping Decisions & Provenance
    mapping_strategy: MappingStrategy = MappingStrategy.SEMANTIC_ONLY
    mapping_status: MappingStatus = MappingStatus.INCONCLUSIVE
    mapping_rationale: Optional[str] = None
    fds_primitive_ids: List[str] = Field(default_factory=list)
    validation_notes: List[str] = Field(default_factory=list)


class CanonicalModel(BaseModel):
    simulation_domain: Optional[BoundingBox] = None
    domain_origin: str = "UNRESOLVED"
    schema_version: str = SCHEMA_VERSION
    source: SourceMetadata
    sources: List[SourceMetadata] = Field(default_factory=list)
    elements: List[CanonicalElement] = Field(default_factory=list)
    mep_graph: MEPGraph = Field(default_factory=MEPGraph)
    hvac_network: HvacNetworkPlan = Field(default_factory=HvacNetworkPlan)
    storeys: List[str] = Field(default_factory=list)
    model_bounds: Optional[BoundingBox] = None
    storey_references: List[StoreyReference] = Field(default_factory=list)
    requested_scope: Dict[str, Any] = Field(default_factory=dict)
    exported_bounds: Optional[BoundingBox] = None
    timings: Dict[str, float] = Field(default_factory=dict)

    def get_element_by_guid(self, guid: str) -> Optional[CanonicalElement]:
        matches = [el for el in self.elements if el.global_id == guid]
        if len(matches) > 1:
            raise ValueError("Ambiguous GlobalId; use entity_key")
        return matches[0] if matches else None

    def get_elements_by_type(self, ifc_type: str) -> List[CanonicalElement]:
        t_upper = ifc_type.upper()
        return [el for el in self.elements if el.ifc_type.upper() == t_upper]
