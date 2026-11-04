"""Authoritative Geometry Engine powered by IfcOpenShell OpenCASCADE kernel.

Extracts meshes, records bounded numerical normalization and reports remaining
kernel/topology failures explicitly. Extraction does not establish independent
geometry or opening verification.

Geometry Validation Boundary & Fire Safety Fidelity:
----------------------------------------------------
In CFD fire and smoke simulations (such as FDS), geometric topology dictates
fluid flow paths, air entrainment, compartment pressure, and smoke boundaries.
A common naive heuristic in CAD/BIM conversion is to substitute failed or
non-manifold solids and 2D open sheets with axis-aligned bounding boxes (AABBs).

This pipeline explicitly enforces a strict geometry validation boundary and
rejects bounding box substitution for invalid or open geometries:

1. Void Carving Preservation: Architectural elements frequently define critical
   voids (doors, window openings, shafts, stairwells, and HVAC penetrations).
   Silently substituting a complex or invalid mesh with its bounding box fills
   these carved voids, sealing intentional openings and corrupting building cavities.
2. Phantom Fire Barriers: Open sheets (e.g. 2D covering surfaces, thin plate
   railings) or unclosed topological shells substituted by 3D bounding boxes
   turn paper-thin or decorative elements into solid, impermeable obstacles.
   These "phantom barriers" artificially block smoke movement, alter cavity
   topology (e.g., merging or partitioning compartment cavities), and produce
   catastrophically misleading fire safety simulations.
3. Honest Rejection: After auditable roundoff-seam/winding normalization, if
   extracted geometry contains unclosed surfaces, non-manifold
   edges, zero-volume sheets, or self-intersections (such as architectural
   sample models with non-watertight coverings or stairs), the engine retains
   the raw mesh for diagnostics, marks the element as `GeometryStatus.FAILED`,
   and allows downstream verification gates to honestly reject the model (`REJECTED`)
   rather than producing unverified or dangerously fabricated FDS geometries.
"""

from typing import Any, List, Optional
import numpy as np
import ifcopenshell
import ifcopenshell.geom
from ifc_to_fds.diagnostics import operation, progress

from ifc_to_fds.core.canonical import (
    CanonicalElement,
    CanonicalModel,
    MappingStatus,
    TriangleMesh,
    GeometryStatus,
)
from .mesh import bounds_for_vertices, inspect_mesh_quality, as_trimesh, valid_solid
from .normalization import normalize_source_mesh


def create_geom_settings(linear_deflection: float = 0.0001) -> Any:
    settings: Any = ifcopenshell.geom.settings()
    # Apply standard settings for world coordinate triangulated meshes
    settings.set(settings.USE_WORLD_COORDS, True)
    settings.set(settings.APPLY_DEFAULT_MATERIALS, False)
    settings.set(settings.WELD_VERTICES, True)
    settings.set("convert-back-units", False)
    settings.set("mesher-linear-deflection", linear_deflection)
    return settings


def mesh_from_geometry(geom) -> TriangleMesh:
    # Vectorized conversion directly from native buffer to avoid quadratic slicing overhead
    raw_verts, raw_faces = geom.verts, geom.faces
    v = np.asarray(raw_verts, dtype=np.float64).reshape(-1, 3).tolist() if raw_verts else []
    f = np.asarray(raw_faces, dtype=np.int32).reshape(-1, 3).tolist() if raw_faces else []
    return TriangleMesh(vertices=v, faces=f)


