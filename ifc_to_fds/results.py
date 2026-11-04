"""Public, bounded result metadata and registered research-source discovery."""

import json
import os
from pathlib import Path


def registered_cases():
    result = []
    from ifc_to_fds.adapters.reference import FilesystemReferenceRepository
    repo = FilesystemReferenceRepository()
    for key, value in json.loads(
        os.environ.get("IFCFDS_REFERENCE_CASES", "{}")
    ).items():
        path = Path(value if isinstance(value, str) else value["path"])
        try:
            sources = json.loads((path / "sources.json").read_text(encoding="utf-8"))[
                "sources"
            ]
            approval = json.loads((path / "approval.json").read_text(encoding="utf-8"))
            try:
                checksum = repo.bundle_digest(path)
                if approval.get("bundle_sha256") == checksum:
                    integrity_status = "VERIFIED"
                    approval_status = approval.get("status", "DRAFT")
                else:
                    integrity_status = "CORRUPTED"
                    approval_status = "UNVERIFIED_CORRUPT"
            except Exception:
                integrity_status = "CORRUPTED"
                approval_status = "UNVERIFIED_CORRUPT"

            result.append(
                dict(
                    id=key,
                    name=value.get("name", key) if isinstance(value, dict) else key,
                    source_hashes=[s["file_hash_sha256"] for s in sources],
                    approval_status=approval_status,
                    integrity_status=integrity_status,
                )
            )
        except (OSError, ValueError, KeyError):
            result.append(
                dict(id=key, name=key, source_hashes=[], approval_status="UNAVAILABLE", integrity_status="UNAVAILABLE")
            )
    return result


def research_context(sources, config, report=None):
    hashes = {s["file_hash_sha256"] for s in sources}
    matches = []
    for case in registered_cases():
        expected = set(case["source_hashes"])
        if hashes & expected:
            matches.append(
                {**case, "source_match": "EXACT" if hashes == expected else "PARTIAL"}
            )
    gate = (report or {}).get("gates", {}).get("golden_reference_parity", {})
    return dict(
        known_cases=matches,
        profile=config.get("profile", "mapping"),
        parity_status=gate.get("status", "NOT_RUN")
        if config.get("reference_case")
        else "NOT_RUN",
        research_acceptance=(report or {}).get("mapping_status", "INCONCLUSIVE")
        if config.get("profile") == "research-basement"
        else "NOT_RUN",
    )


ARTIFACTS = {
    "fds": "model.fds",
    "scenario_fds": "scenario.fds",
    "scenario": "scenario.json",
    "manifest": "model_manifest.json",
    "manifest_csv": "model_manifest.csv",
    "report": "model_acceptance_report.json",
    "markdown": "model_acceptance_report.md",
    "inventory": "model_inventory.json",
    "mep": "model_mep_graph.json",
    "configuration": "model_configuration.json",
    "geometry": "model_geometry.json",
    "geometry_archive": "model_geometry.zip",
    "parity": "model_parity.json",
    "checksums": "model_checksums.json",
}


def public_result(result, directory=None):
    report = result["report"]

    def counts(value):
        if isinstance(value, dict):
            return {k: counts(v) for k, v in value.items()}
        if isinstance(value, list):
            return len(value)
        return value

    all_findings = report.get("findings", [])
    dir_path = Path(directory) if directory else None
    available_artifacts = {
        k: dict(filename=v)
        for k, v in ARTIFACTS.items()
        if dir_path is None or (dir_path / v).is_file()
    }

    return dict(
        schema_version="0.5.0",
        status=result["status"],
        mapping_status=result["mapping_status"],
        simulation_status=result["simulation_status"],
        output_complete=result["output_complete"],
        source_filename=result["manifest"]["source_filename"],
        profile=result["configuration"].get("profile", "mapping"),
        coverage=counts(report["coverage"]),
        timings=result["timings"],
        gates={
            k: dict(
                status=v["status"], required=v["required"], reason=v["reason"][:1000],
                reason_code=v.get("reason_code", ""),
            )
            for k, v in report["gates"].items()
        },
        findings=all_findings,
        findings_count=len(all_findings),
        blocker_count=sum(
            v["required"] and v["status"] not in ("PASS", "NOT_APPLICABLE")
            for v in report["gates"].values()
        ),
        research=research_context(
            result["manifest"]["sources"], result["configuration"], report
        ),
        artifacts=available_artifacts,
    )
