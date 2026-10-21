#!/usr/bin/env python3
"""Verify and assemble independently produced Windows native release packages."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import shutil
import tempfile


PACKAGES = {"MSVC": "msvc-release", "ClangCL": "clangcl-release"}
COMMON_FIELDS = (
    "configuration", "platform", "child_propagation", "vc_tools_version",
    "windows_sdk", "bootstrap",
)
RUNTIME_FIELDS = ("python_abi", "python_major_minor", "pyside2")


def read_manifest(path):
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Expected a manifest object: " + str(path))
    return value


def write_manifest(path, manifest):
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def check_commit(value, description):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?", value):
        raise ValueError(description + " must be a full Git commit ID")


def verify_files(package_root, manifest):
    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        raise ValueError("Package has no file inventory: " + str(package_root))
    expected = set()
    for record in records:
        relative = PureWindowsPath(record["path"])
        if relative.anchor or ".." in relative.parts or not relative.parts:
            raise ValueError("Invalid package-relative path: " + record["path"])
        normalized = relative.as_posix().casefold()
        if normalized == "manifest.json" or normalized in expected:
            raise ValueError("Invalid or duplicate inventory entry: " + record["path"])
        expected.add(normalized)
        path = package_root.joinpath(*relative.parts)
        if not path.resolve().is_relative_to(package_root):
            raise ValueError("Package file escapes its directory: " + record["path"])
        if path.is_symlink() or not path.is_file() or path.stat().st_size != record["bytes"]:
            raise ValueError("Missing or altered package file: " + str(path))
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest().casefold() != record["sha256"].casefold():
            raise ValueError("Package file hash mismatch: " + str(path))
    actual = set()
    for path in package_root.rglob("*"):
        if path.is_symlink():
            raise ValueError("Package contains a symbolic link: " + str(path))
        if path.is_file() and path != package_root / "manifest.json":
            actual.add(path.relative_to(package_root).as_posix().casefold())
    if actual != expected:
        raise ValueError("Package files differ from the inventory: " + str(package_root))


def merge(input_roots, output_directory, source_commit):
    check_commit(source_commit, "Assembly source commit")
    output_directory = Path(output_directory).resolve()
    if output_directory.exists():
        raise ValueError("Output directory already exists: " + str(output_directory))
    common = None
    packages = {}
    for input_root in input_roots:
        input_root = Path(input_root).resolve(strict=True)
        matrix = read_manifest(input_root / "manifest.json")
        check_commit(matrix.get("source_commit"), "Native producer commit")
        for field in COMMON_FIELDS:
            if field not in matrix:
                raise ValueError("Native manifest is missing " + field)
        digest = matrix.get("native_inputs_digest")
        profile = matrix.get("native_build_profile")
        if digest is not None and (
            not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or not isinstance(profile, dict)
        ):
            raise ValueError("Native cache metadata is incomplete or invalid")
        if digest is None and profile is not None:
            raise ValueError("Native build profile has no input digest")
        if common is None:
            common = matrix
        else:
            for field in (*COMMON_FIELDS, "native_inputs_digest", "native_build_profile"):
                if matrix.get(field) != common.get(field):
                    raise ValueError("Native manifests disagree on " + field)
        if matrix["source_commit"] != source_commit and digest is None:
            raise ValueError("Cross-commit native reuse requires matching input digests")
        toolchains = matrix.get("toolchains")
        if not isinstance(toolchains, list) or not toolchains:
            raise ValueError("Native manifest has no toolchains")
        for descriptor in toolchains:
            toolchain = descriptor.get("toolchain")
            if toolchain not in PACKAGES or toolchain in packages:
                raise ValueError("Unexpected or duplicate toolchain: " + str(toolchain))
            if descriptor.get("package") != PACKAGES[toolchain]:
                raise ValueError("Unexpected package directory for " + toolchain)
            platform_toolset = descriptor.get("platform_toolset", "")
            if ((toolchain == "ClangCL" and platform_toolset != "ClangCL") or
                    (toolchain == "MSVC" and not re.fullmatch(r"v[0-9]+", platform_toolset))):
                raise ValueError("Unexpected platform toolset for " + toolchain)
            if descriptor.get("runtime_closure_verified") is not True:
                raise ValueError("Runtime closure was not verified for " + toolchain)
            if descriptor.get("vc_tools_version") != matrix["vc_tools_version"]:
                raise ValueError("C++ tools version differs inside " + toolchain + " manifest")
            if descriptor.get("native_source_commit", matrix["source_commit"]) != matrix["source_commit"]:
                raise ValueError("Native producer commit differs inside " + toolchain + " manifest")
            if any(field not in descriptor for field in RUNTIME_FIELDS):
                raise ValueError("Missing Python/Qt runtime metadata for " + toolchain)
            package_root = input_root / descriptor["package"]
            if package_root.is_symlink() or not package_root.is_dir():
                raise ValueError("Missing native package directory: " + str(package_root))
            if read_manifest(package_root / "manifest.json") != descriptor:
                raise ValueError("Package manifest differs from its matrix entry: " + toolchain)
            verify_files(package_root, descriptor)
            combined = dict(descriptor)
            combined["native_source_commit"] = matrix["source_commit"]
            combined["native_generated_at"] = matrix.get("generated_at")
            combined["assembly_commit"] = source_commit
            if digest is not None:
                combined["native_inputs_digest"] = digest
                combined["native_build_profile"] = profile
            packages[toolchain] = (package_root, combined)
    if set(packages) != set(PACKAGES):
        raise ValueError("A release matrix requires both MSVC and ClangCL packages")
    for field in RUNTIME_FIELDS:
        if packages["MSVC"][1].get(field) != packages["ClangCL"][1].get(field):
            raise ValueError("Native packages disagree on " + field)

    assembled = dict(common)
    assembled["generated_at"] = datetime.now(timezone.utc).isoformat()
    assembled["source_commit"] = source_commit
    assembled["assembly_commit"] = source_commit
    assembled["toolchains"] = [packages[toolchain][1] for toolchain in PACKAGES]
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="native-matrix-", dir=output_directory.parent) as temporary:
        staging = Path(temporary) / "matrix"
        staging.mkdir()
        for toolchain, package_name in PACKAGES.items():
            package_root, manifest = packages[toolchain]
            destination = staging / package_name
            shutil.copytree(package_root, destination)
            write_manifest(destination / "manifest.json", manifest)
        write_manifest(staging / "manifest.json", assembled)
        lines = [
            "# Windows Release matrix", "",
            "Assembly source commit: `" + source_commit + "`.", "",
            "Native packages retain their original producer commits and embedded version identifiers:", "",
        ]
        for toolchain, package_name in PACKAGES.items():
            lines.append("- `" + package_name + "`: native producer `"
                         + packages[toolchain][1]["native_source_commit"] + "`.")
        lines.extend(["", "Each package includes its verified runtime and file-hash manifest.", ""])
        (staging / "README.md").write_text("\n".join(lines), encoding="utf-8")
        staging.rename(output_directory)
    return assembled


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", action="append", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    try:
        manifest = merge(args.input_root, args.output_directory, args.source_commit)
    except (ValueError, KeyError, OSError) as error:
        parser.error(str(error))
    print("Windows native release matrix assembled: " + str(args.output_directory))
    for toolchain in manifest["toolchains"]:
        print(toolchain["toolchain"] + " native producer: " + toolchain["native_source_commit"])


if __name__ == "__main__":
    main()
