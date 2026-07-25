import argparse
import json
import os
import sys

from . import SCHEMA_VERSION, TOOL_VERSION
from .common import atomic_write_json, atomic_write_text, sha256_file, utc_now
from .health import aggregate_health, health_csv, validate_health_document
from .launcher import run_worker


def _manifest_entries(path):
    with open(path, "r", encoding="utf-8-sig") as stream:
        document = json.load(stream)
    if isinstance(document, list):
        entries = document
    elif isinstance(document, dict):
        entries = document.get("captures", [])
    else:
        raise ValueError("Manifest must be an array or an object with a captures array")

    resolved = []
    base = os.path.dirname(os.path.abspath(path))
    for entry in entries:
        pairing = None
        if isinstance(entry, str):
            value = entry
        elif isinstance(entry, dict):
            value = entry.get("path")
            pairing = {
                key: entry[key]
                for key in ("pairId", "platform", "counterpart")
                if key in entry
            }
        else:
            raise ValueError("Manifest entries must be strings or objects")
        if not value:
            raise ValueError("Manifest capture entry is missing path")
        if not os.path.isabs(value):
            value = os.path.join(base, value)
        resolved.append((os.path.abspath(value), pairing))
    return resolved


def expand_inputs(inputs, recursive=False):
    captures = []
    for input_path in inputs:
        path = os.path.abspath(input_path)
        if os.path.isdir(path):
            if recursive:
                for root, directories, files in os.walk(path):
                    directories.sort(key=str.casefold)
                    for filename in sorted(files, key=str.casefold):
                        if filename.lower().endswith(".rdc"):
                            captures.append((os.path.join(root, filename), None))
            else:
                for filename in sorted(os.listdir(path), key=str.casefold):
                    candidate = os.path.join(path, filename)
                    if os.path.isfile(candidate) and filename.lower().endswith(".rdc"):
                        captures.append((candidate, None))
        elif path.lower().endswith(".json") and os.path.isfile(path):
            captures.extend(_manifest_entries(path))
        else:
            captures.append((path, None))

    deduplicated = []
    seen = set()
    for path, pairing in captures:
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append((os.path.abspath(path), pairing))
    return sorted(deduplicated, key=lambda item: item[0].casefold())


def _invalid_input(path, message):
    capture_hash = sha256_file(path) if os.path.isfile(path) else None
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "capture-analysis-worker-result",
        "toolVersion": TOOL_VERSION,
        "generatedAt": utc_now(),
        "capturePath": os.path.abspath(path),
        "captureSHA256": capture_hash,
        "status": "failed",
        "workerFailure": {"reason": "invalid-input", "details": message},
        "analysisDurationMs": 0,
        "peakMemoryBytes": None,
    }


def _health_projection(result):
    fields = (
        "capturePath",
        "captureSHA256",
        "captureSizeBytes",
        "status",
        "openResult",
        "replayResult",
        "api",
        "driver",
        "driverInformation",
        "localRenderer",
        "gpuVendor",
        "degradedReplay",
        "actionCount",
        "drawCount",
        "dispatchCount",
        "executeIndirectCount",
        "multiActionCount",
        "indirectActionCount",
        "shaderCount",
        "textureCount",
        "bufferCount",
        "mainOutput",
        "fatalError",
        "deviceLost",
        "unsupportedFeature",
        "warningCount",
        "errorCount",
        "missingDependencyCount",
        "missingDependencies",
        "captureVersion",
        "replayVersion",
        "analysisDurationMs",
        "peakMemoryBytes",
        "workerFailure",
        "workerException",
    )
    return {field: result[field] for field in fields if field in result}


def _artifact(kind, results, field):
    captures = []
    for result in results:
        if field not in result:
            continue
        captures.append(
            {
                "capturePath": result["capturePath"],
                "captureSHA256": result["captureSHA256"],
                field: result[field],
            }
        )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": kind,
        "toolVersion": TOOL_VERSION,
        "generatedAt": utc_now(),
        "captures": captures,
    }


