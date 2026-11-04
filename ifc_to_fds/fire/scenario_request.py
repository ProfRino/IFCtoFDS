"""Canonical scenario input for HTTP and previously queued worker requests."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from .scenario_emitter import DeviceSelection, EVSelection, OpeningEvent, _normalize_opening_events


_LEGACY_PREVIEW_FIELDS = {
    "ev_library_version", "total_peak_hrr_mw", "peak_hrr_mw", "peak_hrr_kw", "cell_size",
    "confidence", "vehicle_count", "spacing_m", "chemistry_mix", "door_state", "soc_percent",
    "ev_count", "opening_events", "fds_fragment", "disclaimer", "notes",
    "chemistry", "vehicle_class",
}
_LEGACY_VEHICLE_FIELDS = {"vehicle_class", "chemistry", "soc_percent", "confidence"}


class EnergyBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)

    scope: Literal["WHOLE_VEHICLE_FLEET"]
    battery_chemical_energy_mj: float = Field(ge=0, strict=True)
    other_vehicle_energy_mj: float = Field(ge=0, strict=True)
    source: str = Field(min_length=1)


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    schema_version: Literal[1] = 1
    scenario_id: str | None = None
    bundle_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    ev_selections: list[EVSelection] = Field(min_length=1)
    devices: list[DeviceSelection] = Field(default_factory=list)
    opening_states: list[OpeningEvent] = Field(default_factory=list)
    t_end_s: float | None = Field(default=None, ge=0, strict=True)
    energy_budget: EnergyBudget | None = None
    require_quantitative_hf: StrictBool = False

    @field_validator("require_quantitative_hf")
    @classmethod
    def reject_unsupported_hf(cls, requested):
        if requested:
            raise ValueError("Quantitative HF modeling is unsupported")
        return requested

    @model_validator(mode="before")
    @classmethod
    def convert_legacy_payload(cls, value: Any):
        if not isinstance(value, dict):
            return value
        merged = dict(value)
        nested = merged.pop("scenario_data", None)
        if nested is not None:
            if not isinstance(nested, dict):
                raise ValueError("scenario_data must be an object")
            for name, field_value in nested.items():
                if name in merged and merged[name] != field_value:
                    raise ValueError(f"Conflicting scenario field: {name}")
                merged[name] = field_value
        if "opening_states" not in merged and "opening_events" in merged:
            merged["opening_states"] = merged["opening_events"]
        # The browser's matrix contains preview metadata and a placeholder opening.
        # Actual events use opening_states and require a mapped IFC entity.
        for name in _LEGACY_PREVIEW_FIELDS:
            merged.pop(name, None)
        if isinstance(merged.get("ev_selections"), list):
            selections = []
            for selection in merged["ev_selections"]:
                if isinstance(selection, dict):
                    selection = {k: v for k, v in selection.items() if k not in _LEGACY_VEHICLE_FIELDS}
                    unknown = selection.keys() - EVSelection.model_fields.keys()
                    if unknown:
                        raise ValueError(f"Unknown vehicle field: {', '.join(sorted(unknown))}")
                selections.append(selection)
            merged["ev_selections"] = selections
        if "opening_states" in merged:
            merged["opening_states"] = _normalize_opening_events(merged["opening_states"])
        return merged
