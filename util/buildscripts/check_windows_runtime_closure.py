#!/usr/bin/env python3
"""Verify that a portable Windows package satisfies its own PE import closure.

The release packages ship a curated runtime: the interpreter DLL, the embedded
Python modules, the PySide2/Shiboken2 bindings, Qt and the MSVC runtime.  A
curated copy list drifts from what the binaries actually import, and the
resulting package fails on a clean machine with a "DLL was not found" dialog
instead of failing the build.

This script walks every PE module in the package, reads its static and
delay-load import tables and checks that each imported DLL either ships inside
the package or is provided by Windows.  Any other dependency is reported as a
missing runtime file and the script exits non-zero.

Only the Python standard library is used so the check runs on any build agent.
"""

import argparse
import os
import struct
import sys

PE_MACHINE_NAMES = {
    0x014C: "x86",
    0x8664: "x64",
    0xAA64: "arm64",
}

# Windows-provided modules.  Names are matched case-insensitively and the
# api-ms-win-*/ext-ms-win-* API sets are accepted by prefix.
SYSTEM_MODULES = {
    # Core loader and low level runtime
    "ntdll.dll", "kernel32.dll", "kernelbase.dll", "msvcrt.dll",
    "ucrtbase.dll", "ucrtbased.dll", "msvcp_win.dll", "win32u.dll",
    "advapi32.dll", "sechost.dll", "rpcrt4.dll", "bcrypt.dll",
    "bcryptprimitives.dll", "cryptbase.dll", "cryptsp.dll", "crypt32.dll",
    "cryptnet.dll", "msasn1.dll", "wintrust.dll", "imagehlp.dll",
    "profapi.dll", "sspicli.dll", "rsaenh.dll", "wldp.dll",
    # Windowing, shell and user interface
    "user32.dll", "gdi32.dll", "gdi32full.dll", "shell32.dll", "shlwapi.dll",
    "shcore.dll", "comctl32.dll", "comdlg32.dll", "combase.dll", "ole32.dll",
    "oleaut32.dll", "uxtheme.dll", "dwmapi.dll", "imm32.dll", "winmm.dll",
    "wtsapi32.dll", "version.dll", "setupapi.dll", "cfgmgr32.dll",
    "devobj.dll", "drvstore.dll", "windows.storage.dll", "kernel.appcore.dll",
    "powrprof.dll", "umpdc.dll", "ntmarta.dll",
    # Networking
    "ws2_32.dll", "wsock32.dll", "iphlpapi.dll", "dnsapi.dll", "mpr.dll",
    "nsi.dll", "dsparse.dll", "winhttp.dll", "wininet.dll", "urlmon.dll",
    "cabinet.dll", "lz32.dll", "netapi32.dll", "userenv.dll", "secur32.dll",
    # Graphics
    "dxgi.dll", "dxcore.dll", "d3d11.dll", "d3d12.dll", "d3dcompiler_47.dll",
    "directxdatabasehelper.dll", "winspool.drv", "wintab32.dll",
    "opengl32.dll", "glu32.dll", "tdh.dll", "winusb.dll",
    # Debugging support
    "dbghelp.dll", "dbgcore.dll", "psapi.dll", "symsrv.dll",
}
SYSTEM_MODULE_PREFIXES = ("api-ms-win-", "ext-ms-win-")

# Not part of Windows itself, but installed machine-wide by the Visual C++
# redistributable.  This fork deliberately bundles them for portable packages;
# the release scripts require the copies explicitly through --expect-runtime,
# so they are tolerated here instead of being reported as a closure failure.
REDISTRIBUTABLE_MODULES = {
    "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
    "msvcp140_atomic_wait.dll", "msvcp140_codecvt_ids.dll",
    "vcruntime140.dll", "vcruntime140_1.dll",
    "vccorlib140.dll", "concrt140.dll",
    "msvcr100.dll", "msvcp100.dll", "msvcr110.dll", "msvcp110.dll",
    "msvcr120.dll", "msvcp120.dll",
}

IMPORT_DIRECTORY = 1
DELAY_IMPORT_DIRECTORY = 13


