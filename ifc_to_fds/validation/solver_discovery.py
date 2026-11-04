"""Resolve only operator-configured or known local FDS installations.

Discovery does not download, install or execute anything. The bundled fallback
must match the binary pinned by scripts/install-fds.py before it is usable.
"""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import platform
import shutil


PINNED_VERSION = "6.11.1"
PINNED_BINARY_SHA256 = "dfaf04f1d46dbad77969b1cdd17baaa02a7aa6d63f46e96e93b9d9e635452b55"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PINNED_WINDOWS_RELATIVE_PATH = Path(
    ".deps/fds-6.11.1/firemodels/FDS6/bin/fds_openmp.exe"
)


def binary_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class SolverResolution:
    executable: Path | None
    source: str
    reason: str
    sha256: str | None = None

    def evidence(self):
        return dict(
            source=self.source,
            executable=str(self.executable) if self.executable is not None else None,
            reason=self.reason,
            sha256=self.sha256,
        )


def _candidate(value, source):
    try:
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            return SolverResolution(None, source, f"{source} FDS executable is not a file: {path}")
        return SolverResolution(path, source, f"FDS executable resolved from {source}")
    except (OSError, ValueError, TypeError) as exc:
        return SolverResolution(None, source, f"Invalid {source} FDS executable: {exc}")


def resolve_solver_executable(configured=None, version=PINNED_VERSION):
    """Precedence: explicit path, PATH, checksum-verified pinned installation.

    An explicit invalid path is an error rather than permission to choose a
    different executable. Operators may disable *automatic* discovery using
    IFCFDS_SOLVER_AUTODISCOVERY=0; explicit configuration still takes effect.
    Uploaded configuration never reaches this function as an executable path:
    the server rejects that field and supplies its operator-only setting.
    """
    if configured is not None:
        if not str(configured).strip():
            return SolverResolution(None, "explicit", "Explicit FDS executable path is empty")
        return _candidate(configured, "explicit")

    if os.getenv("IFCFDS_SOLVER_AUTODISCOVERY", "1").strip().lower() in (
        "0", "false", "off", "no"
    ):
        return SolverResolution(
            None, "disabled",
            "FDS auto-discovery disabled by IFCFDS_SOLVER_AUTODISCOVERY; configure an explicit operator path to run the solver",
        )

    on_path = shutil.which("fds")
    if on_path:
        return _candidate(on_path, "PATH")

    if platform.system() != "Windows" or version != PINNED_VERSION:
        return SolverResolution(
            None, "not-found",
            "FDS executable not installed/configured; no compatible pinned installation for this platform/version",
        )
    candidate = _candidate(PROJECT_ROOT / PINNED_WINDOWS_RELATIVE_PATH, "project-pinned")
    if candidate.executable is None:
        return SolverResolution(
            None, "not-found",
            "FDS executable not installed/configured; checked PATH and the project-pinned FDS 6.11.1 installation",
        )
    try:
        digest = binary_sha256(candidate.executable)
    except OSError as exc:
        return SolverResolution(None, "project-pinned", f"Cannot read project-pinned FDS executable: {exc}")
    if digest != PINNED_BINARY_SHA256:
        return SolverResolution(
            None, "project-pinned",
            "Project-pinned FDS binary checksum differs; reinstall using scripts/install-fds.py before running it",
            sha256=digest,
        )
    return SolverResolution(
        candidate.executable, "project-pinned",
        "Checksum-verified project-pinned FDS 6.11.1 installation found",
        sha256=digest,
    )
