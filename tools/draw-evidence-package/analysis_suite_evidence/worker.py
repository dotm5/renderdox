import json
import os
import time
import traceback

from .common import SCHEMA_VERSION, TOOL_VERSION, atomic_write_json, sha256_file
from .exporter import export_action_evidence


def _result_base(job):
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "draw-evidence-export-result",
        "toolVersion": TOOL_VERSION,
        "capturePath": os.path.abspath(job.get("capturePath", "")),
        "captureSHA256": job.get("captureSHA256"),
        "eventId": int(job.get("eventId", 0)),
    }


def run_job(job):
    import renderdoc as rd

    started = time.monotonic()
    result = _result_base(job)
    capture_path = result["capturePath"]
    if not os.path.isfile(capture_path):
        raise ValueError("Capture path does not exist: {}".format(capture_path))
    actual_hash = sha256_file(capture_path)
    expected_hash = job.get("captureSHA256")
    if expected_hash and str(expected_hash).upper() != actual_hash:
        raise ValueError("Capture SHA-256 changed after the export request was created")
    result["captureSHA256"] = actual_hash

    capture = None
    controller = None
    try:
        capture = rd.OpenCaptureFile()
        open_result = capture.OpenFile(capture_path, "", None)
        result["openResult"] = str(getattr(open_result, "code", open_result))
        if open_result != rd.ResultCode.Succeeded:
            raise RuntimeError("OpenFile failed: {}".format(open_result))
        replay_result, controller = capture.OpenCapture(rd.ReplayOptions(), None)
        result["replayResult"] = str(getattr(replay_result, "code", replay_result))
        if replay_result != rd.ResultCode.Succeeded or controller is None:
            raise RuntimeError("OpenCapture failed: {}".format(replay_result))
        exported = export_action_evidence(
            rd,
            controller,
            capture_path,
            int(job["eventId"]),
            os.path.abspath(job["outputRoot"]),
            int(job.get("instance", 0)),
            int(job.get("maxResourceBytes", 256 * 1024 * 1024)),
        )
        result.update(exported)
        result["status"] = "succeeded"
        return result
    finally:
        if controller is not None:
            controller.Shutdown()
        if capture is not None:
            capture.Shutdown()
        result["durationMs"] = int((time.monotonic() - started) * 1000)


def main():
    job_path = os.environ.get("DRAW_EVIDENCE_JOB")
    if not job_path:
        raise RuntimeError("DRAW_EVIDENCE_JOB is not set")
    with open(job_path, "r", encoding="utf-8") as stream:
        job = json.load(stream)
    output_path = os.path.abspath(job["resultPath"])
    try:
        result = run_job(job)
    except BaseException as exception:
        result = _result_base(job)
        result.update(
            {
                "status": "failed",
                "error": {
                    "type": type(exception).__name__,
                    "message": str(exception),
                    "traceback": traceback.format_exc()[-16384:],
                },
            }
        )
    atomic_write_json(output_path, result)