def read_pe_imports(path):
    """Return the imported DLL names of a PE module, or None if it is not a PE."""
    with open(path, "rb") as handle:
        data = handle.read()

    if len(data) < 0x40 or data[0:2] != b"MZ":
        return None

    (pe_offset,) = struct.unpack_from("<I", data, 0x3C)
    if data[pe_offset:pe_offset + 4] != b"PE\0\0":
        return None

    coff_offset = pe_offset + 4
    (machine, section_count, _timestamp, _symbols, _symbol_count,
     optional_size, _characteristics) = struct.unpack_from("<HHIIIHH", data, coff_offset)
    optional_offset = coff_offset + 20
    magic = struct.unpack_from("<H", data, optional_offset)[0]
    if magic == 0x10B:
        directory_offset = optional_offset + 96
    elif magic == 0x20B:
        directory_offset = optional_offset + 112
    else:
        raise ValueError("%s: unsupported PE optional header" % path)

    sections = []
    section_offset = optional_offset + optional_size
    for index in range(section_count):
        offset = section_offset + index * 40
        _name, virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
            "<8sIIII", data, offset)
        sections.append((virtual_address, max(virtual_size, raw_size), raw_offset))

    def rva_to_offset(rva):
        for virtual_address, size, raw_offset in sections:
            if virtual_address <= rva < virtual_address + size:
                return raw_offset + (rva - virtual_address)
        if rva < len(data):
            return rva
        raise ValueError("%s: RVA %#x is outside every section" % (path, rva))

    def read_name(rva):
        offset = rva_to_offset(rva)
        end = data.index(b"\0", offset)
        return data[offset:end].decode("ascii", errors="replace")

    imports = set()

    def parse_descriptors(directory_index):
        (directory_rva, directory_size) = struct.unpack_from(
            "<II", data, directory_offset + directory_index * 8)
        if not directory_rva or not directory_size:
            return
        offset = rva_to_offset(directory_rva)
        # Import descriptors are 20 bytes, delay-load descriptors are 32.
        entry_size = 20 if directory_index == IMPORT_DIRECTORY else 32
        name_field_offset = 12 if directory_index == IMPORT_DIRECTORY else 4
        while True:
            entry = data[offset:offset + entry_size]
            if len(entry) < entry_size or not any(entry):
                return
            (name_rva,) = struct.unpack_from("<I", entry, name_field_offset)
            if name_rva:
                imports.add(os.path.basename(read_name(name_rva)))
            offset += entry_size

    parse_descriptors(IMPORT_DIRECTORY)
    parse_descriptors(DELAY_IMPORT_DIRECTORY)

    return {"imports": imports, "machine": PE_MACHINE_NAMES.get(machine, "0x%04x" % machine)}


def is_system_module(name):
    lowered = name.lower()
    if lowered in SYSTEM_MODULES or lowered in REDISTRIBUTABLE_MODULES:
        return True
    return lowered.startswith(SYSTEM_MODULE_PREFIXES)


def collect_package_modules(package_root):
    """Index every packaged file by lower-case base name and parse the PE ones."""
    index = {}
    modules = []
    for directory, _subdirectories, files in os.walk(package_root):
        for file_name in files:
            full_path = os.path.join(directory, file_name)
            relative = os.path.relpath(full_path, package_root)
            index.setdefault(file_name.lower(), []).append(relative)
            try:
                parsed = read_pe_imports(full_path)
            except (ValueError, struct.error, OSError) as error:
                raise ValueError("%s: %s" % (relative, error))
            if parsed is not None:
                modules.append((relative, parsed))
    return index, modules


def main():
    parser = argparse.ArgumentParser(
        description="Verify the DLL import closure of a portable Windows package.")
    parser.add_argument("package", help="package root directory to inspect")
    parser.add_argument(
        "--expect-runtime", action="append", default=[], metavar="NAME",
        help="runtime file that must exist in the package (repeatable)")
    parser.add_argument(
        "--quiet", action="store_true",
        help="only report problems and the final summary line")
    arguments = parser.parse_args()

    package_root = os.path.abspath(arguments.package)
    if not os.path.isdir(package_root):
        print("Package directory does not exist: %s" % package_root, file=sys.stderr)
        return 2

    try:
        index, modules = collect_package_modules(package_root)
    except (ValueError, struct.error, OSError) as error:
        print("Unable to inspect the package: %s" % error, file=sys.stderr)
        return 2

    failures = []

    for expected in arguments.expect_runtime:
        if os.path.basename(expected).lower() not in index:
            failures.append("%s: required runtime file is not packaged" % expected)

    for relative, parsed in sorted(modules):
        for imported in sorted(parsed["imports"]):
            if is_system_module(imported):
                continue
            if imported.lower() not in index:
                failures.append("%s (%s): missing import %s" %
                                (relative, parsed["machine"], imported))

    if not arguments.quiet:
        print("Inspected %d PE modules in %s" % (len(modules), package_root))
        for prefix in ("python3", "shiboken2", "pyside2"):
            matches = sorted(entry for entry in index
                             if entry.startswith(prefix) and entry.endswith((".dll", ".pyd")))
            if matches:
                print("  runtime bindings: %s" % ", ".join(matches))

    if failures:
        print("\nThe package does not satisfy its runtime dependency closure:")
        for failure in failures:
            print("  - %s" % failure)
        print("\nExtend the packaged runtime in "
              "util/buildscripts/build_windows_release_matrix.ps1 so the release is "
              "self-contained.")
        return 1

    print("Runtime dependency closure verified: %d modules, no missing DLLs" % len(modules))
    return 0


if __name__ == "__main__":
    sys.exit(main())
