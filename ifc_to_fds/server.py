"""Loopback service, bounded streaming uploads and isolated conversion jobs."""

import asyncio
from contextlib import asynccontextmanager
import hmac
import json
import os
from pathlib import Path
import shutil
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Query, Body
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from .jobs import JobManager
from .results import ARTIFACTS
from .http_limits import BodyLimitMiddleware
from .mapping.scope import SpatialScope
from .validation.acceptance import AuditConfig
from .fire.scenario_request import ScenarioRequest

manager = JobManager(
    max_waiting=int(os.getenv("IFCFDS_MAX_WAITING", "2")),
    timeout_s=int(os.getenv("IFCFDS_TIMEOUT_S", "1800")),
)
MAX_FILE = int(os.getenv("IFCFDS_MAX_FILE_BYTES", str(200 * 1024**2)))
MAX_TOTAL = int(os.getenv("IFCFDS_MAX_JOB_BYTES", str(500 * 1024**2)))


@asynccontextmanager
async def lifespan(app):
    yield
    manager.close()


app = FastAPI(
    title="IFCtoFDS local conversion and audit", version="0.5.0", lifespan=lifespan
)

app.add_middleware(BodyLimitMiddleware, maximum=MAX_TOTAL + 1024**2)


@app.middleware("http")
async def security_guard(request: Request, call_next):
    # 1. Host header validation
    allowed_hosts_str = os.getenv("IFCFDS_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1],testserver")
    if allowed_hosts_str != "*":
        allowed_hosts = {h.strip().lower() for h in allowed_hosts_str.split(",") if h.strip()}
        host_header = request.headers.get("host", "").strip()
        if not host_header:
            raw_host = ""
        elif host_header.startswith("[") and "]" in host_header:
            raw_host = host_header[: host_header.index("]") + 1].lower()
        else:
            raw_host = host_header.split(":")[0].strip().lower()
        if not raw_host or raw_host not in allowed_hosts:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=400, content={"detail": f"Invalid Host header: {raw_host or 'missing'}"})

    # 2. API Key authentication for /api/* (excluding /api/health)
    api_key = os.getenv("IFCFDS_API_KEY")
    if api_key and request.url.path.startswith("/api/") and request.url.path != "/api/health":
        provided_key = request.headers.get("x-api-key")
        if not provided_key:
            auth_header = request.headers.get("authorization", "")
            if auth_header.lower().startswith("bearer "):
                provided_key = auth_header[7:].strip()
        if not provided_key or not hmac.compare_digest(provided_key, api_key):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
                headers={"WWW-Authenticate": "Bearer"},
            )

    # 3. Origin guard for state-modifying requests
    origin = request.headers.get("origin")
    allowed_origins_str = os.getenv("IFCFDS_ALLOWED_ORIGINS", "")
    allowed_origins = {o.strip().rstrip("/") for o in allowed_origins_str.split(",") if o.strip()}
    if (
        request.method not in ("GET", "HEAD", "OPTIONS")
        and origin
        and origin.rstrip("/") != str(request.base_url).rstrip("/")
        and origin.rstrip("/") not in allowed_origins
    ):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=403,
            content={"detail": "Use the workbench served by this local backend"},
        )

    response = await call_next(request)
    # HTTP security headers (M-7)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


@app.get("/api/reference-cases")
def reference_cases():
    from .results import registered_cases

    return {"cases": registered_cases()}


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "ifc_to_fds", "version": "0.5.0"}


