"""IfcOpenShell preview adapter, without retaining all product meshes in Python.

This is source visualization, never an independent mapping acceptance result.
"""

import json
import os
from pathlib import Path
import ifcopenshell.geom
import ifcopenshell.util.shape
import numpy as np

from ifc_to_fds.core.inventory import extract_inventory
from ifc_to_fds.mep.mep_graph import extract_mep_graph
from ifc_to_fds.geometry.engine import (
    create_geom_settings,
    extract_element_geometry,
    mesh_from_geometry,
)
from ifc_to_fds.geometry.mesh import bounds_for_vertices
from ifc_to_fds.geometry.storage import payload_dir, store_mesh
from ifc_to_fds.core.canonical import SCHEMA_VERSION
from ifc_to_fds.geometry.package import seal
from ifc_to_fds.diagnostics import progress
from .preview_cache import read_preview, save_preview


def preview_model(paths, directory):
    if len(paths) != 1:
        raise ValueError(
            "Preview accepts one source; use Verified Mapping for federation"
        )
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    model, file = extract_inventory(str(paths[0]))
    cached = read_preview(model, directory)
    if cached is not None:
        progress("PREVIEW_CACHE", "COMPLETED")
        return cached
    extract_mep_graph(model, file)
    # Display tessellation is deliberately separate from authoritative extraction.
    # A 0.1 mm mesh for every curved MEP product is excessive for an overview.
    settings = create_geom_settings(linear_deflection=0.005)
    # Keep iterator geometry local so mapped/repeated products can share the
    # kernel's cached shapes. Convert placements to world metres before saving.
    settings.set(settings.USE_WORLD_COORDS, False)
    payloads = payload_dir(directory / "model_geometry.json")
    payloads.mkdir(parents=True, exist_ok=True)
    entries, corners = {}, []
    pending = {
        e.step_id: e
        for e in model.elements
        if e.has_3d_geometry and e.role == "PHYSICAL"
    }
    total = len(pending)
    completed = 0
    progress("IFC_GEOMETRY", "RUNNING", completed=0, total=total)
    for e in model.elements:
        entries[e.entity_key] = dict(
            entity_key=e.entity_key,
            source_id=e.source_id,
            step_id=e.step_id,
            global_id=e.global_id,
            name=e.name,
            ifc_type=e.ifc_type,
            storey=e.storey,
            building_id=e.building_id,
            type_class=e.type_class,
            predefined_type=e.predefined_type,
            ports=[p.model_dump(mode="json") for p in e.ports],
            operational_status="NOT_CONFIGURED"
            if e.classification_evidence
            else "NOT_APPLICABLE",
            system_ids=e.system_ids,
            system_names=e.system_names,
            mep_category=e.mep_category,
            classification_evidence=e.classification_evidence,
            bounds=None,
            mesh=None,
            openings={},
            diagnostic="; ".join(e.validation_notes),
        )

    def save(e, mesh):
        nonlocal completed
        bounds = bounds_for_vertices(mesh.vertices) if mesh else None
        if bounds:
            corners.extend(
                [
                    [bounds.xmin, bounds.ymin, bounds.zmin],
                    [bounds.xmax, bounds.ymax, bounds.zmax],
                ]
            )
            entries[e.entity_key].update(
                bounds=bounds.model_dump(), mesh=store_mesh(mesh, payloads)
            )
        entries[e.entity_key]["diagnostic"] = "; ".join(e.validation_notes)
        completed += 1
        if completed % 16 == 0 or completed == total:
            progress("IFC_GEOMETRY", "RUNNING", completed=completed, total=total)

    # Consume iterator products immediately. Never build a shapes dictionary or
    # a second full model in Python memory. Host geometry includes IFC voids.
    iterator = (
        ifcopenshell.geom.iterator(
            settings,
            file,
            min(4, os.cpu_count() or 1),
            include=[file.by_id(s) for s in pending],
        )
        if pending
        else None
    )
    try:
        if iterator and iterator.initialize():
            while True:
                shape = iterator.get()
                e = pending.get(shape.id)
                if e:
                    g = shape.geometry
                    mesh = mesh_from_geometry(g)
                    matrix = ifcopenshell.util.shape.get_shape_matrix(shape)
                    vertices = np.asarray(mesh.vertices, dtype=float)
                    if vertices.size:
                        mesh.vertices = (vertices @ matrix[:3, :3].T + matrix[:3, 3]).tolist()
                    save(e, mesh)
                    del mesh
                    pending.pop(shape.id)
                if not iterator.next():
                    break
    except Exception as exc:
        for e in pending.values():
            e.validation_notes.append(f"Preview iterator fallback: {exc}")
    for e in pending.values():
        # Per-product fallback uses the ordinary authoritative world placement.
        mesh = extract_element_geometry(file, e, create_geom_settings(linear_deflection=0.005))
        save(e, mesh)
        del mesh
    rendered = sum(bool(e["mesh"]) for e in entries.values())
    failed = sum(
        e.has_3d_geometry and e.role == "PHYSICAL" and not entries[e.entity_key]["mesh"]
        for e in model.elements
    )
    index = seal(
        dict(
            schema_version=SCHEMA_VERSION,
            storage_format="float64-uint32-le-v1",
            units="METRE",
            coordinate_frame="COMMON_WORLD",
            elements=entries,
        )
    )
    (directory / "model_geometry.json").write_text(json.dumps(index), encoding="utf-8")
    (directory / "model_mep_graph.json").write_text(
        model.mep_graph.model_dump_json(), encoding="utf-8"
    )
    bounds = bounds_for_vertices(corners)
    progress("IFC_GEOMETRY", "COMPLETED")
    result = dict(
        status="PREVIEW_ONLY",
        verification="NOT_RUN",
        display_linear_deflection_m=0.005,
        total_elements=len(model.elements),
        rendered_elements=rendered,
        failed_elements=failed,
        bounds=bounds.model_dump() if bounds else None,
        sources=[model.source.model_dump(mode="json")],
        storeys=[s.model_dump(mode="json") for s in model.storey_references],
        artifacts={"geometry": {}, "mep": {}},
    )
    save_preview(model, directory, result)
    return result
