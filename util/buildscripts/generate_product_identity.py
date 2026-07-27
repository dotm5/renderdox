#!/usr/bin/env python3

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPOSITORY_ROOT / "build" / "product_identity.json"
PROPS_PATH = REPOSITORY_ROOT / "build" / "product_identity.props"
PRI_PATH = REPOSITORY_ROOT / "build" / "product_identity.pri"
HEADER_PATH = REPOSITORY_ROOT / "renderdoc" / "generated" / "product_identity.h"

DISPLAY_FIELDS = ("productDisplayName", "uiDisplayName")
BASENAME_FIELDS = (
    "coreBaseName",
    "uiBaseName",
    "commandBaseName",
    "uiStubBaseName",
    "shimBaseName",
)
NAMESPACE_FIELDS = ("configNamespace", "logNamespace")
EXPECTED_FIELDS = {"schemaVersion", *DISPLAY_FIELDS, *BASENAME_FIELDS, *NAMESPACE_FIELDS}
VALID_BASENAME = re.compile(r"^[a-z][a-z0-9_]*$")
VALID_DISPLAY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._+()&'\-]{0,63}$")
VALID_NAMESPACE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *("com{}".format(index) for index in range(1, 10)),
    *("lpt{}".format(index) for index in range(1, 10)),
}


class IdentityError(ValueError):
    pass


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise IdentityError("Duplicate manifest field: {}".format(key))
        result[key] = value
    return result


def load_identity():
    try:
        identity = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8"), object_pairs_hook=unique_object
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, IdentityError) as ex:
        raise IdentityError("Could not read {}: {}".format(MANIFEST_PATH, ex))

    if not isinstance(identity, dict):
        raise IdentityError("Product identity manifest must contain a JSON object")

    fields = set(identity)
    missing = sorted(EXPECTED_FIELDS - fields)
    extra = sorted(fields - EXPECTED_FIELDS)
    if missing:
        raise IdentityError("Missing manifest fields: {}".format(", ".join(missing)))
    if extra:
        raise IdentityError("Unknown manifest fields: {}".format(", ".join(extra)))

    if type(identity["schemaVersion"]) is not int or identity["schemaVersion"] != 1:
        raise IdentityError("Unsupported schemaVersion: {!r}".format(identity["schemaVersion"]))

    for field in DISPLAY_FIELDS:
        value = identity[field]
        if not isinstance(value, str) or not VALID_DISPLAY_NAME.fullmatch(value):
            raise IdentityError(
                "{} must match {}".format(field, VALID_DISPLAY_NAME.pattern)
            )

    for field in BASENAME_FIELDS:
        value = identity[field]
        if not isinstance(value, str) or not VALID_BASENAME.fullmatch(value):
            raise IdentityError(
                "{} must match {}".format(field, VALID_BASENAME.pattern)
            )
        if len(value) > 64:
            raise IdentityError("{} must contain at most 64 characters".format(field))
        if value.casefold() in WINDOWS_RESERVED_NAMES:
            raise IdentityError("{} is a reserved Windows device name".format(field))

    for field in NAMESPACE_FIELDS:
        value = identity[field]
        if not isinstance(value, str) or not VALID_NAMESPACE.fullmatch(value):
            raise IdentityError(
                "{} must match {}".format(field, VALID_NAMESPACE.pattern)
            )
        if value.endswith("."):
            raise IdentityError("{} must not end with a period".format(field))
        if value.split(".", 1)[0].casefold() in WINDOWS_RESERVED_NAMES:
            raise IdentityError("{} is a reserved Windows device name".format(field))

    if len(set(identity[field].lower() for field in BASENAME_FIELDS)) != len(BASENAME_FIELDS):
        raise IdentityError("Every output basename must be unique")

    output_filenames = (
        identity["coreBaseName"] + ".dll",
        identity["uiBaseName"] + ".exe",
        identity["commandBaseName"] + ".exe",
        identity["uiStubBaseName"] + ".exe",
        identity["shimBaseName"] + "32.dll",
        identity["shimBaseName"] + "64.dll",
    )
    if len(set(filename.casefold() for filename in output_filenames)) != len(output_filenames):
        raise IdentityError("Derived Windows output filenames must be unique")

    return identity


