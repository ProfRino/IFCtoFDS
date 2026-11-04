import json
from unittest.mock import patch
import pytest

from ifc_to_fds.adapters.jobs.runner import WorkerRunner
from ifc_to_fds.application.services.scenario_base import load_verified_base
from ifc_to_fds.domain.mapping import MappingPlan, build_mapping_plan
from ifc_to_fds.domain.validation import GateResult, GateStatus
from ifc_to_fds.fire.scenario_composer import compose_scenario, configure_scenario_time
from ifc_to_fds.fire.scenario_emitter import emit_fire_scenario
from ifc_to_fds.mapping.exporter import serialize_fds
from ifc_to_fds.pipeline import convert, save_artifacts
from ifc_to_fds.validation.engine import run_independent_validation
from ifc_to_fds.validation.parser import parse_fds
from ifc_to_fds.validation.runner import ValidationRunner


def test_scenario_worker_rejects_a_hash_without_a_verified_base(tmp_path):
    directory = tmp_path / 'job-scenario'
    directory.mkdir()
    payload = dict(mode='scenario', configuration=dict(bundle_sha256='a'*64,
                   ev_selections=[dict(preset_id='auto-nmc', position=[5,5,.75])]))
    (directory / 'request.json').write_text(json.dumps(payload))
    assert WorkerRunner.run(directory) == 1
    assert not (directory / 'scenario.fds').exists()
    assert 'Verified base bundle not found' in (directory / 'error.txt').read_text()


def test_verified_base_rejects_changed_fds_and_acceptance(tiny_ifc, tmp_path):
    base = tmp_path / 'base'
    result = convert([str(tiny_ifc[0])], output_directory=base)
    save_artifacts(result, base / 'model.fds')
    digest = result['manifest']['bundle_sha256']
    load_verified_base(tmp_path, digest)
    (base / 'model.fds').write_text(result['fds_text'] + '\n! changed')
    with pytest.raises(ValueError, match='FDS hash'):
        load_verified_base(tmp_path, digest)
    (base / 'model.fds').write_bytes(result['fds_text'].encode())
    path = base / 'model_manifest.json'
    raw = json.loads(path.read_text())
    raw['output_complete'] = False
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match='not MAPPING_VERIFIED'):
        load_verified_base(tmp_path, digest)


def test_door_event_replaces_fixed_base_fill(box_model):
    model = box_model
    door = model.elements[0]
    door.ifc_type = 'IfcDoor'
    # Use a larger verified domain so the EV remains within the CFD model.
    from ifc_to_fds.domain.bim import BoundingBox
    model.simulation_domain = BoundingBox(xmin=-5,xmax=10,ymin=-5,ymax=10,zmin=0,zmax=5)
    base, manifest = serialize_fds(model)
    plan = build_mapping_plan(model)
    bundle = emit_fire_scenario(plan, 'a'*64, [dict(preset_id='auto-nmc',position=[5,5,.75])],
                               opening_states=[dict(entity_key=door.entity_key, state='OPEN', event_time_s=30)])
    text = compose_scenario(base, bundle, manifest)
    closures = [r for r in parse_fds(text).records if r.kind=='OBST' and r.values.get('XB')==door.bounding_box.to_xb()]
    assert len(closures)==1
    assert closures[0].values.get('CTRL_ID') or closures[0].values.get('DEVC_ID')
    assert closures[0].id == door.fds_primitive_ids[0]
    assert closures[0].values['SURF_ID'] == ['GLASS']
    assert parse_fds(base).records, 'Base mapping remains intact'


def test_both_validation_paths_block_coarse_fire_mesh(box_model):
    plan = build_mapping_plan(box_model)
    bundle = emit_fire_scenario(plan, 'a'*64, [dict(preset_id='e-bike-lfp', position=[1,.5,.5])])
    text = "&HEAD CHID='coarse' /\n&TIME T_END=0 /\n&MESH IJK=4,4,4, XB=0,2,0,2,0,2 /\n" + bundle.fds_fragment + '\n&TAIL /'
    with patch('ifc_to_fds.validation.engine.solver_gates') as engine_solver:
        engine = run_independent_validation(box_model, text)
        engine_solver.assert_not_called()
    with patch('ifc_to_fds.validation.checkers.solver.solver_gates') as runner_solver:
        runner = ValidationRunner().validate(box_model, text)
        runner_solver.assert_not_called()
    assert engine.gates['mesh_resolution'].status == runner.gates['mesh_resolution'].status == 'FAIL'


