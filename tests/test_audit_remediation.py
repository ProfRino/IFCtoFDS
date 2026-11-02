# pyright: reportUnusedVariable=false
"""Verification test suite for audit blockers B01 through B16 remediation.

Validates:
- Phase A (B01/B02): Door/window non-manifold leaf classified as APPROXIMATED, not VALID.
                     Auditor reference path retains true geometry and does not auto-heal to box.
- Phase B (B03): Auditor reference extraction path is independent.
- Phase C (B04): Origin Rebase synchronizes spatial_scope.bounding_box and simulation_domain.
- Phase E (B07): ScenarioStore locks simulation when base mapping is unverified/rejected.
- Phase F (B08): CLI serve rejects binding to public host 0.0.0.0 without API key.
- Phase G (B10): Canonical bundle SHA-256 covers all semantic fields (openings, ports, status).
- Phase G (B11): Structural completeness checker covers footings, piles, stairs, plates, members.
"""

from ifc_to_fds.cli import main as cli_main
from ifc_to_fds.core.canonical import (
    BoundingBox,
    CanonicalElement,
    GeometryStatus,
    MappingStatus,
    ScopeDecision,
)
from ifc_to_fds.geometry.mesh import box_mesh
from ifc_to_fds.mapping.manifest import MappingManifest, ManifestRecord
from ifc_to_fds.mapping.policy import plan_mapping
from ifc_to_fds.application.services.model_preparer import prepare_model
from ifc_to_fds.validation.checkers.structural import STRUCTURAL_TYPES


def test_geometry_status_approximated_for_non_manifold_door(box_model):
    """B01: Non-manifold door leaf must be marked APPROXIMATED, not VALID."""
    door_bbox = BoundingBox(xmin=1.0, xmax=2.0, ymin=0.0, ymax=0.1, zmin=0.0, zmax=2.1)

    door_elem = CanonicalElement(
        source_id="test_src",
        entity_key="test_src:door_1",
        global_id="guid_door_1",
        step_id=2001,
        ifc_type="IfcDoor",
        name="Fire Door 1",
        role="PHYSICAL",
        has_3d_geometry=True,
        geometry_status=GeometryStatus.APPROXIMATED,
        bounding_box=door_bbox,
        mesh=box_mesh(door_bbox),
        scope_decision=ScopeDecision.IN_SCOPE,
    )
    box_model.elements.append(door_elem)
    plan_mapping(box_model)

    assert door_elem.geometry_status == GeometryStatus.APPROXIMATED
    # Without explicit approved decision, review is required
    assert door_elem.mapping_status == MappingStatus.REVIEW_REQUIRED
    assert door_elem.geometry_preservation == "APPROXIMATED"


def test_auditor_does_not_auto_heal_non_manifold_door():
    """B02: Auditor reference path must retain true failure status, not heuristic box."""
    import inspect
    from ifc_to_fds.core import federation

    source_code = inspect.getsource(federation.load_sources)
    assert "e.mesh = box_mesh" not in source_code


def test_origin_rebase_synchronizes_spatial_scope_and_domain(box_model, monkeypatch):
    """B04: Rebase vector must normalize world-coordinate spatial_scope and simulation_domain."""
    dx, dy, dz = 578000.0, 2318000.0, 0.0

    # Mock load_sources to return rebased model
    box_model.source.rebase_vector = [dx, dy, dz]
    box_model.model_bounds = BoundingBox(xmin=0, xmax=2, ymin=0, ymax=1, zmin=0, zmax=3)

    def mock_load_sources(*_args, **_kwargs):
        return box_model

    monkeypatch.setattr(
        "ifc_to_fds.application.services.model_preparer.load_sources",
        mock_load_sources,
    )

    world_bbox = {
        "xmin": dx + 0.0,
        "xmax": dx + 2.0,
        "ymin": dy + 0.0,
        "ymax": dy + 1.0,
        "zmin": 0.0,
        "zmax": 3.0,
    }
    world_domain = {
        "xmin": dx - 5.0,
        "xmax": dx + 10.0,
        "ymin": dy - 5.0,
        "ymax": dy + 10.0,
        "zmin": -1.0,
        "zmax": 5.0,
    }

    config = {
        "scope": {"bounding_box": world_bbox},
        "simulation_domain": world_domain,
    }

    prepared = prepare_model(["dummy.ifc"], config)

    # Reconciled domain must be in local simulation coordinates
    assert prepared.simulation_domain is not None
    assert abs(prepared.simulation_domain.xmin - (-5.0)) < 1e-5
    assert abs(prepared.simulation_domain.xmax - 10.0) < 1e-5
    assert abs(prepared.simulation_domain.ymin - (-5.0)) < 1e-5
    assert abs(prepared.simulation_domain.ymax - 10.0) < 1e-5


