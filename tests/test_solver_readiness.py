"""Executable resolution must be deterministic and must not execute candidates."""

import ast
import hashlib
from pathlib import Path

import pytest

from ifc_to_fds.validation import solver_discovery as discovery
from ifc_to_fds.validation.acceptance import AuditConfig
from ifc_to_fds.validation.solver import solver_gates


@pytest.fixture
def discovery_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("IFCFDS_SOLVER_AUTODISCOVERY", "1")
    monkeypatch.setattr(discovery, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(discovery.platform, "system", lambda: "Windows")
    monkeypatch.setattr(discovery.shutil, "which", lambda _: None)
    return tmp_path


def pinned_file(root, monkeypatch, content=b"pinned fixture"):
    path = root / discovery.PINNED_WINDOWS_RELATIVE_PATH
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    monkeypatch.setattr(discovery, "PINNED_BINARY_SHA256", hashlib.sha256(content).hexdigest())
    return path


def test_pinned_installation_used_without_path(discovery_environment, monkeypatch):
    path = pinned_file(discovery_environment, monkeypatch)
    result = discovery.resolve_solver_executable()
    assert result.executable == path.resolve()
    assert result.source == "project-pinned"
    assert result.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_explicit_precedes_path_and_pinned(discovery_environment, monkeypatch):
    explicit = discovery_environment / "operator.exe"
    explicit.write_bytes(b"operator")
    pinned_file(discovery_environment, monkeypatch)
    monkeypatch.setattr(discovery.shutil, "which", lambda _: pytest.fail("Explicit path must not search PATH"))
    result = discovery.resolve_solver_executable(str(explicit))
    assert result.executable == explicit.resolve()
    assert result.source == "explicit"


def test_invalid_explicit_never_falls_back(discovery_environment, monkeypatch):
    pinned_file(discovery_environment, monkeypatch)
    monkeypatch.setattr(discovery.shutil, "which", lambda _: pytest.fail("Invalid explicit path must not fall back"))
    result = discovery.resolve_solver_executable(str(discovery_environment / "missing.exe"))
    assert result.executable is None
    assert result.source == "explicit"
    assert "not a file" in result.reason


@pytest.mark.parametrize("configured", ["", " ", "\x00"])
def test_malformed_explicit_does_not_raise(configured, discovery_environment):
    result = discovery.resolve_solver_executable(configured)
    assert result.executable is None
    assert result.source == "explicit"


def test_path_precedes_pinned(discovery_environment, monkeypatch):
    on_path = discovery_environment / "fds.exe"
    on_path.write_bytes(b"PATH installation")
    pinned_file(discovery_environment, monkeypatch)
    monkeypatch.setattr(discovery.shutil, "which", lambda _: str(on_path))
    result = discovery.resolve_solver_executable()
    assert result.executable == on_path.resolve()
    assert result.source == "PATH"


def test_wrong_pinned_binary_is_never_available(discovery_environment, monkeypatch):
    path = pinned_file(discovery_environment, monkeypatch)
    path.write_bytes(b"changed binary")
    result = discovery.resolve_solver_executable()
    assert result.executable is None
    assert result.source == "project-pinned"
    assert "checksum differs" in result.reason


@pytest.mark.parametrize("platform,version", [("Linux", "6.11.1"), ("Darwin", "6.11.1"), ("Windows", "../6.12.0")])
def test_incompatible_platform_or_version_not_searched(platform, version, discovery_environment, monkeypatch):
    pinned_file(discovery_environment, monkeypatch)
    monkeypatch.setattr(discovery.platform, "system", lambda: platform)
    result = discovery.resolve_solver_executable(version=version)
    assert result.executable is None
    assert result.source == "not-found"


def test_operator_can_disable_discovery_without_blocking_explicit(discovery_environment, monkeypatch):
    path = pinned_file(discovery_environment, monkeypatch)
    monkeypatch.setenv("IFCFDS_SOLVER_AUTODISCOVERY", "0")
    monkeypatch.setattr(discovery.shutil, "which", lambda _: pytest.fail("Disabled discovery must not search PATH"))
    result = discovery.resolve_solver_executable()
    assert result.executable is None
    assert result.source == "disabled"
    assert discovery.resolve_solver_executable(str(path)).executable == path.resolve()


def test_missing_and_invalid_config_retain_resolution_without_launch(box_model, discovery_environment, monkeypatch):
    from ifc_to_fds.mapping.exporter import serialize_fds
    monkeypatch.setattr("ifc_to_fds.validation.solver.subprocess.Popen", lambda *a, **k: pytest.fail("Unavailable solver must not launch"))
    text, _ = serialize_fds(box_model)
    for configuration, source in [(AuditConfig(), "not-found"), (AuditConfig(solver_executable=str(discovery_environment / "missing.exe")), "explicit")]:
        solver, effective = solver_gates(text, configuration)
        assert solver.status == effective.status == "INCONCLUSIVE"
        assert solver.evidence["resolution"]["source"] == source


def test_pinned_checksum_matches_installer_contract():
    installer = Path(__file__).resolve().parents[1] / "scripts/install-fds.py"
    assignments = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in ast.parse(installer.read_text(encoding="utf-8")).body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in ("BINARY_SHA",)
    }
    assert assignments["BINARY_SHA"] == discovery.PINNED_BINARY_SHA256


def test_changed_binary_after_discovery_never_launches(box_model, tmp_path, monkeypatch):
    from ifc_to_fds.mapping.exporter import serialize_fds
    path = tmp_path / "fds.exe"
    path.write_bytes(b"changed since discovery")
    result = discovery.SolverResolution(path, "project-pinned", "found", sha256="previous checksum")
    monkeypatch.setattr("ifc_to_fds.validation.solver.resolve_solver_executable", lambda *a: result)
    monkeypatch.setattr("ifc_to_fds.validation.solver.platform.platform", lambda: "fixture-platform")
    monkeypatch.setattr("ifc_to_fds.validation.solver.subprocess.Popen", lambda *a, **k: pytest.fail("Changed pinned binary must not launch"))
    text, _ = serialize_fds(box_model)
    solver, effective = solver_gates(text, AuditConfig())
    assert solver.status == effective.status == "INCONCLUSIVE"
    assert "changed after discovery" in solver.reason
