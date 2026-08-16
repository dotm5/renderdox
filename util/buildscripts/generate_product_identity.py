#!/usr/bin/env python3

import argparse
import json
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPOSITORY_ROOT / "build" / "product_identity.json"
PROPS_PATH = REPOSITORY_ROOT / "build" / "product_identity.props"
PRI_PATH = REPOSITORY_ROOT / "build" / "product_identity.pri"
CMAKE_IDENTITY_PATH = REPOSITORY_ROOT / "build" / "product_identity.cmake"
HEADER_PATH = REPOSITORY_ROOT / "renderdoc" / "generated" / "product_identity.h"
WIX_INCLUDE_PATH = REPOSITORY_ROOT / "build" / "product_identity.wxi"

DISPLAY_FIELDS = ("productDisplayName", "uiDisplayName")
BASENAME_FIELDS = (
    "coreBaseName",
    "uiBaseName",
    "commandBaseName",
    "uiStubBaseName",
    "shimBaseName",
)
NAMESPACE_FIELDS = ("configNamespace", "logNamespace")
VULKAN_FIELDS = ("vulkanLayerName", "vulkanEnableVar")
GUID_FIELDS = (
    "installerUpgradeCode",
    "thumbnailHandlerClsid",
    "fileAssociationRdcComponentGuid",
    "fileAssociationCapComponentGuid",
)
EXPECTED_FIELDS = {
    "schemaVersion",
    *DISPLAY_FIELDS,
    *BASENAME_FIELDS,
    *NAMESPACE_FIELDS,
    *VULKAN_FIELDS,
    *GUID_FIELDS,
}
VALID_BASENAME = re.compile(r"^[a-z][a-z0-9_]*$")
VALID_DISPLAY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._+()&'\-]{0,63}$")
VALID_NAMESPACE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
VALID_VULKAN_LAYER = re.compile(r"^VK_LAYER_[A-Za-z0-9_]+$")
VALID_ENVIRONMENT_VARIABLE = re.compile(r"^[A-Z][A-Z0-9_]+$")
VALID_GUID = re.compile(
    r"^[0-9A-F]{8}-[0-9A-F]{4}-[1-5][0-9A-F]{3}-[89AB][0-9A-F]{3}-[0-9A-F]{12}$"
)
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

    if type(identity["schemaVersion"]) is not int or identity["schemaVersion"] != 2:
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

    if not VALID_VULKAN_LAYER.fullmatch(identity["vulkanLayerName"]):
        raise IdentityError(
            "vulkanLayerName must match {}".format(VALID_VULKAN_LAYER.pattern)
        )
    if not VALID_ENVIRONMENT_VARIABLE.fullmatch(identity["vulkanEnableVar"]):
        raise IdentityError(
            "vulkanEnableVar must match {}".format(
                VALID_ENVIRONMENT_VARIABLE.pattern
            )
        )
    if not identity["vulkanEnableVar"].startswith("ENABLE_"):
        raise IdentityError("vulkanEnableVar must start with ENABLE_")

    for field in GUID_FIELDS:
        value = identity[field]
        if not isinstance(value, str) or not VALID_GUID.fullmatch(value):
            raise IdentityError("{} must be an uppercase RFC 4122 GUID".format(field))
    if len({identity[field] for field in GUID_FIELDS}) != len(GUID_FIELDS):
        raise IdentityError("Every installer identity GUID must be unique")

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


def cmake_string(value):
    return value.replace("\\", "\\\\").replace('"', '\\"').replace(";", "\\;")


def c_guid_initializer(value):
    guid = uuid.UUID(value)
    data4 = (guid.clock_seq_hi_variant, guid.clock_seq_low) + tuple(
        guid.node.to_bytes(6, byteorder="big")
    )
    return "{{0x{:08x}, 0x{:04x}, 0x{:04x}, {{{}}}}}".format(
        guid.time_low,
        guid.time_mid,
        guid.time_hi_version,
        ", ".join("0x{:02x}".format(byte) for byte in data4),
    )


def derived_identity(identity):
    namespace = identity["configNamespace"]
    return {
        "captureProgId": namespace + ".RDCCapture.1",
        "settingsProgId": namespace + ".RDCSettings.1",
        "globalHookDataBaseName": namespace + "GlobalHookData",
        "globalHookData32Name": namespace + "GlobalHookData32",
        "globalHookData64Name": namespace + "GlobalHookData64",
        "crashHandlerReadyEventFallback": namespace + "CrashHandlerReady",
        "vulkanDisableVar": "DISABLE_" + identity["vulkanEnableVar"][len("ENABLE_") :],
    }


