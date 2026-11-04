import pytest
from ifc_to_fds.core.canonical import (
    CanonicalModel,
    CanonicalElement,
    SourceMetadata,
    BoundingBox,
    GeometryStatus,
)
from ifc_to_fds.geometry.mesh import box_mesh
from ifc_to_fds.mapping.policy import plan_mapping


@pytest.fixture(autouse=True)
def isolate_automatic_solver_execution(request, monkeypatch):
    """Keep unit/API workers independent of external software on the test host.

    Spawned conversion workers inherit this operator option. Explicit solver
    paths (e.g. the timeout adapter fixture) remain usable; real solver tests
    opt into their installed FDS through the existing solver marker.
    """
    if request.node.get_closest_marker("solver") is None:
        monkeypatch.setenv("IFCFDS_SOLVER_AUTODISCOVERY", "0")
        monkeypatch.delenv("IFCFDS_SOLVER", raising=False)


@pytest.fixture
def box_model():
    source = SourceMetadata(
        source_id="fixture",
        filename="box.ifc",
        file_path="box.ifc",
        file_hash_sha256="fixture",
        file_size_bytes=0,
        schema_version="IFC4",
    )
    bounds = BoundingBox(xmin=0, xmax=2, ymin=0, ymax=1, zmin=0, zmax=3)
    wall = CanonicalElement(
        source_id="fixture",
        entity_key="fixture:1",
        global_id="wall-guid",
        step_id=1,
        ifc_type="IfcWall",
        name="Wall",
        has_3d_geometry=True,
        geometry_status=GeometryStatus.VALID,
        bounding_box=bounds,
        mesh=box_mesh(bounds),
    )
    model = CanonicalModel(
        source=source, sources=[source], elements=[wall], model_bounds=bounds
    )
    return plan_mapping(model)


@pytest.fixture
def tiny_ifc(tmp_path):
    import ifcopenshell.api.project
    import ifcopenshell.api.root
    import ifcopenshell.api.unit
    import ifcopenshell.api.context
    import ifcopenshell.api.geometry
    import ifcopenshell.api.aggregate
    import ifcopenshell.api.spatial

    file = ifcopenshell.api.project.create_file(version="IFC4")
    project = ifcopenshell.api.root.create_entity(
        file, ifc_class="IfcProject", name="Test"
    )
    ifcopenshell.api.unit.assign_unit(
        file, units=[ifcopenshell.api.unit.add_si_unit(file, unit_type="LENGTHUNIT")]
    )
    context = ifcopenshell.api.context.add_context(file, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        file,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=context,
    )
    storey = ifcopenshell.api.root.create_entity(
        file, ifc_class="IfcBuildingStorey", name="Ground"
    )
    storey.Elevation = 0.0
    ifcopenshell.api.aggregate.assign_object(
        file, products=[storey], relating_object=project
    )
    wall = ifcopenshell.api.root.create_entity(file, ifc_class="IfcWall", name="Wall")
    ifcopenshell.api.spatial.assign_container(
        file, products=[wall], relating_structure=storey
    )
    representation = ifcopenshell.api.geometry.add_wall_representation(
        file, context=body, length=2.0, height=3.0, thickness=1.0
    )
    ifcopenshell.api.geometry.assign_representation(
        file, product=wall, representation=representation
    )
    ifcopenshell.api.geometry.edit_object_placement(file, product=wall)
    path = tmp_path / "tiny.ifc"
    file.write(str(path))
    return path, file, wall
