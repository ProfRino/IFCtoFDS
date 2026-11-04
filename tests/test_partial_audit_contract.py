"""Explicit partial evidence must never turn a rejected package into a pass."""

import pytest
from pydantic import ValidationError

from ifc_to_fds.mapping.exporter import serialize_fds
from ifc_to_fds.mapping.policy import plan_mapping
from ifc_to_fds.validation.acceptance import AuditConfig
import ifc_to_fds.validation.engine as engine


def mixed_artifact(model):
    healthy = model.elements[0].model_copy(deep=True)
    healthy.entity_key, healthy.step_id, healthy.global_id = "fixture:2", 2, "healthy"
    model.elements.append(healthy)
    model.elements[0].mesh.faces.pop()
    plan_mapping(model)
    text, manifest = serialize_fds(model)
    return healthy, text, manifest


def block_global_checks(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Rejected source topology must block dependent global checks")

    monkeypatch.setattr(engine, "solver_gates", forbidden)
    monkeypatch.setattr(
        "ifc_to_fds.validation.checkers.air_path.AirPathTopologyChecker.check", forbidden
    )


def test_fast_preflight_reports_written_as_uncompared(box_model, monkeypatch):
    healthy, text, manifest = mixed_artifact(box_model)
    block_global_checks(monkeypatch)
    monkeypatch.setattr(engine, "compare_solids", lambda *a: pytest.fail("fail-fast"))
    report = engine.run_independent_validation(
        box_model, text, manifest, AuditConfig(fail_fast_on_source_errors=True)
    )
    counts = report.coverage["fds_export"]
    assert counts["entities"] == counts["not_compared_entities"] == 1
    assert counts["comparison_mode"] == "FAIL_FAST"
    assert counts["attempted_entities"] == counts["compared_entities"] == 0
    assert counts["source_invalid_entities"] == counts["skipped_for_source_errors"] == 1
    assert report.element_statuses[healthy.entity_key] == "INCONCLUSIVE"
    assert "not compared" in report.to_markdown().lower()
    assert report.status == "REJECTED"


def test_partial_mode_checks_healthy_peer_but_blocks_global_checks(box_model, monkeypatch):
    healthy, text, manifest = mixed_artifact(box_model)
    block_global_checks(monkeypatch)
    report = engine.run_independent_validation(
        box_model, text, manifest,
        AuditConfig(fail_fast_on_source_errors=True, collect_partial_geometry_evidence=True),
    )
    counts = report.coverage["fds_export"]
    assert counts["comparison_mode"] == "PARTIAL"
    assert counts["attempted_entities"] == counts["compared_entities"] == 1
    assert counts["verified_entities"] == 1
    assert counts["not_compared_entities"] == counts["skipped_for_source_errors"] == 0
    assert counts["source_invalid_entities"] == 1
    assert not counts["comparisons_skipped_for_source_errors"]
    assert report.element_statuses[healthy.entity_key] == "MATCHED"
    assert report.gates["geometry"].status == "FAIL"
    assert report.gates["air_path"].status == report.gates["solver"].status == "NOT_RUN"
    assert report.gates["effective_geometry"].status == "NOT_RUN"
    assert report.status == report.simulation_status == "REJECTED"


@pytest.mark.parametrize("failure", [ValueError("invalid output"), RuntimeError("backend unavailable")])
def test_attempt_is_not_misreported_as_completed_comparison(box_model, monkeypatch, failure):
    healthy, text, manifest = mixed_artifact(box_model)
    block_global_checks(monkeypatch)

    def failed(*args):
        raise failure

    monkeypatch.setattr(engine, "compare_solids", failed)
    report = engine.run_independent_validation(
        box_model, text, manifest,
        AuditConfig(fail_fast_on_source_errors=True, collect_partial_geometry_evidence=True),
    )
    counts = report.coverage["fds_export"]
    assert counts["attempted_entities"] == counts["not_compared_entities"] == 1
    assert counts["compared_entities"] == counts["verified_entities"] == 0
    assert counts["failed_comparison_entities"] == int(isinstance(failure, ValueError))
    assert counts["inconclusive_comparison_entities"] == int(not isinstance(failure, ValueError))
    assert report.status == "REJECTED"


def test_partial_mode_cannot_hide_measured_deviation(box_model, monkeypatch):
    healthy, text, manifest = mixed_artifact(box_model)
    block_global_checks(monkeypatch)
    original = engine.compare_solids

    def deviated(*args):
        metrics = original(*args)
        metrics["solid_iou"] = 0.5
        return metrics

    monkeypatch.setattr(engine, "compare_solids", deviated)
    report = engine.run_independent_validation(
        box_model, text, manifest,
        AuditConfig(fail_fast_on_source_errors=True, collect_partial_geometry_evidence=True),
    )
    counts = report.coverage["fds_export"]
    assert counts["compared_entities"] == counts["deviated_entities"] == 1
    assert counts["not_compared_entities"] == counts["verified_entities"] == 0
    assert report.element_statuses[healthy.entity_key] == "DEVIATED"
    assert report.status == "REJECTED"


def test_partial_switch_requires_actual_boolean():
    with pytest.raises(ValidationError):
        AuditConfig(collect_partial_geometry_evidence="yes")


@pytest.mark.parametrize("partial", [False, True])
def test_runner_uses_the_same_preflight_and_comparison_coverage(box_model, monkeypatch, partial):
    from ifc_to_fds.validation.runner import ValidationRunner

    healthy, text, manifest = mixed_artifact(box_model)
    block_global_checks(monkeypatch)

    def forbidden(*args, **kwargs):
        pytest.fail("Preflight must block dependent checks in ValidationRunner")

    monkeypatch.setattr("ifc_to_fds.validation.checkers.solver.SolverChecker.check", forbidden)
    monkeypatch.setattr("ifc_to_fds.validation.checkers.openings.OpeningsChecker.check", forbidden)
    config = AuditConfig(fail_fast_on_source_errors=True, collect_partial_geometry_evidence=partial)
    engine_report = engine.run_independent_validation(box_model, text, manifest, config)
    runner_report = ValidationRunner().validate(box_model, text, manifest, config)
    assert runner_report.coverage["fds_export"] == engine_report.coverage["fds_export"]
    assert runner_report.element_statuses[healthy.entity_key] == engine_report.element_statuses[healthy.entity_key]
    assert runner_report.status == engine_report.status == "REJECTED"
    for gate in ("openings", "air_path", "solver", "effective_geometry"):
        assert runner_report.gates[gate].status == engine_report.gates[gate].status == "NOT_RUN"
