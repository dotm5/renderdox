#!/usr/bin/env python3
"""Verify that a bootstrap deployment subset is self-contained on the target machine.

`check_windows_runtime_closure.py` validates the portable package as a whole, where
the MSVC runtime DLLs (msvcp140/vcruntime140) sit in the package root next to the
GUI, Qt, and Python.  The bootstrap deployment contract is different: an operator
copies only a handful of files into the target application directory, and every
dependency of those files must therefore either be provided by Windows or be one
of the copied files.

The failure this catches is silent and environment-dependent.  A module built with
the dynamic CRT (/MD) loads fine on a development machine, where the Visual C++
redistributable has installed msvcp140.dll/vcruntime140.dll into System32, and then
fails to load on a clean image.  If the target imports the file by name - the usual
case for dxgi/d3d11/d3d12 - the process dies at load time with STATUS_DLL_NOT_FOUND
before any of the module's own logging runs, which is indistinguishable from "the
proxy was blocked" unless the import closure is checked first.

Usage:
  python check_windows_deployment_subset.py <package-root> [--subset NAME] [--add PATH]

  --subset  d3d11 | d3d12 | loader | all   (default: all)
  --add     additional file the operator copies, relative to the package root
            (repeatable); use it for extra deployment files or to self-test

Exit status is 0 when every subset is closed, 1 otherwise.
"""

import argparse
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLOSURE_CHECKER = os.path.join(HERE, "check_windows_runtime_closure.py")

if not os.path.exists(CLOSURE_CHECKER):
    sys.stderr.write("missing %s; run this script from the repository tree\n" % CLOSURE_CHECKER)
    raise SystemExit(2)

_spec = importlib.util.spec_from_file_location("check_windows_runtime_closure", CLOSURE_CHECKER)
_closure = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_closure)

# Deployment subsets, as documented in bootstrap/README.md.  Paths are relative to
# the package root; the file name is what the target imports, the path is where the
# release package keeps it.
SUBSETS = {
    "d3d11": [
        "bootstrap/dxgi_proxy/dxgi.dll",
        "bootstrap/d3d11_proxy/d3d11.dll",
        "dgcore.dll",
    ],
    "d3d12": [
        "bootstrap/dxgi_proxy/dxgi.dll",
        "bootstrap/d3d12_proxy/d3d12.dll",
        "dgcore.dll",
    ],
    "loader": [
        "bootstrap/injection_loader/dgbootstrap.dll",
        "dgcore.dll",
    ],
    # Non-system slot route: the stub replaces a third-party DLL that the
    # application loads from its own tree (deployed as
    # ...\Engine\Binaries\ThirdParty\NVIDIA\NVaftermath\Win64\GFSDK_Aftermath_Lib.x64.dll).
    "aftermath": [
        "bootstrap/gfsdk_aftermath_stub/GFSDK_Aftermath_Lib.x64.dll",
        "dgcore.dll",
    ],
}


def is_windows_provided(name):
    """True when Windows itself resolves the import without the package."""
    lowered = name.lower()
    if lowered in _closure.SYSTEM_MODULES:
        return True
    return any(lowered.startswith(prefix) for prefix in _closure.SYSTEM_MODULE_PREFIXES)


def subset_modules(package_root, subset_name):
    """Return [(file_name, path, exists)] for the subset plus any --add files."""
    entries = []
    for relative in SUBSETS[subset_name]:
        path = os.path.join(package_root, relative.replace("/", os.sep))
        entries.append((os.path.basename(relative), path, os.path.exists(path)))
    return entries


def check_subset(package_root, subset_name, extra_files):
    entries = subset_modules(package_root, subset_name)

    for relative in extra_files:
        path = os.path.join(package_root, relative.replace("/", os.sep))
        entries.append((os.path.basename(relative), path, os.path.exists(path)))

    present = {name.lower() for name, _path, exists in entries if exists}
    problems = []
    missing_files = []
    loaded = 0

    for name, path, exists in entries:
        if not exists:
            missing_files.append(name)
            continue

        info = _closure.read_pe_imports(path)
        if info is None:
            problems.append("%s: not a PE module" % name)
            continue
        loaded += 1

        for imported in sorted(info["imports"]):
            lowered = imported.lower()
            if imported.lower() in present or lowered in present:
                continue
            if is_windows_provided(imported):
                continue
            if lowered in _closure.REDISTRIBUTABLE_MODULES:
                problems.append(
                    "%s: imports %s - the Visual C++ redistributable is NOT part of "
                    "this subset; the module must be built with the static CRT (/MT)"
                    % (name, imported))
            else:
                problems.append(
                    "%s: imports %s - not in the subset and not provided by Windows"
                    % (name, imported))

    return entries, present, missing_files, problems, loaded


def main():
    parser = argparse.ArgumentParser(
        description="Verify that a bootstrap deployment subset is self-contained.")
    parser.add_argument("package", help="portable package root directory")
    parser.add_argument("--subset", action="append", default=[],
                        choices=sorted(SUBSETS) + ["all"],
                        help="subset to check (repeatable, default: all)")
    parser.add_argument("--add", action="append", default=[], metavar="PATH",
                        help="extra file copied to the target, relative to the package root")
    parser.add_argument("--quiet", action="store_true",
                        help="only report problems and the summary line")
    arguments = parser.parse_args()

    if not os.path.isdir(arguments.package):
        parser.error("package root %s is not a directory" % arguments.package)

    selected = arguments.subset or ["all"]
    if "all" in selected:
        selected = sorted(SUBSETS)

    failed = False
    for subset_name in selected:
        entries, present, missing_files, problems, loaded = check_subset(
            arguments.package, subset_name, arguments.add)

        print("=== subset %s ===" % subset_name)
        for name, _path, exists in entries:
            print("  %s %s" % ("[ok]  " if exists else "[skip]", name))

        if missing_files:
            print("  not built in this package: %s" % ", ".join(sorted(missing_files)))

        if loaded == 0:
            print("  no files to inspect")
            failed = True
        elif problems:
            failed = True
            for problem in problems:
                print("  FAIL %s" % problem)
        else:
            print("  closed: %d file(s), every import is Windows-provided or in the subset"
                  % loaded)
        print()

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
