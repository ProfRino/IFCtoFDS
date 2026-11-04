"""Numerical normalization must not invent source surfaces or close real gaps."""

import numpy as np
import pytest
import trimesh

from ifc_to_fds.domain.bim import TriangleMesh, GeometryStatus, OpeningReference
from ifc_to_fds.geometry.mesh import inspect_mesh_quality, valid_solid
from ifc_to_fds.geometry.normalization import normalize_source_mesh


def mesh(vertices, faces):
    return TriangleMesh(vertices=np.asarray(vertices).tolist(), faces=np.asarray(faces).tolist())


def cube():
    value = trimesh.creation.box()
    return mesh(value.vertices, value.faces)


def split_triangles(value, roundoff=False):
    vertices = np.asarray(value.vertices)[np.asarray(value.faces)].reshape(-1, 3)
    if roundoff:
        vertices[::2] = np.nextafter(vertices[::2], np.inf)
    return mesh(vertices, np.arange(len(vertices)).reshape(-1, 3))


def test_winding_normalization_preserves_exact_source_triangles():
    raw = cube()
    raw.faces[0] = raw.faces[0][::-1]
    raw.faces[3] = raw.faces[3][::-1]
    before = raw.model_dump()
    assert not valid_solid(raw)
    result, proof = normalize_source_mesh(raw)
    assert valid_solid(result)
    assert raw.model_dump() == before
    assert result.vertices == raw.vertices
    assert [sorted(f) for f in result.faces] == [sorted(f) for f in raw.faces]
    assert proof["status"] == "NORMALIZED"
    assert proof["faces_flipped"] == [0, 3]
    assert proof["max_vertex_displacement_m"] == 0
    assert proof["source_mesh_sha256"] != proof["result_mesh_sha256"]
    assert proof["raw_quality"]["inconsistent_edges"] > 0
    assert proof["result_quality"]["inconsistent_edges"] == 0


def test_roundoff_seams_have_measured_vertex_and_triangle_correspondence():
    raw = split_triangles(cube(), roundoff=True)
    before = raw.model_dump()
    assert inspect_mesh_quality(raw)["open_edges"] > 0
    result, proof = normalize_source_mesh(raw)
    assert valid_solid(result)
    assert raw.model_dump() == before
    assert proof["vertices_merged"] == 28
    assert proof["triangle_count_preserved"]
    assert proof["face_correspondence_preserved"]
    assert not proof["faces_flipped"]
    mapping = np.asarray(proof["vertex_map"])
    original, normalized = np.asarray(raw.vertices), np.asarray(result.vertices)
    measured = np.linalg.norm(original - normalized[mapping], axis=1).max()
    assert measured == proof["max_vertex_displacement_m"]
    assert 0 < measured <= proof["tolerance_m"] <= 1e-12
    assert np.array_equal(mapping[np.asarray(raw.faces)], np.asarray(result.faces))
    again, repeated = normalize_source_mesh(raw)
    assert again.model_dump() == result.model_dump()
    assert repeated == proof
    unchanged, next_proof = normalize_source_mesh(result)
    assert unchanged.model_dump() == result.model_dump()
    assert next_proof["status"] == "NOT_NEEDED"


def test_weld_only_can_preserve_multiple_closed_shells():
    first, second = trimesh.creation.box(), trimesh.creation.box()
    second.apply_translation([3, 0, 0])
    combined = trimesh.util.concatenate([first, second])
    raw = split_triangles(mesh(combined.vertices, combined.faces), roundoff=True)
    result, proof = normalize_source_mesh(raw)
    assert valid_solid(result)
    assert len(result.faces) == len(raw.faces)
    assert not proof["faces_flipped"]
    assert proof["status"] == "NORMALIZED"


def test_multiple_shell_winding_requires_containment_proof():
    first, second = trimesh.creation.box(), trimesh.creation.box()
    second.apply_translation([3, 0, 0])
    combined = trimesh.util.concatenate([first, second])
    raw = mesh(combined.vertices, combined.faces)
    raw.faces[0] = raw.faces[0][::-1]
    before = raw.model_dump()
    result, proof = normalize_source_mesh(raw)
    assert proof["status"] == "REFUSED"
    assert proof["reason"] == "AMBIGUOUS_MULTI_SHELL_ORIENTATION"
    assert result.model_dump() == before == raw.model_dump()


def test_valid_nested_cavity_winding_is_untouched():
    outer, inner = trimesh.creation.box(extents=[3, 3, 3]), trimesh.creation.box()
    inner.faces = inner.faces[:, ::-1]
    combined = trimesh.util.concatenate([outer, inner])
    raw = mesh(combined.vertices, combined.faces)
    assert valid_solid(raw)
    before = raw.model_dump()
    result, proof = normalize_source_mesh(raw)
    assert result.model_dump() == raw.model_dump() == before
    assert proof["status"] == "NOT_NEEDED"


@pytest.mark.parametrize("defect", ["missing_triangle", "non_manifold", "real_gap"])
def test_true_source_defects_are_not_replaced_or_filled(defect):
    raw = cube()
    if defect == "missing_triangle":
        raw.faces.pop()
    elif defect == "non_manifold":
        raw.faces.append(raw.faces[0][:])
    else:
        raw = split_triangles(raw)
        raw.vertices[0][0] += 1e-8
    before = raw.model_dump()
    result, proof = normalize_source_mesh(raw)
    assert proof["status"] == "REFUSED"
    assert result.model_dump() == raw.model_dump() == before
    assert proof["source_mesh_sha256"] == proof["result_mesh_sha256"]
    assert not valid_solid(result)


