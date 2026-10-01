"""Freeze the modern service and add a matching portable native-worker runtime.

This script packages an existing cloud build. It never builds RenderDoc itself.
"""
import argparse
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from contracts import VERSION
WORKER_RUNTIMES = {
    "36": ("3.6.4", "F6CA955D6885A2AC01595DC7857C5C06EE0A5B1F7B3774F89EC52692C7CB691C"),
}


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def build(build_root):
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--name", "renderdoc-mcp", "--contents-directory", "mcp-runtime", "--paths", str(ROOT),
        "--distpath", str(build_root / "dist"), "--workpath", str(build_root / "work"),
        "--specpath", str(build_root), "--exclude-module", "matplotlib", "--exclude-module", "scipy",
        "--exclude-module", "IPython", "--exclude-module", "pytest", "--exclude-module", "tkinter",
        str(ROOT / "renderdoc_mcp.py")], check=True)
    return build_root / "dist" / "renderdoc-mcp"


def bundle(package, frozen, build_root, developer_tools=None):
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    abi = str(manifest["python_major_minor"])
    if abi not in WORKER_RUNTIMES:
        raise RuntimeError("Add a pinned embedded worker runtime for Python ABI " + abi)
    version, expected = WORKER_RUNTIMES[abi]
    archive = build_root / ("python-" + version + "-embed-amd64.zip")
    if not archive.exists():
        urllib.request.urlretrieve("https://www.python.org/ftp/python/{0}/python-{0}-embed-amd64.zip".format(version), archive)
    if digest(archive) != expected:
        raise RuntimeError("Worker Python archive digest mismatch")
    shutil.copytree(frozen, package, dirs_exist_ok=True)
    if developer_tools is not None:
        shutil.copytree(developer_tools, package / 'developer-tools')
        manifest['developerTools'] = json.loads(
            (developer_tools / 'component-manifest.json').read_text(encoding='utf-8'))
    runtime = package / "mcp" / "worker-runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        z.extractall(runtime)
    # Bindings and worker use the exact interpreter DLL/stdlib shipped by the
    # main product rather than assuming minor-revision compatibility.
    for name in (manifest["python_abi"], "python" + abi + ".zip"):
        shutil.copy2(package / name, runtime / name)
    (runtime / ("python" + abi + "._pth")).write_text("python" + abi + ".zip\n.\n", encoding="utf-8")
    source = package / "mcp" / "source"
    for folder in ("contracts", "adapters", "worker", "gui_bridge", "skills"):
        shutil.copytree(ROOT / folder, source / folder, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(ROOT / "README.md", package / "MCP-README.md")
    licenses = package / "mcp" / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    for name in ("numpy", "Pillow", "PyInstaller", "pyinstaller-hooks-contrib"):
        dist = importlib.metadata.distribution(name)
        for file in dist.files or []:
            if "license" in str(file).lower() or "copying" in str(file).lower():
                path = dist.locate_file(file)
                if path.is_file():
                    target = licenses / name / str(file)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
    component = {"schemaVersion": 1, "version": VERSION, "architecture": "x64",
                 "configNamespace": json.loads((ROOT.parents[1] / "build" / "product_identity.json").read_text())["configNamespace"],
                 "workerPythonABI": manifest["python_abi"], "workerPythonVersion": version,
                 "serverPython": sys.version, "workerArchiveSHA256": expected,
                 "sourceCommit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
                 "sourceTreeDirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip()),
                 "dependencies": {x: importlib.metadata.version(x) for x in ("numpy", "Pillow", "PyInstaller", "pyinstaller-hooks-contrib")},
                 "transport": "stdio", "entry": "renderdoc-mcp.exe", "workerEntry": "mcp/source/worker/entry.py"}
    (package / "mcp" / "component-manifest.json").write_text(json.dumps(component, indent=2), encoding="utf-8")
    manifest["mcp"] = component
    manifest["files"] = [{"path": str(path.relative_to(package)), "bytes": path.stat().st_size, "sha256": digest(path)}
                         for path in sorted(package.rglob("*")) if path.is_file() and path != manifest_path]
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    subprocess.run([str(package / "renderdoc-mcp.exe"), "--version"], check=True)
    subprocess.run([str(package / "renderdoc-mcp.exe"), "config"], check=True, stdout=subprocess.DEVNULL)
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", action="append", required=True)
    parser.add_argument("--build-root", required=True)
    parser.add_argument("--matrix-manifest")
    parser.add_argument("--native-acceptance", help="Both-toolchain fixture results; include Builder and Capture Doctor")
    args = parser.parse_args()
    build_root = Path(args.build_root).resolve()
    build_root.mkdir(parents=True, exist_ok=True)
    frozen = build(build_root)
    developer_tools = None
    if args.native_acceptance:
        from developer_tools import prepare
        developer_tools = prepare(build_root, args.native_acceptance)
    manifests = [bundle(Path(root).resolve(), frozen, build_root, developer_tools) for root in args.package_root]
    if args.matrix_manifest:
        path = Path(args.matrix_manifest)
        matrix = json.loads(path.read_text(encoding="utf-8-sig"))
        replacements = {m["toolchain"]: m for m in manifests}
        matrix["toolchains"] = [replacements.get(m["toolchain"], m) for m in matrix["toolchains"]]
        path.write_text(json.dumps(matrix, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
