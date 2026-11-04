"""Worker execution runner calling application use cases."""

import json
from pathlib import Path
from typing import Any


class WorkerRunner:
    """Executes background jobs by invoking application use cases."""

    @staticmethod
    def run(directory: str | Path) -> int:
        from ifc_to_fds.diagnostics import execution_scope

        with execution_scope(directory):
            return WorkerRunner.execute(directory)

    @staticmethod
    def execute(directory: str | Path) -> int:
        directory = Path(directory)
        job_id = directory.name
        try:
            request = json.loads(
                (directory / "request.json").read_text(encoding="utf-8")
            )
            job_id = request.get("job_id", job_id)
            if request.get("mode") == "preview":
                from ifc_to_fds.application.use_cases.preview_model import preview_model

                result = preview_model(request["paths"], directory)
            elif request.get("mode") == "inventory":
                from ifc_to_fds.core.inventory import extract_inventory

                models = [extract_inventory(path)[0] for path in request["paths"]]
                result: dict[str, Any] = dict(
                    total_elements=sum(len(m.elements) for m in models),
                    storeys=[s.name for m in models for s in m.storey_references],
                    storey_references=[
                        s.model_dump() for m in models for s in m.storey_references
                    ],
                    sources=[m.source.model_dump() for m in models],
                )
            elif request.get("mode") == "scenario":
                import hashlib
                from ifc_to_fds.application.services.scenario_base import load_verified_base
                from ifc_to_fds.fire.scenario_composer import compose_scenario, configure_scenario_time
                from ifc_to_fds.fire.scenario_emitter import emit_fire_scenario
                from ifc_to_fds.fire.scenario_request import ScenarioRequest
                from ifc_to_fds.fire.physics_assessment import assess_scenario_physics
                from ifc_to_fds.domain.validation.model import ValidationContext, AuditConfig
                from ifc_to_fds.validation.checkers.mesh_resolution import MeshResolutionChecker
                from ifc_to_fds.results import ARTIFACTS

                scenario_payload = request.get("configuration") or {}
                if not scenario_payload and (directory / "scenario.json").is_file():
                    scenario_payload = json.loads((directory / "scenario.json").read_text(encoding="utf-8"))
                scenario = ScenarioRequest.model_validate(scenario_payload)
                base_text, mapping_plan, base_manifest = load_verified_base(directory.parent, scenario.bundle_sha256)
                bundle = emit_fire_scenario(
                    mapping_plan=mapping_plan,
                    bundle_sha256=base_manifest.bundle_sha256,
                    ev_selections=scenario.ev_selections,
                    opening_states=scenario.opening_states,
                    devices=scenario.devices,
                    verification_status="MAPPING_VERIFIED",
                )
                composed = compose_scenario(base_text, bundle, base_manifest)
                final_text, end = configure_scenario_time(composed, bundle.opening_events, scenario.t_end_s)
                mesh_gate = MeshResolutionChecker().check(ValidationContext(
                    model=None, fds_text=final_text, manifest=base_manifest, config=AuditConfig()
                )).result
                physics = assess_scenario_physics(final_text, bundle, scenario.energy_budget)
                scenario_bytes = final_text.encode("utf-8")
                (directory / "scenario.fds").write_bytes(scenario_bytes)
                evidence = dict(
                    mesh_gate.evidence,
                    fds_sha256=hashlib.sha256(scenario_bytes).hexdigest(),
                    t_end_s=end,
                    scenario_id=bundle.scenario_id,
                    bundle_sha256=bundle.bundle_sha256,
                    ev_evaluations=[ev.model_dump() for ev in bundle.ev_selections],
                    physics=physics,
                )
                mesh_status = mesh_gate.status.value
                physics_status = physics.get("status", "INCONCLUSIVE")
                if mesh_status == "FAIL" or physics_status == "FAIL":
                    scenario_verdict = "FAIL"
                else:
                    scenario_verdict = mesh_status
                result = {
                    "status": "COMPLETED",
                    "verdict": scenario_verdict,
                    "mesh_status": mesh_status,
                    "physics_status": physics_status,
                    "simulation_status": "NOT_RUN",
                    "peak_hrr_mw": bundle.total_peak_hrr_mw,
                    "evidence": evidence,
                    "artifacts": {
                        key: dict(filename=name)
                        for key, name in ARTIFACTS.items() if (directory / name).is_file()
                    },
                    "scenario_id": bundle.scenario_id,
                    "bundle_sha256": bundle.bundle_sha256,
                    "fds_file": "scenario.fds",
                }
            else:
                from ifc_to_fds.pipeline import convert, save_artifacts

                result = convert(
                    request["paths"], request["configuration"], str(directory)
                )
                save_artifacts(result, directory / "model.fds")
                from ifc_to_fds.results import public_result

                result = public_result(result, directory=directory)
            if request.get("mode") == "inventory":
                from ifc_to_fds.results import research_context

                result["research"] = research_context(result["sources"], {})
            (directory / "result.json").write_text(json.dumps(result), encoding="utf-8")
            return 0
        except Exception as exc:
            from ifc_to_fds.diagnostics import failure_diagnostic

            diagnostic = failure_diagnostic(exc, job_id)
            (directory / "diagnostics.json").write_text(
                json.dumps(diagnostic), encoding="utf-8"
            )
            (directory / "error.txt").write_text(
                f"{type(exc).__name__}: {exc}", encoding="utf-8"
            )
            return 1
