"""Exercise the 2026-11-02 logic fixes and generate a reviewable HVAC example.

Run from the repository: .venv/Scripts/python scripts/audit-project-logic.py
Outputs use a new directory under scripts/out on every run. Observations are
diagnostics, not assertions that a generated FDS model is accepted by a solver.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.unit
import numpy as np

from ifc_to_fds.adapters.jobs.runner import WorkerRunner
from ifc_to_fds.pipeline import convert, prepare, save_artifacts
from ifc_to_fds.validation.parser import parse_fds


def make_connected_duct_fixture(path):
    """Real IFC4: wall, two rectangular ducts, four ports, one port connection."""
    f = ifcopenshell.api.project.create_file(version="IFC4")
    root = ifcopenshell.api.root.create_entity
    project = root(f, ifc_class="IfcProject", name="Logic review fixture")
    unit = ifcopenshell.api.unit.add_si_unit(f, unit_type="LENGTHUNIT")
    ifcopenshell.api.unit.assign_unit(f, units=[unit])
    context = ifcopenshell.api.context.add_context(f, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        f, context_type="Model", context_identifier="Body",
        target_view="MODEL_VIEW", parent=context,
    )
    storey = root(f, ifc_class="IfcBuildingStorey", name="Review floor")
    storey.Elevation = 0.0
    ifcopenshell.api.aggregate.assign_object(
        f, products=[storey], relating_object=project,
    )
    products = []
    for cls, name, x, y, z, length, height, thickness in (
        ("IfcWall", "Wall", 0, 0, 0, 8, 4, 0.2),
        ("IfcDuctSegment", "Duct A", 1, 1, 2, 3, 0.3, 0.4),
        ("IfcDuctSegment", "Duct B", 4, 1, 2, 3, 0.3, 0.4),
    ):
        item = root(f, ifc_class=cls, name=name)
        ifcopenshell.api.spatial.assign_container(
            f, products=[item], relating_structure=storey,
        )
        # Use a rectangle profile understood by both the legacy JS reader and
        # IfcOpenShell, so this fixture also exercises Quick Export's role policy.
        profile_origin = f.create_entity(
            "IfcCartesianPoint", Coordinates=(length / 2.0, thickness / 2.0),
        )
        profile = f.create_entity(
            "IfcRectangleProfileDef", ProfileType="AREA",
            Position=f.create_entity("IfcAxis2Placement2D", Location=profile_origin),
            XDim=float(length), YDim=float(thickness),
        )
        origin = f.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
        solid = f.create_entity(
            "IfcExtrudedAreaSolid", SweptArea=profile,
            Position=f.create_entity("IfcAxis2Placement3D", Location=origin),
            ExtrudedDirection=f.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0)),
            Depth=float(height),
        )
        rep = f.create_entity(
            "IfcShapeRepresentation", ContextOfItems=body,
            RepresentationIdentifier="Body", RepresentationType="SweptSolid", Items=[solid],
        )
        ifcopenshell.api.geometry.assign_representation(f, product=item, representation=rep)
        matrix = np.eye(4)
        matrix[:3, 3] = [x, y, z]
        ifcopenshell.api.geometry.edit_object_placement(f, product=item, matrix=matrix)
        products.append(item)
    system = root(f, ifc_class="IfcDistributionSystem", name="Supply air",
                  predefined_type="VENTILATION")
    f.create_entity("IfcRelAssignsToGroup", GlobalId=ifcopenshell.guid.new(),
                    RelatedObjects=products[1:], RelatingGroup=system)
    all_ports = []
    for owner in products[1:]:
        ports = []
        for x in (0.0, 3.0):
            port = root(f, ifc_class="IfcDistributionPort", name=f"Port {x}")
            port.FlowDirection = "SOURCEANDSINK"
            point = f.create_entity("IfcCartesianPoint", Coordinates=(x, 0.2, 0.15))
            placement = f.create_entity("IfcAxis2Placement3D", Location=point)
            port.ObjectPlacement = f.create_entity(
                "IfcLocalPlacement", PlacementRelTo=owner.ObjectPlacement,
                RelativePlacement=placement,
            )
            f.create_entity("IfcRelNests", GlobalId=ifcopenshell.guid.new(),
                            RelatingObject=owner, RelatedObjects=[port])
            ports.append(port)
        all_ports.append(ports)
    f.create_entity("IfcRelConnectsPorts", GlobalId=ifcopenshell.guid.new(),
                    RelatingPort=all_ports[0][1], RelatedPort=all_ports[1][0])
    f.write(str(path))


def reviewed_hvac():
    return dict(action="HVAC", policy_version="audit-2026-11-02",
                rationale="Exercise existing HVAC path", reviewer="synthetic audit",
                evidence="Generated IFC with explicit port relationship")


def gates(report):
    return {key: dict(status=g["status"], reason=g["reason"])
            for key, g in report["gates"].items()}


def hvac_observations(text):
    parsed = parse_fds(text)
    nodes = [r for r in parsed.records
             if r.kind == "HVAC" and r.values.get("TYPE_ID") == ["NODE"]]
    ducts = [r for r in parsed.records
             if r.kind == "HVAC" and r.values.get("TYPE_ID") == ["DUCT"]]
    adjacency = {n.id: set() for n in nodes}
    for duct in ducts:
        ids = duct.values.get("NODE_ID", [])
        if len(ids) == 2 and all(i in adjacency for i in ids):
            adjacency[ids[0]].add(ids[1])
            adjacency[ids[1]].add(ids[0])
    remaining, components = set(adjacency), 0
    while remaining:
        components += 1
        stack = [remaining.pop()]
        while stack:
            for key in adjacency[stack.pop()]:
                if key in remaining:
                    remaining.remove(key)
                    stack.append(key)
    return dict(
        parse_errors=parsed.errors, unsupported=parsed.unsupported,
        record_counts=dict(Counter(r.kind for r in parsed.records)),
        node_count=len(nodes), duct_count=len(ducts),
        connected_components=components,
        endpoint_nodes_without_boundary=[n.id for n in nodes
            if len(n.values.get("DUCT_ID", [])) == 1
            and not any(n.values.get(k) for k in ("VENT_ID", "AMBIENT", "GEOM"))],
        ducts=[r.values for r in ducts],
    )


def main():
    output = ROOT / "scripts/out" / ("logic-review-" + uuid.uuid4().hex[:12])
    output.mkdir(parents=True)
    fixture = output / "connected-ducts.ifc"
    make_connected_duct_fixture(fixture)
    configuration = {"simulation_domain": dict(xmin=0, xmax=10, ymin=0, ymax=5, zmin=0, zmax=5)}
    source = prepare([str(fixture)], configuration)
    ducts = [e for e in source.elements if e.ifc_type == "IfcDuctSegment"]
    decisions = {}
    for duct in ducts:
        decision = reviewed_hvac()
        decision["hvac"] = dict(area_m2=0.12, perimeter_m=1.4, endpoints={
            p.port_key: {"kind": "AMBIENT"} for p in duct.ports if p.world_position[0] in (1.0, 7.0)
        })
        decisions[duct.entity_key] = decision
    observations = {}
    for name, extra in (
        ("mapping", {"profile": "mapping"}),
        ("geometry-fidelity", {"profile": "geometry-fidelity"}),
        ("hvac", {"decisions": decisions}),
    ):
        config = {**configuration, **extra}
        result = convert([str(fixture)], config, output / name)
        save_artifacts(result, output / name / "model.fds")
        observations[name] = dict(status=result["status"], fds=hvac_observations(result["fds_text"]),
                                  gates=gates(result["report"]))
        (output / name / "input-configuration.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    try:
        convert([str(fixture)], {**configuration, "decisions": {e.entity_key: reviewed_hvac() for e in ducts}}, output / "unconfigured")
    except ValueError as exc:
        observations["unconfigured_hvac"] = {"blocked": True, "reason": str(exc)}
    directory = output / "scenario-without-base"
    directory.mkdir()
    (directory / "request.json").write_text(json.dumps(dict(mode="scenario", configuration=dict(
        bundle_sha256="a" * 64, ev_selections=[dict(preset_id="auto-nmc", position=[5, 2.5, 1])]
    ))), encoding="utf-8")
    exit_code = WorkerRunner.run(directory)
    observations["scenario_without_verified_base"] = dict(worker_exit_code=exit_code,
        scenario_written=(directory / "scenario.fds").exists(),
        reason=(directory / "error.txt").read_text(encoding="utf-8") if (directory / "error.txt").exists() else "")
    evidence = dict(reviewed_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                    working_tree_changes=True, generated_utc=datetime.now(timezone.utc).isoformat(),
                    output_directory=output.relative_to(ROOT).as_posix(), observations=observations)
    (output / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(output / "evidence.json")


if __name__ == "__main__":
    main()