def configuration_value(
    text, cell_size=None, storey=None, all_geom=None, include_review=None, profile=None
):
    try:
        config = json.loads(text or "{}")
        if not isinstance(config, dict):
            raise ValueError("Configuration must be a JSON object")
        for key, value in (
            ("cell_size", cell_size),
            ("all_geom", all_geom),
            ("include_review", include_review),
            ("profile", profile),
        ):
            if value is not None:
                config[key] = value
        if storey:
            config.setdefault("scope", {})["storeys"] = [storey]
        import math

        cell = float(config.get("cell_size", 0.2))
        if not math.isfinite(cell) or cell <= 0:
            raise ValueError("cell_size must be finite and positive")
        config["cell_size"] = cell
        SpatialScope.model_validate(config.get("scope", {}))
        AuditConfig.model_validate(config.get("audit", {}))
        case = config.get("reference_case")
        if case:
            registered = json.loads(os.getenv("IFCFDS_REFERENCE_CASES", "{}"))
            if case not in registered:
                raise ValueError(
                    "Choose a registered reference case ID; server paths are not accepted"
                )
            entry = registered[case]
            config["reference_case"] = str(
                Path(entry if isinstance(entry, str) else entry["path"]).resolve()
            )
        # Executables are local operator configuration, never selectable by an upload.
        if any(
            config.get("audit", {}).get(k)
            for k in (
                "solver_executable",
                "solver_evidence_directory",
                "boundary_fixture_certificate",
            )
        ):
            raise ValueError(
                "Solver executable must be configured by the local operator"
            )
        if os.getenv("IFCFDS_SOLVER"):
            config.setdefault("audit", {})["solver_executable"] = os.environ[
                "IFCFDS_SOLVER"
            ]
        if os.getenv("IFCFDS_BOUNDARY_CERTIFICATE"):
            config.setdefault("audit", {})["boundary_fixture_certificate"] = os.environ[
                "IFCFDS_BOUNDARY_CERTIFICATE"
            ]
        from .pipeline import validate_configuration

        return validate_configuration(config)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc))


async def store_uploads(uploads):
    if not uploads or len(uploads) > 16:
        raise HTTPException(422, "Upload between 1 and 16 IFC files")
    import uuid

    directory = manager.root / ("job-" + uuid.uuid4().hex)
    directory.mkdir()
    total = 0
    paths = []
    original_names = {}
    try:
        for index, upload in enumerate(uploads):
            if not (upload.filename or "").lower().endswith(".ifc"):
                raise HTTPException(422, "Only .ifc uploads are accepted")
            path = directory / f"source-{index}.ifc"
            size = 0
            with path.open("wb") as output:
                while True:
                    chunk = await upload.read(1024**2)
                    if not chunk:
                        break
                    size += len(chunk)
                    total += len(chunk)
                    if size > MAX_FILE or total > MAX_TOTAL:
                        raise HTTPException(
                            413, "IFC upload exceeds configured size limit"
                        )
                    output.write(chunk)
            if size == 0:
                raise HTTPException(422, "Empty IFC file")
            paths.append(path)
            original_names[path.name] = Path(upload.filename.replace("\\", "/")).name
        (directory / "upload-names.json").write_text(
            json.dumps(original_names), encoding="utf-8"
        )
        return directory, paths
    except (Exception, asyncio.CancelledError):
        shutil.rmtree(directory, ignore_errors=True)
        raise
    finally:
        for upload in uploads:
            await upload.close()


@app.post("/api/inventory")
async def inventory(
    file: Optional[UploadFile] = File(None),
    files: Optional[list[UploadFile]] = File(None),
):
    if not manager.can_accept():
        raise HTTPException(429, "Job queue is full; retry after existing jobs finish")
    directory, paths = await store_uploads(files or ([file] if file else []))
    try:
        job = manager.submit(paths, {}, directory, mode="inventory")
    except OverflowError as exc:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(429, str(exc))
    return await wait_for_job(job["id"])


async def wait_for_job(jid):
    try:
        while True:
            state = manager.snapshot(jid)
            if state["state"] == "COMPLETED":
                return manager.result(jid)
            if state["state"] in ("FAILED", "TIMED_OUT", "CANCELLED"):
                raise HTTPException(422, state.get("error") or state["state"])
            await asyncio.sleep(0.2)
    except asyncio.CancelledError:
        manager.cancel(jid)
        raise


@app.post("/api/jobs", status_code=202)
async def submit(files: list[UploadFile] = File(...), configuration: str = Form("{}")):
    config = configuration_value(configuration)
    if not manager.can_accept():
        raise HTTPException(429, "Job queue is full; retry after existing jobs finish")
    directory, paths = await store_uploads(files)
    try:
        return manager.submit(paths, config, directory)
    except OverflowError as exc:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(429, str(exc))


