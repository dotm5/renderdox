import json
import os
import sys
import traceback

from . import SCHEMA_VERSION, TOOL_VERSION
from .common import atomic_write_json, utc_now
from .replay import analyse_capture


def main():
    job_path = os.environ.get("RDX_ANALYSIS_JOB")
    if not job_path:
        raise RuntimeError("RDX_ANALYSIS_JOB is not set")
    with open(job_path, "r", encoding="utf-8") as stream:
        job = json.load(stream)

    output_path = job["outputPath"]
    try:
        result = analyse_capture(job["capturePath"])
    except BaseException as exception:
        result = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": "capture-analysis-worker-result",
            "toolVersion": TOOL_VERSION,
            "generatedAt": utc_now(),
            "capturePath": os.path.abspath(job.get("capturePath", "")),
            "captureSHA256": job.get("captureSHA256"),
            "status": "failed",
            "workerException": {
                "type": type(exception).__name__,
                "message": str(exception),
                "traceback": traceback.format_exc(),
            },
        }
    atomic_write_json(output_path, result)


if __name__ == "__main__":
    main()
    sys.exit(0)
