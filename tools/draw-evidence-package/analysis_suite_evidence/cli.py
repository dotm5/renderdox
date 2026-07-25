import argparse
import json
import os
import sys

from . import TOOL_VERSION
from .launcher import run_export


def build_parser():
    parser = argparse.ArgumentParser(
        prog="draw-evidence",
        description="Export a read-only evidence package for one RenderDoc action",
    )
    parser.add_argument("--version", action="version", version=TOOL_VERSION)
    parser.add_argument("--qrenderdoc", required=True)
    parser.add_argument("--capture", required=True)
    parser.add_argument("--event", required=True, type=int)
    parser.add_argument("--instance", type=int, default=0)
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument(
        "--max-resource-mib",
        type=int,
        default=256,
        help="Per-resource export limit in MiB",
    )
    parser.add_argument("--result-json")
    return parser


def main(argv=None):
    arguments = build_parser().parse_args(argv)
    try:
        result = run_export(
            arguments.qrenderdoc,
            arguments.capture,
            arguments.event,
            arguments.output,
            arguments.timeout_seconds,
            arguments.instance,
            arguments.max_resource_mib * 1024 * 1024,
        )
        if arguments.result_json:
            os.makedirs(os.path.dirname(os.path.abspath(arguments.result_json)), exist_ok=True)
            with open(arguments.result_json, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if result.get("status") == "succeeded" else 2
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as exception:
        print("error: {}".format(exception), file=sys.stderr)
        return 2
