"""Operational HVAC contracts, independent of IFC kernels and FDS text."""

import math
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class EndpointSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["AMBIENT", "VENT"]
    vent_xb: tuple[float, float, float, float, float, float] | None = None
    loss: tuple[float, float] = (1.0, 1.0)

    @model_validator(mode="after")
    def validate_boundary(self):
        if any(x < 0 for x in self.loss):
            raise ValueError("Endpoint losses must be nonnegative")
        if self.kind == "AMBIENT" and self.vent_xb is not None:
            raise ValueError("AMBIENT endpoint cannot have a CFD vent")
        if self.kind == "VENT":
            if self.vent_xb is None:
                raise ValueError("VENT endpoint requires vent_xb in model metres")
            spans = [self.vent_xb[i + 1] - self.vent_xb[i] for i in (0, 2, 4)]
            if sum(x == 0 for x in spans) != 1 or any(x < 0 for x in spans):
                raise ValueError("HVAC vent must be a positive-area axis-aligned rectangle")
        return self


class DuctSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    diameter_m: float | None = Field(None, gt=0)
    area_m2: float | None = Field(None, gt=0)
    perimeter_m: float | None = Field(None, gt=0)
    length_m: float | None = Field(None, gt=0)
    roughness_m: float = Field(0.0, ge=0)
    volume_flow_m3_s: float | None = None
    endpoints: dict[str, EndpointSpec] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_section(self):
        if self.diameter_m is not None:
            if self.area_m2 is not None or self.perimeter_m is not None:
                raise ValueError("Specify diameter OR area and perimeter")
        elif self.area_m2 is None or self.perimeter_m is None:
            raise ValueError("HVAC requires diameter_m or area_m2 and perimeter_m; AABB inference is disabled")
        elif self.perimeter_m**2 < 4 * math.pi * self.area_m2 * (1 - 1e-8):
            raise ValueError("Cross-sectional area and perimeter are inconsistent")
        return self


class HvacNode(BaseModel):
    id: str
    port_keys: list[str]
    entity_keys: list[str]
    xyz: tuple[float, float, float]
    duct_ids: list[str]
    boundary: EndpointSpec | None = None


class HvacDuct(BaseModel):
    id: str
    entity_key: str
    node_ids: tuple[str, str]
    length_m: float
    spec: DuctSpec


class HvacNetworkPlan(BaseModel):
    nodes: list[HvacNode] = Field(default_factory=list)
    ducts: list[HvacDuct] = Field(default_factory=list)

    def assignments(self):
        result: dict[str, list[str]] = {}
        for duct in self.ducts:
            result.setdefault(duct.entity_key, []).append(duct.id)
        for node in self.nodes:
            ids = [node.id]
            if node.boundary and node.boundary.kind == "VENT":
                ids.append("V_" + node.id)
            for key in node.entity_keys:
                result.setdefault(key, []).extend(ids)
        return result
