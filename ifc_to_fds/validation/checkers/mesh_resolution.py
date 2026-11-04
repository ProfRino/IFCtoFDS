"""Mesh resolution gate checker for fire scenarios based on plume characteristic diameter D*."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Union

from ifc_to_fds.domain.validation.checkers.base import CheckerOutcome
from ifc_to_fds.domain.validation.model import (
    Finding,
    GateResult,
    GateStatus,
    Severity,
    ValidationContext,
)

# Reference constant: rho_inf * c_p * T_inf * sqrt(g)
# 1.204 * 1.005 * 293.15 * sqrt(9.81) ~= 1111.4
PLUME_COEFFICIENT = 1111.4


def calculate_d_star(heat_release_rate_kw: float) -> float:
    """Calculate characteristic fire diameter D* in meters.

    D* = (Q / (rho_inf * c_p * T_inf * sqrt(g)))^(2/5)
    where denominator is approximately 1111.4 (with Q in kW).
    """
    if heat_release_rate_kw <= 0.0:
        return 0.0
    return float((heat_release_rate_kw / PLUME_COEFFICIENT) ** 0.4)


def _get_ev_peak_hrr_kw(ev: Any) -> float:
    """Resolve peak HRR in kW for a given EV selection or dict."""
    if hasattr(ev, "peak_hrr_mw") and ev.peak_hrr_mw is not None:
        return float(ev.peak_hrr_mw) * 1000.0
    if isinstance(ev, dict):
        if "peak_hrr_kw" in ev and ev["peak_hrr_kw"] is not None:
            return float(ev["peak_hrr_kw"])
        if "peak_hrr_mw" in ev and ev["peak_hrr_mw"] is not None:
            return float(ev["peak_hrr_mw"]) * 1000.0

    preset_id = getattr(ev, "preset_id", None) or (
        ev.get("preset_id") if isinstance(ev, dict) else None
    )
    if preset_id:
        try:
            from ifc_to_fds.fire.ev_library import load_ev_preset

            preset_key = str(preset_id).strip().lower()
            if "-" in preset_key:
                vclass, chem = preset_key.rsplit("-", 1)
                preset = load_ev_preset(vclass, chem)
                min_hrr, max_hrr = preset.peak_hrr_mw_range
                return ((min_hrr + max_hrr) / 2.0) * 1000.0
        except Exception:
            pass
    return 0.0


def check_mesh_resolution(
    scenario: Union[Any, Dict[str, Any]], cell_size: float = 0.2
) -> GateResult:
    """Check whether computational cell size satisfies 4 <= D*/dx <= 16 for fire scenario.

    Parameters
    ----------
    scenario: ScenarioBundle, dict, or numeric peak HRR
        Carries total peak HRR (or individual max peak HRR). If total_peak_hrr_mw
        is in MW, converts to kW (* 1000.0).
    cell_size: float
        Computational mesh cell size in meters (dx). Default 0.2m.

    Returns
    -------
    GateResult with PASS, FAIL, or NOT_APPLICABLE and evidence dict.
    """
    cell_size = float(cell_size)
    if cell_size <= 0.0:
        return GateResult(
            status=GateStatus.FAIL,
            reason=f"Mesh resolution invalid: cell_size must be positive (> 0), got {cell_size}",
            evidence={"cell_size_m": cell_size},
        )

    # Multi-source evaluation: if scenario carries ev_selections, check each vehicle individually
    ev_selections = getattr(scenario, "ev_selections", None) or (
        scenario.get("ev_selections") if isinstance(scenario, dict) else None
    )
    if ev_selections:
        ev_evaluations: List[Dict[str, Any]] = []
        failing_evaluations: List[tuple[str, float, float, float, str]] = []
        for idx, ev in enumerate(ev_selections):
            ev_id = getattr(ev, "id", None) or getattr(ev, "preset_id", None)
            if not ev_id and isinstance(ev, dict):
                ev_id = ev.get("id") or ev.get("preset_id")
            if not ev_id:
                ev_id = f"vehicle_{idx}"

            hrr_kw = _get_ev_peak_hrr_kw(ev)
            d_star = calculate_d_star(hrr_kw)
            ratio = d_star / cell_size if cell_size > 0 else 0.0

            evaluation = {
                "vehicle": ev_id,
                "peak_hrr_kw": hrr_kw,
                "d_star_m": d_star,
                "cell_size_m": cell_size,
                "d_star_over_dx": ratio,
            }
            ev_evaluations.append(evaluation)
            if ratio < 4.0:
                failing_evaluations.append(
                    (
                        ev_id,
                        ratio,
                        d_star,
                        hrr_kw,
                        f"Mesh resolution too coarse for vehicle '{ev_id}': D*/dx = {ratio:.2f} < 4.0 "
                        f"(cell_size={cell_size:.3f}m, required cell_size <= {d_star / 4.0:.3f}m)",
                    )
                )
            elif ratio > 16.0:
                failing_evaluations.append(
                    (
                        ev_id,
                        ratio,
                        d_star,
                        hrr_kw,
                        f"Mesh resolution too fine for vehicle '{ev_id}': D*/dx = {ratio:.2f} > 16.0 "
                        f"(exceeds validated [4.0, 16.0] range; computationally expensive)",
                    )
                )

        if failing_evaluations:
            has_coarse = any(f[1] < 4.0 for f in failing_evaluations)
            rep = failing_evaluations[0]
            evidence = {
                "d_star_m": rep[2],
                "cell_size_m": cell_size,
                "d_star_over_dx": rep[1],
                "peak_hrr_kw": rep[3],
                "ev_evaluations": ev_evaluations,
            }
            reasons = "; ".join(f[4] for f in failing_evaluations)
            return GateResult(
                status=GateStatus.FAIL if has_coarse else GateStatus.INCONCLUSIVE,
                reason=reasons,
                evidence=evidence,
            )
        else:
            first = ev_evaluations[0] if ev_evaluations else {}
            evidence = {
                "d_star_m": first.get("d_star_m", 0.0),
                "cell_size_m": cell_size,
                "d_star_over_dx": first.get("d_star_over_dx", 0.0),
                "peak_hrr_kw": first.get("peak_hrr_kw", 0.0),
                "ev_evaluations": ev_evaluations,
            }
            return GateResult(
                status=GateStatus.PASS,
                reason=f"Mesh resolution adequate for all {len(ev_evaluations)} vehicle fire source(s) within [4.0, 16.0]",
                evidence=evidence,
            )

    peak_hrr_kw = 0.0
    if isinstance(scenario, dict):
        if "individual_max_peak_hrr_mw" in scenario:
            peak_hrr_kw = float(scenario["individual_max_peak_hrr_mw"]) * 1000.0
        elif "individual_peak_hrr_mw" in scenario:
            peak_hrr_kw = float(scenario["individual_peak_hrr_mw"]) * 1000.0
        elif "individual_max_peak_hrr_kw" in scenario:
            peak_hrr_kw = float(scenario["individual_max_peak_hrr_kw"])
        elif "individual_peak_hrr_kw" in scenario:
            peak_hrr_kw = float(scenario["individual_peak_hrr_kw"])
        elif "total_peak_hrr_mw" in scenario:
            peak_hrr_kw = float(scenario["total_peak_hrr_mw"]) * 1000.0
        elif "peak_hrr_mw" in scenario:
            peak_hrr_kw = float(scenario["peak_hrr_mw"]) * 1000.0
        elif "total_peak_hrr_kw" in scenario:
            peak_hrr_kw = float(scenario["total_peak_hrr_kw"])
        elif "peak_hrr_kw" in scenario:
            peak_hrr_kw = float(scenario["peak_hrr_kw"])
        elif "total_peak_hrr" in scenario:
            raise ValueError(
                "Ambiguous key 'total_peak_hrr' without unit suffix is rejected. "
                "Specify 'peak_hrr_kw' or 'total_peak_hrr_mw'."
            )
        else:
            raise ValueError(
                "Scenario dict must specify peak HRR with explicit unit (e.g. 'total_peak_hrr_mw' or 'peak_hrr_kw')"
            )
    elif hasattr(scenario, "total_peak_hrr_mw"):
        peak_hrr_kw = float(getattr(scenario, "total_peak_hrr_mw")) * 1000.0
    elif isinstance(scenario, (int, float)):
        raise TypeError(
            "Scalar number for scenario HRR is ambiguous without unit. "
            "Pass a dict specifying 'peak_hrr_kw' or 'total_peak_hrr_mw'."
        )
    elif hasattr(scenario, "peak_hrr_kw"):
        peak_hrr_kw = float(scenario.peak_hrr_kw)
    else:
        raise TypeError(f"Unsupported scenario type for check_mesh_resolution: {type(scenario)}")

    if peak_hrr_kw <= 0.0:
        return GateResult(
            status=GateStatus.NOT_APPLICABLE,
            reason="No positive fire HRR for mesh resolution checking",
            evidence={"peak_hrr_kw": peak_hrr_kw, "cell_size_m": cell_size},
        )

    d_star = calculate_d_star(peak_hrr_kw)
    ratio = d_star / cell_size

    evidence = {
        "d_star_m": d_star,
        "cell_size_m": cell_size,
        "d_star_over_dx": ratio,
        "peak_hrr_kw": peak_hrr_kw,
    }

    if ratio < 4.0:
        status = GateStatus.FAIL
        reason = (
            f"Mesh resolution too coarse: D*/dx = {ratio:.2f} < 4.0 "
            f"(cell_size={cell_size:.3f}m, required cell_size <= {d_star / 4.0:.3f}m)"
        )
    elif 4.0 <= ratio <= 16.0:
        status = GateStatus.PASS
        reason = f"Mesh resolution adequate: D*/dx = {ratio:.2f} within [4.0, 16.0]"
    else:
        status = GateStatus.INCONCLUSIVE
        reason = f"Mesh resolution too fine: D*/dx = {ratio:.2f} > 16.0 (exceeds validated [4.0, 16.0] range; computationally expensive)"

    return GateResult(
        status=status,
        reason=reason,
        evidence=evidence,
    )


class MeshResolutionChecker:
    """Validation checker verifying computational mesh resolution against fire plume D*."""

    name = "mesh_resolution"

    def check(self, context: ValidationContext, parsed: Any = None) -> CheckerOutcome:
        parsed = parsed if parsed is not None else context.parsed
        if parsed is None:
            return CheckerOutcome(
                gate_name=self.name,
                result=GateResult(
                    status=GateStatus.INCONCLUSIVE,
                    reason="Incomplete diagnostic artifact: FDS text missing",
                ),
                findings=[],
            )

        # Inspect parsed for fire sources: &SURF with HRRPUA/RAMP_Q, &REAC, or fire &VENT
        fire_surfs: Dict[str, float] = {}
        has_reac = False

        if hasattr(parsed, "records"):
            for r in parsed.records:
                if r.kind == "REAC":
                    has_reac = True
                elif r.kind == "SURF":
                    surf_id = str(r.values.get("ID", [""])[0]) if "ID" in r.values else ""
                    if "HRRPUA" in r.values or "RAMP_Q" in r.values:
                        try:
                            val = float(r.values.get("HRRPUA", [0.0])[0])
                            fire_surfs[surf_id] = val
                        except (ValueError, TypeError, IndexError):
                            fire_surfs[surf_id] = 0.0

        # Fallback inspection of raw text if records don't explicitly parse REAC/SURF
        if not fire_surfs and not has_reac and context.fds_text:
            if re.search(r"&(?:REAC|RAMP)\b", context.fds_text, re.IGNORECASE):
                has_reac = True
            m_surf = re.findall(
                r"&SURF\s+ID='([^']+)'[^/]*HRRPUA=([\d.]+)", context.fds_text, re.IGNORECASE
            )
            for sid, hval in m_surf:
                fire_surfs[sid] = float(hval)

        if not fire_surfs and not has_reac:
            return CheckerOutcome(
                gate_name=self.name,
                result=GateResult(
                    status=GateStatus.NOT_APPLICABLE,
                    reason="No fire sources defined for mesh resolution checking",
                ),
                findings=[],
            )

        # Determine cell size from MESH records or context.config.cell_size
        mesh_cell_sizes: List[float] = []
        if hasattr(parsed, "records"):
            for r in parsed.records:
                if r.kind == "MESH":
                    xb = [float(x) for x in r.values.get("XB", [])]
                    ijk = [float(x) for x in r.values.get("IJK", [])]
                    if len(xb) == 6 and len(ijk) == 3 and all(n > 0 for n in ijk):
                        dx = abs(xb[1] - xb[0]) / ijk[0]
                        dy = abs(xb[3] - xb[2]) / ijk[1]
                        dz = abs(xb[5] - xb[4]) / ijk[2]
                        mesh_cell_sizes.append(max(dx, dy, dz))

        if mesh_cell_sizes:
            cell_size = max(mesh_cell_sizes)
        elif context.config is not None and getattr(context.config, "cell_size", None) is not None:
            cell_size = float(getattr(context.config, "cell_size"))
        else:
            cell_size = 0.2

        # Collect individual burner sources from geometry (&VENT / &OBST)
        burner_sources: List[Dict[str, Any]] = []
        if hasattr(parsed, "records"):
            for r in parsed.records:
                if r.kind == "VENT":
                    surf_id = str(r.values.get("SURF_ID", [""])[0]) if "SURF_ID" in r.values else ""
                    if surf_id in fire_surfs:
                        hrrpua = fire_surfs[surf_id]
                        xb = [float(x) for x in r.values.get("XB", [])]
                        if len(xb) == 6:
                            dx = abs(xb[1] - xb[0])
                            dy = abs(xb[3] - xb[2])
                            dz = abs(xb[5] - xb[4])
                            dims = sorted([dx, dy, dz])
                            area = dims[1] * dims[2]
                            if area > 0:
                                vent_id = str(r.values.get("ID", [""])[0]) if "ID" in r.values else surf_id
                                burner_sources.append({
                                    "id": vent_id or surf_id,
                                    "surf_id": surf_id,
                                    "hrrpua": hrrpua,
                                    "area": area,
                                    "hrr_kw": hrrpua * area,
                                })
                elif r.kind == "OBST":
                    surf_id = str(r.values.get("SURF_ID", [""])[0]) if "SURF_ID" in r.values else ""
                    if surf_id in fire_surfs:
                        hrrpua = fire_surfs[surf_id]
                        xb = [float(x) for x in r.values.get("XB", [])]
                        if len(xb) == 6:
                            dx = abs(xb[1] - xb[0])
                            dy = abs(xb[3] - xb[2])
                            dz = abs(xb[5] - xb[4])
                            area = 2 * (dx * dy + dy * dz + dx * dz)
                            if area > 0:
                                obst_id = str(r.values.get("ID", [""])[0]) if "ID" in r.values else surf_id
                                burner_sources.append({
                                    "id": obst_id or surf_id,
                                    "surf_id": surf_id,
                                    "hrrpua": hrrpua,
                                    "area": area,
                                    "hrr_kw": hrrpua * area,
                                })

        # If burners exist, evaluate each burner individually
        if burner_sources:
            evaluations: List[Dict[str, Any]] = []
            failing_burners: List[Dict[str, Any]] = []
            for burner in burner_sources:
                bid = burner["id"]
                hrr_kw = burner["hrr_kw"]
                d_star = calculate_d_star(hrr_kw)
                ratio = d_star / cell_size if cell_size > 0 else 0.0
                evaluations.append({
                    "id": bid,
                    "hrr_kw": hrr_kw,
                    "d_star_m": d_star,
                    "cell_size_m": cell_size,
                    "d_star_over_dx": ratio,
                })
                if ratio < 4.0:
                    failing_burners.append({
                        "id": bid,
                        "ratio": ratio,
                        "d_star": d_star,
                        "hrr_kw": hrr_kw,
                        "reason": (
                            f"Mesh resolution too coarse for fire source '{bid}': "
                            f"D*/dx = {ratio:.2f} < 4.0 (cell_size={cell_size:.3f}m, "
                            f"required cell_size <= {d_star / 4.0:.3f}m)"
                        ),
                    })
                elif ratio > 16.0:
                    failing_burners.append({
                        "id": bid,
                        "ratio": ratio,
                        "d_star": d_star,
                        "hrr_kw": hrr_kw,
                        "reason": (
                            f"Mesh resolution too fine for fire source '{bid}': "
                            f"D*/dx = {ratio:.2f} > 16.0 (exceeds validated [4.0, 16.0] range; computationally expensive)"
                        ),
                    })

            if failing_burners:
                has_coarse = any(fb["ratio"] < 4.0 for fb in failing_burners)
                rep = failing_burners[0]
                reason = "; ".join(fb["reason"] for fb in failing_burners)
                gate_result = GateResult(
                    status=GateStatus.FAIL if has_coarse else GateStatus.INCONCLUSIVE,
                    reason=reason,
                    evidence={
                        "d_star_m": rep["d_star"],
                        "cell_size_m": cell_size,
                        "d_star_over_dx": rep["ratio"],
                        "peak_hrr_kw": rep["hrr_kw"],
                        "burner_evaluations": evaluations,
                    },
                )
                findings = [
                    Finding(
                        id=f"FND-MESH-{i + 1:04d}",
                        severity=Severity.P1 if fb["ratio"] < 4.0 else Severity.P2,
                        category="mesh_resolution",
                        title="Computational mesh resolution outside validated [4.0, 16.0] range for fire plume",
                        detail=fb["reason"],
                        element_id=fb["id"],
                    )
                    for i, fb in enumerate(failing_burners)
                ]
            else:
                rep = evaluations[0]
                gate_result = GateResult(
                    status=GateStatus.PASS,
                    reason=f"Mesh resolution adequate for all {len(burner_sources)} fire source(s): D*/dx within [4.0, 16.0]",
                    evidence={
                        "d_star_m": rep["d_star_m"],
                        "cell_size_m": cell_size,
                        "d_star_over_dx": rep["d_star_over_dx"],
                        "peak_hrr_kw": rep["hrr_kw"],
                        "burner_evaluations": evaluations,
                    },
                )
                findings = []

            return CheckerOutcome(
                gate_name=self.name,
                result=gate_result,
                findings=findings,
                metrics=gate_result.evidence,
            )

        # Context fallbacks if burning area could not be determined from geometry
        scen = getattr(context, "scenario", None) or getattr(context, "scenario_bundle", None)
        if scen:
            gate_result = check_mesh_resolution(scen, cell_size=cell_size)
            findings = []
            if gate_result.status == GateStatus.FAIL:
                findings.append(
                    Finding(
                        id="FND-MESH-0001",
                        severity=Severity.P1,
                        category="mesh_resolution",
                        title="Computational mesh resolution outside validated [4.0, 16.0] range for fire plume",
                        detail=gate_result.reason,
                        element_id="",
                    )
                )
            return CheckerOutcome(
                gate_name=self.name,
                result=gate_result,
                findings=findings,
                metrics=gate_result.evidence,
            )

        if context.manifest:
            if isinstance(context.manifest, dict):
                manifest_hrr = context.manifest.get("total_peak_hrr_mw") or context.manifest.get("peak_hrr_kw")
            else:
                manifest_hrr = getattr(context.manifest, "total_peak_hrr_mw", None) or getattr(context.manifest, "peak_hrr_kw", None)
            if manifest_hrr:
                gate_result = check_mesh_resolution(context.manifest, cell_size=cell_size)
                findings = []
                if gate_result.status == GateStatus.FAIL:
                    findings.append(
                        Finding(
                            id="FND-MESH-0001",
                            severity=Severity.P1,
                            category="mesh_resolution",
                            title="Computational mesh resolution outside validated [4.0, 16.0] range for fire plume",
                            detail=gate_result.reason,
                            element_id="",
                        )
                    )
                return CheckerOutcome(
                    gate_name=self.name,
                    result=gate_result,
                    findings=findings,
                    metrics=gate_result.evidence,
                )

        if context.fds_text:
            m_peak = re.search(r"! Total Peak HRR:\s*([\d.]+)\s*MW", context.fds_text)
            if m_peak:
                total_hrr_kw = float(m_peak.group(1)) * 1000.0
                gate_result = check_mesh_resolution({"total_peak_hrr_kw": total_hrr_kw}, cell_size=cell_size)
                findings = []
                if gate_result.status == GateStatus.FAIL:
                    findings.append(
                        Finding(
                            id="FND-MESH-0001",
                            severity=Severity.P1,
                            category="mesh_resolution",
                            title="Computational mesh resolution outside validated [4.0, 16.0] range for fire plume",
                            detail=gate_result.reason,
                            element_id="",
                        )
                    )
                return CheckerOutcome(
                    gate_name=self.name,
                    result=gate_result,
                    findings=findings,
                    metrics=gate_result.evidence,
                )

        # Dimensional fallback: cannot determine burning area for HRR calculation
        return CheckerOutcome(
            gate_name=self.name,
            result=GateResult(
                status=GateStatus.INCONCLUSIVE,
                reason="Cannot determine burning area for HRR calculation",
            ),
            findings=[],
        )