def test_runner_preserves_effective_geometry_result(box_model):
    text, manifest = serialize_fds(box_model)
    with patch('ifc_to_fds.validation.checkers.solver.solver_gates', return_value=(
        GateResult(status=GateStatus.PASS), GateResult(status=GateStatus.FAIL, reason='Changed effective solid')
    )):
        report = ValidationRunner().validate(box_model,text,manifest)
    assert report.gates['effective_geometry'].status == 'FAIL'
    assert report.simulation_status == 'REJECTED'


def test_door_controls_do_not_collide_for_same_ifc_source(box_model):
    plan = build_mapping_plan(box_model)
    events = [dict(entity_key='a'*64 + ':' + str(step),state='OPEN',event_time_s=10) for step in (100,101)]
    original = plan.decisions[0]
    plan = MappingPlan(decisions=[
        original.model_copy(update={"entity_key": event["entity_key"], "fds_representation": "OBST"})
        for event in events
    ])
    bundle = emit_fire_scenario(plan,'b'*64,[dict(preset_id='auto-nmc',position=[5,5,.75])],opening_states=events)
    parsed = parse_fds("&HEAD CHID='doors' /\n&TIME T_END=0 /\n&MESH IJK=1,1,1, XB=0,10,0,10,0,4 /\n"+bundle.fds_fragment+'\n&TAIL /')
    assert not parsed.errors
    controls = [r.id for r in parsed.records if r.kind=='DEVC' and r.values.get("QUANTITY") == ["TIME"]]
    assert len(controls)==len(set(controls))==2


def test_unmapped_opening_cannot_emit_dangling_timer():
    with pytest.raises(ValueError, match="no mapped bounds: absent"):
        emit_fire_scenario(
            MappingPlan(), 'a' * 64,
            [dict(preset_id='e-bike-lfp', position=[1, 1, 1])],
            opening_states=[dict(entity_key='absent', state='OPEN', event_time_s=1)],
        )


@pytest.mark.parametrize("number", ["1.8E3", "1.8e3", "+1.8D3"])
def test_scenario_time_replaces_the_whole_scientific_value(number):
    text = (
        "&HEAD CHID='time', TITLE='&TIME T_END=8000 /' /\n"
        f"! &TIME T_END=9000 /\n&time\n T_END={number} /\n"
        "&MESH IJK=10,10,10, XB=0,1,0,1,0,1 /\n"
        "&RAMP ID='fire', T=1936.2, F=0 /\n&TAIL /\n"
    )
    result, end = configure_scenario_time(text, [])
    assert end == 1936.2
    assert f"&TIME T_END={end} /" in result
    assert "! &TIME T_END=9000 /" in result
    assert "TITLE='&TIME T_END=8000 /'" in result
    assert not parse_fds(result).errors


def test_scenario_time_preserves_longer_base_and_rejects_invalid_requests():
    text = "&HEAD CHID='time' /\n&TIME T_END=2E3 /\n&MESH IJK=1,1,1, XB=0,1,0,1,0,1 /\n&TAIL /"
    assert configure_scenario_time(text, [], 1000)[1] == 2000
    for invalid in (float("nan"), float("inf"), -1, True):
        with pytest.raises(ValueError):
            configure_scenario_time(text, [], invalid)
    with pytest.raises(ValueError, match="exactly one TIME"):
        configure_scenario_time(text.replace("&TAIL /", "&TIME T_END=20 /\n&TAIL /"), [])


