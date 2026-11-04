"""Local conversion, independent audit and inspection."""

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any
from .pipeline import convert, audit, save_artifacts
from .core.inventory import extract_inventory
from .mapping.manifest import MappingManifest


def exit_status(status):
    return {
        "MAPPING_VERIFIED": 0,
        "SIMULATION_VERIFIED": 0,
        "REJECTED": 1,
        "INCONCLUSIVE": 2,
    }.get(str(status), 3)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ifc_to_fds")
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("convert")
    p.add_argument("input_ifc", nargs="+")
    p.add_argument("-o", "--output")
    p.add_argument(
        "--config",
        help="JSON configuration with source transforms, scope and audit settings",
    )
    p.add_argument("--cell-size", type=float, default=None)
    p.add_argument("--storey", action="append")
    p.add_argument(
        "--bbox",
        nargs=6,
        type=float,
        metavar=("XMIN", "XMAX", "YMIN", "YMAX", "ZMIN", "ZMAX"),
    )
    p.add_argument("--all-geom", action="store_true", default=None)
    p.add_argument("--include-review", action="store_true", default=None)
    p.add_argument("--common-coordinates", action="store_true")
    p.add_argument("--solver")
    p.add_argument("--profile", choices=["mapping", "research-basement", "simulation", "geometry-fidelity"])
    p.add_argument("--reference-case")
    p.add_argument("--decisions", help="Explicit entity decisions JSON")
    p.add_argument("--intentional-deltas", help="Approved delta JSON")
    p.add_argument("--domain", nargs=6, type=float)
    p.add_argument("--coordinate-frame", choices=["WORLD", "REBASED"], default=None, help="Coordinate frame for domain/bbox")
    p = commands.add_parser("audit")
    p.add_argument("input_ifc", nargs="+")
    p.add_argument("--fds", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--geometry-package")
    p.add_argument("--profile", choices=["mapping", "research-basement", "simulation", "geometry-fidelity"])
    p.add_argument("--reference-case")
    p.add_argument("--intentional-deltas")
    p.add_argument("--config")
    p.add_argument("-o", "--output", required=True, help="Audit report JSON")
    p = commands.add_parser("reference-candidate")
    p.add_argument("input_ifc", nargs="+")
    p.add_argument("--config", required=True)
    p.add_argument(
        "--reference-fds", help="Existing manually reviewed FDS, imported as a draft"
    )
    p.add_argument(
        "--reference-manifest", help="Source mapping for the existing FDS primitive IDs"
    )
    p.add_argument("-o", "--output", required=True)
    p = commands.add_parser("reference-check")
    p.add_argument("directory")
    p = commands.add_parser("reference-resolve")
    p.add_argument("directory")
    p.add_argument(
        "--source-map",
        required=True,
        help="Local JSON mapping source SHA256 to file path",
    )
    p = commands.add_parser("inventory")
    p.add_argument("input_ifc")
    p.add_argument("--json", action="store_true")
    p = commands.add_parser("serve")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--api-key", help="API key required for /api/* requests")
    p.add_argument("--api-key-file", help="Path to file containing API key")
    p.add_argument("--allowed-hosts", help="Comma-separated list of allowed Host header values")
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            import uvicorn

            loopback_hosts = {"127.0.0.1", "localhost", "::1", "testserver"}
            is_public_host = args.host not in loopback_hosts
            api_key = args.api_key
            if not api_key and getattr(args, "api_key_file", None):
                key_path = Path(args.api_key_file)
                if not key_path.is_file():
                    sys.stderr.write(
                        f"SECURITY ERROR: Specified --api-key-file does not exist or is not a file: {args.api_key_file}\n"
                    )
                    return 1
                api_key = key_path.read_text(encoding="utf-8").strip()
            if not api_key:
                api_key = os.getenv("IFCFDS_API_KEY")

            if is_public_host and not api_key:
                sys.stderr.write(
                    f"SECURITY ERROR: Binding to public/external host interface ({args.host}) "
                    "requires --api-key or IFCFDS_API_KEY environment variable.\n"
                )
                return 1

            if api_key:
                os.environ["IFCFDS_API_KEY"] = api_key
            if args.allowed_hosts:
                os.environ["IFCFDS_ALLOWED_HOSTS"] = args.allowed_hosts

            uvicorn.run("ifc_to_fds.server:app", host=args.host, port=args.port)
            return 0
        if args.command == "reference-check":
            from .validation.golden import inspect_case

            checksum, approval, _ = inspect_case(args.directory)
            print(json.dumps(dict(bundle_sha256=checksum, approval=approval), indent=2))
            return (
                0
                if approval.get("status") == "APPROVED"
                and all(approval.get(k) for k in ("reviewer", "rationale", "evidence"))
                else 2
            )
        if args.command == "reference-resolve":
            from .validation.golden import resolve_sources

            mapping = json.loads(Path(args.source_map).read_text(encoding="utf-8"))
            print(
                json.dumps([str(p) for p in resolve_sources(args.directory, mapping)])
            )
            return 0
        if args.command == "inventory":
            model, _ = extract_inventory(args.input_ifc)
            print(
                model.model_dump_json(indent=2)
                if args.json
                else f"{model.source.filename}: {len(model.elements)} IfcProduct entities"
            )
            return 0
        config = (
            json.loads(Path(args.config).read_text(encoding="utf-8"))
            if args.config
            else {}
        )
        if args.command == "reference-candidate":
            from .validation.golden import create_candidate
            from .pipeline import prepare

            result = convert(args.input_ifc, config)
            manifest = MappingManifest.model_validate(result["manifest"])
            from .validation.acceptance import AcceptanceReport

            model = prepare(args.input_ifc, config, reference=True)
            fds_text = result["fds_text"]
            report = AcceptanceReport.model_validate(result["report"])
            if args.reference_manifest and not args.reference_fds:
                raise ValueError("--reference-manifest requires --reference-fds")
            if args.reference_fds:
                fds_text = Path(args.reference_fds).read_bytes().decode("utf-8")
                if args.reference_manifest:
                    manifest = MappingManifest.model_validate_json(
                        Path(args.reference_manifest).read_text(encoding="utf-8")
                    )
                model, manifest, report = audit(
                    args.input_ifc,
                    fds_text,
                    manifest,
                    result["configuration"],
                    result["geometry_package"],
                )
            print(
                create_candidate(
                    args.output,
                    model,
                    manifest,
                    result["geometry_package"],
                    report,
                    config,
                    fds_text,
                )
            )
            return 2  # Candidate generation is never approval.
        for name in ("profile", "reference_case"):
            if getattr(args, name, None):
                config[name] = getattr(args, name)
        for name in ("decisions", "intentional_deltas"):
            if getattr(args, name, None):
                config[name] = json.loads(
                    Path(getattr(args, name)).read_text(encoding="utf-8")
                )
        if args.command == "audit":
            manifest = MappingManifest.model_validate_json(
                Path(args.manifest).read_text(encoding="utf-8")
            )
            from ifc_to_fds.geometry.storage import read_package, restore_package

            geom_arg = Path(args.geometry_package) if args.geometry_package else None
            default_json = Path(args.fds).with_suffix("").with_name(Path(args.fds).stem + "_geometry.json")
            default_zip = Path(args.fds).with_suffix("").with_name(Path(args.fds).stem + "_geometry.zip")

            package = None
            if geom_arg and geom_arg.suffix == ".zip" and geom_arg.is_file():
                unpacked_json = geom_arg.with_suffix("").with_name(geom_arg.stem + "_unpacked.json")
                package = restore_package(geom_arg, unpacked_json)
            elif geom_arg and geom_arg.is_file():
                package = read_package(geom_arg)
            elif default_json.is_file():
                package = read_package(default_json)
            elif default_zip.is_file():
                package = restore_package(default_zip, default_json)
            if not args.config:
                config = {**{k: v for k, v in manifest.configuration.items() if k != "audit"}, **config}
            _, _, report = audit(
                args.input_ifc,
                Path(args.fds).read_bytes().decode("utf-8"),
                manifest,
                config,
                package,
            )
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
            output.with_suffix(".md").write_text(report.to_markdown(), encoding="utf-8")
            print(report.status.value)
            return exit_status(report.status.value)
        for key in ("cell_size", "all_geom", "include_review"):
            if getattr(args, key) is not None:
                config[key] = getattr(args, key)
        if args.domain:
            config["simulation_domain"] = dict(
                zip(("xmin", "xmax", "ymin", "ymax", "zmin", "zmax"), args.domain)
            )
            if getattr(args, "coordinate_frame", None):
                config["simulation_domain_coordinate_frame"] = args.coordinate_frame
        if args.storey:
            config.setdefault("scope", {})["storeys"] = args.storey
        if args.bbox:
            bbox_dict: dict[str, Any] = dict(
                zip(("xmin", "xmax", "ymin", "ymax", "zmin", "zmax"), args.bbox)
            )
            if getattr(args, "coordinate_frame", None):
                bbox_dict["coordinate_frame"] = args.coordinate_frame
            config.setdefault("scope", {})["bounding_box"] = bbox_dict
        if args.common_coordinates:
            config.setdefault("sources", {})["common_coordinates"] = True
        if args.solver:
            config.setdefault("audit", {})["solver_executable"] = args.solver
        output = (
            args.output
            or str(Path(args.input_ifc[0]).with_suffix("")) + "_converted.fds"
        )
        # Build checkpoints beside the chosen destination, in an isolated work
        # directory. A conversion must not overwrite an unrelated model.fds.
        import tempfile

        target = Path(output).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".ifcfds-work-", dir=target.parent) as work:
            result = convert(args.input_ifc, config, output_directory=work)
            save_artifacts(result, target)
        print(f"{result['status']}: {output}")
        return exit_status(result["status"])
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Conversion/audit error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
