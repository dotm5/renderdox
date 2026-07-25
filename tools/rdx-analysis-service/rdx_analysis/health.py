import csv
import io

from . import SCHEMA_VERSION, TOOL_VERSION
from .common import utc_now


HEALTH_COLUMNS = [
    "capturePath",
    "captureSHA256",
    "status",
    "openResult",
    "replayResult",
    "api",
    "driver",
    "actionCount",
    "drawCount",
    "dispatchCount",
    "executeIndirectCount",
    "multiActionCount",
    "shaderCount",
    "textureCount",
    "bufferCount",
    "mainOutput",
    "deviceLost",
    "unsupportedFeature",
    "warningCount",
    "errorCount",
    "missingDependencyCount",
    "analysisDurationMs",
    "peakMemoryBytes",
]


def aggregate_health(results, source_description):
    ordered = sorted(results, key=lambda item: item.get("capturePath", "").casefold())
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "capture-health",
        "toolVersion": TOOL_VERSION,
        "generatedAt": utc_now(),
        "source": source_description,
        "captures": ordered,
        "summary": {
            "captureCount": len(ordered),
            "healthyCount": sum(item.get("status") == "healthy" for item in ordered),
            "degradedCount": sum(item.get("status") == "degraded" for item in ordered),
            "failedCount": sum(item.get("status") == "failed" for item in ordered),
        },
    }


def health_csv(document):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=HEALTH_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for capture in document["captures"]:
        row = dict(capture)
        main_output = row.get("mainOutput")
        if isinstance(main_output, dict):
            row["mainOutput"] = "{width}x{height} {format}".format(
                width=main_output.get("width", "unknown"),
                height=main_output.get("height", "unknown"),
                format=main_output.get("format", "unknown"),
            )
        writer.writerow(row)
    return output.getvalue()


def validate_health_document(document):
    errors = []
    if document.get("schemaVersion") != SCHEMA_VERSION:
        errors.append("schemaVersion must be {}".format(SCHEMA_VERSION))
    if document.get("kind") != "capture-health":
        errors.append("kind must be capture-health")
    captures = document.get("captures")
    if not isinstance(captures, list):
        errors.append("captures must be an array")
        return errors
    for index, capture in enumerate(captures):
        prefix = "captures[{}]".format(index)
        for field in ("capturePath", "captureSHA256", "status"):
            if field not in capture:
                errors.append("{} missing {}".format(prefix, field))
        if capture.get("status") not in ("healthy", "degraded", "failed"):
            errors.append("{} has invalid status".format(prefix))
    return errors
