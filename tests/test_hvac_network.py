"""Operational network regressions: real IFC topology, serialization and audit."""

import hashlib
import math
from pathlib import Path
import runpy
import pytest

from ifc_to_fds.domain.mapping import build_mapping_plan
from ifc_to_fds.domain.mep.hvac import DuctSpec
from ifc_to_fds.mapping.exporter import serialize_fds
from ifc_to_fds.mapping.policy import plan_mapping
from ifc_to_fds.pipeline import convert, prepare
from ifc_to_fds.validation.engine import run_independent_validation
from ifc_to_fds.validation.parser import parse_fds


@pytest.fixture
def connected_ifc(tmp_path):
    factory = runpy.run_path(str(Path(__file__).parents[1] / "scripts/audit-project-logic.py"))["make_connected_duct_fixture"]
    path = tmp_path / "ducts.ifc"
    factory(path)
    config = {"simulation_domain": dict(xmin=0, xmax=10, ymin=0, ymax=5, zmin=0, zmax=5)}
    source = prepare([str(path)], config)
    ducts = [e for e in source.elements if e.ifc_type == "IfcDuctSegment"]
    decisions = {}
    for duct in ducts:
        endpoints = {p.port_key: {"kind": "AMBIENT"} for p in duct.ports
                     if p.world_position[0] in (1.0, 7.0)}
        decisions[duct.entity_key] = dict(
            action="HVAC", policy_version="hvac-v1", reviewer="fixture",
            rationale="Confirmed ventilation and explicit port boundaries", evidence="IFC port relationships",
            hvac=dict(area_m2=0.12, perimeter_m=1.4, endpoints=endpoints),
        )
    return path, {**config, "decisions": decisions}


def test_connected_ifc_is_verified_as_one_operational_network(connected_ifc, tmp_path):
    path, config = connected_ifc
    result = convert([str(path)], config, tmp_path / "conversion")
    assert result["status"] == "MAPPING_VERIFIED", result["report"]["findings"]
    assert result["report"]["gates"]["hvac"]["status"] == "PASS"
    parsed = parse_fds(result["fds_text"])
    assert not parsed.errors and not parsed.unsupported
    nodes = [r for r in parsed.operational_records if r.values.get("TYPE_ID") == ["NODE"]]
    ducts = [r for r in parsed.operational_records if r.values.get("TYPE_ID") == ["DUCT"]]
    assert len(nodes) == 3 and len(ducts) == 2
    assert sum(len(n.values["DUCT_ID"]) == 2 for n in nodes) == 1
    assert all(d.values["AREA"] == [0.12] and d.values["LENGTH"] == [3.0] for d in ducts)
    mep = [e for e in result["inventory"]["elements"] if e["ifc_type"] == "IfcDuctSegment"]
    assert all(e["fds_representation"] == "HVAC" for e in mep)
    coverage = result["report"]["coverage"]["mep_systems"]["VENTILATION"]
    assert coverage["operational_configured"] == coverage["operational_verified"] == 2
    assert coverage["fds_obstacles"] == 0


def test_network_parameters_are_audited_after_fds_hash_is_updated(connected_ifc):
    path, config = connected_ifc
    model = prepare([str(path)], config)
    text, manifest = serialize_fds(model)
    changed = text.replace("AREA=0.12", "AREA=0.24", 1)
    assert changed != text
    manifest.fds_sha256 = hashlib.sha256(changed.encode()).hexdigest()
    manifest.reseal()
    report = run_independent_validation(model, changed, manifest)
    assert report.gates["hvac"].status == "FAIL"


def test_plan_cannot_change_operational_parameters(connected_ifc):
    path, config = connected_ifc
    model = prepare([str(path)], config)
    plan = build_mapping_plan(model)
    plan.hvac_network.ducts[0].length_m = 99
    with pytest.raises(ValueError, match="HVAC network differs"):
        serialize_fds(model, mapping_plan=plan)


def test_missing_endpoint_never_defaults_to_ambient(connected_ifc):
    path, config = connected_ifc
    for decision in config["decisions"].values():
        decision["hvac"]["endpoints"] = {}
    with pytest.raises(ValueError, match="Unconfigured HVAC endpoint"):
        prepare([str(path)], config)


def test_round_diagonal_duct_uses_port_chord_and_diameter(connected_ifc):
    path, config = connected_ifc
    model = prepare([str(path)], config)
    # Rigidly rotate all ports 45 degrees without changing source AABBs:
    # network hydraulics must be independent of the world-space box.
    for e in model.elements:
        for p in e.ports:
            x, y, z = p.world_position
            p.world_position = [(x-y)/math.sqrt(2), (x+y)/math.sqrt(2), z]
    for d in config["decisions"].values():
        d["hvac"].pop("area_m2")
        d["hvac"].pop("perimeter_m")
        d["hvac"]["diameter_m"] = 0.2
    plan_mapping(model, decisions=config["decisions"])
    text, _ = serialize_fds(model)
    ds = [r for r in parse_fds(text).operational_records if r.values.get("TYPE_ID") == ["DUCT"]]
    assert all(d.values["DIAMETER"] == [0.2] for d in ds)
    assert all(d.values["LENGTH"][0] == pytest.approx(3.0) for d in ds)
    assert all("AREA" not in d.values for d in ds)