def render_props(identity):
    derived = derived_identity(identity)
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
        ("RDocCaptureProgId", derived["captureProgId"]),
        ("RDocSettingsProgId", derived["settingsProgId"]),
        ("RDocGlobalHookDataBaseName", derived["globalHookDataBaseName"]),
        ("RDocGlobalHookData32Name", derived["globalHookData32Name"]),
        ("RDocGlobalHookData64Name", derived["globalHookData64Name"]),
        (
            "RDocCrashHandlerReadyEventFallback",
            derived["crashHandlerReadyEventFallback"],
        ),
        ("RDocReplayBaseName", identity["coreBaseName"]),
        ("RDocVulkanJsonBaseName", identity["coreBaseName"]),
        ("RDocVulkanLayerName", identity["vulkanLayerName"]),
        ("RDocVulkanEnableVar", identity["vulkanEnableVar"]),
        ("RDocVulkanDisableVar", derived["vulkanDisableVar"]),
        ("RDocInstallerUpgradeCode", identity["installerUpgradeCode"]),
        ("RDocThumbnailHandlerClsid", identity["thumbnailHandlerClsid"]),
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
    derived = derived_identity(identity)

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
        ("RDOC_CAPTURE_PROGID", derived["captureProgId"]),
        ("RDOC_SETTINGS_PROGID", derived["settingsProgId"]),
        ("RDOC_GLOBAL_HOOK_DATA_BASE_NAME", derived["globalHookDataBaseName"]),
        ("RDOC_GLOBAL_HOOK_DATA32_NAME", derived["globalHookData32Name"]),
        ("RDOC_GLOBAL_HOOK_DATA64_NAME", derived["globalHookData64Name"]),
        (
            "RDOC_CRASH_HANDLER_READY_EVENT_FALLBACK",
            derived["crashHandlerReadyEventFallback"],
        ),
        ("RDOC_THUMBNAIL_HANDLER_CLSID", identity["thumbnailHandlerClsid"]),
        ("RDOC_VULKAN_LAYER_NAME", identity["vulkanLayerName"]),
        ("RDOC_VULKAN_ENABLE_VAR", identity["vulkanEnableVar"]),
        ("RDOC_VULKAN_DISABLE_VAR", derived["vulkanDisableVar"]),
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
        "RDOC_CAPTURE_PROGID",
        "RDOC_SETTINGS_PROGID",
        "RDOC_GLOBAL_HOOK_DATA_BASE_NAME",
        "RDOC_GLOBAL_HOOK_DATA32_NAME",
        "RDOC_GLOBAL_HOOK_DATA64_NAME",
        "RDOC_CRASH_HANDLER_READY_EVENT_FALLBACK",
        "RDOC_THUMBNAIL_HANDLER_CLSID",
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
    lines.append(
        "#define RDOC_THUMBNAIL_HANDLER_CLSID_INITIALIZER {}".format(
            c_guid_initializer(identity["thumbnailHandlerClsid"])
        )
    )
    lines.extend(("", "#endif    // DCOMP_GENERATED_PRODUCT_IDENTITY_H", ""))
    return "\n".join(lines)


def render_cmake(identity):
    derived = derived_identity(identity)
    variables = (
        ("RDOC_PRODUCT_DISPLAY_NAME", identity["productDisplayName"]),
        ("RDOC_PRODUCT_CORE_BASE_NAME", identity["coreBaseName"]),
        ("RDOC_PRODUCT_UI_BASE_NAME", identity["uiBaseName"]),
        ("RDOC_PRODUCT_COMMAND_BASE_NAME", identity["commandBaseName"]),
        ("RDOC_PRODUCT_UI_STUB_BASE_NAME", identity["uiStubBaseName"]),
        ("RDOC_PRODUCT_SHIM_BASE_NAME", identity["shimBaseName"]),
        ("RDOC_PRODUCT_VULKAN_LAYER_NAME", identity["vulkanLayerName"]),
        ("RDOC_PRODUCT_VULKAN_ENABLE_VAR", identity["vulkanEnableVar"]),
        ("RDOC_PRODUCT_VULKAN_DISABLE_VAR", derived["vulkanDisableVar"]),
    )
    lines = [
        "# Generated by util/buildscripts/generate_product_identity.py.",
        "# Edit build/product_identity.json, then regenerate this file.",
        "",
    ]
    for name, value in variables:
        lines.append('set({} "{}")'.format(name, cmake_string(value)))
    lines.append("")
    return "\n".join(lines)


def render_wix_include(identity):
    derived = derived_identity(identity)
    definitions = (
        ("RDocProductDisplayName", identity["productDisplayName"]),
        ("RDocUIDisplayName", identity["uiDisplayName"]),
        ("RDocCoreFilename", identity["coreBaseName"] + ".dll"),
        ("RDocUIFilename", identity["uiBaseName"] + ".exe"),
        ("RDocCommandFilename", identity["commandBaseName"] + ".exe"),
        ("RDocUIStubFilename", identity["uiStubBaseName"] + ".exe"),
        ("RDocShim32Filename", identity["shimBaseName"] + "32.dll"),
        ("RDocShim64Filename", identity["shimBaseName"] + "64.dll"),
        ("RDocVulkanJsonFilename", identity["coreBaseName"] + ".json"),
        ("RDocCaptureProgId", derived["captureProgId"]),
        ("RDocSettingsProgId", derived["settingsProgId"]),
        ("RDocInstallerUpgradeCode", identity["installerUpgradeCode"]),
        ("RDocThumbnailHandlerClsid", identity["thumbnailHandlerClsid"]),
        (
            "RDocFileAssociationRdcComponentGuid",
            identity["fileAssociationRdcComponentGuid"],
        ),
        (
            "RDocFileAssociationCapComponentGuid",
            identity["fileAssociationCapComponentGuid"],
        ),
    )
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<Include xmlns="http://schemas.microsoft.com/wix/2006/wi">',
        "  <!-- Generated by util/buildscripts/generate_product_identity.py. -->",
    ]
    for name, value in definitions:
        lines.append(
            '  <?define {} = "{}" ?>'.format(name, xml_escape(value, {'"': '&quot;'}))
        )
    lines.extend(("</Include>", ""))
    return "\n".join(lines)


def expected_outputs(identity):
    return {
        PROPS_PATH: render_props(identity),
        PRI_PATH: render_pri(identity),
        CMAKE_IDENTITY_PATH: render_cmake(identity),
        HEADER_PATH: render_header(identity),
        WIX_INCLUDE_PATH: render_wix_include(identity),
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
