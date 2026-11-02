import json
from pathlib import Path
import shutil
import time
import uuid
import pytest
from fastapi.testclient import TestClient
from ifc_to_fds.server import app

client = TestClient(app)


def test_api_health_and_private_paths():
    assert client.get("/api/health").json()["status"] == "ok"
    for path in ("/.git/config", "/pyproject.toml", "/ifc_to_fds/server.py"):
        assert client.get(path).status_code == 404


def test_api_inventory(tiny_ifc):
    path, _, _ = tiny_ifc
    response = client.post(
        "/api/inventory", files={"file": ("tiny.ifc", path.read_bytes())}
    )
    assert response.status_code == 200, response.text
    assert response.json()["total_elements"] == 2
    assert response.json()["storey_references"][0]["name"] == "Ground"


def test_api_convert_job(tiny_ifc):
    path, _, _ = tiny_ifc
    response = client.post(
        "/api/jobs", files=[("files", ("tiny.ifc", path.read_bytes()))]
    )
    assert response.status_code == 202, response.text
    jid = response.json()["id"]
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        job = client.get("/api/jobs/" + jid).json()
        if job["state"] in ("COMPLETED", "FAILED", "TIMED_OUT"):
            break
        time.sleep(0.1)
    assert job["state"] == "COMPLETED", job
    result = client.get("/api/jobs/" + jid + "/result").json()
    assert result["status"] == "MAPPING_VERIFIED"
    assert result["simulation_status"] == "INCONCLUSIVE"
    assert result["gates"]["source_inventory"]["status"] == "PASS"
    assert result["gates"]["geometry"]["status"] == "PASS"
    assert "geometry_package" not in result and "fds_text" not in result
    manifest = client.get(result["artifacts"]["manifest"]["url"]).json()
    assert manifest["acceptance_status"] == result["status"]
    assert client.get("/api/jobs/" + jid + "/artifacts/fds").status_code == 200
    index = client.get(result["artifacts"]["geometry"]["url"]).json()
    ref = next(e["mesh"] for e in index["elements"].values() if e["mesh"])
    payload = client.get("/api/jobs/" + jid + "/geometry/" + ref["payload"])
    import hashlib

    assert hashlib.sha256(payload.content).hexdigest() == ref["payload"]
    batch = client.get(
        "/api/jobs/" + jid + "/geometry-batch",
        params=[("payloads", ref["payload"])] * 2,
    )
    assert batch.status_code == 200
    assert batch.content == payload.content * 2
    assert (
        client.get(
            "/api/jobs/" + jid + "/geometry-batch",
            params=[("payloads", ref["payload"])] * 17,
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/jobs/" + jid + "/geometry-batch", params={"payloads": "0" * 64}
        ).status_code
        == 404
    )
    assert client.get("/api/jobs/" + jid + "/geometry/" + "0" * 64).status_code == 404
    assert "_geometry_payloads" not in client.get("/api/jobs/" + jid).json()
    assert client.get(result["artifacts"]["geometry_archive"]["url"]).status_code == 200


@pytest.mark.parametrize("cell", ["0", "-1", "nan", "inf"])
def test_invalid_cell_size(cell):
    response = client.post(
        "/api/convert",
        files={"file": ("tiny.ifc", b"not parsed")},
        data={"cell_size": cell},
    )
    assert response.status_code == 422


def test_cross_origin_and_upload_limit(monkeypatch):
    assert (
        client.post(
            "/api/jobs",
            headers={"Origin": "https://other.example"},
            files={"files": ("tiny.ifc", b"abc")},
        ).status_code
        == 403
    )
    monkeypatch.setattr("ifc_to_fds.server.MAX_FILE", 2)
    assert (
        client.post("/api/jobs", files={"files": ("tiny.ifc", b"123")}).status_code
        == 413
    )


@pytest.mark.parametrize(
    "configuration",
    [
        '{"scope":{"boundingBox":[0,1,0,1,0,1]}}',
        '{"all_geom":"false"}',
        '{"sources":{"common_coordinates":"yes"}}',
        '{"skip_validation":true}',
        '{"audit":{"surface_tolernce_m":1.0}}',
    ],
)
def test_unknown_or_mistyped_configuration_rejected(configuration):
    response = client.post(
        "/api/jobs",
        files={"files": ("tiny.ifc", b"not parsed")},
        data={"configuration": configuration},
    )
    assert response.status_code == 422