@pytest.mark.parametrize("spec", [{}, {"diameter_m": 0}, {"area_m2": 1},
                                  {"diameter_m": float("inf")}, {"diameter_m": .2, "area_m2": 1}])
def test_incomplete_or_inconsistent_parameters_are_rejected(spec):
    with pytest.raises(ValueError):
        DuctSpec.model_validate(spec)


def scaffold(fragment):
    return "&HEAD CHID='hvac' /\n&TIME T_END=0 /\n&MESH IJK=10,10,10, XB=0,1,0,1,0,1 /\n" + fragment + "\n&TAIL /"


def test_parser_namespaces_and_ambient_boundaries():
    text = scaffold("""&HVAC ID='D', TYPE_ID='NODE', DUCT_ID='D', XYZ=0,0,0, AMBIENT=.TRUE. /
&HVAC ID='B', TYPE_ID='NODE', DUCT_ID='D', XYZ=1,0,0, AMBIENT=.TRUE. /
&HVAC ID='D', TYPE_ID='DUCT', NODE_ID='D','B', DIAMETER=.2, LENGTH=1 /""")
    parsed = parse_fds(text)
    assert not parsed.errors and not parsed.unsupported


def test_parser_rejects_broken_network():
    parsed = parse_fds(scaffold("&HVAC TYPE_ID='DUCT', ID='D', NODE_ID='missing1','missing2', AREA=0, LENGTH=-1 /"))
    assert any("NODE_ID" in e for e in parsed.errors)
    assert any("AREA" in e for e in parsed.errors)


def test_water_pipe_cannot_be_promoted_to_air_network(connected_ifc):
    path, config = connected_ifc
    model = prepare([str(path)], config)
    duct = next(e for e in model.elements if e.ifc_type == "IfcDuctSegment")
    duct.ifc_type, duct.mep_category = "IfcPipeSegment", "FIRE_SUPPRESSION"
    with pytest.raises(ValueError, match="ventilation duct segment"):
        plan_mapping(model, decisions=config["decisions"])


def test_hvac_outside_cfd_domain_is_not_clipped_as_a_solid(connected_ifc):
    path, config = connected_ifc
    model = prepare([str(path)], config)
    from ifc_to_fds.domain.bim import BoundingBox
    from ifc_to_fds.domain.scope import ScopeDecision
    model.simulation_domain = BoundingBox(xmin=0,xmax=2,ymin=0,ymax=2,zmin=0,zmax=2)
    for e in model.elements:
        if e.ifc_type == "IfcWall":
            e.scope_decision = ScopeDecision.OUT_OF_SCOPE
    plan_mapping(model, decisions=config["decisions"])
    text, manifest = serialize_fds(model)
    assert all(e.boundary_treatment == "NOT_APPLICABLE" for e in model.elements if e.simulation_role == "HVAC")
    assert not parse_fds(text).errors
    assert run_independent_validation(model,text,manifest).gates['boundary'].status == 'PASS'


@pytest.mark.solver
@pytest.mark.parametrize("vent_endpoint", [False, True])
def test_real_fds_accepts_connected_network(connected_ifc, tmp_path, vent_endpoint):
    import os
    from ifc_to_fds.domain.validation import AuditConfig
    from ifc_to_fds.domain.scope import ScopeDecision
    from ifc_to_fds.validation.solver import solver_gates
    executable = os.environ.get("IFCFDS_SOLVER")
    if not executable:
        pytest.skip("Pinned FDS not configured")
    path, config = connected_ifc
    model = prepare([str(path)], config)
    if vent_endpoint:
        model.simulation_domain.xmin = 1
        for e in model.elements:
            if e.ifc_type == "IfcWall":
                e.scope_decision = ScopeDecision.OUT_OF_SCOPE
        for decision in config["decisions"].values():
            for port, endpoint in decision["hvac"]["endpoints"].items():
                original = next(p for e in model.elements for p in e.ports if p.port_key == port)
                if original.world_position[0] == 1:
                    endpoint.update(kind="VENT", vent_xb=[1,1,1,1.4,2,2.3])
    plan_mapping(model, decisions=config["decisions"])
    text, _ = serialize_fds(model)
    gate, _ = solver_gates(text, AuditConfig(solver_executable=executable,
                          solver_evidence_directory=str(tmp_path / "solver")))
    assert gate.status == "PASS", gate.model_dump()
