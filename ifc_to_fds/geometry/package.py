"""Portable, checksummed geometry evidence. Audit never trusts exporter memory."""

from ifc_to_fds.core.canonical import SCHEMA_VERSION, TriangleMesh, MappingStrategy
from ifc_to_fds.geometry.mesh import valid_solid
from ifc_to_fds.validation.metrics import compare_solids
from ifc_to_fds.validation.acceptance import GateResult, GateStatus, Finding, Severity
from .package_integrity import digest as digest, seal, verify_package_metadata
from .storage import DiskPackage


def build_package(model):
    return seal(
        dict(
            schema_version=SCHEMA_VERSION,
            units="METRE",
            coordinate_frame="COMMON_WORLD",
            sources=[
                dict(source_id=s.source_id, world_transform=s.world_transform)
                for s in model.sources or [model.source]
            ],
            elements={
                e.entity_key: dict(
                    source_id=e.source_id,
                    global_id=e.global_id,
                    transform=e.transform,
                    placement=e.placement,
                    ports=[p.model_dump(mode="json") for p in e.ports],
                    mesh=e.mesh.model_dump(mode="json") if e.mesh else None,
                    openings={
                        str(o.opening_step_id): o.mesh.model_dump(mode="json")
                        if o.mesh
                        else None
                        for o in e.openings
                    },
                )
                for e in model.elements
            },
        )
    )


def verify_package(package):
    if isinstance(package, DiskPackage):
        package.verify()
    else:
        verify_package_metadata(package)


def metrics_pass(metrics, config):
    return (
        metrics["surface_distance_m"] <= config.surface_tolerance_m
        and metrics["relative_volume_error"] <= config.relative_volume_tolerance
        and metrics["solid_iou"] >= config.min_solid_iou
        and metrics["reference_components"] == metrics["output_components"]
    )


def audit_package(model, package, report, config):
    gate = GateResult(
        status=GateStatus.PASS,
        reason="Saved geometry independently compared with re-read IFC",
    )
    report.gates["geometry_preservation"] = gate
    failed_keys = set()

    def fail(key, message):
        failed_keys.add(key)
        gate.status = GateStatus.FAIL
        report.findings.append(
            Finding(
                id=f"PKG-{len(report.findings)}",
                severity=Severity.P1,
                category="geometry_preservation",
                title=message,
                detail=message,
                element_id=key,
            )
        )

    def unknown(key, message):
        if gate.status != GateStatus.FAIL:
            gate.status = GateStatus.INCONCLUSIVE
        gate.reason += f"; {key}: {message}"

    if package is None:
        gate.status = GateStatus.INCONCLUSIVE
        gate.reason = "No saved geometry package supplied; metadata is insufficient"
        return
    try:
        if isinstance(package, DiskPackage):
            package.verify_index()
        else:
            verify_package(package)
    except (ValueError, TypeError, OSError) as exc:
        fail("", str(exc))
        return
    expected_sources = [
        dict(source_id=s.source_id, world_transform=s.world_transform)
        for s in model.sources or [model.source]
    ]
    if package["sources"] != expected_sources:
        fail("", "Geometry package source transforms differ")
    entries = package["elements"]
    if set(entries) != {e.entity_key for e in model.elements}:
        fail("", "Geometry package inventory differs from IFC")
    for e in model.elements:
        try:
            entry = entries.get(e.entity_key)
        except (ValueError, OSError, KeyError) as exc:
            fail(e.entity_key, str(exc))
            continue
        if not entry:
            fail(e.entity_key, "Missing source geometry package entry")
            continue
        if (
            entry.get("source_id") != e.source_id
            or entry.get("global_id") != e.global_id
            or (
                package.get("schema_version") != "0.4.0"
                and entry.get("transform") != e.transform
            )
            or (
                package.get("schema_version") != "0.4.0"
                and entry.get("placement") != e.placement
            )
        ):
            fail(e.entity_key, "Geometry package identity/transform differs")
        if package.get("storage_format") and any(
            entry.get(field) != expected
            for field, expected in (
                ("simulation_role", e.simulation_role),
                ("scope_decision", e.scope_decision.value),
                ("ifc_type", e.ifc_type),
            )
        ):
            fail(e.entity_key, "Geometry index role/scope/type differs")
        from ifc_to_fds.core.compare import normalize

        if normalize(entry.get("ports", [])) != normalize(
            [p.model_dump(mode="json") for p in e.ports]
        ):
            fail(e.entity_key, "Saved ports/ownership/positions differ from IFC")
        in_scope = e.scope_decision.value in (
            "IN_SCOPE",
            "BOUNDARY_RETAINED",
            "UNRESOLVED",
        )
        if not in_scope or e.role != "PHYSICAL":
            continue
        if getattr(e, "mapping_strategy", None) in (
            MappingStrategy.SEMANTIC_ONLY,
            MappingStrategy.EXCLUDED_SCOPE,
            MappingStrategy.EXCLUDED_APPROVED,
        ):
            continue
        if not e.has_3d_geometry and not e.mesh:
            unknown(
                e.entity_key, "Source physical element has no geometry representation"
            )
            continue
        pairs = [("solid", e.mesh, entry.get("mesh"))]
        pairs += [
            (
                f"opening:{o.opening_step_id}",
                o.mesh,
                entry.get("openings", {}).get(str(o.opening_step_id)),
            )
            for o in e.openings
        ]
        preserved = True
        for label, source, output in pairs:
            if source is None:
                unknown(e.entity_key, f"Source {label} extraction unavailable")
                preserved = False
                continue
            if not valid_solid(source):
                fail(e.entity_key, f"Invalid or missing source {label}")
                preserved = False
                continue
            if output is None:
                fail(e.entity_key, f"Missing saved {label} geometry")
                preserved = False
                continue
            try:
                metrics = compare_solids(source, [TriangleMesh.model_validate(output)])
                report.metrics.setdefault(e.entity_key, {})[f"preserved:{label}"] = (
                    metrics
                )
                if not metrics_pass(metrics, config):
                    fail(e.entity_key, f"Saved {label} geometry deviates: {metrics}")
                    preserved = False
                elif not metrics["surface_proven"]:
                    unknown(e.entity_key, f"{label} surface proof incomplete")
                    preserved = False
            except ValueError as exc:
                if hasattr(exc, "evidence"):
                    report.metrics.setdefault(e.entity_key, {})[f"preserved:{label}"] = {
                        "self_intersection": exc.evidence
                    }
                fail(e.entity_key, f"Invalid saved {label}: {exc}")
                preserved = False
            except Exception as exc:
                unknown(e.entity_key, f"{label} comparison unavailable: {exc}")
                preserved = False
        preserved = preserved and e.entity_key not in failed_keys
        e.geometry_preservation = (
            "PRESERVED"
            if preserved
            else ("FAILED" if e.entity_key in failed_keys else "INCONCLUSIVE")
        )
        if (
            preserved
            and e.simulation_role == "REFERENCE_GEOMETRY"
            and e.review_status != "REVIEW_REQUIRED"
            and e.boundary_treatment != "PENDING_VALIDATION"
        ):
            report.element_statuses[e.entity_key] = "REFERENCE_PRESERVED"
