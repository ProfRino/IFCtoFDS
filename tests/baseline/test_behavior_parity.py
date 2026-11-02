"""Behavior parity harness.

Compares conversion and audit outputs against the frozen baseline snapshots (cases A-F).
Ensures semantic parity across refactoring stages without unexplained diffs:
  - Canonical inventory counts & types
  - Scope decisions
  - Boundary treatments
  - Mapping strategies & FDS primitive IDs
  - MEP graph systems & connections
  - Gate statuses
  - Verdicts (status, mapping_status, simulation_status)
"""

import json
import tempfile
from pathlib import Path

from ifc_to_fds.core.inventory import extract_inventory
from ifc_to_fds.geometry.engine import process_model_geometry
from ifc_to_fds.geometry.package import build_package
from ifc_to_fds.mapping.boundary import POLICY
from ifc_to_fds.mapping.exporter import serialize_fds
from ifc_to_fds.mapping.policy import plan_mapping
from ifc_to_fds.pipeline import convert, save_artifacts
from ifc_to_fds.validation.engine import run_independent_validation
from ifc_to_fds.validation.golden import create_candidate
from .generate_baseline import (
    FIXTURES_DIR,
    SNAPSHOT_DIR,
    build_semantic_snapshot,
    ensure_fixtures,
    assert_fixture_hash,
)


def assert_semantic_parity(actual: dict, expected: dict):
    assert actual["source_sha256"] == expected["source_sha256"]
    assert actual["status"] == expected["status"]
    assert actual["mapping_status"] == expected["mapping_status"]
    assert actual["simulation_status"] == expected["simulation_status"]
    assert actual["output_complete"] == expected["output_complete"]
    assert actual["elements_count"] == expected["elements_count"]
    assert actual["records_count"] == expected["records_count"]
    assert actual["mep_systems_count"] == expected["mep_systems_count"]
    assert actual["mep_connections_count"] == expected["mep_connections_count"]
    assert actual["fds_summary"] == expected["fds_summary"]
    # Preserve the frozen baseline, requiring the new completeness and air_path gates to pass
    # as well. These six baseline cases have no withheld structural solids or envelope leaks.
    expected_air_path = (
        "NOT_APPLICABLE" if actual["case_id"] == "case_d_mep" else "PASS"
    )
    assert actual["gates"] == {
        **expected["gates"],
        "structural_completeness": "PASS",
        "air_path": expected_air_path,
        # Additive gates: frozen fixtures contain no operational HVAC or fires.
        "hvac": "NOT_APPLICABLE",
        "mesh_resolution": "NOT_APPLICABLE",
    }
    assert actual["findings_count"] == expected["findings_count"]
    assert actual["geometry_package_sha256"] == expected["geometry_package_sha256"]
    assert actual["manifest_csv_sha256"] == expected["manifest_csv_sha256"]
    if "fds_primitives" in expected:
        assert actual["fds_primitives"] == expected["fds_primitives"]

    # Verify elements semantic equivalence
    for act_el, exp_el in zip(actual["elements"], expected["elements"]):
        assert act_el["ifc_type"] == exp_el["ifc_type"]
        assert act_el["name"] == exp_el["name"]
        assert act_el["storey"] == exp_el["storey"]
        assert act_el["scope_decision"] == exp_el["scope_decision"]
        assert act_el["mapping_strategy"] == exp_el["mapping_strategy"]
        assert act_el["simulation_role"] == exp_el["simulation_role"]
        assert act_el["operational_status"] == exp_el["operational_status"]
        assert act_el["fds_representation"] == exp_el["fds_representation"]
        assert act_el["review_status"] == exp_el["review_status"]
        assert act_el["boundary_treatment"] == exp_el["boundary_treatment"]
        assert act_el["boundary_policy"] == exp_el["boundary_policy"]
        assert act_el["has_3d_geometry"] == exp_el["has_3d_geometry"]
        assert act_el["openings_count"] == exp_el["openings_count"]
        assert act_el["ports_count"] == exp_el["ports_count"]
        assert act_el["system_names"] == exp_el["system_names"]
        assert act_el["fds_primitive_ids"] == exp_el["fds_primitive_ids"]

    # Verify manifest records semantic equivalence
    for act_r, exp_r in zip(actual["records"], expected["records"]):
        assert act_r["mapping_status"] == exp_r["mapping_status"]
        assert act_r["mapping_strategy"] == exp_r["mapping_strategy"]
        assert act_r["simulation_role"] == exp_r["simulation_role"]
        assert act_r["boundary_treatment"] == exp_r["boundary_treatment"]
        assert act_r["fds_primitive_ids"] == exp_r["fds_primitive_ids"]
        assert act_r["openings_count"] == exp_r["openings_count"]
        assert act_r["ports_count"] == exp_r["ports_count"]

    # Verify findings semantic equivalence
    for act_f, exp_f in zip(actual["findings"], expected["findings"]):
        assert act_f["category"] == exp_f["category"]
        assert act_f["severity"] == exp_f["severity"]
        assert act_f["element_id"] == exp_f["element_id"]
        assert act_f["title"] == exp_f["title"]