def extract_element_geometry(
    ifc_file: ifcopenshell.file,
    element: CanonicalElement,
    settings: Any,
) -> Optional[TriangleMesh]:
    try:
        product = ifc_file.by_id(element.step_id)
    except Exception:
        return None

    if not getattr(product, "Representation", None):
        return None

    try:
        shape: Any = ifcopenshell.geom.create_shape(settings, product)
        geom = getattr(shape, "geometry", None)
        if geom is None:
            return None
        raw_verts = getattr(geom, "verts", [])
        raw_faces = getattr(geom, "faces", [])

        # Vectorized conversion directly from native buffer
        vertices = np.asarray(raw_verts, dtype=np.float64).reshape(-1, 3).tolist() if raw_verts else []
        faces = np.asarray(raw_faces, dtype=np.int32).reshape(-1, 3).tolist() if raw_faces else []

        mesh = TriangleMesh(vertices=vertices, faces=faces)
        quality = inspect_mesh_quality(mesh)
        mesh.is_closed_manifold = bool(quality["is_closed_manifold"])
        mesh.has_consistent_normals = quality["inconsistent_edges"] == 0

        return mesh
    except Exception as exc:
        element.mapping_status = MappingStatus.DEVIATED
        element.validation_notes.append(f"Geometry creation failed: {str(exc)}")
        return None


def prepare_source_mesh(mesh):
    """Normalize only independently supplied raw triangles and retain the proof."""
    if mesh is None:
        return None, {"extraction_failed": True, "repair_applied": False}
    mesh, proof = normalize_source_mesh(mesh)
    quality = proof["result_quality"]
    mesh.is_closed_manifold = bool(quality["is_closed_manifold"])
    mesh.has_consistent_normals = quality["inconsistent_edges"] == 0
    diagnostics = dict(
        quality, vertices=len(mesh.vertices), faces=len(mesh.faces),
        repair_applied=False, numerical_normalization_applied=proof["status"] == "NORMALIZED",
        raw_quality=proof["raw_quality"], normalization=proof,
    )
    return mesh, diagnostics


def assign_source_openings(element, ifc_file, settings):
    for opening in element.openings:
        source = CanonicalElement(
            global_id=opening.opening_global_id,
            step_id=opening.opening_step_id,
            ifc_type="IfcOpeningElement",
        )
        raw = extract_element_geometry(ifc_file, source, settings)
        opening.mesh, diagnostics = prepare_source_mesh(raw)
        opening.bounding_box = (
            bounds_for_vertices(opening.mesh.vertices) if opening.mesh else None
        )
        opening.extraction_diagnostic = opening_diagnostic(
            opening.mesh, source.validation_notes
        )
        element.geometry_diagnostics.setdefault("openings", {})[
            str(opening.opening_step_id)
        ] = diagnostics


