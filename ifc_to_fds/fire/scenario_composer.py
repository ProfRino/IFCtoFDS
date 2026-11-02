"""Compose fire events with the actual base closure instead of overlapping it."""

import math
import re
from ifc_to_fds.validation.parser import parse_fds
from .scenario_emitter import opening_control_key


def compose_scenario(base_text, bundle, manifest):
    base = parse_fds(base_text)
    domain = manifest.simulation_domain
    for ev in bundle.ev_selections:
        dimensions = ev.dimensions or ((4.5, 1.8, 1.5) if ev.preset_id.lower().startswith("auto-") else (1.8, 0.6, 1.1))
        for axis, name in enumerate(("x", "y", "z")):
            lo, hi = ev.position[axis] - dimensions[axis]/2, ev.position[axis] + dimensions[axis]/2
            if not math.isfinite(lo) or not math.isfinite(hi) or not domain or lo < domain[name + "min"] - 1e-8 or hi > domain[name + "max"] + 1e-8:
                raise ValueError("Vehicle must lie inside the verified simulation domain")
    records = {r.entity_key: r for r in manifest.records}
    controls = {}
    seen = set()
    for event in bundle.opening_events:
        if event.entity_key in seen:
            raise ValueError("Multiple events for one opening require an explicit control schedule")
        seen.add(event.entity_key)
        record = records.get(event.entity_key)
        if record is None or record.ifc_type.upper() not in ("IFCDOOR", "IFCWINDOW"):
            raise ValueError("Opening events require a mapped IFC door or window fill")
        originals = [r for r in base.records if r.id in record.fds_primitive_ids]
        if len(originals) != 1 or originals[0].kind != "OBST":
            raise ValueError("Dynamic opening currently requires one OBST fill; GEOM controls are not supported")
        if event.state not in ("OPEN", "CLOSED") or not math.isfinite(event.event_time_s) or event.event_time_s < 0:
            raise ValueError("Opening event requires OPEN/CLOSED and a finite nonnegative time")
        if originals[0].values.get("CTRL_ID") or originals[0].values.get("DEVC_ID"):
            raise ValueError("Base fill already has a control schedule")
        controls[originals[0].id] = "CTRL_" + opening_control_key(event.entity_key)

    def replace_record(match):
        parsed = parse_fds("&HEAD CHID='match' /\n&TIME T_END=0 /\n&MESH IJK=1,1,1, XB=0,1,0,1,0,1 /\n" + match.group() + "\n&TAIL /")
        record = next((r for r in parsed.records if r.kind == "OBST"), None)
        if record and record.id in controls:
            return match.group()[:-1].rstrip() + ", CTRL_ID='" + controls[record.id] + "' /"
        return match.group()

    # The supported base subset escapes quotes by doubling them.
    pattern = r"&OBST\b(?:'[^']*(?:''[^']*)*'|\"[^\"]*\"|[^/'\"])*?/"
    base_text = re.sub(pattern, replace_record, base_text, flags=re.I)
    # Attach the timer to the original fill, preserving its identity, geometry
    # and surface. Drop the emitter's standalone fallback closure.
    controlled_ids = set(controls.values())
    def drop_fallback(match):
        control = re.search(r"\bCTRL_ID\s*=\s*'([^']+)'", match.group(), re.I)
        return "" if control and control.group(1) in controlled_ids else match.group()
    fragment = re.sub(pattern, drop_fallback, bundle.fds_fragment, flags=re.I)
    if len(re.findall(r"&TAIL\s*/", base_text, re.I)) != 1:
        raise ValueError("Scenario base requires exactly one TAIL")
    text = re.sub(r"&TAIL\s*/", lambda _: fragment + "\n&TAIL /", base_text, flags=re.I)
    parsed = parse_fds(text)
    if parsed.errors or parsed.unsupported:
        raise ValueError(f"Composed scenario failed validation: {parsed.errors + parsed.unsupported}")
    return text