@app.post("/api/preview-jobs", status_code=202)
async def submit_preview(file: UploadFile = File(...)):
    if not manager.can_accept():
        raise HTTPException(429, "Job queue is full; retry after existing jobs finish")
    directory, paths = await store_uploads([file])
    try:
        return manager.submit(paths, {}, directory, mode="preview")
    except OverflowError as exc:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(429, str(exc))


@app.post("/api/scenario-jobs", status_code=202)
async def submit_scenario_job(payload: ScenarioRequest):
    if not manager.can_accept():
        raise HTTPException(429, "Job queue is full; retry after existing jobs finish")
    import uuid

    raw_payload = payload.model_dump(mode="json", exclude_none=True)
    directory = manager.root / ("job-" + uuid.uuid4().hex)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        (directory / "scenario.json").write_text(
            json.dumps(raw_payload), encoding="utf-8"
        )
        return manager.submit([], raw_payload, directory, mode="scenario")
    except OverflowError as exc:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(429, str(exc))
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


@app.get("/api/jobs/{jid}")
def status(jid: str):
    try:
        return manager.snapshot(jid)
    except KeyError:
        raise HTTPException(404, "Unknown job")


@app.post("/api/jobs/{jid}/cancel")
def cancel_job(jid: str):
    try:
        return manager.cancel(jid)
    except KeyError:
        raise HTTPException(404, "Unknown job")


@app.delete("/api/jobs/{jid}")
def delete_job(jid: str, purge: bool = False):
    try:
        if not purge:
            with manager.lock:
                # Read-only use of the jobs view (do not mutate); writes go
                # through the repository/service methods under the same lock.
                job = manager.jobs.get(jid)
                if not job:
                    raise HTTPException(404, "Unknown job")
                if job["state"] not in ("QUEUED", "RUNNING"):
                    raise HTTPException(
                        409,
                        "Job is terminal; pass ?purge=true to delete its artifacts",
                    )
        return manager.delete_job(jid, purge=purge)
    except KeyError:
        raise HTTPException(404, "Unknown job")


@app.get("/api/jobs/{jid}/result")
def result(
    jid: str,
    offset: int = Query(0, ge=0),
    limit: Optional[int] = Query(None, ge=1),
):
    try:
        manager.touch(jid)
        data = manager.result(jid)
        if (offset > 0 or limit is not None) and isinstance(data, dict):
            all_f = data.get("findings", [])
            end = (offset + limit) if limit is not None else len(all_f)
            paged = dict(data)
            paged["findings"] = all_f[offset:end]
            paged["findings_offset"] = offset
            paged["findings_limit"] = limit
            return paged
        return data
    except KeyError:
        raise HTTPException(404, "Unknown job")
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.get("/api/jobs/{jid}/diagnostics")
def diagnostics(jid: str):
    with manager.lock:
        job = manager.jobs.get(jid)
        if not job:
            raise HTTPException(404, "Unknown job")
        manager.touch(jid)
        path = Path(job["directory"]) / "diagnostics.json"
        if not path.is_file():
            raise HTTPException(404, "No diagnostic produced")
        return FileResponse(
            path, filename="diagnostics.json", media_type="application/json"
        )


@app.get("/api/jobs/{jid}/artifacts/{artifact}")
def artifact(jid: str, artifact: str):
    if artifact not in ARTIFACTS:
        raise HTTPException(404, "Unknown artifact")
    with manager.lock:
        if jid not in manager.jobs:
            raise HTTPException(404, "Unknown job")
        job = manager.jobs[jid]
        if job["state"] != "COMPLETED":
            raise HTTPException(409, "Job is not complete")
        manager.touch(jid)
        path = Path(job["directory"]) / ARTIFACTS[artifact]
        if not path.exists():
            raise HTTPException(404, "Artifact not produced by this job")
        return FileResponse(path, filename=ARTIFACTS[artifact])


