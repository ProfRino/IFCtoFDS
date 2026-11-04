"""Report the nominal energy implied by the serialized burner schedules."""

import math

from ifc_to_fds.validation.parser import parse_fds


def assess_scenario_physics(text, bundle, budget):
    parsed = parse_fds(text)
    burners = {r.id: r for r in parsed.records if r.kind == "SURF"}
    vents = {r.id: r for r in parsed.records if r.kind == "VENT"}
    ramps = {}
    for record in parsed.records:
        if record.kind == "RAMP":
            ramps.setdefault(record.id, []).append(record)
    t_end = next(
        (
            float(r.values["T_END"][0])
            for r in parsed.records
            if r.kind == "TIME"
            and "T_END" in r.values
            and len(r.values["T_END"]) == 1
            and math.isfinite(float(r.values["T_END"][0]))
        ),
        None,
    )
    vehicle_energy = []
    vehicle_energy_within_t_end = []
    for index in range(1, bundle.ev_count + 1):
        burner = burners[f"BURNER_EV_{index}"]
        xb = vents[f"VENT_BURNER_{index}"].values["XB"]
        area = (xb[1] - xb[0]) * (xb[3] - xb[2])
        peak_kw = burner.values["HRRPUA"][0] * area
        points = [(r.values["T"][0], r.values["F"][0]) for r in ramps[burner.values["RAMP_Q"][0]]]
        if any(right[0] <= left[0] for left, right in zip(points, points[1:])):
            raise ValueError(f"Burner ramp times must be strictly increasing: {burner.id}")
        integral = math.fsum(
            (right_time - left_time) * (left_fraction + right_fraction) / 2
            for (left_time, left_fraction), (right_time, right_fraction) in zip(points, points[1:])
        )
        if t_end is None:
            integral_within_t_end = integral
        else:
            within_segs = []
            for (t1, f1), (t2, f2) in zip(points, points[1:]):
                if t1 >= t_end:
                    continue
                if t2 <= t_end:
                    within_segs.append((t2 - t1) * (f1 + f2) / 2)
                else:
                    f_end = f1 + (f2 - f1) * (t_end - t1) / (t2 - t1)
                    within_segs.append((t_end - t1) * (f1 + f_end) / 2)
            integral_within_t_end = math.fsum(within_segs)
        vehicle_energy.append(peak_kw * integral / 1000)
        vehicle_energy_within_t_end.append(peak_kw * integral_within_t_end / 1000)
    total = math.fsum(vehicle_energy)
    total_within_t_end = math.fsum(vehicle_energy_within_t_end)
    limit = budget.battery_chemical_energy_mj + budget.other_vehicle_energy_mj if budget else None
    if limit is not None and not math.isfinite(limit):
        raise ValueError("Total vehicle energy budget must be finite")
    status = "INCONCLUSIVE" if limit is None else "FAIL" if total > limit else "PASS"
    reasons = {
        "INCONCLUSIVE": "No sourced chemical energy budget for the whole vehicle fleet",
        "FAIL": "Nominal burner energy exceeds the declared fleet budget",
        "PASS": "Nominal burner energy is within the declared fleet budget",
    }
    return {
        "status": "FAIL" if status == "FAIL" else "INCONCLUSIVE",
        "energy_budget_status": status,
        "energy_reason": reasons[status],
        "nominal_energy_mj": total,
        "nominal_energy_within_t_end_mj": total_within_t_end,
        "vehicle_energy_mj": vehicle_energy,
        "energy_basis": "Serialized HRRPUA and vent area before solver grid snapping",
        "budget": budget.model_dump() if budget else None,
        "hf_status": "NOT_MODELED",
        "hf_library_yield_ranges": bundle.hf_preset_yields,
        "ev_library_digest": bundle.ev_library_digest,
    }
