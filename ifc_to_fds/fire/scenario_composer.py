"""Compose fire events with the actual base closure instead of overlapping it."""

import math
import re
from ifc_to_fds.validation.parser import parse_fds
from .scenario_emitter import opening_timer_id, opening_control_id


def configure_scenario_time(text, opening_events, requested_end_s=None):
    """Keep the verified base duration and include the full scenario schedule."""
    parsed = parse_fds(text)
    if parsed.errors or parsed.unsupported:
        raise ValueError(f"Cannot set scenario time: {parsed.errors + parsed.unsupported}")
    time_records = [r for r in parsed.records if r.kind == "TIME"]
    if len(time_records) != 1:
        raise ValueError("Scenario requires exactly one TIME namelist")
    time_record = time_records[0]

    def seconds(values, field):
        if len(values) != 1 or type(values[0]) not in (int, float) or not math.isfinite(values[0]):
            raise ValueError(f"{field} requires one finite number of seconds")
        return float(values[0])

    base_end = seconds(time_record.values.get("T_END", [0.0]), "TIME.T_END")
    requested_end = seconds([requested_end_s], "t_end_s") if requested_end_s is not None else 0.0
    if min(base_end, requested_end) < 0:
        raise ValueError("Scenario duration must be nonnegative")
    ramp_end = max(
        (seconds(r.values.get("T", []), "RAMP.T") for r in parsed.records if r.kind == "RAMP"),
        default=0.0,
    )
    event_end = max((event.event_time_s for event in opening_events), default=0.0)
    end = max(base_end, requested_end, ramp_end, event_end)
    time_span = time_record.text_span
    if time_span is None:
        raise ValueError("TIME record has no source position")
    start, stop = time_span
    orig_time = text[start:stop]
    other_params = [k for k in time_record.values if k != "T_END"]
    if other_params:
        if re.search(r"\bT_END\s*=\s*[\d.EedD+-]+", orig_time, re.I):
            new_time = re.sub(
                r"\bT_END\s*=\s*[\d.EedD+-]+", f"T_END={end!r}", orig_time, count=1, flags=re.I
            )
        else:
            slash = orig_time.rfind("/")
            prefix = orig_time[:slash].rstrip()
            c_idx = prefix.find("!")
            if c_idx != -1:
                prefix = prefix[:c_idx].rstrip()
            sep = ", " if prefix and not prefix.endswith(",") else " "
            new_time = f"{prefix}{sep}T_END={end!r} /"
        final_text = text[:start] + new_time + text[stop:]
    else:
        final_text = text[:start] + f"&TIME T_END={end!r} /" + text[stop:]
    final = parse_fds(final_text)
    if final.errors or final.unsupported:
        raise ValueError(f"Invalid final scenario: {final.errors + final.unsupported}")
    return final_text, end


def compose_scenario(base_text, bundle, manifest):
    base = parse_fds(base_text)
    domain = manifest.simulation_domain
    if not domain:
        meshes = [r.values["XB"] for r in base.records if r.kind == "MESH" and "XB" in r.values]
        if meshes:
            domain = {
                "xmin": min(xb[0] for xb in meshes),
                "xmax": max(xb[1] for xb in meshes),
                "ymin": min(xb[2] for xb in meshes),
                "ymax": max(xb[3] for xb in meshes),
                "zmin": min(xb[4] for xb in meshes),
                "zmax": max(xb[5] for xb in meshes),
            }
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
        timer_id = opening_timer_id(event.entity_key)
        ctrl_id = opening_control_id(event.entity_key)
        controls[originals[0].id] = (timer_id, ctrl_id)

    def replace_record(match):
        parsed = parse_fds("&HEAD CHID='match' /\n&TIME T_END=0 /\n&MESH IJK=1,1,1, XB=0,1,0,1,0,1 /\n" + match.group() + "\n&TAIL /")
        record = next((r for r in parsed.records if r.kind == "OBST"), None)
        if record and record.id in controls:
            _, ctrl_id = controls[record.id]
            body = match.group()[:-1].rstrip()
            c_idx = body.find("!")
            if c_idx != -1:
                body = body[:c_idx].rstrip()
            return body + f", CTRL_ID='{ctrl_id}' /"
        return match.group()

    # The supported base subset escapes quotes by doubling them.
    pattern = r"&OBST\b(?:'[^']*(?:''[^']*)*'|\"[^\"]*\"|[^/'\"])*?/"
    base_text = re.sub(pattern, replace_record, base_text, flags=re.I)
    # Attach the timer to the original fill, preserving its identity, geometry
    # and surface. Drop the emitter's standalone fallback closure.
    controlled_ctrl_ids = {ctrl_id for _, ctrl_id in controls.values()}
    def drop_fallback(match):
        control = re.search(r"\bCTRL_ID\s*=\s*'([^']+)'", match.group(), re.I)
        return "" if control and control.group(1) in controlled_ctrl_ids else match.group()
    fragment = re.sub(pattern, drop_fallback, bundle.fds_fragment, flags=re.I)

    parsed_base = parse_fds(base_text)
    tails = [r for r in parsed_base.records if r.kind == "TAIL"]
    if len(tails) != 1:
        raise ValueError("Scenario base requires exactly one TAIL")
    tail_span = tails[0].text_span
    if tail_span is None:
        raise ValueError("Scenario base TAIL has no source position")
    tail_start, _ = tail_span
    text = base_text[:tail_start] + fragment + "\n" + base_text[tail_start:]

    parsed = parse_fds(text)
    if parsed.errors or parsed.unsupported:
        raise ValueError(f"Composed scenario failed validation: {parsed.errors + parsed.unsupported}")
    meshes = [r.values["XB"] for r in parsed.records if r.kind == "MESH"]
    for fill_id, (timer_id, ctrl_id) in controls.items():
        timers = [r for r in parsed.records if r.kind == "DEVC" and r.id == timer_id]
        ctrls = [r for r in parsed.records if r.kind == "CTRL" and r.id == ctrl_id]
        fills = [r for r in parsed.records if r.kind == "OBST" and r.values.get("CTRL_ID") == [ctrl_id]]
        if len(timers) != 1 or len(ctrls) != 1 or len(fills) != 1 or fills[0].id != fill_id:
            raise ValueError(f"Opening timer must control exactly one original fill: {fill_id}")
        xyz = timers[0].values.get("XYZ", [])
        if len(xyz) != 3 or not any(
            all(xb[2 * axis] - 1e-6 <= value <= xb[2 * axis + 1] + 1e-6 for axis, value in enumerate(xyz))
            for xb in meshes
        ):
            raise ValueError(f"Opening timer lies outside the FDS meshes: {fill_id}")
    return text
