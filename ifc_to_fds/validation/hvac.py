"""Semantic checks shared by the FDS reader and independent network checker."""

import math


def hvac_errors(parsed):
    errors = []
    nodes = {r.id: r for r in parsed.records if r.kind == "HVAC" and r.values.get("TYPE_ID") == ["NODE"]}
    ducts = {r.id: r for r in parsed.records if r.kind == "HVAC" and r.values.get("TYPE_ID") == ["DUCT"]}
    vents = {r.id: r for r in parsed.records if r.kind == "VENT"}

    def bad(record, reason):
        errors.append(f"HVAC {record.id}: {reason}")

    for duct in ducts.values():
        ns = duct.values.get("NODE_ID", [])
        if len(ns) != 2 or ns[0] == ns[1] or any(n not in nodes for n in ns):
            bad(duct, "DUCT requires two distinct existing NODE_ID references")
        else:
            for n in ns:
                if duct.id not in nodes[n].values.get("DUCT_ID", []):
                    bad(duct, "NODE/DUCT references are not reciprocal")
        for field in ("AREA", "DIAMETER", "LENGTH", "PERIMETER"):
            values = duct.values.get(field)
            if values is not None and (len(values) != 1 or isinstance(values[0], bool) or not isinstance(values[0], (int, float)) or not math.isfinite(values[0]) or values[0] <= 0):
                bad(duct, f"{field} must be a finite positive number")
        if not any(duct.values.get(k) for k in ("AREA", "DIAMETER")):
            bad(duct, "DUCT requires AREA or DIAMETER")
    assigned_vents = set()
    for node in nodes.values():
        ds = node.values.get("DUCT_ID", [])
        ambient = node.values.get("AMBIENT", [False]) == [True]
        vent = node.values.get("VENT_ID", [])
        geom = node.values.get("GEOM", [False]) == [True]
        for field, size in (("XYZ", 3), ("XYZ(3)", 1)):
            xyz = node.values.get(field)
            if xyz is not None and (len(xyz) != size or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in xyz)):
                bad(node, f"{field} requires {size} finite coordinates")
        if not ds or len(ds) > 10 or len(ds) != len(set(ds)) or any(d not in ducts for d in ds):
            bad(node, "NODE requires 1..10 distinct existing DUCT_ID references")
        for d in ds:
            if d in ducts and node.id not in ducts[d].values.get("NODE_ID", []):
                bad(node, "NODE/DUCT references are not reciprocal")
        if len(ds) == 1 and not (ambient or vent or geom):
            bad(node, "single-duct endpoint requires AMBIENT, VENT_ID or GEOM")
        if len(ds) > 1 and (ambient or vent or geom):
            bad(node, "internal node cannot be an endpoint")
        if sum((ambient, bool(vent), geom)) > 1:
            bad(node, "endpoint boundary types are mutually exclusive")
        if not vent and "XYZ" not in node.values and "XYZ(3)" not in node.values:
            bad(node, "ambient/internal node requires its elevation")
        if vent:
            if len(vent) != 1 or vent[0] not in vents or vents[vent[0]].values.get("SURF_ID") != ["HVAC"]:
                bad(node, "VENT_ID must identify one HVAC surface vent")
            elif vent[0] in assigned_vents:
                bad(node, "HVAC vent is assigned to multiple nodes")
            else:
                assigned_vents.add(vent[0])
    return errors
