import argparse
import json
import sys

from . import TOOL_VERSION
from .converter import convert_to_fbx, validate_path


def build_parser():
    parser = argparse.ArgumentParser(
        prog="draw-package-converter",
        description="Validate Draw Evidence GLB files and optionally convert them with Blender",
    )
    parser.add_argument("--version", action="version", version=TOOL_VERSION)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("path")
    convert = commands.add_parser("fbx")
    convert.add_argument("--blender", required=True)
    convert.add_argument("--input", required=True)
    convert.add_argument("--output", required=True)
    convert.add_argument("--timeout-seconds", type=int, default=300)
    return parser


def main(argv=None):
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.command == "validate":
            result = validate_path(arguments.path)
        else:
            result = convert_to_fbx(
                arguments.blender,
                arguments.input,
                arguments.output,
                arguments.timeout_seconds,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if result.get("status") in ("pass", "succeeded") else 2
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as exception:
        print("error: {}".format(exception), file=sys.stderr)
        return 2
