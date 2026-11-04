"""EV fire scenario emitter: generates standard FDS 6+ fire scenarios.

Consumes verified mapping plans and EV preset physics to produce self-contained
FDS scenario bundles with &REAC, &RAMP, &SURF, &OBST, &VENT, &DEVC, &CTRL namelists.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ifc_to_fds.domain.mapping import MappingPlan
from ifc_to_fds.fire.ev_library import EV_LIBRARY_VERSION, EVPreset, load_ev_preset


def clean_fds_id(name: str, fallback: str = "ID") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name or "")
    cleaned = cleaned.strip("._-")
    if not cleaned:
        cleaned = fallback
    return cleaned[:30]


def opening_control_key(entity_key: str) -> str:
    key = clean_fds_id(entity_key)[:20].rstrip("._-")
    if len(entity_key) > 20:
        key = key[:7] + "_" + hashlib.sha256(entity_key.encode()).hexdigest()[:12]
    return key


def format_xb(xb: List[float] | Tuple[float, ...]) -> str:
    return ",".join(
        str(int(v)) if float(v).is_integer() else f"{float(v):.4f}".rstrip("0").rstrip(".")
        for v in xb
    )


class EVSelection(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    preset_id: str
    position: Tuple[float, float, float]
    ignition_delay_s: float = Field(default=0.0, ge=0)
    dimensions: Optional[Tuple[float, float, float]] = None
    pack_kwh: Optional[float] = None
    peak_hrr_mw: Optional[float] = None

    @field_validator("dimensions")
    @classmethod
    def validate_dimensions(
        cls, v: Optional[Tuple[float, float, float]]
    ) -> Optional[Tuple[float, float, float]]:
        if v is not None:
            if len(v) != 3 or any(d <= 0.0 or not math.isfinite(d) for d in v):
                raise ValueError("EV dimensions (dx, dy, dz) must be strictly positive (> 0.0)")
        return v


VALID_FDS_DEVICE_QUANTITIES = {
    "TEMPERATURE",
    "VELOCITY",
    "U-VELOCITY",
    "V-VELOCITY",
    "W-VELOCITY",
    "VISIBILITY",
    "OPTICAL DENSITY",
    "VOLUME FRACTION",
    "MASS FRACTION",
    "MASS LOSS RATE",
    "HEAT FLUX",
    "GAUGE HEAT FLUX",
    "RADIATIVE HEAT FLUX",
    "CONVECTIVE HEAT FLUX",
    "TOTAL HEAT FLUX",
    "TIME",
    "WALL TEMPERATURE",
    "PRESSURE",
    "DENSITY",
    "HRR",
    "MLR",
    "SPRINKLER LINK TEMPERATURE",
    "CHAMBER OBSCURATION",
    "EXTINCTION COEFFICIENT",
}


def escape_fds_string(val: Any) -> str:
    """Sanitize string for FDS namelists to prevent injection.
    Disallows quotes, slashes, newlines, and ampersands.
    """
    s = str(val)
    if any(char in s for char in ("'", '"', '/', '\n', '\r', '&')):
        raise ValueError(f"FDS string parameter contains disallowed characters: {val!r}")
    return s.strip()


class DeviceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    id: str
    device_type: str
    position: Tuple[float, float, float]
    setpoint: float
    quantity: str

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return escape_fds_string(v)

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: str) -> str:
        clean = escape_fds_string(v).upper()
        if clean not in VALID_FDS_DEVICE_QUANTITIES:
            raise ValueError(
                f"Invalid FDS device quantity: {v!r}. "
                f"Must be one of: {sorted(VALID_FDS_DEVICE_QUANTITIES)}"
            )
        return clean


class OpeningEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_key: str = Field(min_length=1)
    state: Literal["OPEN", "CLOSED"]
    event_time_s: float = Field(ge=0, allow_inf_nan=False)


def opening_timer_id(entity_key: str) -> str:
    return f"DEVC_{opening_control_key(entity_key)}_TIME"


def opening_control_id(entity_key: str) -> str:
    return f"CTRL_{opening_control_key(entity_key)}"


class ScenarioBundle(BaseModel):
    scenario_id: str
    bundle_sha256: str
    ev_library_version: str
    ev_library_digest: Optional[str] = None
    fds_fragment: str
    total_peak_hrr_mw: float
    ev_count: int
    ev_selections: List[EVSelection] = Field(default_factory=list)
    devices: List[DeviceSelection] = Field(default_factory=list)
    opening_events: List[OpeningEvent] = Field(default_factory=list)
    hf_preset_yields: dict[str, tuple[float, float]] = Field(default_factory=dict)


def _resolve_preset(preset_id: str) -> EVPreset:
    if "-" in preset_id:
        vclass, chem = preset_id.rsplit("-", 1)
        return load_ev_preset(vclass, chem)
    raise ValueError(
        f"Invalid preset_id format: {preset_id!r}, expected 'vehicle_class-chemistry'"
    )


def _normalize_opening_events(opening_states: Any) -> List[OpeningEvent]:
    if not opening_states:
        return []
    events: List[OpeningEvent] = []
    if isinstance(opening_states, list):
        for item in opening_states:
            if isinstance(item, OpeningEvent):
                events.append(item)
            elif isinstance(item, dict):
                events.append(OpeningEvent.model_validate(item))
            else:
                raise ValueError("Opening events must be objects")
        return events
    if isinstance(opening_states, dict):
        for key, val in opening_states.items():
            if isinstance(val, OpeningEvent):
                events.append(val)
            elif isinstance(val, dict):
                state = str(val.get("state", "CLOSED")).upper()
                raw_time = val.get("event_time_s", val.get("eventTime", 0.0))
                event_time = float(raw_time if raw_time is not None else 0.0)
                entity_key = str(val.get("entity_key", key))
                events.append(OpeningEvent(entity_key=entity_key, state=state, event_time_s=event_time))
            elif isinstance(val, str):
                state = val.strip().upper()
                events.append(OpeningEvent(entity_key=key, state=state, event_time_s=0.0))
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, OpeningEvent):
                        events.append(item)
                    elif isinstance(item, dict):
                        events.append(OpeningEvent.model_validate(item))
                    else:
                        raise ValueError("Opening events must be objects")
            else:
                raise ValueError(f"Invalid opening event for {key}")
        return events
    raise ValueError("Opening states must be a list or an object")


def emit_fire_scenario(
    mapping_plan: MappingPlan,
    bundle_sha256: str,
    ev_selections: List[EVSelection],
    opening_states: Optional[Union[Dict[str, Any], List[Any]]] = None,
    devices: Optional[List[DeviceSelection]] = None,
    verification_status: str = "MAPPING_VERIFIED",
    allow_multi_reac: bool = False,
) -> ScenarioBundle:
    """Emits an FDS fire scenario bundle adhering to strict verification invariants."""
    if (
        verification_status != "MAPPING_VERIFIED"
        or not bundle_sha256
        or str(bundle_sha256).strip().lower() == "stale"
    ):
        raise ValueError("MAPPING_VERIFIED required to emit fire scenario")

    if not ev_selections:
        raise ValueError("At least one EV selection is required")

    normalized_evs = [
        ev if isinstance(ev, EVSelection) else EVSelection.model_validate(ev)
        for ev in ev_selections
    ]
    normalized_devices = [
        d if isinstance(d, DeviceSelection) else DeviceSelection.model_validate(d)
        for d in (devices or [])
    ]
    normalized_opening_events = _normalize_opening_events(opening_states)
    opening_bounds = {}
    for event in normalized_opening_events:
        if event.entity_key in opening_bounds:
            raise ValueError("Multiple events for one opening require an explicit control schedule")
        decision = mapping_plan.get_decision(event.entity_key)
        bounds = (decision.representation_bounds or decision.element_bounds) if decision else None
        if bounds is None:
            raise ValueError(f"Opening event has no mapped bounds: {event.entity_key}")
        if decision.fds_representation != "OBST":
            raise ValueError(f"Dynamic opening requires one OBST fill: {event.entity_key}")
        xb = bounds.to_xb()
        if any(not math.isfinite(v) for v in xb) or any(xb[i] >= xb[i + 1] for i in (0, 2, 4)):
            raise ValueError(f"Invalid opening bounds: {event.entity_key}")
        opening_bounds[event.entity_key] = xb

    resolved_presets: Dict[str, EVPreset] = {}
    ev_configs: List[Dict[str, Any]] = []
    total_peak_hrr_mw = 0.0

    for ev in normalized_evs:
        preset_key = ev.preset_id.strip().lower()
        if preset_key not in resolved_presets:
            resolved_presets[preset_key] = _resolve_preset(ev.preset_id)
        preset = resolved_presets[preset_key]

        # Validate pack_kwh
        if ev.pack_kwh is not None:
            min_kwh, max_kwh = preset.pack_kwh_range
            if not (min_kwh <= ev.pack_kwh <= max_kwh):
                raise ValueError(
                    f"Custom pack_kwh {ev.pack_kwh} out of preset range {preset.pack_kwh_range}"
                )
            actual_kwh = ev.pack_kwh
        else:
            actual_kwh = (preset.pack_kwh_range[0] + preset.pack_kwh_range[1]) / 2.0

        # Validate peak_hrr_mw
        if ev.peak_hrr_mw is not None:
            min_hrr, max_hrr = preset.peak_hrr_mw_range
            if not (min_hrr <= ev.peak_hrr_mw <= max_hrr):
                raise ValueError(
                    f"Custom peak_hrr_mw {ev.peak_hrr_mw} out of preset range {preset.peak_hrr_mw_range}"
                )
            actual_peak_hrr = ev.peak_hrr_mw
        else:
            actual_peak_hrr = (preset.peak_hrr_mw_range[0] + preset.peak_hrr_mw_range[1]) / 2.0

        # Resolve dimensions
        if ev.dimensions is not None:
            dx, dy, dz = ev.dimensions
        else:
            if "auto" in ev.preset_id.lower() or preset.vehicle_class.lower() == "auto":
                dx, dy, dz = (4.5, 1.8, 1.5)
            else:
                dx, dy, dz = (1.8, 0.6, 1.1)

        total_peak_hrr_mw += actual_peak_hrr
        ev_configs.append(
            {
                "ev": ev,
                "preset": preset,
                "preset_key": preset_key,
                "actual_kwh": actual_kwh,
                "actual_peak_hrr": actual_peak_hrr,
                "dx": dx,
                "dy": dy,
                "dz": dz,
            }
        )

    # Collision detection between placed vehicles (Item 44)
    placed_boxes: List[Tuple[float, float, float, float, float, float]] = []
    for cfg in ev_configs:
        e_pos = cfg["ev"].position
        e_dx, e_dy, e_dz = cfg["dx"], cfg["dy"], cfg["dz"]
        e_box = (
            round(e_pos[0] - e_dx / 2.0, 4),
            round(e_pos[0] + e_dx / 2.0, 4),
            round(e_pos[1] - e_dy / 2.0, 4),
            round(e_pos[1] + e_dy / 2.0, 4),
            round(e_pos[2] - e_dz / 2.0, 4),
            round(e_pos[2] + e_dz / 2.0, 4),
        )
        for prev in placed_boxes:
            if (
                max(e_box[0], prev[0]) < min(e_box[1], prev[1]) - 1e-4
                and max(e_box[2], prev[2]) < min(e_box[3], prev[3]) - 1e-4
                and max(e_box[4], prev[4]) < min(e_box[5], prev[5]) - 1e-4
            ):
                raise ValueError(
                    f"Vehicle collision detected: vehicle at {e_pos} intersects another vehicle bounding box"
                )
        placed_boxes.append(e_box)

    lines: List[str] = [
        "! ==========================================================================",
        "! EV Fire Scenario Fragment (Generated by IFCtoFDS Task 3 Scenario Emitter)",
        f"! Base Mapping Bundle SHA256: {bundle_sha256}",
        f"! EV Library Version: {EV_LIBRARY_VERSION}",
        f"! Total Peak HRR: {total_peak_hrr_mw:.4f} MW",
        "! ==========================================================================",
        "",
    ]

    # 1. &REAC namelists
    lines.append("! --- Combustion Reaction & Species Namelists ---")
    preset_fuel_ids: Dict[str, str] = {}
    if allow_multi_reac:
        lines.append("! Multi-REAC mode: one reaction per preset")
        for preset_key, preset in resolved_presets.items():
            reac_id = clean_fds_id(f"REAC_{preset.preset_id.upper()}")
            fuel_id = clean_fds_id(f"OFFGAS_{reac_id}")
            preset_fuel_ids[preset_key] = fuel_id
            co_yield = (preset.yields.co[0] + preset.yields.co[1]) / 2.0
            soot_yield = (preset.yields.soot[0] + preset.yields.soot[1]) / 2.0
            lines.append(
                f"&REAC ID='{reac_id}', FUEL='{fuel_id}', C=2.0, H=4.0, O=1.0, "
                f"CO_YIELD={co_yield:g}, SOOT_YIELD={soot_yield:g} /"
            )
        lines.append("")
    else:
        lines.append("! Simple chemistry in FDS permits exactly one &REAC namelist.")
        lines.append("! Multi-vehicle mixes are blended into an effective composite reaction.")
        total_hrr = sum(cfg["actual_peak_hrr"] for cfg in ev_configs) or 1.0
        weighted_co = sum(
            cfg["actual_peak_hrr"] * ((cfg["preset"].yields.co[0] + cfg["preset"].yields.co[1]) / 2.0)
            for cfg in ev_configs
        ) / total_hrr
        weighted_soot = sum(
            cfg["actual_peak_hrr"] * ((cfg["preset"].yields.soot[0] + cfg["preset"].yields.soot[1]) / 2.0)
            for cfg in ev_configs
        ) / total_hrr

        composite_reac_id = "REAC_COMPOSITE_EV" if len(resolved_presets) > 1 else clean_fds_id(f"REAC_{list(resolved_presets.values())[0].preset_id.upper()}")
        composite_fuel_id = clean_fds_id(f"OFFGAS_{composite_reac_id}")
        for preset_key in resolved_presets:
            preset_fuel_ids[preset_key] = composite_fuel_id

        lines.append(
            f"&REAC ID='{composite_reac_id}', FUEL='{composite_fuel_id}', C=2.0, H=4.0, O=1.0, "
            f"CO_YIELD={weighted_co:.4f}, SOOT_YIELD={weighted_soot:.4f} /"
        )
        lines.append("")

    # 2. EV Fire Sources: RAMP, SURF, OBST, VENT
    lines.append("! --- EV Physical Obstacles and Fire Sources ---")
    for idx, cfg in enumerate(ev_configs, start=1):
        ev: EVSelection = cfg["ev"]
        preset: EVPreset = cfg["preset"]
        actual_peak_hrr: float = cfg["actual_peak_hrr"]
        actual_kwh: float = cfg["actual_kwh"]
        dx, dy, dz = cfg["dx"], cfg["dy"], cfg["dz"]

        cx, cy, cz = ev.position
        xmin = round(cx - dx / 2.0, 4)
        xmax = round(cx + dx / 2.0, 4)
        ymin = round(cy - dy / 2.0, 4)
        ymax = round(cy + dy / 2.0, 4)
        zmin = round(cz - dz / 2.0, 4)
        zmax = round(cz + dz / 2.0, 4)

        burning_area = dx * dy
        hrrpua_kw_m2 = (actual_peak_hrr * 1000.0) / burning_area

        ramp_id = clean_fds_id(f"RAMP_EV_{idx}")
        surf_id = clean_fds_id(f"BURNER_EV_{idx}")
        obst_id = clean_fds_id(f"OBST_EV_{idx}")
        vent_id = clean_fds_id(f"VENT_BURNER_{idx}")

        # Standard T-squared RAMP calculation: Q(t) = 1055 * (t / t_alpha)^2 (kW)
        # At peak: Q_peak = 1055 * (t_growth / t_alpha)^2 => t_growth = t_alpha * sqrt(Q_peak / 1055)
        t_delay = round(ev.ignition_delay_s, 2)
        t_alpha = (preset.t_alpha_s[0] + preset.t_alpha_s[1]) / 2.0
        q_peak_kw = actual_peak_hrr * 1000.0
        t_growth = max(1.0, t_alpha * math.sqrt(max(0.001, q_peak_kw / 1055.0)))
        t_plateau = max(1.0, t_growth / 2.0)
        t_decay = max(1.0, t_growth)

        # Energy balance (MJ)
        integral_factor_s = (1.0 / 3.0) * t_growth + t_plateau + 0.5 * t_decay
        e_total_mj = (q_peak_kw * integral_factor_s) / 1000.0
        battery_mj = actual_kwh * 3.6

        lines.append(f"! Fire Curve: {ramp_id} (delay={t_delay:.2f}s, growth={t_growth:.2f}s via standard t^2 Q=1055*(t/t_alpha)^2)")
        lines.append(f"! Energy balance: total fire curve energy = {e_total_mj:.1f} MJ, nominal battery pack = {battery_mj:.1f} MJ")
        if t_delay > 0:
            lines.append(f"&RAMP ID='{ramp_id}', T=0.00, F=0.0 /")
            lines.append(f"&RAMP ID='{ramp_id}', T={t_delay:.2f}, F=0.0 /")
        else:
            lines.append(f"&RAMP ID='{ramp_id}', T=0.00, F=0.0 /")

        prev_t = round(t_delay, 2) if t_delay > 0 else 0.0
        num_ramp_points = 20
        for i in range(1, num_ramp_points + 1):
            frac = i / float(num_ramp_points)
            t_curr = round(t_delay + frac * t_growth, 2)
            if t_curr <= prev_t:
                t_curr = round(prev_t + 0.01, 2)
            prev_t = t_curr
            f_curr = frac * frac
            lines.append(f"&RAMP ID='{ramp_id}', T={t_curr:.2f}, F={f_curr:.4f} /")

        # Plateau
        t_plateau_end = round(max(prev_t + 0.01, t_delay + t_growth + t_plateau), 2)
        lines.append(f"&RAMP ID='{ramp_id}', T={t_plateau_end:.2f}, F=1.0000 /")
        prev_t = t_plateau_end

        # Decay
        t_decay_mid = round(max(prev_t + 0.01, t_plateau_end + 0.5 * t_decay), 2)
        lines.append(f"&RAMP ID='{ramp_id}', T={t_decay_mid:.2f}, F=0.5000 /")
        prev_t = t_decay_mid
        t_decay_end = round(max(prev_t + 0.01, t_plateau_end + t_decay), 2)
        lines.append(f"&RAMP ID='{ramp_id}', T={t_decay_end:.2f}, F=0.0000 /")

        # &SURF
        fuel_id = preset_fuel_ids[cfg["preset_key"]]
        lines.append(
            f"&SURF ID='{surf_id}', HRRPUA={hrrpua_kw_m2:.2f}, RAMP_Q='{ramp_id}', FUEL_ID='{fuel_id}' /"
        )

        # &OBST
        obst_xb = [xmin, xmax, ymin, ymax, zmin, zmax]
        lines.append(
            f"&OBST ID='{obst_id}', XB={format_xb(obst_xb)}, SURF_ID='INERT' /"
        )

        # &VENT (top surface of obstacle)
        vent_xb = [xmin, xmax, ymin, ymax, zmax, zmax]
        lines.append(
            f"&VENT ID='{vent_id}', XB={format_xb(vent_xb)}, SURF_ID='{surf_id}' /"
        )
        lines.append("")

    # 3. &DEVC for detection & suppression devices
    if normalized_devices:
        lines.append("! --- Fire Safety Devices ---")
        for dev in normalized_devices:
            dev_id = clean_fds_id(dev.id)
            lines.append(
                f"&DEVC ID='{dev_id}', QUANTITY='{dev.quantity}', "
                f"XYZ={format_xb(dev.position)}, SETPOINT={dev.setpoint} /"
            )
        lines.append("")

    # 4. &DEVC and &CTRL for door/opening events
    if normalized_opening_events:
        lines.append("! --- Opening & Boundary Controls ---")
        for ev_open in normalized_opening_events:
            timer_devc_id = opening_timer_id(ev_open.entity_key)
            ctrl_id = opening_control_id(ev_open.entity_key)
            xb = opening_bounds[ev_open.entity_key]
            xyz = ",".join(repr(xb[i] + (xb[i + 1] - xb[i]) / 2) for i in (0, 2, 4))
            # FDS 6.11.1: OBST is removed when control evaluates to .FALSE.
            # OPEN: door starts closed (.TRUE.), opens (.FALSE.) when timer activates.
            # CLOSED: door starts open (.FALSE.), closes (.TRUE.) when timer activates.
            initial = ".TRUE." if ev_open.state == "OPEN" else ".FALSE."
            lines.append(
                f"&DEVC ID='{timer_devc_id}', XYZ={xyz}, QUANTITY='TIME', "
                f"SETPOINT={ev_open.event_time_s!r} /"
            )
            lines.append(
                f"&CTRL ID='{ctrl_id}', FUNCTION_TYPE='ANY', INPUT_ID='{timer_devc_id}', "
                f"INITIAL_STATE={initial} /"
            )
            lines.append(
                f"&OBST XB={format_xb(xb)}, SURF_ID='INERT', CTRL_ID='{ctrl_id}' /"
            )
            lines.append("")

    fds_fragment = "\n".join(lines)

    # Validate emitted fragment syntax against FDS parser grammar
    from ifc_to_fds.validation.parser import parse_fds
    scaffold = f"&HEAD CHID='TEST' /\n&TIME T_END=1.0 /\n&MESH IJK=1,1,1, XB=0,1,0,1,0,1 /\n{fds_fragment}\n&TAIL /\n"
    parsed_check = parse_fds(scaffold)
    if parsed_check.errors:
        raise ValueError(f"FDS syntax error in emitted scenario fragment: {parsed_check.errors}")

    # Deterministic scenario ID based on full scenario fragment
    scenario_hash = hashlib.sha256(fds_fragment.encode("utf-8")).hexdigest()[:12]
    scenario_id = f"ev_scenario_{scenario_hash}"

    # Compute EV library content digest for reproducibility (M-14)
    lib_digest = None
    try:
        from ifc_to_fds.fire.ev_library import library_digest
        lib_digest = library_digest()
    except Exception:
        pass

    return ScenarioBundle(
        scenario_id=scenario_id,
        bundle_sha256=bundle_sha256,
        ev_library_version=EV_LIBRARY_VERSION,
        ev_library_digest=lib_digest,
        hf_preset_yields={key: preset.yields.hf for key, preset in resolved_presets.items()},
        fds_fragment=fds_fragment,
        total_peak_hrr_mw=round(total_peak_hrr_mw, 6),
        ev_count=len(normalized_evs),
        ev_selections=normalized_evs,
        devices=normalized_devices,
        opening_events=normalized_opening_events,
    )