def c_string(value):
    return json.dumps(value, ensure_ascii=True)


def render_props(identity):
    properties = (
        ("RDocProductDisplayName", identity["productDisplayName"]),
        ("RDocUIDisplayName", identity["uiDisplayName"]),
        ("RDocCoreBaseName", identity["coreBaseName"]),
        ("RDocUIBaseName", identity["uiBaseName"]),
        ("RDocCommandBaseName", identity["commandBaseName"]),
        ("RDocUIStubBaseName", identity["uiStubBaseName"]),
        ("RDocShimBaseName", identity["shimBaseName"]),
        ("RDocConfigNamespace", identity["configNamespace"]),
        ("RDocLogNamespace", identity["logNamespace"]),
        ("RDocReplayBaseName", identity["coreBaseName"]),
        ("RDocVulkanJsonBaseName", identity["coreBaseName"]),
        ("RDocVulkanLayerName", "VK_LAYER_DCOMP_Capture"),
        ("RDocVulkanEnableVar", "ENABLE_VULKAN_DCOMP_CAPTURE"),
    )

    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">',
        "  <!-- Generated by util/buildscripts/generate_product_identity.py. -->",
        '  <PropertyGroup Label="ProductIdentity">',
    ]
    for name, value in properties:
        lines.append("    <{0}>{1}</{0}>".format(name, xml_escape(value)))
    lines.extend(("  </PropertyGroup>", "</Project>", ""))
    return "\n".join(lines)


def render_pri(identity):
    variables = (
        ("RDOC_CORE_BASE_NAME", identity["coreBaseName"]),
        ("RDOC_UI_BASE_NAME", identity["uiBaseName"]),
        ("RDOC_COMMAND_BASE_NAME", identity["commandBaseName"]),
        ("RDOC_UI_STUB_BASE_NAME", identity["uiStubBaseName"]),
        ("RDOC_SHIM_BASE_NAME", identity["shimBaseName"]),
    )

    lines = [
        "# Generated by util/buildscripts/generate_product_identity.py.",
        "# Edit build/product_identity.json, then regenerate this file.",
        "",
    ]
    for name, value in variables:
        lines.append("{} = {}".format(name, value))
    lines.append("")
    return "\n".join(lines)


