import json
import os
import subprocess
import tempfile
import time

from . import SCHEMA_VERSION, TOOL_VERSION
from .common import atomic_write_json, bounded_text, sha256_file, utc_now


def _failed_result(capture_path, capture_hash, reason, details=None):
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "capture-analysis-worker-result",
        "toolVersion": TOOL_VERSION,
        "generatedAt": utc_now(),
        "capturePath": os.path.abspath(capture_path),
        "captureSHA256": capture_hash,
        "status": "failed",
        "workerFailure": {"reason": reason},
        "analysisDurationMs": 0,
        "peakMemoryBytes": None,
    }
    if details:
        result["workerFailure"]["details"] = bounded_text(details)
    return result


def run_worker(qrenderdoc, embedded_entry, capture_path, work_root, timeout_seconds):
    capture_path = os.path.abspath(capture_path)
    capture_hash = sha256_file(capture_path)
    os.makedirs(work_root, exist_ok=True)
    work_directory = tempfile.mkdtemp(prefix="capture-", dir=work_root)
    result_path = os.path.join(work_directory, "worker-result.json")
    job_path = os.path.join(work_directory, "job.json")
    stdout_path = os.path.join(work_directory, "stdout.log")
    stderr_path = os.path.join(work_directory, "stderr.log")
    progress_path = os.path.join(work_directory, "progress.log")
    atomic_write_json(
        job_path,
        {
            "schemaVersion": SCHEMA_VERSION,
            "capturePath": capture_path,
            "captureSHA256": capture_hash,
            "outputPath": result_path,
        },
    )

    environment = os.environ.copy()
    environment["RDX_ANALYSIS_JOB"] = job_path
    environment["RDX_ANALYSIS_PROGRESS"] = progress_path
    environment["RDX_ANALYSIS_ROOT"] = os.path.dirname(os.path.abspath(embedded_entry))
    command = [os.path.abspath(qrenderdoc), "--python", os.path.abspath(embedded_entry)]
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    started = time.monotonic()
    process = None
    try:
        with open(stdout_path, "wb") as stdout, open(stderr_path, "wb") as stderr:
            process = subprocess.Popen(
                command,
                cwd=os.path.dirname(os.path.abspath(qrenderdoc)),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                creationflags=creation_flags,
            )
            try:
                return_code = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
                try:
                    with open(
                        progress_path, "r", encoding="utf-8", errors="replace"
                    ) as stream:
                        progress_text = bounded_text(stream.read())
                except OSError:
                    progress_text = ""
                return _failed_result(
                    capture_path,
                    capture_hash,
                    "timeout",
                    "Worker exceeded {} seconds\nprogress:\n{}".format(
                        timeout_seconds, progress_text
                    ),
                )
    except KeyboardInterrupt:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        raise
    except OSError as exception:
        return _failed_result(capture_path, capture_hash, "launch-failed", str(exception))

    duration_ms = int((time.monotonic() - started) * 1000)
    try:
        with open(stdout_path, "r", encoding="utf-8", errors="replace") as stream:
            stdout_text = stream.read()
        with open(stderr_path, "r", encoding="utf-8", errors="replace") as stream:
            stderr_text = stream.read()
    except OSError:
        stdout_text = ""
        stderr_text = ""

    if not os.path.isfile(result_path):
        return _failed_result(
            capture_path,
            capture_hash,
            "missing-result",
            "exitCode={}\nstdout:\n{}\nstderr:\n{}".format(
                return_code, bounded_text(stdout_text), bounded_text(stderr_text)
            ),
        )

    try:
        with open(result_path, "r", encoding="utf-8") as stream:
            result = json.load(stream)
    except (OSError, ValueError) as exception:
        return _failed_result(
            capture_path,
            capture_hash,
            "invalid-result",
            "{}\nstdout:\n{}\nstderr:\n{}".format(
                exception, bounded_text(stdout_text), bounded_text(stderr_text)
            ),
        )

    if (
        result.get("schemaVersion") != SCHEMA_VERSION
        or result.get("kind") != "capture-analysis-worker-result"
        or result.get("captureSHA256") != capture_hash
    ):
        return _failed_result(
            capture_path,
            capture_hash,
            "result-provenance-mismatch",
            json.dumps(result, ensure_ascii=False)[:4096],
        )

    result["worker"] = {
        "exitCode": return_code,
        "wallDurationMs": duration_ms,
        "stdout": bounded_text(stdout_text),
        "stderr": bounded_text(stderr_text),
    }
    return result
