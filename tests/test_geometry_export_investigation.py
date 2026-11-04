"""Regressions found by the source geometry and export investigation."""
from pathlib import Path
import pytest
import trimesh

from ifc_to_fds.domain.bim import TriangleMesh, GeometryStatus
from ifc_to_fds.geometry.mesh import as_trimesh, self_intersection_evidence


def test_intersection_evidence_has_triangle_witness():
    one = trimesh.creation.box()
    two = trimesh.creation.box()
    two.apply_translation([0.25, 0.25, 0.25])
    mesh = trimesh.util.concatenate([one, two])
    raw = TriangleMesh(vertices=mesh.vertices.tolist(), faces=mesh.faces.tolist())
    before = raw.model_dump()
    evidence = self_intersection_evidence(raw)
    assert evidence['status'] == 'CONFIRMED'
    assert evidence['witness']['kind'] in ('TRIANGLE_CROSSING', 'COPLANAR_FACE_OVERLAP', 'COMPONENT_VOLUME_OVERLAP')
    assert raw.model_dump() == before


def test_audit_component_count_never_repairs_source(box_model, monkeypatch):
    from ifc_to_fds.validation.metrics import compare_solids
    def forbidden(*args, **kwargs):
        raise AssertionError('Auditor attempted to fill source holes')
    monkeypatch.setattr(trimesh.Trimesh, 'fill_holes', forbidden)
    mesh = box_model.elements[0].mesh
    assert self_intersection_evidence(mesh)['status'] == 'CLEAN'
    metrics = compare_solids(mesh, [mesh.model_copy(deep=True)])
    assert metrics['reference_components'] == metrics['output_components'] == 1


def test_invalid_door_is_retained_without_bounding_box_substitution(tiny_ifc, monkeypatch):
    from ifc_to_fds.core.inventory import extract_inventory
    from ifc_to_fds.geometry import engine
    model, source = extract_inventory(str(tiny_ifc[0]))
    elem = next(e for e in model.elements if e.has_3d_geometry)
    elem.ifc_type = 'IfcDoor'
    opened = as_trimesh(elem.mesh) if elem.mesh else trimesh.creation.box()
    raw = TriangleMesh(vertices=opened.vertices.tolist(), faces=opened.faces[:-1].tolist())
    class EmptyIterator:
        def initialize(self): return False
    monkeypatch.setattr(engine.ifcopenshell.geom, 'iterator', lambda *a, **kw: EmptyIterator())
    monkeypatch.setattr(engine, 'extract_element_geometry', lambda *a, **kw: raw.model_copy(deep=True))
    engine.process_model_geometry(model, source)
    assert elem.geometry_status == GeometryStatus.FAILED
    assert elem.mesh.vertices == raw.vertices and elem.mesh.faces == raw.faces
    assert elem.geometry_diagnostics['open_edges'] > 0
    assert elem.geometry_diagnostics['repair_applied'] is False


def test_inventory_records_source_representation(tiny_ifc):
    from ifc_to_fds.core.inventory import extract_inventory
    model, _ = extract_inventory(str(tiny_ifc[0]))
    elem = next(e for e in model.elements if e.has_3d_geometry)
    assert elem.source_representations
    assert elem.source_representations[0]['representation_type']
    assert elem.source_representations[0]['item_step_ids']


def snapshot(directory):
    return {str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob('*') if p.is_file()}


def test_backup_failure_preserves_entire_existing_bundle(tiny_ifc, tmp_path, monkeypatch):
    from ifc_to_fds.pipeline import convert, save_artifacts
    from ifc_to_fds.adapters.storage import filesystem
    result = convert([tiny_ifc[0]], output_directory=tmp_path / 'work')
    target = tmp_path / 'target/model.fds'
    save_artifacts(result, target)
    before = snapshot(target.parent)
    original = filesystem.shutil.copytree
    def failing_backup(src, dst, *args, **kwargs):
        if any(p.startswith('.backup-') for p in Path(dst).parts):
            Path(dst).mkdir(parents=True, exist_ok=True)
            (Path(dst) / 'partial').write_bytes(b'incomplete backup')
            raise OSError('backup disk full')
        return original(src, dst, *args, **kwargs)
    monkeypatch.setattr(filesystem.shutil, 'copytree', failing_backup)
    with pytest.raises(OSError, match='backup disk full'):
        save_artifacts(result, target)
    assert snapshot(target.parent) == before


def test_failed_rollback_retains_recoverable_backup(tiny_ifc, tmp_path, monkeypatch):
    from ifc_to_fds.pipeline import convert, save_artifacts
    from ifc_to_fds.adapters.storage import filesystem
    result = convert([tiny_ifc[0]], output_directory=tmp_path / 'work')
    target = tmp_path / 'target/model.fds'
    save_artifacts(result, target)
    original_fds = target.read_bytes()
    result['fds_text'] = 'changed FDS'
    original_replace, original_copy = Path.replace, filesystem.shutil.copy2
    def fail_second_publication(src, dst):
        if src.parent.name.startswith('.staging-') and src.name.endswith('_manifest.json'):
            raise OSError('publication failure')
        return original_replace(src, dst)
    def fail_restore(src, dst, *args, **kwargs):
        if Path(src).parent.name.startswith('.backup-'):
            raise OSError('restore failure')
        return original_copy(src, dst, *args, **kwargs)
    monkeypatch.setattr(Path, 'replace', fail_second_publication)
    monkeypatch.setattr(filesystem.shutil, 'copy2', fail_restore)
    with pytest.raises(RuntimeError, match='Original backup retained at'):
        save_artifacts(result, target)
    backups = list(target.parent.glob('.backup-*'))
    assert len(backups) == 1
    assert (backups[0] / 'model.fds').read_bytes() == original_fds
    assert not list(target.parent.glob('.staging-*'))


