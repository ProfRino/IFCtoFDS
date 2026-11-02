import json
from unittest.mock import patch
import pytest

from ifc_to_fds.adapters.jobs.runner import WorkerRunner
from ifc_to_fds.application.services.scenario_base import load_verified_base
from ifc_to_fds.domain.mapping import build_mapping_plan
from ifc_to_fds.domain.validation import GateResult, GateStatus
from ifc_to_fds.fire.scenario_composer import compose_scenario
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
    assert closures[0].values.get('CTRL_ID')
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
    bundle = emit_fire_scenario(plan,'b'*64,[dict(preset_id='auto-nmc',position=[5,5,.75])],opening_states=events)
    parsed = parse_fds("&HEAD CHID='doors' /\n&TIME T_END=0 /\n&MESH IJK=1,1,1, XB=0,10,0,10,0,4 /\n"+bundle.fds_fragment+'\n&TAIL /')
    assert not parsed.errors
    controls = [r.id for r in parsed.records if r.kind=='CTRL']
    assert len(controls)==len(set(controls))==2
