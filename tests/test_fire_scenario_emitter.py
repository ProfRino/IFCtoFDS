"""Tests for EV fire scenario emitter (Task 3)."""

import pytest
import re

from ifc_to_fds.domain.bim.bounding_box import BoundingBox
from ifc_to_fds.domain.mapping import MappingDecision, MappingPlan, MappingStrategy
from ifc_to_fds.fire import (
    DeviceSelection,
    EVSelection,
    OpeningEvent,
    ScenarioBundle,
    emit_fire_scenario,
)


def _sample_mapping_plan() -> MappingPlan:
    return MappingPlan()


def _door(key: str) -> MappingDecision:
    return MappingDecision(
        entity_key=key, strategy=MappingStrategy.OBST, simulation_role="DOOR",
        fds_representation="OBST",
        representation_bounds=BoundingBox(xmin=1, xmax=2, ymin=0, ymax=.2, zmin=0, zmax=2.1),
    )


def _valid_bundle_hash() -> str:
    return "a" * 64


# --- Step 1 & Requirement Tests ---


def test_emitter_rejects_unverified_bundle():
    """Verify ValueError('MAPPING_VERIFIED') is raised when bundle is unverified or stale."""
    plan = _sample_mapping_plan()
    ev = EVSelection(preset_id="e-bike-lfp", position=(0.0, 0.0, 0.55))

    # Stale bundle hash
    with pytest.raises(ValueError, match="MAPPING_VERIFIED"):
        emit_fire_scenario(
            mapping_plan=plan,
            bundle_sha256="stale",
            ev_selections=[ev],
            opening_states={},
            verification_status="MAPPING_VERIFIED",
        )

    # Unverified status
    with pytest.raises(ValueError, match="MAPPING_VERIFIED"):
        emit_fire_scenario(
            mapping_plan=plan,
            bundle_sha256=_valid_bundle_hash(),
            ev_selections=[ev],
            opening_states={},
            verification_status="UNVERIFIED",
        )

    # Empty bundle hash
    with pytest.raises(ValueError, match="MAPPING_VERIFIED"):
        emit_fire_scenario(
            mapping_plan=plan,
            bundle_sha256="",
            ev_selections=[ev],
            opening_states={},
            verification_status="MAPPING_VERIFIED",
        )


def test_emitter_rejects_empty_ev_selections():
    """Verify ValueError is raised when ev_selections is empty."""
    plan = _sample_mapping_plan()
    with pytest.raises(ValueError, match="At least one EV selection is required"):
        emit_fire_scenario(
            mapping_plan=plan,
            bundle_sha256=_valid_bundle_hash(),
            ev_selections=[],
            verification_status="MAPPING_VERIFIED",
        )


def test_emit_single_ebike_fire_scenario():
    """Verify single e-bike emission produces REAC, RAMP, SURF, VENT, OBST in fds_fragment."""
    plan = _sample_mapping_plan()
    ev = EVSelection(preset_id="e-bike-lfp", position=(1.0, 2.0, 0.55))

    bundle = emit_fire_scenario(
        mapping_plan=plan,
        bundle_sha256=_valid_bundle_hash(),
        ev_selections=[ev],
        verification_status="MAPPING_VERIFIED",
    )

    assert isinstance(bundle, ScenarioBundle)
    assert bundle.ev_count == 1
    assert bundle.ev_library_version == "1.0.0"
    assert bundle.bundle_sha256 == _valid_bundle_hash()

    # Peak HRR within e-bike-lfp preset range: (0.02, 0.15) MW
    assert 0.02 <= bundle.total_peak_hrr_mw <= 0.15
    assert bundle.total_peak_hrr_mw == pytest.approx(0.085, rel=1e-3)

    frag = bundle.fds_fragment
    assert "&REAC" in frag
    assert "&RAMP" in frag
    assert "&SURF" in frag
    assert "&VENT" in frag
    assert "&OBST" in frag
    assert "SURF_ID='INERT'" in frag
    assert "HRRPUA=" in frag


def test_emit_auto_fire_scenario():
    """Verify auto-nmc combustion parameters and HRR peak within preset range."""
    plan = _sample_mapping_plan()
    ev = EVSelection(preset_id="auto-nmc", position=(5.0, 5.0, 0.75))

    bundle = emit_fire_scenario(
        mapping_plan=plan,
        bundle_sha256=_valid_bundle_hash(),
        ev_selections=[ev],
        verification_status="MAPPING_VERIFIED",
    )

    assert isinstance(bundle, ScenarioBundle)
    assert bundle.ev_count == 1
    # Auto NMC range: (2.0, 7.0) MW, midpoint = 4.5 MW
    assert 2.0 <= bundle.total_peak_hrr_mw <= 7.0
    assert bundle.total_peak_hrr_mw == pytest.approx(4.5, rel=1e-3)

    frag = bundle.fds_fragment
    # Combustion parameters: CO_YIELD = (0.05 + 0.20)/2 = 0.125, SOOT_YIELD = (0.08 + 0.20)/2 = 0.14
    assert re.search(r"CO_YIELD\s*=\s*0\.125", frag) is not None
    assert re.search(r"SOOT_YIELD\s*=\s*0\.14", frag) is not None

    # Check default dimensions for auto: 4.5 x 1.8 x 1.5
    # Center = (5.0, 5.0, 0.75) -> x=[2.75, 7.25], y=[4.1, 5.9], z=[0.0, 1.5]
    assert "2.75" in frag
    assert "7.25" in frag


