"""FDS HVAC records adapter. The network compiler never formats namelists."""


def network_records(plan):
    records = []
    for node in plan.nodes:
        values = dict(TYPE_ID=["NODE"], ID=[node.id], DUCT_ID=node.duct_ids)
        if node.boundary:
            values["LOSS"] = list(node.boundary.loss)
            if node.boundary.kind == "VENT":
                vent_id = "V_" + node.id
                records.append(("VENT", dict(ID=[vent_id], XB=list(node.boundary.vent_xb), SURF_ID=["HVAC"]), node.entity_keys))
                values["VENT_ID"] = [vent_id]
            else:
                values.update(AMBIENT=[True], XYZ=list(node.xyz))
        else:
            values["XYZ"] = list(node.xyz)
        records.append(("HVAC", values, node.entity_keys))
    for duct in plan.ducts:
        spec = duct.spec
        values = dict(TYPE_ID=["DUCT"], ID=[duct.id], NODE_ID=list(duct.node_ids), LENGTH=[duct.length_m], ROUGHNESS=[spec.roughness_m])
        if spec.diameter_m is not None:
            values["DIAMETER"] = [spec.diameter_m]
        else:
            values.update(AREA=[spec.area_m2], PERIMETER=[spec.perimeter_m])
        if spec.volume_flow_m3_s is not None:
            values["VOLUME_FLOW"] = [spec.volume_flow_m3_s]
        records.append(("HVAC", values, [duct.entity_key]))
    return records


def render_network(plan, elements):
    import json
    by_key = {e.entity_key: e for e in elements}

    def value(v):
        if isinstance(v, bool):
            return ".TRUE." if v else ".FALSE."
        if isinstance(v, str):
            return "'" + v.replace("'", "''") + "'"
        return repr(float(v))

    lines = []
    for kind, values, keys in network_records(plan):
        if not keys or any(key not in by_key for key in keys):
            raise ValueError(f"HVAC {kind} record has missing source assignments: {values.get('ID')}")
        e = by_key[keys[0]]
        source = dict(entity_key=e.entity_key, entity_keys=keys, source_id=e.source_id,
                      global_id=e.global_id, step_id=e.step_id, ifc_type=e.ifc_type)
        lines.append("! IFC_SOURCE " + json.dumps(source))
        lines.append("&" + kind + " " + ", ".join(k + "=" + ",".join(value(v) for v in vs) for k, vs in values.items()) + " /")
    return lines
