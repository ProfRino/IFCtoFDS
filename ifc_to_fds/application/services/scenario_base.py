"""Resolve an accepted artifact bundle; never synthesize a replacement building."""

import hashlib
import json
from pathlib import Path
from ifc_to_fds.domain.bim import BoundingBox
from ifc_to_fds.domain.mapping import MappingDecision, MappingManifest, MappingPlan
from ifc_to_fds.domain.validation import AcceptanceReport
from ifc_to_fds.geometry.package import verify_package
from ifc_to_fds.geometry.storage import DiskPackage
from ifc_to_fds.validation.parser import parse_fds


def load_verified_base(job_root, bundle_sha):
    if not isinstance(bundle_sha, str) or len(bundle_sha) != 64 or any(c not in "0123456789abcdef" for c in bundle_sha):
        raise ValueError("A valid verified base bundle hash is required")
    for directory in sorted(Path(job_root).iterdir()):
        path = directory / "model_manifest.json"
        if not directory.is_dir() or not path.is_file():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("bundle_sha256") != bundle_sha:
            continue
        manifest = MappingManifest.model_validate(raw)
        if (manifest.compute_bundle_sha256() != bundle_sha or not manifest.output_complete
                or manifest.mapping_acceptance != "MAPPING_VERIFIED"):
            raise ValueError("Base artifact is unsealed or not MAPPING_VERIFIED")
        report = AcceptanceReport.model_validate_json((directory / "model_acceptance_report.json").read_text(encoding="utf-8"))
        if report.finalize().mapping_status.value != "MAPPING_VERIFIED":
            raise ValueError("Base acceptance report does not verify the mapping")
        text = (directory / "model.fds").read_bytes().decode("utf-8")
        if hashlib.sha256(text.encode()).hexdigest() != manifest.fds_sha256:
            raise ValueError("Base FDS hash differs from verified manifest")
        package = DiskPackage(directory / "model_geometry.json")
        verify_package(package)
        if package["sha256"] != manifest.geometry_package_sha256:
            raise ValueError("Base geometry package differs from verified manifest")
        parsed = parse_fds(text)
        if parsed.errors or parsed.unsupported:
            raise ValueError("Verified base FDS cannot be parsed with supported grammar")
        decisions = [MappingDecision(
            entity_key=r.entity_key, strategy=r.mapping_strategy, simulation_role=r.simulation_role,
            fds_representation=r.fds_representation, fds_primitive_ids=r.fds_primitive_ids,
            representation_bounds=r.representation_bounds, element_bounds=r.source_bounds,
            scope_decision=r.scope_decision, decision=r.decision, review_status=r.review_status,
        ) for r in manifest.records]
        plan = MappingPlan(decisions=decisions,
                           simulation_domain=BoundingBox.model_validate(manifest.simulation_domain),
                           cell_size=manifest.configuration.get("cell_size", 0.2))
        return text, plan, manifest
    raise ValueError("Verified base bundle not found; convert and verify the building first")