def test_emit_cluster_ebikes_with_propagation_delays():
    """Verify multiple e-bikes with staggered ignition delays."""
    plan = _sample_mapping_plan()
    evs = [
        EVSelection(preset_id="e-bike-lfp", position=(0.0, 0.0, 0.55), ignition_delay_s=0.0),
        EVSelection(preset_id="e-bike-lfp", position=(0.0, 1.0, 0.55), ignition_delay_s=60.0),
        EVSelection(preset_id="e-bike-lfp", position=(0.0, 2.0, 0.55), ignition_delay_s=120.0),
    ]

    bundle = emit_fire_scenario(
        mapping_plan=plan,
        bundle_sha256=_valid_bundle_hash(),
        ev_selections=evs,
        verification_status="MAPPING_VERIFIED",
    )

    assert bundle.ev_count == 3
    # Total peak HRR is sum of 3 e-bikes: 3 * 0.085 = 0.255 MW
    assert bundle.total_peak_hrr_mw == pytest.approx(3 * 0.085, rel=1e-3)

    frag = bundle.fds_fragment
    # 3 OBSTs and 3 VENTs
    assert frag.count("&OBST") == 3
    assert frag.count("&VENT") == 3

    # Staggered delays present in RAMP definitions
    assert re.search(r"&RAMP.*T\s*=\s*60\.0", frag) is not None
    assert re.search(r"&RAMP.*T\s*=\s*120\.0", frag) is not None


def test_emit_scenario_with_devices_and_doors():
    """Verify DEVC output and opening events."""
    plan = MappingPlan(decisions=[_door("DOOR_MAIN"), _door("DOOR_FIRE")])
    ev = EVSelection(preset_id="e-bike-lfp", position=(1.0, 1.0, 0.55))
    devices = [
        DeviceSelection(
            id="SPK_01",
            device_type="SPRINKLER",
            position=(2.0, 2.0, 3.0),
            setpoint=68.0,
            quantity="SPRINKLER LINK TEMPERATURE",
        ),
        DeviceSelection(
            id="SMK_01",
            device_type="SMOKE_DETECTOR",
            position=(3.0, 3.0, 3.0),
            setpoint=0.03,
            quantity="CHAMBER OBSCURATION",
        ),
    ]
    opening_states = {
        "DOOR_MAIN": {"state": "OPEN", "event_time_s": 90.0},
        "DOOR_FIRE": {"state": "CLOSED", "eventTime": 180.0},
    }

    bundle = emit_fire_scenario(
        mapping_plan=plan,
        bundle_sha256=_valid_bundle_hash(),
        ev_selections=[ev],
        devices=devices,
        opening_states=opening_states,
        verification_status="MAPPING_VERIFIED",
    )

    assert len(bundle.devices) == 2
    assert len(bundle.opening_events) == 2

    frag = bundle.fds_fragment
    # Device namelists
    assert "SPK_01" in frag
    assert "SMK_01" in frag
    assert "SPRINKLER LINK TEMPERATURE" in frag
    assert "CHAMBER OBSCURATION" in frag

    # Door control DEVC and CTRL namelists
    assert "DOOR_MAIN" in frag
    assert "DOOR_FIRE" in frag
    assert "&CTRL" in frag
    assert "CTRL_ID='CTRL_DOOR_MAIN'" in frag


def test_custom_pack_and_peak_hrr():
    """Verify custom pack_kwh and peak_hrr_mw validation and usage."""
    plan = _sample_mapping_plan()

    # Valid custom values within preset range
    ev_custom = EVSelection(
        preset_id="auto-nmc",
        position=(0.0, 0.0, 0.75),
        pack_kwh=80.0,
        peak_hrr_mw=5.5,
    )
    bundle = emit_fire_scenario(
        mapping_plan=plan,
        bundle_sha256=_valid_bundle_hash(),
        ev_selections=[ev_custom],
        verification_status="MAPPING_VERIFIED",
    )
    assert bundle.total_peak_hrr_mw == pytest.approx(5.5)

    # Invalid custom peak HRR out of range (auto-nmc range is 2.0 to 7.0)
    ev_out_of_range = EVSelection(
        preset_id="auto-nmc",
        position=(0.0, 0.0, 0.75),
        peak_hrr_mw=15.0,
    )
    with pytest.raises(ValueError, match="out of.*range"):
        emit_fire_scenario(
            mapping_plan=plan,
            bundle_sha256=_valid_bundle_hash(),
            ev_selections=[ev_out_of_range],
            verification_status="MAPPING_VERIFIED",
        )


