import json
import os
import subprocess
import tempfile
import time

from .common import SCHEMA_VERSION, TOOL_VERSION, atomic_write_json, sha256_file


def _failure(capture_path, event_id, reason, details=None):
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "draw-evidence-export-result",
        "toolVersion": TOOL_VERSION,
        "status": "failed",
        "capturePath": os.path.abspath(capture_path),
        "captureSHA256": sha256_file(capture_path)
        if os.path.isfile(capture_path)
        else None,
        "eventId": int(event_id),
        "error": {"type": reason, "message": str(details or reason)[:16384]},
    }
    return result


def run_export(
    qrenderdoc,
    capture_path,
    event_id,
    output_root,
    timeout_seconds=300,
    instance=0,
    max_resource_bytes=256 * 1024 * 1024,
):
    qrenderdoc = os.path.abspath(qrenderdoc)
    capture_path = os.path.abspath(capture_path)
    output_root = os.path.abspath(output_root)
    if not os.path.isfile(qrenderdoc):
        raise ValueError("QRenderDoc executable does not exist: " + qrenderdoc)
    if not os.path.isfile(capture_path):
        raise ValueError("Capture does not exist: " + capture_path)
    os.makedirs(output_root, exist_ok=True)

    tool_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    embedded_entry = os.path.join(tool_root, "embedded_entry.py")
    work_root = os.path.join(output_root, ".draw-evidence-worker")
    os.makedirs(work_root, exist_ok=True)
    work_directory = tempfile.mkdtemp(prefix="job-", dir=work_root)
    job_path = os.path.join(work_directory, "job.json")
    result_path = os.path.join(work_directory, "result.json")
    stdout_path = os.path.join(work_directory, "stdout.log")
    stderr_path = os.path.join(work_directory, "stderr.log")
    capture_hash = sha256_file(capture_path)
    atomic_write_json(
        job_path,
        {
            "schemaVersion": SCHEMA_VERSION,
            "capturePath": capture_path,
            "captureSHA256": capture_hash,
            "eventId": int(event_id),
            "instance": int(instance),
            "maxResourceBytes": int(max_resource_bytes),
            "outputRoot": output_root,
            "resultPath": result_path,
        },
    )

    environment = os.environ.copy()
    environment["DRAW_EVIDENCE_JOB"] = job_path
    environment["DRAW_EVIDENCE_ROOT"] = tool_root
    command = [qrenderdoc, "--python", embedded_entry]
    started = time.monotonic()
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
            try:
                return_code = process.wait(timeout=max(1, int(timeout_seconds)))
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                return _failure(
                    capture_path,
                    event_id,
                    "timeout",
                    "Exporter exceeded {} seconds".format(timeout_seconds),
                )
    except KeyboardInterrupt:
        if process is not None and process.poll() is None:
            process.terminate()
        raise
    except OSError as exception:
        return _failure(capture_path, event_id, "launch-failed", exception)

    if not os.path.isfile(result_path):
        try:
            with open(stderr_path, "r", encoding="utf-8", errors="replace") as stream:
                details = stream.read()
        except OSError:
            details = ""
        return _failure(
            capture_path,
            event_id,
            "missing-result",
            "exitCode={}\n{}".format(return_code, details[-12000:]),
        )
    try:
        with open(result_path, "r", encoding="utf-8") as stream:
            result = json.load(stream)
    except (OSError, ValueError) as exception:
        return _failure(capture_path, event_id, "invalid-result", exception)
    if (
        result.get("schemaVersion") != SCHEMA_VERSION
        or result.get("kind") != "draw-evidence-export-result"
        or result.get("captureSHA256") != capture_hash
        or int(result.get("eventId", -1)) != int(event_id)
    ):
        return _failure(
            capture_path, event_id, "provenance-mismatch", json.dumps(result)[:4096]
        )
    result["worker"] = {
        "exitCode": return_code,
        "wallDurationMs": int((time.monotonic() - started) * 1000),
        "jobDirectory": work_directory,
    }
    return result