def test_large_coordinates_do_not_turn_ulp_budget_into_physical_gap_tolerance():
    raw = cube()
    raw.vertices = (np.asarray(raw.vertices) + [1e12, 1e12, 1e12]).tolist()
    raw = split_triangles(raw, roundoff=True)
    before = raw.model_dump()
    result, proof = normalize_source_mesh(raw)
    assert proof["tolerance_m"] == 1e-12
    assert proof["status"] == "REFUSED"
    assert result.model_dump() == before


def test_bad_indices_and_nonfinite_coordinates_are_retained_with_reason():
    for corrupt in ("index", "nan"):
        raw = cube()
        if corrupt == "index":
            raw.faces[0][0] = 10**100
        else:
            raw.vertices[0][0] = float("nan")
        result, proof = normalize_source_mesh(raw)
        assert result is raw
        assert proof["status"] == "REFUSED"
        assert proof["source_mesh_sha256"] == proof["result_mesh_sha256"]


def test_converter_and_fresh_reference_build_separate_normalization_proofs(tiny_ifc, monkeypatch):
    from ifc_to_fds.core.inventory import extract_inventory
    from ifc_to_fds.geometry import engine

    raw = split_triangles(cube(), roundoff=True)

    class EmptyIterator:
        def initialize(self):
            return False

    monkeypatch.setattr(engine.ifcopenshell.geom, "iterator", lambda *a, **kw: EmptyIterator())
    monkeypatch.setattr(engine, "extract_element_geometry", lambda *a, **kw: raw.model_copy(deep=True))
    converter, source_one = extract_inventory(str(tiny_ifc[0]))
    reference, source_two = extract_inventory(str(tiny_ifc[0]))
    assert source_one is not source_two
    engine.process_model_geometry(converter, source_one)
    engine.process_reference_geometry(reference, source_two)
    one = next(e for e in converter.elements if e.has_3d_geometry)
    two = next(e for e in reference.elements if e.has_3d_geometry)
    assert one.geometry_status == two.geometry_status == GeometryStatus.VALID
    assert one.mesh is not two.mesh
    assert one.geometry_diagnostics["normalization"] == two.geometry_diagnostics["normalization"]
    assert one.geometry_diagnostics is not two.geometry_diagnostics
    one.geometry_diagnostics["normalization"]["reason"] = "converter proof tampered"
    assert two.geometry_diagnostics["normalization"]["reason"] != "converter proof tampered"


def test_opening_failure_remains_visible_after_host_normalization(tiny_ifc, monkeypatch):
    from ifc_to_fds.core.inventory import extract_inventory
    from ifc_to_fds.geometry import engine

    model, source = extract_inventory(str(tiny_ifc[0]))
    host = next(e for e in model.elements if e.has_3d_geometry)
    host.openings = [OpeningReference(
        opening_global_id="bad-opening", opening_step_id=999999,
        opening_name="Kernel cannot construct this opening",
    )]
    raw = split_triangles(cube(), roundoff=True)

    class EmptyIterator:
        def initialize(self):
            return False

    def extract(_file, element, _settings):
        if element.ifc_type == "IfcOpeningElement":
            element.validation_notes.append("Geometry creation failed: deliberate kernel fixture")
            return None
        return raw.model_copy(deep=True)

    monkeypatch.setattr(engine.ifcopenshell.geom, "iterator", lambda *a, **kw: EmptyIterator())
    monkeypatch.setattr(engine, "extract_element_geometry", extract)
    engine.process_model_geometry(model, source)
    assert host.geometry_status == GeometryStatus.VALID
    assert host.openings[0].mesh is None
    assert "deliberate kernel fixture" in host.openings[0].extraction_diagnostic
    assert host.openings[0].verification_status == "NOT_RUN"
    assert host.geometry_diagnostics["openings"]["999999"]["extraction_failed"]


def test_normalization_evidence_survives_converter_cache(tiny_ifc, tmp_path, monkeypatch):
    from ifc_to_fds.core.inventory import extract_inventory
    from ifc_to_fds.geometry import cache, engine

    raw = split_triangles(cube(), roundoff=True)

    class EmptyIterator:
        def initialize(self):
            return False

    monkeypatch.setenv("IFCFDS_GEOMETRY_CACHE", str(tmp_path / "geometry-cache"))
    monkeypatch.setattr(engine.ifcopenshell.geom, "iterator", lambda *a, **kw: EmptyIterator())
    monkeypatch.setattr(engine, "extract_element_geometry", lambda *a, **kw: raw.model_copy(deep=True))
    first, source = extract_inventory(str(tiny_ifc[0]))
    cache.cached_geometry(first, source)
    original = next(e for e in first.elements if e.has_3d_geometry)
    assert original.geometry_diagnostics["numerical_normalization_applied"]

    def must_reuse(*args):
        raise AssertionError("Fresh extraction instead of a valid cache read")

    monkeypatch.setattr(cache, "process_model_geometry", must_reuse)
    second, source = extract_inventory(str(tiny_ifc[0]))
    cache.cached_geometry(second, source)
    cached = next(e for e in second.elements if e.has_3d_geometry)
    assert cached.geometry_diagnostics == original.geometry_diagnostics
    assert cached.mesh.vertices == original.mesh.vertices
    assert cached.mesh.faces == original.mesh.faces