def test_scenario_id_unique_across_matrix_permutations():
    """Verify scenario_id does not collide across permutations of position, delay, or doors."""
    plan = _sample_mapping_plan()
    ev_base = EVSelection(preset_id="e-bike-lfp", position=(0.0, 0.0, 0.55), ignition_delay_s=0.0)
    ev_moved = EVSelection(preset_id="e-bike-lfp", position=(5.0, 0.0, 0.55), ignition_delay_s=0.0)
    ev_delayed = EVSelection(preset_id="e-bike-lfp", position=(0.0, 0.0, 0.55), ignition_delay_s=60.0)

    bundle_base = emit_fire_scenario(
        mapping_plan=plan,
        bundle_sha256=_valid_bundle_hash(),
        ev_selections=[ev_base],
        verification_status="MAPPING_VERIFIED",
    )
    bundle_moved = emit_fire_scenario(
        mapping_plan=plan,
        bundle_sha256=_valid_bundle_hash(),
        ev_selections=[ev_moved],
        verification_status="MAPPING_VERIFIED",
    )
    bundle_delayed = emit_fire_scenario(
        mapping_plan=plan,
        bundle_sha256=_valid_bundle_hash(),
        ev_selections=[ev_delayed],
        verification_status="MAPPING_VERIFIED",
    )
    bundle_doors = emit_fire_scenario(
        mapping_plan=MappingPlan(decisions=[_door("DOOR_1")]),
        bundle_sha256=_valid_bundle_hash(),
        ev_selections=[ev_base],
        opening_states={"DOOR_1": {"state": "OPEN", "event_time_s": 30.0}},
        verification_status="MAPPING_VERIFIED",
    )

    # Identical bundle_sha256 and vehicle count/type MUST NOT collide when parameters change
    assert bundle_base.scenario_id != bundle_moved.scenario_id
    assert bundle_base.scenario_id != bundle_delayed.scenario_id
    assert bundle_base.scenario_id != bundle_doors.scenario_id
    assert bundle_moved.scenario_id != bundle_delayed.scenario_id


def test_mixed_preset_unique_fuel_and_surf_binding():
    """Verify mixed presets produce composite &REAC in simple chemistry (H-2) and support multi-reac mode."""
    plan = _sample_mapping_plan()
    evs = [
        EVSelection(preset_id="e-bike-lfp", position=(0.0, 0.0, 0.55)),
        EVSelection(preset_id="auto-nmc", position=(5.0, 0.0, 0.75)),
    ]

    # 1. Default simple chemistry: exactly 1 composite &REAC and &SPEC HF (H-2 and H-3)
    bundle = emit_fire_scenario(
        mapping_plan=plan,
        bundle_sha256=_valid_bundle_hash(),
        ev_selections=evs,
        verification_status="MAPPING_VERIFIED",
    )
    frag = bundle.fds_fragment
    reac_fuels = re.findall(r"&REAC.*?FUEL='([^']+)'", frag)
    assert len(reac_fuels) == 1, f"Expected 1 composite &REAC line in simple chemistry, found {len(reac_fuels)}"
    assert "REAC_COMPOSITE_EV" in frag
    assert "&SPEC ID='HYDROGEN FLUORIDE' /" not in frag
    assert bundle.hf_preset_yields
    surf_fuel_ids = re.findall(r"&SURF.*?FUEL_ID='([^']+)'", frag)
    assert len(surf_fuel_ids) == 2
    for fid in surf_fuel_ids:
        assert fid == reac_fuels[0]

    # 2. Explicit multi-reac mode emits distinct &REAC lines
    bundle_multi = emit_fire_scenario(
        mapping_plan=plan,
        bundle_sha256=_valid_bundle_hash(),
        ev_selections=evs,
        verification_status="MAPPING_VERIFIED",
        allow_multi_reac=True,
    )
    multi_fuels = re.findall(r"&REAC.*?FUEL='([^']+)'", bundle_multi.fds_fragment)
    assert len(multi_fuels) == 2
    assert len(set(multi_fuels)) == 2