@operation("IFC_GEOMETRY")
def process_model_geometry(
    canonical_model: CanonicalModel,
    ifc_file: ifcopenshell.file,
) -> CanonicalModel:
    """Iterates through all elements in CanonicalModel and builds 3D meshes."""
    settings = create_geom_settings()

    all_verts: List[List[float]] = []

    # Iterator supports shared geometry and multiple CPU cores. Missing items are
    # retried individually so a failed iterator item remains visible in diagnostics.
    import os

    shapes = {}
    try:
        products = [e for e in canonical_model.elements if e.has_3d_geometry]
        iterator = ifcopenshell.geom.iterator(
            settings, ifc_file, min(4, os.cpu_count() or 1),
            include=[ifc_file.by_id(e.step_id) for e in products],
        ) if products else None
        if iterator and iterator.initialize():
            while True:
                shape: Any = iterator.get()
                g = shape.geometry
                shapes[shape.id] = mesh_from_geometry(g)
                if len(shapes) % 16 == 0:
                    progress("IFC_GEOMETRY", "RUNNING", completed=len(shapes), total=len(products))
                if not iterator.next():
                    break
    except Exception as exc:
        for item in canonical_model.elements:
            item.validation_notes.append(f"Iterator fallback: {exc}")

    for elem in canonical_model.elements:
        if not elem.has_3d_geometry:
            elem.geometry_status = GeometryStatus.NO_REPRESENTATION
            continue

        mesh = shapes.pop(elem.step_id, None) or extract_element_geometry(
            ifc_file, elem, settings
        )
        mesh, elem.geometry_diagnostics = prepare_source_mesh(mesh)
        elem.mesh = mesh
        elem.bounding_box = None
        if mesh and mesh.vertices:
            bbox = bounds_for_vertices(mesh.vertices)
            elem.bounding_box = bbox
            if bbox:
                all_verts.append([bbox.xmin, bbox.ymin, bbox.zmin])
                all_verts.append([bbox.xmax, bbox.ymax, bbox.zmax])

            quality = elem.geometry_diagnostics["normalization"]["result_quality"]
            mesh.is_closed_manifold = bool(quality["is_closed_manifold"])
            mesh.has_consistent_normals = quality["inconsistent_edges"] == 0
            if valid_solid(mesh):
                tm = as_trimesh(mesh)
                mesh.volume, mesh.area = float(tm.volume), float(tm.area)
                elem.geometry_status = GeometryStatus.VALID
            else:
                # GEOMETRY VALIDATION BOUNDARY:
                # Open sheets (2D surfaces) and non-manifold meshes are strictly rejected
                # rather than silently substituted with axis-aligned bounding boxes (AABBs).
                # Silent AABB substitution would fill intentional architectural voids
                # (destroying opening cuts and cavity connectivity) and fabricate
                # "phantom fire barriers" (turning decorative or open sheets into solid
                # obstacles that block smoke/gas flow in FDS).
                # Retain the raw mesh for audit diagnosis; unsupported topology is
                # explicit in the inventory and flagged as GeometryStatus.FAILED so the
                # downstream verification gates reject the model cleanly.
                elem.geometry_status = GeometryStatus.FAILED
                elem.validation_notes.append(
                    "Invalid extracted solid after bounded numerical normalization: "
                    f"{quality}; {elem.geometry_diagnostics['normalization']['reason']}"
                )
        else:
            elem.geometry_status = GeometryStatus.FAILED
            if elem.has_3d_geometry and elem.mapping_status != MappingStatus.DEVIATED:
                elem.mapping_status = MappingStatus.UNSUPPORTED
                elem.validation_notes.append("No mesh generated by OpenCASCADE kernel.")
        assign_source_openings(elem, ifc_file, settings)

    if all_verts:
        canonical_model.model_bounds = bounds_for_vertices(all_verts)

    return canonical_model


def opening_diagnostic(mesh, notes):
    if mesh is None:
        return "; ".join(notes) or "No opening mesh generated"
    if not valid_solid(mesh):
        return f"Invalid opening solid: {inspect_mesh_quality(mesh)}"
    return None


@operation("IFC_GEOMETRY")
def process_reference_geometry(model, ifc_file):
    """Recompute audit geometry from its reopened source, without converter cache.

    The reader never uses converter meshes/proofs/cache or bounding-box
    substitutes. Numerical normalization is independently recomputed from a
    fresh native iterator; missing native outputs receive create_shape calls.
    """
    import os

    settings = create_geom_settings()
    pending = {e.step_id: e for e in model.elements if e.has_3d_geometry}
    total = len(pending)
    completed = 0

    def assign(element, mesh):
        nonlocal completed
        mesh, element.geometry_diagnostics = prepare_source_mesh(mesh)
        element.mesh = mesh
        element.bounding_box = bounds_for_vertices(mesh.vertices) if mesh else None
        element.geometry_status = (
            GeometryStatus.VALID if mesh and valid_solid(mesh) else GeometryStatus.FAILED
        )
        assign_source_openings(element, ifc_file, settings)
        completed += 1
        if completed % 16 == 0 or completed == total:
            progress("IFC_GEOMETRY", "RUNNING", completed=completed, total=total)

    try:
        iterator = (
            ifcopenshell.geom.iterator(
                settings, ifc_file, min(4, os.cpu_count() or 1),
                include=[ifc_file.by_id(step) for step in pending],
            ) if pending else None
        )
        if iterator and iterator.initialize():
            while True:
                shape = iterator.get()
                element = pending.get(shape.id)
                if element is not None:
                    assign(element, mesh_from_geometry(shape.geometry))
                    pending.pop(shape.id)
                if not iterator.next():
                    break
    except Exception as exc:
        for element in pending.values():
            element.validation_notes.append(f"Independent iterator fallback: {exc}")
    for element in pending.values():
        assign(element, extract_element_geometry(ifc_file, element, settings))
    return model