def render_header(identity):
    product = identity["productDisplayName"]
    ui_display = identity["uiDisplayName"]
    core = identity["coreBaseName"]
    ui = identity["uiBaseName"]
    command = identity["commandBaseName"]
    ui_stub = identity["uiStubBaseName"]
    shim = identity["shimBaseName"]
    config_namespace = identity["configNamespace"]
    log_namespace = identity["logNamespace"]

    values = (
        ("RDOC_PRODUCT_DISPLAY_NAME", product),
        ("RDOC_UI_DISPLAY_NAME", ui_display),
        ("RDOC_CORE_BASE_NAME", core),
        ("RDOC_UI_BASE_NAME", ui),
        ("RDOC_COMMAND_BASE_NAME", command),
        ("RDOC_UI_STUB_BASE_NAME", ui_stub),
        ("RDOC_SHIM_BASE_NAME", shim),
        ("RDOC_CONFIG_NAMESPACE", config_namespace),
        ("RDOC_LOG_NAMESPACE", log_namespace),
        ("RDOC_CORE_FILENAME", core + ".dll"),
        ("RDOC_UI_FILENAME", ui + ".exe"),
        ("RDOC_COMMAND_FILENAME", command + ".exe"),
        ("RDOC_UI_STUB_FILENAME", ui_stub + ".exe"),
        ("RDOC_SHIM32_FILENAME", shim + "32.dll"),
        ("RDOC_SHIM64_FILENAME", shim + "64.dll"),
        ("RDOC_CANONICAL_UI_FILENAME", "qrenderdoc.exe"),
        ("RDOC_CANONICAL_COMMAND_FILENAME", "renderdoccmd.exe"),
        ("RDOC_CANONICAL_UI_STUB_FILENAME", "renderdocui.exe"),
        ("RDOC_VULKAN_JSON_BASE_NAME", core),
        ("RDOC_CORE_FILE_DESCRIPTION", "Core DLL for " + product),
        ("RDOC_UI_FILE_DESCRIPTION", product),
        ("RDOC_COMMAND_FILE_DESCRIPTION", command + " - https://renderdoc.org/"),
        ("RDOC_UI_STUB_FILE_DESCRIPTION", ui_display + " launcher"),
        ("RDOC_SHIM_FILE_DESCRIPTION", product + " injection shim"),
    )

    lines = [
        "#ifndef DCOMP_GENERATED_PRODUCT_IDENTITY_H",
        "#define DCOMP_GENERATED_PRODUCT_IDENTITY_H",
        "",
        "// Generated by util/buildscripts/generate_product_identity.py.",
        "// Edit build/product_identity.json, then regenerate this file.",
        "",
        "#if defined(RDOC_REPLAY_PROGRAM_MARKER)",
        "#undef RDOC_REPLAY_PROGRAM_MARKER",
        "#endif",
        "#define RDOC_REPLAY_PROGRAM_MARKER {}__replay__marker".format(core),
    ]
    wide_values = {
        "RDOC_CORE_BASE_NAME",
        "RDOC_UI_BASE_NAME",
        "RDOC_COMMAND_BASE_NAME",
        "RDOC_UI_STUB_BASE_NAME",
        "RDOC_SHIM_BASE_NAME",
        "RDOC_CONFIG_NAMESPACE",
        "RDOC_LOG_NAMESPACE",
        "RDOC_CORE_FILENAME",
        "RDOC_UI_FILENAME",
        "RDOC_COMMAND_FILENAME",
        "RDOC_UI_STUB_FILENAME",
        "RDOC_SHIM32_FILENAME",
        "RDOC_SHIM64_FILENAME",
        "RDOC_CANONICAL_UI_FILENAME",
        "RDOC_CANONICAL_COMMAND_FILENAME",
        "RDOC_CANONICAL_UI_STUB_FILENAME",
    }

    for name, value in values:
        lines.append("#define {} {}".format(name, c_string(value)))
        if name in wide_values:
            lines.append("#define {}_W L{}".format(name, c_string(value)))
    lines.extend(("", "#endif    // DCOMP_GENERATED_PRODUCT_IDENTITY_H", ""))
    return "\n".join(lines)


def expected_outputs(identity):
    return {
        PROPS_PATH: render_props(identity),
        PRI_PATH: render_pri(identity),
        HEADER_PATH: render_header(identity),
    }


def write_outputs(outputs):
    staged = []
    try:
        for path, contents in outputs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                if path.read_text(encoding="utf-8") == contents:
                    print("current {}".format(path.relative_to(REPOSITORY_ROOT)))
                    continue
            except (OSError, UnicodeDecodeError):
                pass

            temporary = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=str(path.parent),
                prefix=path.name + ".",
                suffix=".tmp",
                delete=False,
            )
            temporary_path = Path(temporary.name)
            staged.append((path, temporary_path))
            with temporary as output:
                output.write(contents)
                output.flush()
                os.fsync(output.fileno())

        for path, temporary_path in staged:
            os.replace(str(temporary_path), str(path))
            print("wrote {}".format(path.relative_to(REPOSITORY_ROOT)))
    finally:
        for _, temporary_path in staged:
            if temporary_path.exists():
                temporary_path.unlink()


def check_outputs(outputs):
    stale = []
    for path, expected in outputs.items():
        try:
            actual = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            stale.append(path)
            continue
        if actual != expected:
            stale.append(path)

    if stale:
        for path in stale:
            print(
                "stale generated product identity: {}".format(
                    path.relative_to(REPOSITORY_ROOT)
                ),
                file=sys.stderr,
            )
        return 1

    print("product identity generated files are current")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Generate or verify RenderDoc product identity build artifacts."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="regenerate checked-in outputs")
    mode.add_argument("--check", action="store_true", help="fail if outputs are missing or stale")
    args = parser.parse_args()

    try:
        outputs = expected_outputs(load_identity())
    except IdentityError as ex:
        print("product identity error: {}".format(ex), file=sys.stderr)
        return 2

    try:
        if args.write:
            write_outputs(outputs)
            return 0
        return check_outputs(outputs)
    except OSError as ex:
        print("product identity I/O error: {}".format(ex), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