def test_reference_paths_are_operator_registered(monkeypatch):
    from ifc_to_fds.server import configuration_value
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        configuration_value('{"reference_case":"C:/private/model"}')
    monkeypatch.setenv(
        "IFCFDS_REFERENCE_CASES", '{"basement":"reference-cases/basement-b1-b2"}'
    )
    cases = client.get("/api/reference-cases").json()["cases"]
    assert cases[0]["id"] == "basement" and cases[0]["approval_status"] == "DRAFT"
    assert "path" not in cases[0]
    assert configuration_value('{"reference_case":"basement"}')[
        "reference_case"
    ].endswith("basement-b1-b2")


def test_research_recognition_does_not_select_or_accept_profile(monkeypatch):
    from ifc_to_fds.results import research_context

    monkeypatch.setattr(
        "ifc_to_fds.results.registered_cases",
        lambda: [
            dict(
                id="basement",
                name="B1/B2",
                source_hashes=["a", "b"],
                approval_status="DRAFT",
            )
        ],
    )
    partial = research_context([dict(file_hash_sha256="a")], {"profile": "mapping"})
    assert partial["known_cases"][0]["source_match"] == "PARTIAL"
    assert partial["parity_status"] == "NOT_RUN"
    assert partial["research_acceptance"] == "NOT_RUN"
    exact = research_context(
        [dict(file_hash_sha256=x) for x in ("a", "b")], {"profile": "mapping"}
    )
    assert exact["known_cases"][0]["source_match"] == "EXACT"
    assert exact["research_acceptance"] == "NOT_RUN"


def test_geometry_payload_returns_404_when_index_file_missing(tmp_path):
    from ifc_to_fds.server import manager

    job_id = "test-job-no-geometry"
    manager.jobs[job_id] = {
        "job_id": job_id,
        "state": "COMPLETED",
        "directory": str(tmp_path),
    }
    dummy_payload = "a" * 64
    response = client.get(f"/api/jobs/{job_id}/geometry/{dummy_payload}")
    assert response.status_code == 404
    assert "Geometry index not available" in response.json()["detail"]


def test_checkpoint_artifacts_accessible_on_failed_or_incomplete_jobs(tmp_path):
    from ifc_to_fds.server import manager

    job_id = "test-job-failed-audit"
    (tmp_path / "model.fds").write_text("&HEAD CHID='test' /", encoding="utf-8")
    manager.jobs[job_id] = {
        "job_id": job_id,
        "state": "FAILED",
        "directory": str(tmp_path),
    }
    # Regular /artifacts requires COMPLETED
    res_reg = client.get(f"/api/jobs/{job_id}/artifacts/fds")
    assert res_reg.status_code == 409

    # /checkpoints allows access with unaccepted header
    res_chk = client.get(f"/api/jobs/{job_id}/checkpoints/fds")
    assert res_chk.status_code == 200
    assert "&HEAD" in res_chk.text
    assert (
        res_chk.headers.get("X-Verification-Status")
        == "UNACCEPTED-AUDIT_INCOMPLETE-DO_NOT_USE_AS_VERIFIED_OUTPUT"
    )


def _register_completed_job():
    """Register a COMPLETED job fixture directly in the repository.

    The directory lives under manager.root so the purge guard
    (parent == root) treats it as a genuine job directory.
    """
    from ifc_to_fds.server import manager

    jid = "test-completed-" + uuid.uuid4().hex[:8]
    job_dir = manager.root / ("job-" + jid)
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "result.json").write_text(
        json.dumps({"status": "MAPPING_VERIFIED"}), encoding="utf-8"
    )
    manager.repository.set(jid, {
        "id": jid,
        "state": "COMPLETED",
        "directory": str(job_dir),
        "created": time.time() - 10,
        "finished": time.time(),
        "mode": "convert",
    })
    return jid, job_dir


def _forget_job(jid, job_dir):
    """Remove a fixture job row + directory; fail loudly on residue (I-D)."""
    from ifc_to_fds.server import manager

    manager.repository.delete(jid)
    shutil.rmtree(job_dir, ignore_errors=True)
    assert manager.repository.get(jid) is None, f"fixture job {jid} still registered"
    assert not job_dir.exists(), f"fixture job dir {job_dir} still on disk"