def test_vehicle_energy_uses_serialized_burner_and_sourced_budget():
    from ifc_to_fds.fire.physics_assessment import assess_scenario_physics
    from ifc_to_fds.fire.scenario_request import EnergyBudget

    bundle = emit_fire_scenario(MappingPlan(), "a" * 64, [
        dict(preset_id="auto-nmc", position=[5, 5, .75], pack_kwh=40, peak_hrr_mw=7),
    ])
    text = ("&HEAD CHID='physics' /\n&TIME T_END=3000 /\n"
            "&MESH IJK=50,50,20, XB=0,10,0,10,0,4 /\n" + bundle.fds_fragment + "\n&TAIL /")
    no_budget = assess_scenario_physics(text, bundle, None)
    assert no_budget["energy_budget_status"] == "INCONCLUSIVE"
    assert 9010 < no_budget["nominal_energy_mj"] < 9030
    assert no_budget["hf_status"] == "NOT_MODELED"
    budget = EnergyBudget(scope="WHOLE_VEHICLE_FLEET", battery_chemical_energy_mj=1000,
                          other_vehicle_energy_mj=3000, source="Synthetic test budget")
    assert assess_scenario_physics(text, bundle, budget)["status"] == "FAIL"
    larger_budget = budget.model_copy(update={"other_vehicle_energy_mj": 10000})
    assert assess_scenario_physics(text, bundle, larger_budget)["energy_budget_status"] == "PASS"


def test_scenario_request_rejects_conflicting_sources_and_unsupported_hf():
    from ifc_to_fds.fire.scenario_request import ScenarioRequest

    payload = dict(bundle_sha256="a" * 64,
                   ev_selections=[dict(preset_id="auto-nmc", position=[5, 5, .75])])
    with pytest.raises(ValueError, match="Conflicting scenario field"):
        ScenarioRequest.model_validate(dict(payload, scenario_data={"bundle_sha256": "b" * 64}))
    with pytest.raises(ValueError, match="Quantitative HF modeling is unsupported"):
        ScenarioRequest.model_validate(dict(payload, require_quantitative_hf=True))


@pytest.mark.solver
@pytest.mark.parametrize("state", ["OPEN", "CLOSED"])
def test_fds_door_timer_changes_the_actual_fill(state, tmp_path):
    import os
    from pathlib import Path
    import re
    import subprocess

    from ifc_to_fds.domain.bim import BoundingBox
    from ifc_to_fds.domain.mapping import MappingDecision, MappingStrategy
    from ifc_to_fds.validation.solver_discovery import resolve_solver_executable

    executable = resolve_solver_executable(os.environ.get("IFCFDS_SOLVER")).executable
    assert executable is not None, "Solver suite requires FDS 6.11.1"
    executable = Path(executable)
    plan = MappingPlan(decisions=[MappingDecision(
        entity_key="door", strategy=MappingStrategy.OBST, simulation_role="DOOR",
        fds_representation="OBST",
        representation_bounds=BoundingBox(xmin=.4, xmax=.6, ymin=.2, ymax=.8, zmin=.2, zmax=.8),
    )])
    bundle = emit_fire_scenario(
        plan, "a" * 64, [dict(preset_id="e-bike-lfp", position=[2, 2, .55])],
        opening_states=[dict(entity_key="door", state=state, event_time_s=1)],
    )
    door = bundle.fds_fragment.split("! --- Opening & Boundary Controls ---", 1)[1]
    (tmp_path / "input.fds").write_bytes((
        "&HEAD CHID='door' /\n&MESH IJK=10,10,10, XB=0,1,0,1,0,1 /\n"
        "&TIME T_END=2 /\n" + door + "\n&TAIL /\n"
    ).encode())
    run = subprocess.run(
        [str(executable), "input.fds"], cwd=tmp_path, capture_output=True, text=True, timeout=45,
        env={**os.environ, "OMP_NUM_THREADS": "1",
             "PATH": str(executable.parent / "mpi") + os.pathsep + os.environ.get("PATH", "")},
    )
    log = run.stdout + run.stderr
    assert run.returncode == 0 and "completed successfully" in log and "ERROR" not in log, log
    smv = (tmp_path / "door.smv").read_text()
    events = [
        (action, float(when))
        for action, when in re.findall(r"(SHOW|HIDE)_OBST[ \t]+\d+\s+\d+[ \t]+([0-9.]+)", smv)
    ]
    before = [event for event in events if event[1] < 1]
    after = [event for event in events if event[1] >= 1]
    assert before == ([] if state == "OPEN" else [("HIDE", 0.0)]), events
    assert len(after) == 1 and after[0][0] == ("HIDE" if state == "OPEN" else "SHOW"), events
