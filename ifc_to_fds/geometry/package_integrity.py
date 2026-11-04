"""Common schema and digest checks for in-memory and on-disk geometry packages."""

import hashlib
import json

from ifc_to_fds.domain.version import SCHEMA_VERSION


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def seal(package):
    value = {key: item for key, item in package.items() if key != "sha256"}
    return {**value, "sha256": digest(value)}


def verify_package_metadata(package):
    if not isinstance(package, dict) or package.get("sha256") != seal(package)["sha256"]:
        raise ValueError("Geometry package checksum mismatch")
    if (package.get("schema_version") not in (SCHEMA_VERSION, "0.4.0")
            or package.get("units") != "METRE"
            or package.get("coordinate_frame") != "COMMON_WORLD"):
        raise ValueError("Unsupported geometry package schema/units/frame")
    if not isinstance(package.get("elements"), dict):
        raise ValueError("Geometry package element index missing")
