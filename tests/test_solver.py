import os
from pathlib import Path
import shutil
import pytest
from ifc_to_fds.mapping.exporter import serialize_fds
from ifc_to_fds.validation.acceptance import AuditConfig
from ifc_to_fds.validation.solver import solver_gates


def test_missing_solver_never_passes(box_model, monkeypatch, tmp_path):
    monkeypatch.setenv("IFCFDS_SOLVER_AUTODISCOVERY", "1")
    monkeypatch.setattr("ifc_to_fds.validation.solver_discovery.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("ifc_to_fds.validation.solver_discovery.shutil.which", lambda _: None)
    text, _ = serialize_fds(box_model)
    solver, effective = solver_gates(text, AuditConfig())
    assert solver.status == "INCONCLUSIVE"
    assert effective.status == "INCONCLUSIVE"
    assert solver.evidence["resolution"]["source"] == "not-found"


@pytest.mark.solver
def test_pinned_fds_initialization(box_model):
    executable = os.environ.get("IFCFDS_SOLVER") or shutil.which("fds")
    if not executable:
        pytest.fail("Solver suite requires FDS 6.11.1; it must not silently skip")
    text, _ = serialize_fds(box_model)
    solver, effective = solver_gates(text, AuditConfig(solver_executable=executable))
    output = Path("scripts/out/solver-evidence")
    output.mkdir(parents=True, exist_ok=True)
    (output / "input.fds").write_text(text, encoding="utf-8")
    (output / "initialization.json").write_text(
        solver.model_dump_json(indent=2), encoding="utf-8"
    )
    (output / "effective_geometry.json").write_text(
        effective.model_dump_json(indent=2), encoding="utf-8"
    )
    assert solver.status == "PASS", solver.reason
    # This fixture uses the supported single-mesh OBST subset.
    assert effective.status == "PASS", effective.reason


@pytest.mark.solver
def test_real_boundary_pipeline_and_changed_output(tiny_ifc, tmp_path):
    from ifc_to_fds.validation.boundary_fixtures import certify
    from ifc_to_fds.mapping.boundary import POLICY, certificate_valid
    from ifc_to_fds.pipeline import convert, audit
    from ifc_to_fds.mapping.manifest import MappingManifest
    import hashlib

    executable = os.environ.get("IFCFDS_SOLVER") or shutil.which("fds")
    assert executable, "Solver suite requires FDS 6.11.1"
    certificate = os.environ.get("IFCFDS_BOUNDARY_CERTIFICATE")
    if not certificate:
        certificate, passed = certify(
            executable, Path("scripts/out/solver-evidence/boundary-fixtures")
        )
        assert passed
    valid, reason = certificate_valid(
        certificate, hashlib.sha256(Path(executable).read_bytes()).hexdigest()
    )
    assert valid, reason
    config = dict(
        boundary_policy=POLICY,
        simulation_domain=dict(xmin=0.4, xmax=4, ymin=-0.2, ymax=1, zmin=-0.2, zmax=4),
        audit=dict(
            solver_executable=executable,
            boundary_fixture_certificate=str(certificate),
            solver_evidence_directory=str(
                Path("scripts/out/solver-evidence/pipeline").resolve()
            ),
        ),
    )
    result = convert([tiny_ifc[0]], config)
    assert result["status"] == "MAPPING_VERIFIED", result["report"]
    manifest = MappingManifest.model_validate(result["manifest"])
    wall = next(r for r in manifest.records if r.ifc_type == "IfcWall")
    assert wall.boundary_treatment == "VALIDATED"
    assert (
        wall.boundary_evidence["fds_sha256"]
        == hashlib.sha256(result["fds_text"].encode()).hexdigest()
    )
    text = result["fds_text"].replace("XB=0.4,2,0,1,0,3", "XB=0.6,2,0,1,0,3")
    assert text != result["fds_text"]
    manifest.fds_sha256 = hashlib.sha256(text.encode()).hexdigest()
    _, _, report = audit(
        [tiny_ifc[0]], text, manifest, config, result["geometry_package"]
    )
    assert report.status == "REJECTED"
    assert report.gates["boundary"].status == "FAIL"
    assert any(
        f.element_id == wall.entity_key
        for f in report.findings
        if f.category == "geometry"
    )


def test_probe_timeout_is_inconclusive_and_retains_evidence(
    box_model, tmp_path, monkeypatch
):
    import subprocess
    import sys
    import json
    import ifc_to_fds.validation.solver as adapter

    stopped = []

    class Probe:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("probe", timeout)
            return b"partial version output", None

    monkeypatch.setattr(adapter.platform, "platform", lambda: "fixture-platform")
    monkeypatch.setattr(adapter.subprocess, "Popen", Probe)
    monkeypatch.setattr(adapter, "stop_tree", lambda process: stopped.append(process))
    text, _ = serialize_fds(box_model)
    gate, effective = solver_gates(
        text,
        AuditConfig(
            solver_executable=sys.executable, solver_evidence_directory=str(tmp_path)
        ),
    )
    assert gate.status == effective.status == "INCONCLUSIVE"
    assert len(stopped) == 1
    directory = Path(gate.evidence["directory"])
    saved = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    assert saved["timed_out"]
    assert (directory / "version.log").read_bytes() == b"partial version output"
    assert (directory / "audit.fds").read_bytes() == text.encode()