def write_outputs(output_directory, results, source):
    os.makedirs(output_directory, exist_ok=True)
    health = aggregate_health([_health_projection(item) for item in results], source)
    errors = validate_health_document(health)
    if errors:
        raise RuntimeError("Generated health document is invalid: " + "; ".join(errors))

    atomic_write_json(os.path.join(output_directory, "capture-health.json"), health)
    atomic_write_text(
        os.path.join(output_directory, "capture-health.csv"), health_csv(health)
    )
    atomic_write_json(
        os.path.join(output_directory, "pass-graph.json"),
        _artifact("pass-graph", results, "passGraph"),
    )
    atomic_write_json(
        os.path.join(output_directory, "action-signatures.json"),
        _artifact("action-signatures", results, "actionSignatures"),
    )
    atomic_write_json(
        os.path.join(output_directory, "resource-summary.json"),
        _artifact("resource-summary", results, "resourceSummary"),
    )
    atomic_write_json(
        os.path.join(output_directory, "shader-summary.json"),
        _artifact("shader-summary", results, "shaderSummary"),
    )
    atomic_write_json(
        os.path.join(output_directory, "multiaction-action-map.json"),
        _artifact("multiaction-action-map", results, "multiActionMap"),
    )

    error_lines = []
    for result in results:
        if result.get("status") == "failed":
            error_lines.append(
                "{} [{}]\n{}\n".format(
                    result.get("capturePath"),
                    result.get("captureSHA256"),
                    json.dumps(
                        result.get("workerFailure")
                        or result.get("workerException")
                        or result.get("fatalError")
                        or result.get("replayResult")
                        or result.get("openResult"),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            )
        for message in result.get("messages", []):
            if message.get("severity") == "High":
                error_lines.append(
                    "{} EID {}: {}\n".format(
                        result.get("capturePath"),
                        message.get("eventId"),
                        message.get("description"),
                    )
                )
    atomic_write_text(
        os.path.join(output_directory, "errors.log"), "".join(error_lines)
    )
    return health


def health_command(arguments):
    qrenderdoc = os.path.abspath(arguments.qrenderdoc)
    if not os.path.isfile(qrenderdoc):
        raise ValueError("QRenderDoc executable does not exist: " + qrenderdoc)
    captures = expand_inputs(arguments.input, arguments.recursive)
    if not captures:
        raise ValueError("No captures were found")

    output_directory = os.path.abspath(arguments.output)
    service_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    embedded_entry = os.path.join(service_root, "embedded_entry.py")
    work_root = os.path.join(output_directory, ".worker")
    results = []
    for capture_path, pairing in captures:
        if not os.path.isfile(capture_path):
            result = _invalid_input(capture_path, "Capture path does not exist")
        elif not capture_path.lower().endswith(".rdc"):
            result = _invalid_input(capture_path, "Capture path does not end in .rdc")
        else:
            result = run_worker(
                qrenderdoc,
                embedded_entry,
                capture_path,
                work_root,
                arguments.timeout_seconds,
            )
        if pairing:
            result["pairing"] = pairing
        results.append(result)
        print(
            "[{}/{}] {}: {}".format(
                len(results), len(captures), result["status"], capture_path
            ),
            flush=True,
        )

    source = {
        "inputs": [os.path.abspath(item) for item in arguments.input],
        "recursive": bool(arguments.recursive),
    }
    health = write_outputs(output_directory, results, source)
    failed = health["summary"]["failedCount"]
    print(
        "Wrote {} capture result(s) to {}".format(len(results), output_directory),
        flush=True,
    )
    return 0 if failed == 0 or arguments.allow_partial else 2


def build_parser():
    parser = argparse.ArgumentParser(
        prog="rdx-analysis",
        description="Read-only RenderDoc capture analysis tools",
    )
    parser.add_argument("--version", action="version", version=TOOL_VERSION)
    subcommands = parser.add_subparsers(dest="command", required=True)
    health = subcommands.add_parser("health", help="Analyse one or more existing RDC files")
    health.add_argument(
        "--qrenderdoc",
        default=os.environ.get("RDX_QRENDERDOC"),
        required=os.environ.get("RDX_QRENDERDOC") is None,
        help="Path to the matching QRenderDoc executable",
    )
    health.add_argument(
        "--input",
        action="append",
        required=True,
        help="RDC file, directory, or JSON manifest (repeatable)",
    )
    health.add_argument("--recursive", action="store_true")
    health.add_argument("--output", required=True)
    health.add_argument("--timeout-seconds", type=int, default=300)
    health.add_argument("--allow-partial", action="store_true")
    health.set_defaults(handler=health_command)
    return parser


def main(argv=None):
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        return arguments.handler(arguments)
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as exception:
        print("error: {}".format(exception), file=sys.stderr)
        return 2