def test_forget_job_detects_lingering_directory(monkeypatch):
    """I-D: verified cleanup must fail loudly if the fixture dir survives."""
    from ifc_to_fds.server import manager

    jid, job_dir = _register_completed_job()
    real_rmtree = shutil.rmtree
    monkeypatch.setattr(shutil, "rmtree", lambda *args, **kwargs: None)
    with pytest.raises(AssertionError, match="still on disk"):
        _forget_job(jid, job_dir)
    manager.repository.delete(jid)
    real_rmtree(job_dir, ignore_errors=True)
    assert manager.repository.get(jid) is None
    assert not job_dir.exists()


def test_forget_job_detects_lingering_row(monkeypatch):
    """I-D: verified cleanup must fail loudly if the fixture row survives."""
    from ifc_to_fds.server import manager

    jid, job_dir = _register_completed_job()
    real_delete = manager.repository.delete
    monkeypatch.setattr(manager.repository, "delete", lambda _jid: None)
    with pytest.raises(AssertionError, match="still registered"):
        _forget_job(jid, job_dir)
    real_delete(jid)
    shutil.rmtree(job_dir, ignore_errors=True)
    assert manager.repository.get(jid) is None
    assert not job_dir.exists()


def test_cancel_completed_job_returns_snapshot_and_preserves_artifacts():
    """B2: POST /cancel on a COMPLETED job returns its snapshot; artifacts survive."""
    from ifc_to_fds.server import manager

    jid, job_dir = _register_completed_job()
    try:
        response = client.post(f"/api/jobs/{jid}/cancel")
        assert response.status_code == 200, response.text
        assert response.json()["id"] == jid
        assert response.json()["state"] == "COMPLETED"
        assert job_dir.exists(), "cancel must not purge artifacts of a COMPLETED job"
        assert manager.repository.get(jid) is not None
    finally:
        _forget_job(jid, job_dir)


def test_delete_completed_job_without_purge_is_rejected():
    """B2: DELETE without purge on a COMPLETED job returns 409; artifacts survive."""
    from ifc_to_fds.server import manager

    jid, job_dir = _register_completed_job()
    try:
        response = client.delete(f"/api/jobs/{jid}")
        assert response.status_code == 409, response.text
        assert job_dir.exists(), "rejected DELETE must not purge artifacts"
        assert manager.repository.get(jid) is not None
    finally:
        _forget_job(jid, job_dir)


def test_delete_completed_job_with_purge_removes_row_and_dir():
    """B2: DELETE?purge=true on a COMPLETED job removes dir + row (404 on next GET)."""
    from ifc_to_fds.server import manager

    jid, job_dir = _register_completed_job()
    try:
        response = client.delete(f"/api/jobs/{jid}", params={"purge": "true"})
        assert response.status_code == 200, response.text
        assert not job_dir.exists(), "purge must remove the artifacts directory"
        assert manager.repository.get(jid) is None
        assert client.get(f"/api/jobs/{jid}").status_code == 404
    finally:
        _forget_job(jid, job_dir)


def test_cancel_queued_job_transitions_to_cancelled():
    """B2: POST /cancel on an active QUEUED job transitions it to CANCELLED."""
    from ifc_to_fds.server import manager

    jid = "test-queued-" + uuid.uuid4().hex[:8]
    job_dir = manager.root / ("job-" + jid)
    job_dir.mkdir(parents=True, exist_ok=True)
    manager.repository.set(jid, {
        "id": jid,
        "state": "QUEUED",
        "directory": str(job_dir),
        "created": time.time(),
        "mode": "convert",
        "process": None,
    })
    try:
        response = client.post(f"/api/jobs/{jid}/cancel")
        assert response.status_code == 200, response.text
        assert response.json()["state"] == "CANCELLED"
    finally:
        _forget_job(jid, job_dir)


def test_cancel_unknown_job_returns_404():
    response = client.post("/api/jobs/does-not-exist-123/cancel")
    assert response.status_code == 404


def test_delete_running_job_with_purge_returns_cancelled_and_preserves_dir():
    """P2: DELETE?purge=true on RUNNING safely downgrades to cancel; dir survives."""
    from ifc_to_fds.server import manager

    jid = "test-running-" + uuid.uuid4().hex[:8]
    job_dir = manager.root / ("job-" + jid)
    job_dir.mkdir(parents=True, exist_ok=True)
    manager.repository.set(jid, {
        "id": jid,
        "state": "RUNNING",
        "directory": str(job_dir),
        "created": time.time(),
        "started": time.time(),
        "mode": "convert",
        "process": None,
    })
    try:
        response = client.delete(f"/api/jobs/{jid}", params={"purge": "true"})
        assert response.status_code == 200, response.text
        assert response.json()["state"] == "CANCELLED"
        assert job_dir.exists(), "safe downgrade must preserve the job directory"
        assert manager.repository.get(jid) is not None
    finally:
        _forget_job(jid, job_dir)


