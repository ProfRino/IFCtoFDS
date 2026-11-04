"""Lossless mesh payloads, with one-mesh-at-a-time reads and a sealed index."""

from collections.abc import Mapping
import copy
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
import numpy as np
from uuid import uuid4
from ifc_to_fds.diagnostics import operation

from .package_integrity import seal, verify_package_metadata
from ifc_to_fds.core.canonical import SCHEMA_VERSION


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def payload_dir(path):
    return Path(path).with_suffix(".payloads")


def store_mesh(mesh, directory):
    if mesh is None:
        return None
    vertices = np.asarray(mesh.vertices, dtype="<f8").reshape(-1, 3)
    faces = np.asarray(mesh.faces, dtype=np.int64).reshape(-1, 3)
    if not np.isfinite(vertices).all() or (
        faces.size and (faces.min() < 0 or faces.max() >= len(vertices))
    ):
        raise ValueError("Invalid mesh coordinates/indices")
    faces = faces.astype("<u4")
    h = hashlib.sha256()
    h.update(vertices.tobytes())
    h.update(faces.tobytes())
    key = h.hexdigest()
    target = directory / (key + ".bin")
    if (
        not target.is_file()
        or target.stat().st_size != vertices.nbytes + faces.nbytes
        or file_hash(target) != key
    ):
        temporary = directory / (key + "." + uuid4().hex + ".tmp")
        with temporary.open("wb") as stream:
            stream.write(vertices.tobytes())
            stream.write(faces.tobytes())
        temporary.replace(target)
    return dict(
        payload=key,
        vertex_count=len(vertices),
        face_count=len(faces),
        vertices_offset=0,
        faces_offset=vertices.nbytes,
        byte_length=vertices.nbytes + faces.nbytes,
        is_closed_manifold=mesh.is_closed_manifold,
        has_consistent_normals=mesh.has_consistent_normals,
    )


class LazyElements(Mapping):
    def __init__(self, package):
        self.package = package

    def __iter__(self):
        return iter(self.package.index["elements"])

    def __len__(self):
        return len(self.package.index["elements"])

    def __getitem__(self, key):
        if key in self.package.overrides:
            return self.package.overrides[key]
        entry = copy.deepcopy(self.package.index["elements"][key])
        entry["mesh"] = self.package.mesh(entry.get("mesh"))
        entry["openings"] = {
            k: self.package.mesh(v) for k, v in entry.get("openings", {}).items()
        }
        return entry


class DiskPackage(dict):
    def __init__(self, path, owner=None):
        self.path = Path(path)
        self.owner = owner
        self.overrides = {}
        self.index = json.loads(self.path.read_text(encoding="utf-8"))
        super().__init__(self.index)
        self["elements"] = LazyElements(self)

    def __deepcopy__(self, memo):
        return DiskPackage(self.path, self.owner)

    def mesh(self, ref):
        if ref is None:
            return None
        key = ref["payload"]
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("Invalid payload identity")
        path = payload_dir(self.path) / (key + ".bin")
        nv, nf = ref["vertex_count"], ref["face_count"]
        if not isinstance(nv, int) or not isinstance(nf, int) or min(nv, nf) < 0:
            raise ValueError("Invalid mesh dimensions")
        if (
            ref["vertices_offset"] != 0
            or ref["faces_offset"] != nv * 24
            or ref["byte_length"] != nv * 24 + nf * 12
        ):
            raise ValueError("Invalid mesh offsets/length")
        if (
            not path.is_file()
            or path.stat().st_size != ref["byte_length"]
            or file_hash(path) != key
        ):
            raise ValueError("Missing or corrupted geometry payload: " + key)
        with path.open("rb") as stream:
            vertices = np.fromfile(stream, dtype="<f8", count=nv * 3).reshape(-1, 3)
            faces = np.fromfile(stream, dtype="<u4", count=nf * 3).reshape(-1, 3)
        if not np.isfinite(vertices).all() or (faces.size and faces.max() >= nv):
            raise ValueError("Invalid payload coordinates/indices")
        return dict(
            vertices=vertices.tolist(),
            faces=faces.tolist(),
            is_closed_manifold=ref.get("is_closed_manifold", False),
            has_consistent_normals=ref.get("has_consistent_normals", False),
        )

    def verify_index(self):
        if self.index.get("storage_format") != "float64-uint32-le-v1":
            raise ValueError("Geometry index format mismatch")
        verify_package_metadata(self.index)

    def verify(self):
        self.verify_index()
        for entry in self.index["elements"].values():
            for ref in [entry.get("mesh"), *entry.get("openings", {}).values()]:
                self.mesh(ref)


