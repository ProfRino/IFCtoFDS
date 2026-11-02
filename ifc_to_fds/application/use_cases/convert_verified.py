"""ConvertVerified use case: end-to-end verified BIM-to-FDS conversion."""

import tempfile
import json
import gc
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional, Union

from ifc_to_fds.domain.mapping import MappingManifest, build_mapping_plan
from ifc_to_fds.domain.validation.model import GateResult, GateStatus
from ifc_to_fds.geometry.storage import write_package
from ifc_to_fds.mapping.exporter import serialize_fds

from ..dto.configuration import validate_configuration
from .audit_conversion import AuditConversionUseCase, prepare_model


class ConvertVerifiedUseCase:
    """Orchestrates verified conversion of IFC models to FDS input."""

    def __init__(self, audit_use_case: Optional[AuditConversionUseCase] = None):
        self.audit_use_case = audit_use_case or AuditConversionUseCase()

    def execute(
        self,
        paths: List[str],
        configuration: Optional[Dict[str, Any]] = None,
        output_directory: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        configuration = validate_configuration(configuration or {})
        start = perf_counter()
        model = prepare_model(paths, configuration)
        configuration["rebase_vector"] = model.source.rebase_vector
        prepared = perf_counter()
        cell_size = configuration.get("cell_size", 0.2)
        from ifc_to_fds.mep.network import build_hvac_network
        mapping_plan = build_mapping_plan(model, cell_size=cell_size, hvac_network=build_hvac_network(model))
        fds, manifest = serialize_fds(
            model, cell_size=cell_size, mapping_plan=mapping_plan
        )
        serialized = perf_counter()

        owner = (
            tempfile.TemporaryDirectory(prefix="ifcfds-artifacts-")
            if output_directory is None
            else None
        )
        workspace = Path(owner.name if owner is not None else (output_directory or "."))
        workspace.mkdir(parents=True, exist_ok=True)
        geometry_package = write_package(
            model, workspace / "model_geometry.json", owner
        )
        (workspace / "model.fds").write_bytes(fds.encode("utf-8"))
        (workspace / "mapping_plan.json").write_text(mapping_plan.model_dump_json(), encoding="utf-8")
        packaged = perf_counter()
        configuration["geometry_package_sha256"] = geometry_package["sha256"]
        manifest.geometry_package_sha256 = geometry_package["sha256"]
        configuration["mep_graph"] = model.mep_graph.model_dump(mode="json")
        manifest.configuration = configuration
        manifest.reseal()
        manifest_path = workspace / "model_manifest.json"
        manifest_path.write_text(manifest.model_dump_json(), encoding="utf-8")
        # Durable checkpoint before the independent audit. These are explicitly
        # unaccepted artifacts, useful even when a large audit is interrupted.
        def sanitize_portable_paths(obj):
            if isinstance(obj, dict):
                return {
                    k: (Path(v).name if k == "file_path" and isinstance(v, str) else sanitize_portable_paths(v))
                    for k, v in obj.items()
                }
            elif isinstance(obj, list):
                return [sanitize_portable_paths(x) for x in obj]
            return obj

        clean_checkpoint_inventory = sanitize_portable_paths(
            model.model_dump(
                mode="json",
                exclude={
                    "elements": {
                        "__all__": {
                            "mesh": True,
                            "openings": {"__all__": {"mesh": True}},
                        }
                    }
                },
            )
        )
        for name, value in (
            ("inventory", clean_checkpoint_inventory),
            ("mep_graph", configuration["mep_graph"]),
            ("configuration", configuration),
        ):
            (workspace / f"model_{name}.json").write_text(
                json.dumps(value), encoding="utf-8"
            )
        (workspace / "audit-state.json").write_text(
            json.dumps(
                {
                    "stage": "VALIDATION",
                    "status": "NOT_RUN",
                    "checkpoint_status": "DRAFT_NOT_SEALED",
                    "output_complete": False,
                    "bundle_sha256": manifest.bundle_sha256,
                    "reason": "Artifacts saved; independent audit has not completed",
                }
            ),
            encoding="utf-8",
        )
        manifest = MappingManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        # The auditor reopens the source. Release the converter's full meshes
        # before constructing that independent model, rather than retaining both.
        source_timings = dict(model.timings)
        exported_bounds = model.exported_bounds
        del mapping_plan, model
        gc.collect()
        fds = (workspace / "model.fds").read_bytes().decode("utf-8")
        audited, manifest, report = self.audit_use_case.execute(
            paths, fds, manifest, configuration, geometry_package
        )
        timings = dict(
            **source_timings,
            prepare_s=prepared - start,
            serialize_s=serialized - prepared,
            package_write_s=packaged - serialized,
            **report.metrics.get("stage_timings", {}),
            audit_s=perf_counter() - serialized,
        )
        (workspace / "model_manifest.json").write_text(
            manifest.model_dump_json(), encoding="utf-8"
        )
        (workspace / "audit-state.json").write_text(
            json.dumps(
                {
                    "stage": "VALIDATION",
                    "status": report.status.value,
                    # NOTE: finalize() never issues SIMULATION_VERIFIED yet
                    # (simulation_status is REJECTED or INCONCLUSIVE only), so the
                    # MAPPING_VERIFIED-only seal is intentional; full dual-state
                    # acceptance rides with the simulation epic (Phase E).
                    "checkpoint_status": "DRAFT_NOT_SEALED" if report.status.value != "MAPPING_VERIFIED" else "VERIFIED_SEALED",
                    "output_complete": manifest.output_complete,
                    "bundle_sha256": manifest.bundle_sha256,
                    "timings": timings,
                }
            ),
            encoding="utf-8",
        )
        from ifc_to_fds.core import get_execution_provenance

        audited.exported_bounds = exported_bounds
        audited.timings = timings
        report.metrics["exported_bounds"] = (
            exported_bounds.model_dump() if exported_bounds else None
        )
        report.metrics["execution_provenance"] = get_execution_provenance()
        return dict(
            status=report.status.value,
            mapping_status=report.mapping_status.value,
            simulation_status=report.simulation_status.value,
            output_complete=manifest.output_complete,
            geometry_package=geometry_package,
            parity_report=report.gates.get(
                "golden_reference_parity", GateResult(status=GateStatus.NOT_RUN)
            ).model_dump(mode="json"),
            fds_text=fds,
            manifest=manifest.model_dump(mode="json"),
            report=report.model_dump(mode="json"),
            markdown_report=report.to_markdown(),
            inventory=sanitize_portable_paths(
                audited.model_dump(
                    mode="json",
                    exclude={
                        "elements": {
                            "__all__": {
                                "mesh": True,
                                "openings": {"__all__": {"mesh": True}},
                            }
                        }
                    },
                )
            ),
            mep_graph=audited.mep_graph.model_dump(mode="json"),
            configuration=configuration,
            timings=timings,
        )
