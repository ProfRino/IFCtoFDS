"""MEP domain models separating SemanticRole, SimulationRole, and operational behavior."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SemanticRole(str, Enum):
    HVAC_DUCT = "HVAC_DUCT"
    SMOKE_EXTRACT = "SMOKE_EXTRACT"
    FIRE_SUPPRESSION = "FIRE_SUPPRESSION"
    PLUMBING = "PLUMBING"
    VENTILATION = "VENTILATION"
    OTHER = "OTHER"
    UNRESOLVED = "UNRESOLVED"


class SimulationRole(str, Enum):
    REFERENCE_GEOMETRY = "REFERENCE_GEOMETRY"
    PASSIVE_OBSTACLE = "PASSIVE_OBSTACLE"
    OPERATIONAL_MEP = "OPERATIONAL_MEP"
    HVAC = "HVAC"


class OperationalStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    CONFIGURED = "CONFIGURED"


class PortReference(BaseModel):
    port_global_id: str
    port_step_id: int
    name: Optional[str] = None
    flow_direction: Optional[str] = None  # SINK, SOURCE, SOURCEANDSINK, NOTDEFINED
    local_position: Optional[List[float]] = None
    connected_port_ids: List[str] = Field(default_factory=list)
    port_key: str = ""
    world_position: Optional[List[float]] = None
    owner_key: str = ""
    ownership_relation_keys: List[str] = Field(default_factory=list)
    ownership_relation_type: Optional[str] = None


class MEPSystem(BaseModel):
    ifc_type: str = ""
    object_type: str = ""
    predefined_type: str = ""
    description: str = ""
    property_sets: Dict[str, Any] = Field(default_factory=dict)
    classifications: List[Dict[str, Any]] = Field(default_factory=list)
    classification_evidence: List[str] = Field(default_factory=list)
    assignment_relation_keys: List[str] = Field(default_factory=list)
    system_id: str
    name: str
    system_type: (
        str  # e.g., "VENTILATION", "SMOKE_EXTRACT", "FIRE_SUPPRESSION", "PLUMBING"
    )
    element_global_ids: List[str] = Field(default_factory=list)
    is_fire_safety_critical: bool = False
    element_keys: List[str] = Field(default_factory=list)


class MEPConnection(BaseModel):
    source_relation_keys: List[str] = Field(default_factory=list)
    connection_id: str
    source_element_id: str
    source_port_id: str
    target_element_id: str
    target_port_id: str
    relation_type: str  # "EXPLICIT_IFC", "GEOMETRIC_PROXIMITY"
    distance_meters: Optional[float] = None
    boundary_connection: bool = False


class MEPGraph(BaseModel):
    systems: List[MEPSystem] = Field(default_factory=list)
    connections: List[MEPConnection] = Field(default_factory=list)
    isolated_element_ids: List[str] = Field(default_factory=list)
    issues: List[str] = Field(default_factory=list)
    coverage: Dict[str, Any] = Field(default_factory=dict)