def test_export_counts_distinguish_written_from_verified(tiny_ifc, tmp_path):
    from ifc_to_fds.pipeline import convert
    result = convert([tiny_ifc[0]], output_directory=tmp_path)
    counts = result['report']['coverage']['fds_export']
    assert counts['entities'] == counts['verified_entities'] == 1
    assert counts['primitives'] == counts['obst'] + counts['geom'] == 1
    assert not counts['comparisons_skipped_for_source_errors']


def test_cli_work_directory_does_not_overwrite_sibling_model(tiny_ifc, tmp_path):
    from ifc_to_fds.cli import main
    destination = tmp_path / 'exports'
    destination.mkdir()
    sibling = destination / 'model.fds'
    sibling.write_bytes(b'Unrelated existing model')
    assert main(['convert', str(tiny_ifc[0]), '-o', str(destination / 'chosen.fds')]) == 0
    assert sibling.read_bytes() == b'Unrelated existing model'
    assert (destination / 'chosen_geometry.zip').is_file()
    assert not list(destination.glob('.ifcfds-work-*'))


def test_duplex_geometry_evaluation_rejects_unverified_architectural_sample():
    """Evaluate conversion of IfcOpenShell-Duplex.ifc architectural sample.

    As specified in the EV fire scenario batch spec ('Nếu mẫu sai thật: document +
    đổi golden trong test'):
    `IfcOpenShell-Duplex.ifc` is an unverified architectural sample model containing
    approximately 211-212 verification findings:
    - Open 2D covering surfaces (e.g. IfcCovering with zero thickness and inconsistent edges).
    - Non-manifold railings, stairs, and furnishings (open edges, degenerate faces, zero volume).
    - Envelope compartmentation breach after audited winding normalization: 2.54 m³
      and 9 source versus 8 FDS cavities. The raw control case omits 14 solids
      and has a different envelope. See docs/audit/remediation-2026-11-04.

    The verified IFC-to-FDS pipeline honestly rejects this model (mapping_status == "REJECTED")
    without crashing or fabricating geometry via silent bounding box substitution.
    """
    from ifc_to_fds.pipeline import convert

    result = convert(["examples/IfcOpenShell-Duplex.ifc"])

    # Conversion finishes cleanly without crashing
    assert result is not None
    assert result["mapping_status"] == "REJECTED"
    assert result["simulation_status"] == "REJECTED"
    assert result["status"] == "REJECTED"
    assert result["output_complete"] is False

    report = result["report"]
    findings = report.get("findings", [])

    # The pipeline records categorized findings (open coverings classified as semantic;
    # non-manifold railings and envelope leaks reported).
    assert 115 <= len(findings) <= 225

    # Categorized findings include geometry and air path
    categories = {f.get("category") for f in findings}
    assert "geometry" in categories
    assert "air_path" in categories

    # Explicit architectural defects: non-manifold railings
    railing_findings = [f for f in findings if "IfcRailing" in f.get("detail", "")]
    assert len(railing_findings) > 0, "Expected non-manifold railing findings"

    # Winding normalization preserves the original triangles and allows
    # previously withheld ceilings and wall STEP 98 into the comparison.
    gates = report.get("gates", {})
    assert gates["geometry"]["status"] == "FAIL"
    assert gates["air_path"]["status"] == "FAIL"
    leak_vol = gates["air_path"]["evidence"]["leak_volume_m3"]
    assert round(leak_vol, 2) == 2.54, f"Expected ~2.54 m^3 leak volume, got {leak_vol}"
    assert gates["air_path"]["evidence"]["source_cavities"] == 9
    assert gates["air_path"]["evidence"]["fds_cavities"] == 8


def test_verified_golden_models_achieve_verified_status(tmp_path):
    """Verified golden models (box.ifc and tiny.ifc) achieve MAPPING_VERIFIED with 0 findings.

    Unlike unverified architectural samples (such as Duplex), these closed-manifold,
    leak-free models pass all verification gates with 0 findings, establishing them
    as the verified golden base for fire scenario batch generation.
    """
    from ifc_to_fds.pipeline import convert

    golden_models = [
        "tests/browser/box.ifc",
        "tests/baseline/fixtures/tiny.ifc",
    ]

    for model_path in golden_models:
        result = convert([model_path], output_directory=tmp_path / Path(model_path).stem)

        assert result["mapping_status"] == "MAPPING_VERIFIED"
        assert result["status"] == "MAPPING_VERIFIED"
        assert result["output_complete"] is True

        # Exactly 0 findings
        findings = result["report"].get("findings", [])
        assert len(findings) == 0, f"Expected 0 findings for {model_path}, got {len(findings)}: {findings}"

        # Key gates pass cleanly
        gates = result["report"].get("gates", {})
        assert gates["geometry"]["status"] == "PASS"
        assert gates["air_path"]["status"] == "PASS"
        assert gates["source_inventory"]["status"] == "PASS"
        assert gates["traceability"]["status"] == "PASS"