def test_submit_scenario_job_executes_mesh_gate(monkeypatch, tiny_ifc):
    """Scenario batch job endpoint submits scenario, evaluates mesh gate, and saves result."""
    from ifc_to_fds.server import manager

    payload = {
        "scenario_id": "SCENARIO_EV_001",
        "bundle_sha256": "a" * 64,
        "ev_library_version": "1.0.0",
        "total_peak_hrr_mw": 4.5,
        "scenario_data": {
            "scenario_id": "SCENARIO_EV_001",
            "bundle_sha256": "a" * 64,
            "ev_library_version": "1.0.0",
            "total_peak_hrr_mw": 4.5,
            "ev_selections": [
                {
                    "preset_id": "auto-nmc",
                    "vehicle_class": "auto",
                    "chemistry": "NMC",
                    "position": [0.0, 0.0, 0.75],
                    "peak_hrr_mw": 4.5,
                    "soc_percent": 80,
                }
            ],
        },
    }

    # A scenario must refer to an actual accepted base artifact.
    from ifc_to_fds.pipeline import convert, save_artifacts
    base_dir = manager.root / ("job-base-" + uuid.uuid4().hex)
    base_result = convert([str(tiny_ifc[0])], {
        "simulation_domain": dict(xmin=0, xmax=10, ymin=0, ymax=10, zmin=0, zmax=4)
    }, base_dir)
    assert base_result["status"] == "MAPPING_VERIFIED"
    save_artifacts(base_result, base_dir / "model.fds")
    payload["bundle_sha256"] = base_result["manifest"]["bundle_sha256"]
    payload["scenario_data"]["bundle_sha256"] = payload["bundle_sha256"]
    payload["scenario_data"]["ev_selections"][0]["position"] = [5, 5, .75]

    # Verify 429 when manager cannot accept
    monkeypatch.setattr(manager, "can_accept", lambda: False)
    res_429 = client.post("/api/scenario-jobs", json=payload)
    assert res_429.status_code == 429

    monkeypatch.undo()

    # Submit valid scenario job
    response = client.post("/api/scenario-jobs", json=payload)
    assert response.status_code == 202, response.text
    job_info = response.json()
    assert "id" in job_info
    assert job_info["state"] == "QUEUED"
    jid = job_info["id"]

    # Poll until completed
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{jid}").json()
        if job["state"] in ("COMPLETED", "FAILED", "TIMED_OUT"):
            break
        time.sleep(0.1)

    assert job["state"] == "COMPLETED", job

    # Verify scenario.json written in job directory
    raw_job = manager.repository.get(jid)
    assert raw_job is not None
    job_dir = Path(raw_job["directory"])
    assert (job_dir / "scenario.json").is_file()
    saved_scenario = json.loads((job_dir / "scenario.json").read_text(encoding="utf-8"))
    assert saved_scenario["scenario_id"] == "SCENARIO_EV_001"

    # Verify result.json via result endpoint
    res = client.get(f"/api/jobs/{jid}/result").json()
    assert res["status"] == "COMPLETED"
    assert res["verdict"] == "PASS"
    assert res["mesh_status"] == "PASS"
    assert res["peak_hrr_mw"] == 4.5
    assert "evidence" in res
    assert "ev_evaluations" in res["evidence"]

    # Verify scenario.fds was generated and contains fire physics namelists (C-2)
    assert (job_dir / "scenario.fds").is_file()
    fds_content = (job_dir / "scenario.fds").read_text(encoding="utf-8")
    assert "&REAC" in fds_content
    assert "&RAMP" in fds_content
    assert "&SURF" in fds_content
    assert "&VENT" in fds_content
    assert "HYDROGEN FLUORIDE" in fds_content

    # Verify scenario_fds artifact is downloadable via API (M-8)
    art_res = client.get(f"/api/jobs/{jid}/artifacts/scenario_fds")
    assert art_res.status_code == 200
    assert "&RAMP" in art_res.text

    # Verify pagination on /api/jobs/{jid}/result (M-8b)
    res_paged = client.get(f"/api/jobs/{jid}/result?offset=0&limit=1").json()
    assert res_paged["findings_offset"] == 0
    assert res_paged["findings_limit"] == 1


def test_http_security_headers():
    """M-7: API responses must carry standard HTTP security headers."""
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert res.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"