@operation("ARTIFACT")
def write_package(model, path, owner=None):
    path = Path(path)
    directory = payload_dir(path)
    directory.mkdir(parents=True, exist_ok=True)
    entries = {}
    for e in model.elements:
        entries[e.entity_key] = dict(
            source_id=e.source_id,
            global_id=e.global_id,
            entity_key=e.entity_key,
            simulation_role=e.simulation_role,
            scope_decision=e.scope_decision.value,
            ifc_type=e.ifc_type,
            name=e.name,
            step_id=e.step_id,
            transform=e.transform,
            placement=e.placement,
            ports=[p.model_dump(mode="json") for p in e.ports],
            mesh=store_mesh(e.mesh, directory),
            openings={
                str(o.opening_step_id): store_mesh(o.mesh, directory)
                for o in e.openings
            },
        )
    index = seal(
        dict(
            schema_version=SCHEMA_VERSION,
            storage_format="float64-uint32-le-v1",
            units="METRE",
            coordinate_frame="COMMON_WORLD",
            sources=[
                dict(source_id=s.source_id, world_transform=s.world_transform)
                for s in model.sources or [model.source]
            ],
            elements=entries,
        )
    )
    path.write_text(
        json.dumps(index, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )
    return DiskPackage(path, owner)


def read_package(path):
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return DiskPackage(path) if data.get("storage_format") else data


def copy_package(package, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(package, DiskPackage):
        if package.path.resolve() != path.resolve():
            shutil.copyfile(package.path, path)
            shutil.copytree(
                payload_dir(package.path), payload_dir(path), dirs_exist_ok=True
            )
    else:
        path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")


def archive_package(path, target):
    index = json.loads(Path(path).read_text(encoding="utf-8"))
    linked = {
        ref["payload"]
        for entry in index["elements"].values()
        for ref in [entry.get("mesh"), *entry.get("openings", {}).values()]
        if ref and "payload" in ref
    }
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(path, "index.json")
        for key in sorted(linked):
            payload = payload_dir(path) / (key + ".bin")
            archive.write(payload, "index.payloads/" + payload.name)


def restore_package(zip_path, target_json_path):
    """Safely extracts a geometry package archive (.zip) and verifies all payload digests.

    Includes strict Zip-slip protection preventing directory traversal.
    """
    zip_path = Path(zip_path)
    target_json = Path(target_json_path).resolve()
    target_payloads = payload_dir(target_json)
    target_json.parent.mkdir(parents=True, exist_ok=True)
    target_payloads.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.infolist():
            # Zip-slip prevention: sanitize and reject path traversal attempts
            norm_name = Path(member.filename).as_posix()
            if norm_name.startswith("/") or ".." in norm_name.split("/") or ":" in norm_name:
                raise ValueError(f"Security: Malicious path traversal detected in archive: {member.filename}")
            if member.is_dir():
                continue

            if norm_name == "index.json":
                content = archive.read(member)
                target_json.write_bytes(content)
            elif norm_name.startswith("index.payloads/"):
                payload_name = Path(norm_name).name
                expected_sha = payload_name.removesuffix(".bin")
                content = archive.read(member)
                actual_sha = hashlib.sha256(content).hexdigest()
                if actual_sha != expected_sha:
                    raise ValueError(f"Corrupted payload in archive: {payload_name} (hash mismatch)")
                (target_payloads / payload_name).write_bytes(content)
            else:
                raise ValueError(f"Unexpected file in geometry archive: {member.filename}")

    package = read_package(target_json)
    if isinstance(package, DiskPackage):
        package.verify()
    else:
        verify_package_metadata(package)
    return package

