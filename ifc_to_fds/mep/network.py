"""Compile explicit IFC port topology and reviewed SI parameters into HVAC intent."""

import hashlib
import math
from ifc_to_fds.domain.mep.hvac import DuctSpec, HvacDuct, HvacNetworkPlan, HvacNode
from ifc_to_fds.domain.mapping.enums import MappingStrategy
from ifc_to_fds.domain.scope import ScopeDecision

PORT_POSITION_TOLERANCE_M = 0.001


def build_hvac_network(model):
    selected = [e for e in model.elements if e.mapping_strategy == MappingStrategy.HVAC
                and e.scope_decision in (ScopeDecision.IN_SCOPE, ScopeDecision.BOUNDARY_RETAINED)]
    if not selected:
        return HvacNetworkPlan()
    ports, owners, specs = {}, {}, {}
    for e in selected:
        declared_type = (e.type_class or e.ifc_type).upper().removesuffix("TYPE")
        if declared_type not in ("IFCDUCTSEGMENT", "IFCFLOWSEGMENT") or e.mep_category not in ("VENTILATION", "SMOKE_EXTRACT"):
            raise ValueError(f"HVAC requires a ventilation duct segment; fittings/fans need a dedicated operational adapter: {e.entity_key}")
        if e.decision.get("action") != "HVAC" or not e.decision.get("hvac"):
            raise ValueError(f"HVAC requires reviewed duct parameters and endpoint boundaries: {e.entity_key}")
        specs[e.entity_key] = DuctSpec.model_validate(e.decision["hvac"])
        if len(e.ports) != 2:
            raise ValueError(f"HVAC duct requires exactly two source ports: {e.entity_key}")
        for p in e.ports:
            if not p.port_key or p.port_key in ports or p.world_position is None or len(p.world_position) != 3 or not all(math.isfinite(x) for x in p.world_position):
                raise ValueError(f"HVAC requires unique source port keys and finite world positions: {e.entity_key}")
            ports[p.port_key], owners[p.port_key] = p, e.entity_key
        if set(specs[e.entity_key].endpoints) - {p.port_key for p in e.ports}:
            raise ValueError(f"Unknown endpoint port in HVAC configuration: {e.entity_key}")
    parent = {key: key for key in ports}

    def find(key):
        while key != parent[key]:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for edge in model.mep_graph.connections:
        a, b = edge.source_port_id, edge.target_port_id
        if a in ports and b in ports:
            if edge.relation_type != "EXPLICIT_IFC":
                raise ValueError("HVAC topology requires explicit IFC port relationships")
            if math.dist(ports[a].world_position, ports[b].world_position) > PORT_POSITION_TOLERANCE_M:
                raise ValueError("Connected HVAC ports disagree in world position")
            parent[find(b)] = find(a)
    groups = {}
    for key in sorted(ports):
        groups.setdefault(find(key), []).append(key)
    nodes, port_node = [], {}
    duct_ids = {e.entity_key: "D_" + hashlib.sha256(e.entity_key.encode()).hexdigest()[:20] for e in selected}
    for keys in groups.values():
        node_id = "N_" + hashlib.sha256("|".join(keys).encode()).hexdigest()[:20]
        boundaries = [specs[owners[k]].endpoints[k] for k in keys if k in specs[owners[k]].endpoints]
        attached = sorted({duct_ids[owners[k]] for k in keys})
        if len(attached) == 1 and len(keys) > 1:
            raise ValueError("HVAC duct cannot connect to itself")
        if len(attached) == 1 and len(boundaries) != 1:
            raise ValueError(f"Unconfigured HVAC endpoint (including scope cuts): {keys}")
        if len(attached) > 1 and boundaries:
            raise ValueError("Internal HVAC junction cannot be AMBIENT or VENT")
        if len(attached) > 10:
            raise ValueError("FDS HVAC nodes support at most ten ducts")
        node = HvacNode(id=node_id, port_keys=keys, entity_keys=sorted({owners[k] for k in keys}),
                        xyz=ports[keys[0]].world_position, duct_ids=attached,
                        boundary=boundaries[0] if boundaries else None)
        if node.boundary and node.boundary.kind == "VENT":
            xb = node.boundary.vent_xb
            domain = model.simulation_domain
            if domain is None or any(xb[i] < domain.to_xb()[i] - 1e-8 if i % 2 == 0 else xb[i] > domain.to_xb()[i] + 1e-8 for i in range(6)):
                raise ValueError("HVAC CFD vent must lie within the declared simulation domain")
            if any(node.xyz[i] < xb[2*i] - 0.001 or node.xyz[i] > xb[2*i+1] + 0.001 for i in range(3)):
                raise ValueError("HVAC source endpoint must lie on its CFD vent")
            axis = next(i for i in range(3) if xb[2*i] == xb[2*i+1])
            def on_face(bounds):
                box = bounds.to_xb()
                return (any(abs(xb[2*axis] - box[j]) < 1e-8 for j in (2*axis, 2*axis+1))
                        and all(box[2*i] <= xb[2*i] + 1e-8 and box[2*i+1] >= xb[2*i+1] - 1e-8 for i in range(3) if i != axis))
            if not on_face(domain) and not any(e.mapping_strategy == MappingStrategy.OBST and e.bounding_box and on_face(e.representation_bounds or e.bounding_box) for e in model.elements):
                raise ValueError("HVAC vent must lie on a supported OBST or mesh boundary face; GEOM vent coupling is not yet supported")
        nodes.append(node)
        for key in keys:
            port_node[key] = node_id
    ducts = []
    for e in selected:
        spec = specs[e.entity_key]
        distance = math.dist(*(p.world_position for p in e.ports))
        length = spec.length_m if spec.length_m is not None else distance
        if length <= 0 or length + 0.001 < distance:
            raise ValueError("HVAC length must be positive and cannot be shorter than the port chord")
        ordered_ports = e.ports
        if len(e.ports) == 2:
            def port_flow_order(p):
                direction = (getattr(p, "flow_direction", None) or "").upper()
                return 0 if direction == "SINK" else 1 if direction == "SOURCE" else 0.5
            ordered_ports = sorted(e.ports, key=port_flow_order)
        ducts.append(HvacDuct(id=duct_ids[e.entity_key], entity_key=e.entity_key,
                              node_ids=tuple(port_node[p.port_key] for p in ordered_ports), length_m=length, spec=spec))
    return HvacNetworkPlan(nodes=sorted(nodes, key=lambda n: n.id), ducts=sorted(ducts, key=lambda d: d.id))
