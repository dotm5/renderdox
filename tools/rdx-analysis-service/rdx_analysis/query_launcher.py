import json
import os
import subprocess
import tempfile
import time

from . import SCHEMA_VERSION, TOOL_VERSION
from .common import atomic_write_json, bounded_text, sha256_file, utc_now


def _failure(capture_path, operation, reason, details=None):
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "rdx-query-result",
        "toolVersion": TOOL_VERSION,
        "generatedAt": utc_now(),
        "status": "failed",
        "operation": operation,
        "capturePath": os.path.abspath(capture_path),
        "captureSHA256": sha256_file(capture_path)
        if os.path.isfile(capture_path)
        else None,
        "error": {
            "type": reason,
            "message": bounded_text(details or reason),
        },
    }


def run_query(
    qrenderdoc,
    capture_path,
    operation,
    parameters,
    work_root,
    timeout_seconds,
    max_resource_bytes,
    cancel_event=None,
):
    qrenderdoc = os.path.abspath(qrenderdoc)
    capture_path = os.path.abspath(capture_path)
    if not os.path.isfile(qrenderdoc):
        raise ValueError("QRenderDoc executable does not exist: " + qrenderdoc)
    if not os.path.isfile(capture_path):
        raise ValueError("Capture does not exist: " + capture_path)
    os.makedirs(work_root, exist_ok=True)
    work_directory = tempfile.mkdtemp(prefix="q-", dir=work_root)
    result_path = os.path.join(work_directory, "result.json")
    job_path = os.path.join(work_directory, "job.json")
    stdout_path = os.path.join(work_directory, "stdout.log")
    stderr_path = os.path.join(work_directory, "stderr.log")
    artifact_directory = os.path.join(work_directory, "artifacts")
    capture_hash = sha256_file(capture_path)
    atomic_write_json(
        job_path,
        {
            "schemaVersion": SCHEMA_VERSION,
            "capturePath": capture_path,
            "captureSHA256": capture_hash,
            "operation": operation,
            "parameters": parameters,
            "artifactDirectory": artifact_directory,
            "maxResourceBytes": int(max_resource_bytes),
            "resultPath": result_path,
        },
    )

    service_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    entry = os.path.join(service_root, "query_entry.py")
    repository_root = os.path.dirname(os.path.dirname(service_root))
    evidence_root = os.path.join(repository_root, "tools", "draw-evidence-package")
    environment = os.environ.copy()
    environment["RDX_QUERY_JOB"] = job_path
    environment["RDX_QUERY_ROOT"] = service_root
    environment["RDX_EVIDENCE_ROOT"] = evidence_root
    command = [qrenderdoc, "--python", entry]
    started = time.monotonic()
    deadline = started + max(1, int(timeout_seconds))
    process = None
    try:
        with open(stdout_path, "wb") as stdout, open(stderr_path, "wb") as stderr:
            process = subprocess.Popen(
                command,
                cwd=os.path.dirname(qrenderdoc),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            while process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    return _failure(capture_path, operation, "cancelled")
                if time.monotonic() >= deadline:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    return _failure(
                        capture_path,
                        operation,
                        "timeout",
                        "Query exceeded {} seconds".format(timeout_seconds),
                    )
                time.sleep(0.05)
            return_code = process.returncode
    except KeyboardInterrupt:
        if process is not None and process.poll() is None:
            process.terminate()
        raise
    except OSError as exception:
        return _failure(capture_path, operation, "launch-failed", exception)

    if not os.path.isfile(result_path):
        try:
            with open(stderr_path, "r", encoding="utf-8", errors="replace") as stream:
                details = stream.read()
        except OSError:
            details = ""
        return _failure(
            capture_path,
            operation,
            "missing-result",
            "exitCode={}\n{}".format(return_code, details[-12000:]),
        )
    try:
        with open(result_path, "r", encoding="utf-8") as stream:
            result = json.load(stream)
    except (OSError, ValueError) as exception:
        return _failure(capture_path, operation, "invalid-result", exception)
    if (
        result.get("schemaVersion") != SCHEMA_VERSION
        or result.get("kind") != "rdx-query-result"
        or result.get("captureSHA256") != capture_hash
        or result.get("operation") != operation
    ):
        return _failure(
            capture_path, operation, "provenance-mismatch", json.dumps(result)[:4096]
        )
    result["worker"] = {
        "exitCode": return_code,
        "wallDurationMs": int((time.monotonic() - started) * 1000),
        "workDirectory": work_directory,
    }
    return result