def test_door_events_with_representation_bounds():
    """Verify each fill references its timer and the timer has its own initial state."""
    decision_open = MappingDecision(
        entity_key="DOOR_OPEN",
        strategy=MappingStrategy.OBST,
        simulation_role="DOOR",
        fds_representation="OBST",
        representation_bounds=BoundingBox(xmin=1.0, xmax=2.0, ymin=0.0, ymax=0.2, zmin=0.0, zmax=2.1),
    )
    decision_close = MappingDecision(
        entity_key="DOOR_CLOSE",
        strategy=MappingStrategy.OBST,
        simulation_role="DOOR",
        fds_representation="OBST",
        representation_bounds=BoundingBox(xmin=5.0, xmax=6.0, ymin=0.0, ymax=0.2, zmin=0.0, zmax=2.1),
    )
    plan = MappingPlan(decisions=[decision_open, decision_close])

    ev = EVSelection(preset_id="e-bike-lfp", position=(0.0, 0.0, 0.55))
    opening_states = {
        "DOOR_OPEN": {"state": "OPEN", "event_time_s": 45.0},
        "DOOR_CLOSE": {"state": "CLOSED", "event_time_s": 90.0},
    }

    bundle = emit_fire_scenario(
        mapping_plan=plan,
        bundle_sha256=_valid_bundle_hash(),
        ev_selections=[ev],
        opening_states=opening_states,
        verification_status="MAPPING_VERIFIED",
    )

    frag = bundle.fds_fragment
    assert "CTRL_ID='CTRL_DOOR_OPEN'" in frag
    assert "CTRL_ID='CTRL_DOOR_CLOSE'" in frag
    assert re.search(r"CTRL_DOOR_OPEN'.*INITIAL_STATE=\.TRUE\.", frag)
    assert re.search(r"CTRL_DOOR_CLOSE'.*INITIAL_STATE=\.FALSE\.", frag)


def test_ev_selection_dimensions_must_be_strictly_positive():
    """Verify EVSelection validator ensures dx, dy, dz are strictly > 0.0."""
    # Valid dimensions
    ev_valid = EVSelection(preset_id="auto-nmc", position=(0, 0, 0), dimensions=(4.5, 1.8, 1.5))
    assert ev_valid.dimensions == (4.5, 1.8, 1.5)

    # Zero dimension
    with pytest.raises(ValueError, match="strictly positive"):
        EVSelection(preset_id="auto-nmc", position=(0, 0, 0), dimensions=(4.5, 0.0, 1.5))

    # Negative dimension
    with pytest.raises(ValueError, match="strictly positive"):
        EVSelection(preset_id="auto-nmc", position=(0, 0, 0), dimensions=(-1.0, 1.8, 1.5))


def test_door_timer_devc_id_preserves_suffix():
    """Verify door timer devc naming prevents truncation of _TIME suffix on long entity keys."""
    ev = EVSelection(preset_id="e-bike-lfp", position=(0, 0, 0))
    long_key = "DOOR_EMERGENCY_EXIT_NORTH_WING_LEVEL_1"
    plan = MappingPlan(decisions=[_door(long_key)])
    opening_states = {long_key: {"state": "OPEN", "event_time_s": 30.0}}

    bundle = emit_fire_scenario(
        mapping_plan=plan,
        bundle_sha256=_valid_bundle_hash(),
        ev_selections=[ev],
        opening_states=opening_states,
        verification_status="MAPPING_VERIFIED",
    )

    frag = bundle.fds_fragment
    match = re.search(r"&DEVC ID='([^']+)', XYZ=", frag)
    assert match is not None
    devc_id = match.group(1)
    assert devc_id.endswith("_TIME")
    assert len(devc_id) <= 30
    assert f"INPUT_ID='{devc_id}'" in frag


def test_vehicle_collision_detection_raises():
    """Item 44: Two overlapping vehicles must raise ValueError."""
    plan = _sample_mapping_plan()
    ev1 = EVSelection(preset_id="auto-nmc", position=(0.0, 0.0, 0.75), dimensions=(4.5, 1.8, 1.5))
    ev2 = EVSelection(preset_id="auto-nmc", position=(0.5, 0.2, 0.75), dimensions=(4.5, 1.8, 1.5))

    with pytest.raises(ValueError, match="Vehicle collision detected"):
        emit_fire_scenario(
            mapping_plan=plan,
            bundle_sha256=_valid_bundle_hash(),
            ev_selections=[ev1, ev2],
            verification_status="MAPPING_VERIFIED",
        )


def test_scenario_bundle_embeds_library_digest():
    """Item 43 (M-14): ScenarioBundle embeds cryptographic library_digest for audit reproducibility."""
    plan = _sample_mapping_plan()
    ev = EVSelection(preset_id="e-bike-lfp", position=(0.0, 0.0, 0.55))
    bundle = emit_fire_scenario(
        mapping_plan=plan,
        bundle_sha256=_valid_bundle_hash(),
        ev_selections=[ev],
        verification_status="MAPPING_VERIFIED",
    )
    assert bundle.ev_library_digest is not None
    assert len(bundle.ev_library_digest) == 64


