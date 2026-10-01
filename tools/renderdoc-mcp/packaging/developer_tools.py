"""Prepare the same developer tools once for both native release packages."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
IGNORE = shutil.ignore_patterns('__pycache__', '*.pyc', 'bin', 'obj')


def prepare(build_root, native_acceptance):
    native = Path(native_acceptance).resolve(strict=True)
    results = json.loads((native / 'results.json').read_text(encoding='utf-8-sig'))
    if {r['toolchain'] for r in results} != {'MSVC', 'ClangCL'}:
        raise ValueError('Developer tools require both native fixture toolchains')
    if not all(r.get('contractVerified') or r.get('safelyRejected') for r in results):
        raise ValueError('Native fixture acceptance contains an unverified result')
    destination = Path(build_root).resolve() / 'developer-tools'
    if destination.exists():
        raise ValueError('Use a fresh developer-tools build directory')
    builder = destination / 'proxy-builder'
    shutil.copytree(REPO / 'tools/proxy-builder', builder, ignore=IGNORE)
    # Run the CLI with its own import root instead of dynamically importing a
    # sibling script whose routes module is not on the MCP packager's sys.path.
    subprocess.run([sys.executable, str(REPO / 'tools/proxy-builder/package.py'),
        '--destination', str(builder), '--build-root', str(Path(build_root) / 'builder-freeze')], check=True)
    doctor = destination / 'capture-doctor'
    shutil.copytree(REPO / 'tools/capture-doctor', doctor, ignore=IGNORE)
    header = doctor / 'include/api/app/renderdoc_app.h'
    header.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO / 'renderdoc/api/app/renderdoc_app.h', header)
    for toolchain in ('MSVC', 'ClangCL'):
        binary = native / toolchain / 'order/bin/d3d12-order.exe'
        target = doctor / 'bin' / toolchain / binary.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(binary, target)
    proof = {'schemaVersion': 1, 'proxyBuilder': '0.4.1',
             'nativeFixtureResults': results,
             'builderBuildDependency': 'Visual Studio C++ and MASM; JDK for JVM hosts',
             'captureDoctorScope': 'Owned D3D12 creation-order fixture; per-target evidence required'}
    (destination / 'component-manifest.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')
    return destination