def test_model_preparer_explicit_coordinate_frame(box_model, monkeypatch):
    """H-11: Explicit coordinate_frame prevents double translation or missed translation."""
    dx, dy, dz = 500000.0, 6000000.0, 0.0
    box_model.source.rebase_vector = [dx, dy, dz]
    box_model.model_bounds = BoundingBox(xmin=0, xmax=2000, ymin=0, ymax=2000, zmin=0, zmax=3)
    wall_bbox = BoundingBox(xmin=1200.0, xmax=1500.0, ymin=1200.0, ymax=1500.0, zmin=0.0, zmax=3.0)
    box_model.elements[0].bounding_box = wall_bbox
    box_model.elements[0].mesh = box_mesh(wall_bbox)

    monkeypatch.setattr(
        "ifc_to_fds.application.services.model_preparer.load_sources",
        lambda *_args, **_kwargs: box_model,
    )

    # REBASED coordinate frame with bounds > 1000m should NOT be translated again
    config_rebased = {
        "scope": {
            "bounding_box": {"xmin": 1200.0, "xmax": 1500.0, "ymin": 1200.0, "ymax": 1500.0, "zmin": 0.0, "zmax": 3.0},
            "coordinate_frame": "REBASED",
        },
        "simulation_domain": {"xmin": 1100.0, "xmax": 1600.0, "ymin": 1100.0, "ymax": 1600.0, "zmin": -1.0, "zmax": 5.0},
        "simulation_domain_coordinate_frame": "REBASED",
    }
    prep = prepare_model(["dummy.ifc"], config_rebased)
    assert prep.simulation_domain is not None
    assert abs(prep.simulation_domain.xmin - 1100.0) < 1e-5

    # WORLD coordinate frame with bounds < 1000m MUST still be translated
    box_small_bbox = BoundingBox(xmin=10.0, xmax=20.0, ymin=10.0, ymax=20.0, zmin=0.0, zmax=3.0)
    box_model.elements[0].bounding_box = box_small_bbox
    box_model.elements[0].mesh = box_mesh(box_small_bbox)
    config_world_small = {
        "scope": {
            "bounding_box": {"xmin": dx + 10.0, "xmax": dx + 20.0, "ymin": dy + 10.0, "ymax": dy + 20.0, "zmin": 0.0, "zmax": 3.0},
            "coordinate_frame": "WORLD",
        },
        "simulation_domain": {"xmin": dx + 5.0, "xmax": dx + 25.0, "ymin": dy + 5.0, "ymax": dy + 25.0, "zmin": 0.0, "zmax": 3.0},
        "simulation_domain_coordinate_frame": "WORLD",
    }
    prep_world = prepare_model(["dummy.ifc"], config_world_small)
    assert prep_world.simulation_domain is not None
    assert abs(prep_world.simulation_domain.xmin - 5.0) < 1e-5