def test_parity_case_a_tiny():
    ensure_fixtures()
    expected = json.loads((SNAPSHOT_DIR / "case_a_tiny.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        p_a = str(FIXTURES_DIR / "tiny.ifc")
        assert_fixture_hash(p_a, expected)
        res_a = convert([p_a], output_directory=tmp)
        save_artifacts(res_a, tmp / "model.fds")
        actual = build_semantic_snapshot("case_a_tiny", res_a, tmp)
    assert_semantic_parity(actual, expected)


def test_parity_case_b_opening():
    ensure_fixtures()
    expected = json.loads((SNAPSHOT_DIR / "case_b_opening.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        p_b = str(FIXTURES_DIR / "opening.ifc")
        assert_fixture_hash(p_b, expected)
        res_b = convert([p_b], output_directory=tmp)
        save_artifacts(res_b, tmp / "model.fds")
        actual = build_semantic_snapshot("case_b_opening", res_b, tmp)
    assert_semantic_parity(actual, expected)


def test_parity_case_c_fzk():
    expected = json.loads((SNAPSHOT_DIR / "case_c_fzk_erdgeschoss.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        p_c = "examples/AC20-FZK-Haus.ifc"
        assert_fixture_hash(p_c, expected)
        res_c = convert([p_c], configuration={"scope": {"storeys": ["Erdgeschoss"]}}, output_directory=tmp)
        save_artifacts(res_c, tmp / "model.fds")
        actual = build_semantic_snapshot("case_c_fzk_erdgeschoss", res_c, tmp)
    assert_semantic_parity(actual, expected)


def test_parity_case_d_mep():
    ensure_fixtures()
    expected = json.loads((SNAPSHOT_DIR / "case_d_mep.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        p_d = str(FIXTURES_DIR / "mep.ifc")
        assert_fixture_hash(p_d, expected)
        res_d = convert([p_d], output_directory=tmp)
        save_artifacts(res_d, tmp / "model.fds")
        actual = build_semantic_snapshot("case_d_mep", res_d, tmp)
    assert_semantic_parity(actual, expected)


def test_parity_case_e_boundary():
    ensure_fixtures()
    expected = json.loads((SNAPSHOT_DIR / "case_e_boundary.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        p_e = str(FIXTURES_DIR / "tiny.ifc")
        assert_fixture_hash(p_e, expected)
        res_e = convert(
            [p_e],
            configuration={
                "simulation_domain": {"xmin": 0.4, "xmax": 4.0, "ymin": 0.0, "ymax": 4.0, "zmin": 0.0, "zmax": 4.0},
                "boundary_policy": POLICY,
            },
            output_directory=tmp,
        )
        save_artifacts(res_e, tmp / "model.fds")
        actual = build_semantic_snapshot("case_e_boundary", res_e, tmp)
    assert_semantic_parity(actual, expected)


def test_parity_case_f_golden():
    ensure_fixtures()
    expected = json.loads((SNAPSHOT_DIR / "case_f_golden.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        p_f = str(FIXTURES_DIR / "tiny.ifc")
        assert_fixture_hash(p_f, expected)
        candidate_dir = tmp / "golden_candidate"
        model_f, ifc_f = extract_inventory(p_f)
        model_f = process_model_geometry(model_f, ifc_f)
        plan_mapping(model_f)
        fds_f, manifest_f = serialize_fds(model_f)
        pkg_f = build_package(model_f)
        cfg_f = {"mep_graph": model_f.mep_graph.model_dump(mode="json")}
        rep_f = run_independent_validation(model_f, fds_f, manifest_f)
        create_candidate(candidate_dir, model_f, manifest_f, pkg_f, rep_f, cfg_f, fds_f)

        res_f = convert([p_f], configuration={"reference_case": str(candidate_dir)}, output_directory=tmp)
        save_artifacts(res_f, tmp / "model.fds")
        actual = build_semantic_snapshot("case_f_golden", res_f, tmp)
    assert_semantic_parity(actual, expected)
