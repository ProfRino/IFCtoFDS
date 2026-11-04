"""Pinned solver runs with durable evidence and killable process trees."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import uuid
import platform
import psutil
from ifc_to_fds.diagnostics import operation
from .acceptance import GateResult, GateStatus
from .effective import effective_obstructions
from .solver_discovery import resolve_solver_executable


def stop_tree(process):
    try:
        parent = psutil.Process(process.pid)
        for child in parent.children(recursive=True):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        parent.kill()
    except psutil.NoSuchProcess:
        pass


@operation("SOLVER")
def solver_gates(fds_text, config):
    resolution = resolve_solver_executable(config.solver_executable, config.solver_version)
    effective = GateResult(
        status=GateStatus.INCONCLUSIVE,
        reason="Effective geometry has not been proved from solver output",
    )
    if resolution.executable is None:
        return GateResult(
            status=GateStatus.INCONCLUSIVE,
            reason=resolution.reason,
            evidence={"resolution": resolution.evidence()},
        ), effective
    path = resolution.executable
    evidence = dict(
        required_version=config.solver_version,
        adapter_version="obst-single-mesh-0.5.0",
        platform=platform.platform(),
        configuration_sha256=hashlib.sha256(
            config.model_dump_json().encode()
        ).hexdigest(),
        fds_sha256=hashlib.sha256(fds_text.encode()).hexdigest(),
        resolution=resolution.evidence(),
    )
    directory = None
    try:
        evidence.update(
            executable=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()
        )
        if resolution.source == "project-pinned" and evidence["sha256"] != resolution.sha256:
            raise OSError("Project-pinned FDS binary changed after discovery; execution refused")
        directory = (
            Path(config.solver_evidence_directory or ".cache/solver-evidence").resolve()
            / uuid.uuid4().hex
        )
        directory.mkdir(parents=True)
        evidence["directory"] = str(directory)
        input_path = directory / "audit.fds"
        input_path.write_bytes(fds_text.encode())
        command = [str(path), input_path.name]
        evidence.update(
            command=command,
            timeout_s=config.solver_timeout_s,
            environment={
                "OMP_NUM_THREADS": "1",
                "mpi_runtime_directory": str(path.parent / "mpi"),
            },
        )
        runtime = {
            **os.environ,
            "OMP_NUM_THREADS": "1",
            "PATH": str(path.parent / "mpi") + os.pathsep + os.environ.get("PATH", ""),
        }
        probe = subprocess.Popen(
            [str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=runtime,
            cwd=directory,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            version_output, _ = probe.communicate(
                timeout=min(15, config.solver_timeout_s)
            )
        except subprocess.TimeoutExpired:
            stop_tree(probe)
            version_output, _ = probe.communicate()
            (directory / "version.log").write_bytes(version_output)
            raise subprocess.TimeoutExpired(
                [str(path)], min(15, config.solver_timeout_s)
            )
        (directory / "version.log").write_bytes(version_output)
        process = subprocess.Popen(
            command,
            cwd=directory,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            env={
                **os.environ,
                "OMP_NUM_THREADS": "1",
                "PATH": str(path.parent / "mpi")
                + os.pathsep
                + os.environ.get("PATH", ""),
            },
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        timeout = False
        try:
            stdout, stderr = process.communicate(timeout=config.solver_timeout_s)
        except subprocess.TimeoutExpired:
            timeout = True
            stop_tree(process)
            stdout, stderr = process.communicate()
        (directory / "stdout.log").write_bytes(stdout)
        (directory / "stderr.log").write_bytes(stderr)
        evidence.update(returncode=process.returncode, timed_out=timeout)
        combined = stdout.decode(errors="replace") + stderr.decode(errors="replace")
        combined += "\n".join(
            f.read_text(encoding="utf-8", errors="replace")
            for f in directory.glob("*.out")
        )
        versions = re.findall(
            r"(?:FDS[-\s]+|FDS\s+Version\s*[:=]?\s*)(\d+\.\d+\.\d+)",
            version_output.decode(errors="replace") + combined,
            re.I,
        )
        evidence["reported_versions"] = versions
        evidence["files"] = {
            f.name: hashlib.sha256(f.read_bytes()).hexdigest()
            for f in directory.iterdir()
            if f.is_file()
        }
        (directory / "run.json").write_text(
            json.dumps(evidence, indent=2), encoding="utf-8"
        )
        if timeout:
            status, reason = GateStatus.INCONCLUSIVE, "FDS initialization timed out"
        elif config.solver_version not in versions:
            status, reason = (
                GateStatus.INCONCLUSIVE,
                "Pinned solver version not confirmed",
            )
        elif process.returncode or re.search(
            r"ERROR:|ERROR\([0-9]+\)|STOP:.*ERROR", combined, re.I
        ):
            status, reason = (
                GateStatus.FAIL,
                "FDS rejected input or exited with an error",
            )
        elif not (
            re.search(r"completed successfully|successfully completed", combined, re.I)
            or (
                re.search(r"STOP: Set-up only", combined, re.I)
                and re.search(r"T_END\s*=\s*0(?:\.0*)?\s*[/,]", fds_text, re.I)
            )
        ):
            status, reason = (
                GateStatus.INCONCLUSIVE,
                "FDS normal completion not confirmed",
            )
        else:
            status, reason = GateStatus.PASS, "Pinned FDS initialization completed"
            smv = list(directory.glob("*.smv"))
            if len(smv) == 1:
                effective = effective_obstructions(
                    fds_text, smv[0].read_text(encoding="utf-8", errors="replace")
                )
                effective.evidence.update(
                    fds_sha256=evidence["fds_sha256"],
                    solver_sha256=evidence["sha256"],
                    directory=str(directory),
                )
        (directory / "effective.json").write_text(
            effective.model_dump_json(indent=2), encoding="utf-8"
        )
        return GateResult(status=status, reason=reason, evidence=evidence), effective
    except (OSError, subprocess.TimeoutExpired) as exc:
        evidence.update(
            termination_reason=str(exc),
            timed_out=isinstance(exc, subprocess.TimeoutExpired),
        )
        if directory is not None:
            (directory / "run.json").write_text(
                json.dumps(evidence, indent=2), encoding="utf-8"
            )
        return GateResult(
            status=GateStatus.INCONCLUSIVE, reason=str(exc), evidence=evidence
        ), effective