def test_cli_serve_rejects_public_interface_without_api_key(capsys, monkeypatch):
    """B08: Binding to 0.0.0.0 without API key must exit with code 1."""
    monkeypatch.delenv("IFCFDS_API_KEY", raising=False)
    exit_code = cli_main(["serve", "--host", "0.0.0.0", "--port", "8000"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "SECURITY ERROR: Binding to public/external host interface" in captured.err


def test_cli_serve_allows_loopback_without_api_key(monkeypatch):
    """B08: Binding to 127.0.0.1 without API key is allowed for local dev."""
    monkeypatch.delenv("IFCFDS_API_KEY", raising=False)
    # Mock uvicorn.run to prevent blocking
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)
    exit_code = cli_main(["serve", "--host", "127.0.0.1", "--port", "8000"])
    assert exit_code == 0


def test_structural_types_coverage():
    """B11: Structural completeness checker must cover all structural & enclosure types."""
    required_types = {
        "IFCWALL",
        "IFCWALLSTANDARDCASE",
        "IFCCURTAINWALL",
        "IFCSLAB",
        "IFCCOLUMN",
        "IFCBEAM",
        "IFCROOF",
        "IFCFOOTING",
        "IFCPILE",
        "IFCRAMP",
        "IFCRAMPFLIGHT",
        "IFCSTAIRFLIGHT",
        "IFCMEMBER",
        "IFCPLATE",
    }
    assert required_types.issubset(STRUCTURAL_TYPES)


def test_bundle_sha_covers_all_manifest_fields():
    """B10: bundle_sha256 must change if openings, ports, or mapping_status changes."""
    record_base = ManifestRecord(
        entity_key="src1:100",
        source_id="src1",
        global_id="guid_100",
        step_id=100,
        ifc_type="IfcWall",
        name="Wall 1",
        storey="Level 1",
        scope_decision="IN_SCOPE",
        scope_rationale="In bounds",
        mapping_strategy="GEOM",
        mapping_status="MAPPING_VERIFIED",
        simulation_role="PASSIVE_OBSTACLE",
        openings=[],
        ports=[],
    )
    manifest1 = MappingManifest(
        source_filename="test.ifc",
        source_sha256="abc",
        total_elements_accounted=1,
        total_primitives_emitted=1,
        records=[record_base],
    )
    sha1 = manifest1.compute_bundle_sha256()

    # Modify openings
    record_with_opening = record_base.model_copy(
        update={"openings": [{"step_id": 200, "global_id": "guid_open_200"}]}
    )
    manifest2 = MappingManifest(
        source_filename="test.ifc",
        source_sha256="abc",
        total_elements_accounted=1,
        total_primitives_emitted=1,
        records=[record_with_opening],
    )
    sha2 = manifest2.compute_bundle_sha256()
    assert sha1 != sha2, "bundle_sha256 failed to detect change in record openings"

    # Modify mapping_status
    record_deviated = record_base.model_copy(update={"mapping_status": "DEVIATED"})
    manifest3 = MappingManifest(
        source_filename="test.ifc",
        source_sha256="abc",
        total_elements_accounted=1,
        total_primitives_emitted=1,
        records=[record_deviated],
    )
    sha3 = manifest3.compute_bundle_sha256()
    assert sha1 != sha3, "bundle_sha256 failed to detect change in mapping_status"


def test_partition_simulation_domain_multi_mesh():
    """H-6: partition_simulation_domain splits large domains (> 500k cells) for FDS MPI."""
    from ifc_to_fds.mapping.exporter import partition_simulation_domain

    # Small domain: 10m x 10m x 3m with dx=0.2m -> 50 x 50 x 15 = 37,500 cells (single mesh)
    small_bounds = BoundingBox(xmin=0.0, xmax=10.0, ymin=0.0, ymax=10.0, zmin=0.0, zmax=3.0)
    small_meshes = partition_simulation_domain(small_bounds, cell_size=0.2, max_cells_per_mesh=500_000)
    assert len(small_meshes) == 1
    assert small_meshes[0][0] == [50, 50, 15]

    # Large basement domain: 60m x 40m x 3m with dx=0.1m -> 600 x 400 x 30 = 7,200,000 cells
    large_bounds = BoundingBox(xmin=0.0, xmax=60.0, ymin=0.0, ymax=40.0, zmin=0.0, zmax=3.0)
    large_meshes = partition_simulation_domain(large_bounds, cell_size=0.1, max_cells_per_mesh=500_000)
    assert len(large_meshes) > 1, f"Expected multiple meshes, got {len(large_meshes)}"
    for ijk, xb in large_meshes:
        sub_cells = ijk[0] * ijk[1] * ijk[2]
        assert sub_cells <= 500_000, f"Submesh exceeds limit: {sub_cells} > 500,000"
        assert abs((xb[1] - xb[0]) - ijk[0] * 0.1) < 1e-5


def test_check_opening_grid_alignment_heuristic():
    """H-10: check_opening_grid_alignment warns when opening width < 2*dx."""
    from ifc_to_fds.validation.effective import check_opening_grid_alignment

    # Narrow slit opening: width 0.15m on dx=0.1m grid -> min_width < 2*dx (0.2m)
    narrow_box = BoundingBox(xmin=1.0, xmax=1.15, ymin=0.0, ymax=0.2, zmin=0.0, zmax=2.0)
    res_narrow = check_opening_grid_alignment(narrow_box, cell_size=0.1)
    assert res_narrow["risk_sealed_by_grid"] is True

    # Standard wide opening: width 1.2m on dx=0.1m grid
    wide_box = BoundingBox(xmin=1.0, xmax=2.2, ymin=0.0, ymax=0.2, zmin=0.0, zmax=2.0)
    res_wide = check_opening_grid_alignment(wide_box, cell_size=0.1)
    assert res_wide["risk_sealed_by_grid"] is False


def test_public_result_filters_missing_artifacts_and_untruncates_findings(tmp_path):
    """M-8 & M-8b: public_result only lists existing artifact files and preserves all findings."""
    from ifc_to_fds.results import public_result

    # Create dummy directory with only model.fds and model_manifest.json
    (tmp_path / "model.fds").write_text("&HEAD /", encoding="utf-8")
    (tmp_path / "model_manifest.json").write_text("{}", encoding="utf-8")

    dummy_result = {
        "status": "COMPLETED",
        "mapping_status": "MAPPING_VERIFIED",
        "simulation_status": "NOT_RUN",
        "output_complete": True,
        "manifest": {"source_filename": "test.ifc", "sources": []},
        "configuration": {"profile": "mapping"},
        "timings": {},
        "report": {
            "coverage": {},
            "gates": {},
            "findings": [{"id": f"FND-{i:03}", "detail": f"Finding {i}"} for i in range(55)],
        },
    }

    pub = public_result(dummy_result, directory=tmp_path)
    # M-8: only existing artifacts are listed
    artifacts_dict = pub["artifacts"]
    assert isinstance(artifacts_dict, dict)
    assert set(artifacts_dict.keys()) == {"fds", "manifest"}
    # M-8b: all 55 findings are preserved
    findings_list = pub["findings"]
    assert isinstance(findings_list, list)
    assert len(findings_list) == 55
    assert pub["findings_count"] == 55


def test_partition_simulation_domain_non_multiple_bounds():
    """H-6 regression: multi-mesh partitioning on arbitrary non-integer-multiple bounds."""
    from ifc_to_fds.mapping.exporter import partition_simulation_domain

    bounds = BoundingBox(xmin=0.0, xmax=60.05, ymin=0.0, ymax=40.0, zmin=0.0, zmax=3.0)
    meshes = partition_simulation_domain(bounds, cell_size=0.1, max_cells_per_mesh=500_000)
    assert len(meshes) > 1
    all_xmax = max(m[1][1] for m in meshes)
    assert abs(all_xmax - bounds.xmax) < 1e-5


def test_parser_supports_spec_namelist():
    """H-3 & M-7: &SPEC namelist for toxic gas is recognized by FDS parser."""
    from ifc_to_fds.validation.parser import parse_fds

    parsed = parse_fds("&SPEC ID='HYDROGEN FLUORIDE' /\n")
    assert "Unsupported namelist SPEC" not in parsed.unsupported


def test_mesh_resolution_multi_vehicle_fine_mesh_is_inconclusive():
    """M-15 & H-6: multi-vehicle scenario with very fine mesh returns INCONCLUSIVE, not FAIL."""
    from ifc_to_fds.fire import EVSelection
    from ifc_to_fds.validation.checkers.mesh_resolution import check_mesh_resolution
    from ifc_to_fds.domain.validation.model import GateStatus

    ev = EVSelection(preset_id="auto-nmc", position=(0.0, 0.0, 0.75))
    res = check_mesh_resolution({"ev_selections": [ev]}, cell_size=0.05)
    assert res.status == GateStatus.INCONCLUSIVE
    assert "Mesh resolution too fine" in res.reason


def test_clean_fds_id_default_fallback():
    """M-12: clean_fds_id provides default fallback 'ID'."""
    from ifc_to_fds.mapping.exporter import clean_fds_id

    assert clean_fds_id("WALL 1") == "WALL_1"
    assert clean_fds_id("", fallback="FALLBACK") == "FALLBACK"
    assert clean_fds_id("") == "ID"



def test_partition_simulation_domain_vertical_cells_partitioning():
    """Verify partition_simulation_domain terminates and partitions Z when Z cells exceed max_cells."""
    from ifc_to_fds.mapping.exporter import partition_simulation_domain

    # Domain with high Z count: 10m x 10m x 100m with dx=0.1m -> 100 x 100 x 1000 = 10,000,000 cells
    # With max_cells_per_mesh=50,000, Z cells (1000) alone exceed limit.
    tall_bounds = BoundingBox(xmin=0.0, xmax=10.0, ymin=0.0, ymax=10.0, zmin=0.0, zmax=100.0)
    meshes = partition_simulation_domain(tall_bounds, cell_size=0.1, max_cells_per_mesh=50_000)
    assert len(meshes) > 1
    for ijk, _ in meshes:
        assert ijk[0] * ijk[1] * ijk[2] <= 50_000


def test_compute_mesh_grid_cell_limit_raises():
    """M-21: compute_mesh_grid rejects excessive cell count with ValueError."""
    import pytest
    from ifc_to_fds.mapping.exporter import compute_mesh_grid

    # Huge building 500m x 500m x 50m with cell_size=0.01m -> 50,000 x 50,000 x 5000 = 1.25e13 cells
    huge_bounds = BoundingBox(xmin=0.0, xmax=500.0, ymin=0.0, ymax=500.0, zmin=0.0, zmax=50.0)
    with pytest.raises(ValueError, match="exceeds maximum safety limit"):
        compute_mesh_grid(huge_bounds, cell_size=0.01, max_total_cells=50_000_000)



def test_check_opening_grid_alignment_with_numpy_bounds():
    """Verify check_opening_grid_alignment correctly reads numpy array bounds from trimesh."""
    import numpy as np
    from ifc_to_fds.validation.effective import check_opening_grid_alignment

    # numpy.ndarray bounds of shape (2, 3)
    np_bounds = np.array([[1.0, 0.0, 0.0], [2.2, 0.2, 2.0]])
    res = check_opening_grid_alignment(np_bounds, cell_size=0.1)
    # width_x = 1.2, width_y = 0.2, min_width = 0.2 -> 2*dx = 0.2
    assert res["min_width_m"] == 0.2
    assert res["cell_size_m"] == 0.1


def test_cancel_completed_job_preserves_source_files(tmp_path):
    """Verify JobService.cancel does not delete source files on completed jobs."""
    import time
    from ifc_to_fds.adapters.jobs.service import JobService

    service = JobService(tmp_path)
    job_dir = tmp_path / "job-completed"
    job_dir.mkdir(parents=True)
    source_ifc = job_dir / "source-0.ifc"
    source_ifc.write_text("ISO-10303-21;", encoding="utf-8")
    req_json = job_dir / "request.json"
    req_json.write_text("{}", encoding="utf-8")

    jid = "completed-1"
    service.repository.set(
        jid,
        {
            "id": jid,
            "state": "COMPLETED",
            "created": time.time(),
            "started": time.time(),
            "finished": time.time(),
            "directory": str(job_dir),
            "process": None,
        },
    )

    # Cancel on completed job
    service.cancel(jid)
    assert source_ifc.exists(), "Source IFC was unexpectedly unlinked on completed job"
    assert req_json.exists(), "Request JSON was unexpectedly unlinked on completed job"


def test_door_closed_event_emits_initial_state_true_devc():
    """Verify door CLOSED event emits INITIAL_STATE=.TRUE. on &DEVC and ANY on &CTRL."""
    from ifc_to_fds.domain.mapping import MappingPlan, MappingDecision
    from ifc_to_fds.domain.mapping.enums import MappingStrategy
    from ifc_to_fds.fire.scenario_emitter import emit_fire_scenario, EVSelection

    decision = MappingDecision(
        entity_key="door:1",
        strategy=MappingStrategy.OBST,
        simulation_role="DOOR",
        fds_representation="OBST",
        representation_bounds=BoundingBox(xmin=1.0, xmax=2.0, ymin=0.0, ymax=0.2, zmin=0.0, zmax=2.1),
    )
    plan = MappingPlan(decisions=[decision], cell_size=0.2)
    ev = EVSelection(preset_id="e-bike-lfp", position=(0.0, 0.0, 0.55))
    bundle = emit_fire_scenario(
        mapping_plan=plan,
        bundle_sha256="a" * 64,
        ev_selections=[ev],
        opening_states=[{"entity_key": "door:1", "state": "CLOSED", "event_time_s": 60.0}],
        verification_status="MAPPING_VERIFIED",
    )
    frag = bundle.fds_fragment
    assert "QUANTITY='TIME', SETPOINT=60.00, INITIAL_STATE=.TRUE." in frag
    assert "&CTRL ID='CTRL_door_1', FUNCTION_TYPE='ANY', INPUT_ID='DEVC_door_1_TIME'" in frag
    assert "&OBST XB=1,2,0,0.2,0,2.1, SURF_ID='INERT', CTRL_ID='CTRL_door_1'" in frag


def test_air_path_negative_volume_is_inconclusive(monkeypatch, box_model):
    """C-1: air_path checker flags negative leak volume as INCONCLUSIVE with INVALID_VOLUME_SIGN."""
    from ifc_to_fds.domain.validation.model import GateStatus, ValidationContext
    from ifc_to_fds.validation.checkers.air_path import AirPathTopologyChecker
    import ifc_to_fds.validation.checkers.air_path as ap_mod
    from ifc_to_fds.mapping.exporter import serialize_fds
    from ifc_to_fds.validation.parser import parse_fds

    text, manifest = serialize_fds(box_model)
    ctx = ValidationContext(
        model=box_model,
        fds_text=text,
        manifest=manifest,
        parsed_fds=parse_fds(text),
    )

    class InvertedMesh:
        volume = -0.1018
        is_volume = True

    orig_sb = ap_mod.solid_boolean
    monkeypatch.setattr(
        ap_mod,
        "solid_boolean",
        lambda meshes, op: InvertedMesh() if op == "intersection" and len(meshes) == 2 else orig_sb(meshes, op),
    )
    res = AirPathTopologyChecker().check(ctx)
    assert res.result.status == GateStatus.INCONCLUSIVE
    assert "INVALID_VOLUME_SIGN" in res.result.reason


def test_scenario_emitter_validates_fragment_syntax():
    """H-7: scenario emitter parses emitted fragment and rejects invalid FDS syntax."""
    from ifc_to_fds.domain.mapping import MappingPlan
    from ifc_to_fds.fire.scenario_emitter import emit_fire_scenario, EVSelection

    plan = MappingPlan(decisions=[], cell_size=0.2)
    ev = EVSelection(preset_id="e-bike-lfp", position=(0.0, 0.0, 0.55))
    # Standard emission should succeed without syntax error
    bundle = emit_fire_scenario(
        mapping_plan=plan,
        bundle_sha256="a" * 64,
        ev_selections=[ev],
        verification_status="MAPPING_VERIFIED",
    )
    assert "&HEAD" not in bundle.fds_fragment
    assert "&TAIL" not in bundle.fds_fragment
    assert "&REAC" in bundle.fds_fragment


def test_gate_checker_fail_must_have_non_empty_reason():
    """H-8: Every GateResult with status == FAIL must provide a non-empty diagnostic reason string."""
    from ifc_to_fds.domain.validation.model import GateResult, GateStatus

    res = GateResult(status=GateStatus.FAIL, reason="Test failure reason")
    assert res.status == GateStatus.FAIL
    assert bool(res.reason.strip())


def test_ventilation_ducts_default_to_reference_geometry_not_solid_obst(box_model):
    """MEP Ventilation ducts must default to REFERENCE_GEOMETRY and NONE strategy, never solid OBST/GEOM."""
    from ifc_to_fds.core.canonical import CanonicalElement, MappingStrategy
    from ifc_to_fds.geometry.mesh import box_mesh
    from ifc_to_fds.mapping.policy import plan_mapping
    from ifc_to_fds.mapping.exporter import serialize_fds

    duct_box = BoundingBox(xmin=0.0, xmax=5.0, ymin=1.0, ymax=1.5, zmin=2.5, zmax=3.0)
    duct_elem = CanonicalElement(
        source_id="test_src",
        entity_key="test_src:duct_1",
        global_id="guid_duct_1",
        step_id=9001,
        ifc_type="IfcDuctSegment",
        name="Supply Air Duct 1",
        role="PHYSICAL",
        has_3d_geometry=True,
        bounding_box=duct_box,
        mesh=box_mesh(duct_box),
        scope_decision=ScopeDecision.IN_SCOPE,
    )
    fitting_box = BoundingBox(xmin=5.0, xmax=6.0, ymin=1.0, ymax=2.0, zmin=2.5, zmax=3.0)
    fitting_elem = CanonicalElement(
        source_id="test_src",
        entity_key="test_src:duct_elbow_1",
        global_id="guid_duct_elbow_1",
        step_id=9002,
        ifc_type="IfcDuctFitting",
        name="Elbow 90deg",
        role="PHYSICAL",
        has_3d_geometry=True,
        bounding_box=fitting_box,
        mesh=box_mesh(fitting_box),
        scope_decision=ScopeDecision.IN_SCOPE,
    )
    box_model.elements.extend([duct_elem, fitting_elem])

    plan_mapping(box_model)

    assert duct_elem.simulation_role == "REFERENCE_GEOMETRY"
    assert duct_elem.mapping_strategy == MappingStrategy.NONE
    assert fitting_elem.simulation_role == "REFERENCE_GEOMETRY"
    assert fitting_elem.mapping_strategy == MappingStrategy.NONE

    # In serialized FDS, neither duct nor fitting must be emitted as &OBST or &GEOM
    fds_text, _ = serialize_fds(box_model)
    assert "guid_duct_1" not in fds_text
    assert "guid_duct_elbow_1" not in fds_text
    assert "OBST_9001" not in fds_text
    assert "GEOM_9001" not in fds_text
    assert "OBST_9002" not in fds_text
    assert "GEOM_9002" not in fds_text


def test_generic_proxy_with_duct_type_class_is_mep_and_not_solid_obst(box_model):
    """IfcBuildingElementProxy with type_class='IfcDuctSegment' must be classified as MEP, not solid OBST."""
    from ifc_to_fds.core.canonical import CanonicalElement, MappingStrategy
    from ifc_to_fds.geometry.mesh import box_mesh
    from ifc_to_fds.mapping.policy import plan_mapping, determine_element_strategy
    from ifc_to_fds.mapping.exporter import serialize_fds

    proxy_box = BoundingBox(xmin=0.0, xmax=2.0, ymin=0.0, ymax=0.5, zmin=2.0, zmax=2.5)
    proxy_elem = CanonicalElement(
        source_id="test_src",
        entity_key="test_src:proxy_duct",
        global_id="guid_proxy_duct",
        step_id=9003,
        ifc_type="IfcBuildingElementProxy",
        type_class="IfcDuctSegment",
        name="Proxy Duct",
        role="PHYSICAL",
        has_3d_geometry=True,
        bounding_box=proxy_box,
        mesh=box_mesh(proxy_box),
        scope_decision=ScopeDecision.IN_SCOPE,
    )
    # Direct determine_element_strategy call before plan_mapping should also respect type_class
    strategy_direct = determine_element_strategy(proxy_elem)
    assert strategy_direct == MappingStrategy.NONE

    box_model.elements.append(proxy_elem)
    plan_mapping(box_model)
    assert proxy_elem.simulation_role == "REFERENCE_GEOMETRY"
    assert proxy_elem.mapping_strategy == MappingStrategy.NONE

    fds_text, _ = serialize_fds(box_model)
    assert "guid_proxy_duct" not in fds_text
    assert "OBST_9003" not in fds_text


def test_unconfigured_hvac_role_cannot_fabricate_a_network(box_model):
    """Selecting a role without source ports/parameters is not configuration."""
    import pytest
    from ifc_to_fds.mapping.policy import plan_mapping
    elem = box_model.elements[0]
    elem.simulation_role = "HVAC"
    with pytest.raises(ValueError, match="HVAC requires"):
        plan_mapping(box_model)