@app.get("/api/jobs/{jid}/checkpoints/{artifact}")
def checkpoint_artifact(jid: str, artifact: str):
    if artifact not in ARTIFACTS:
        raise HTTPException(404, "Unknown artifact")
    with manager.lock:
        if jid not in manager.jobs:
            raise HTTPException(404, "Unknown job")
        job = manager.jobs[jid]
        manager.touch(jid)
        path = Path(job["directory"]) / ARTIFACTS[artifact]
        if not path.is_file():
            raise HTTPException(404, "Checkpoint artifact not available")
        response = FileResponse(path, filename=ARTIFACTS[artifact])
        response.headers["X-Verification-Status"] = (
            "UNACCEPTED-AUDIT_INCOMPLETE-DO_NOT_USE_AS_VERIFIED_OUTPUT"
        )
        return response


@app.get("/api/jobs/{jid}/geometry-batch")
def geometry_batch(jid: str, payloads: list[str] = Query(...)):
    if not 1 <= len(payloads) <= 16:
        raise HTTPException(422, "Request between 1 and 16 geometry payloads")
    try:
        manager.touch(jid)
    except KeyError:
        raise HTTPException(404, "Unknown job")
    # Reuse the job-local, completed-artifact whitelist for every member.
    paths = [Path(geometry_payload(jid, key).path) for key in payloads]
    length = sum(path.stat().st_size for path in paths)
    if length > 16 * 1024**2:
        raise HTTPException(
            413, "Geometry batch exceeds 16 MiB; fetch large payloads individually"
        )

    def chunks():
        for path in paths:
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024**2), b""):
                    yield block

    return StreamingResponse(
        chunks(),
        media_type="application/octet-stream",
        headers={"Content-Length": str(length)},
    )


@app.get("/api/jobs/{jid}/geometry/{payload}")
def geometry_payload(jid: str, payload: str):
    if len(payload) != 64 or any(c not in "0123456789abcdef" for c in payload):
        raise HTTPException(404, "Unknown geometry payload")
    with manager.lock:
        job = manager.jobs.get(jid)
        if not job:
            raise HTTPException(404, "Unknown job")
        if job["state"] != "COMPLETED":
            raise HTTPException(409, "Job is not complete")
        manager.touch(jid)
        index_path = Path(job["directory"]) / "model_geometry.json"
        if not index_path.is_file():
            raise HTTPException(404, "Geometry index not available for this job")
        if "_geometry_payloads" not in job:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            job["_geometry_payloads"] = {
                ref["payload"]
                for entry in index["elements"].values()
                for ref in [entry.get("mesh"), *entry.get("openings", {}).values()]
                if ref
            }
        linked = job["_geometry_payloads"]
        if payload not in linked:
            raise HTTPException(404, "Unlinked geometry payload")
        path = index_path.with_suffix(".payloads") / (payload + ".bin")
        if not path.is_file():
            raise HTTPException(404, "Missing geometry payload")
        return FileResponse(path, media_type="application/octet-stream")


@app.post("/api/convert")
async def legacy_convert(
    file: UploadFile = File(...),
    cell_size: Optional[float] = Form(None),
    storey: Optional[str] = Form(None),
    all_geom: Optional[bool] = Form(None),
    include_review: Optional[bool] = Form(None),
    profile: Optional[str] = Form(None),
    configuration: str = Form("{}"),
):
    if not manager.can_accept():
        raise HTTPException(429, "Job queue is full; retry after existing jobs finish")
    config = configuration_value(
        configuration,
        cell_size=cell_size,
        storey=storey,
        all_geom=all_geom,
        include_review=include_review,
        profile=profile,
    )
    directory, paths = await store_uploads([file])
    try:
        job = manager.submit(paths, config, directory)
    except OverflowError as exc:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(429, str(exc))
    return await wait_for_job(job["id"])


# Serve only public web assets. Never expose .git, Python sources, uploads or job files.
root = Path(__file__).resolve().parent.parent
for name in ("js", "css"):
    app.mount("/" + name, StaticFiles(directory=root / name), name=name)


@app.get("/")
@app.get("/index.html")
def index():
    return FileResponse(root / "index.html")


@app.get("/guide.html")
def guide():
    return FileResponse(root / "guide.html")
