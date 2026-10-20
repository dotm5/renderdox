"""Validate reusable fixture build products without reusing acceptance results.

The workflow supplies RENDERDOX_FIXTURE_CACHE_KEY, including the compiler,
runner image, Python and JDK identities. A second source fingerprint and a
complete artifact digest inventory make a wrong or damaged restored cache fail
closed. Only the test runners can seal a cache, after their checks pass.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat

REPO = Path(__file__).resolve().parents[3]
CACHE_FILE = '.fixture-build-cache.json'
SCHEMA = 1
SOURCE_ROOTS = (
    'tools/proxy-builder', 'bootstrap', 'tools/capture-doctor',
    'renderdoc/api/app', 'renderdoc/generated/product_identity.h',
    'renderdoc/driver/vulkan/dgcore.json', 'build', 'schemas',
    'util/buildscripts/windows_toolchain.ps1',
    'util/buildscripts/check_windows_bootstrap_exports.ps1',
)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def _regular(path):
    info = path.lstat()
    if path.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('Fixture cache cannot contain a link or reparse point: ' + str(path))
    return stat.S_ISREG(info.st_mode)


def source_fingerprint():
    records = {}
    for name in SOURCE_ROOTS:
        base = REPO / name
        paths = base.rglob('*') if base.is_dir() else [base] if base.is_file() else []
        for path in paths:
            relative = path.relative_to(REPO)
            if '__pycache__' in relative.parts or path.suffix == '.pyc':
                continue
            if _regular(path):
                records[relative.as_posix()] = digest(path)
    return hashlib.sha256(json.dumps(records, sort_keys=True).encode('utf-8')).hexdigest()


def _inventory(root):
    records = {}
    for path in sorted(root.rglob('*')):
        if path.parent == root and path.name in (CACHE_FILE, CACHE_FILE + '.tmp'):
            continue
        if _regular(path):
            relative = path.relative_to(root).as_posix()
            records[relative] = {'bytes': path.stat().st_size, 'sha256': digest(path)}
    return records


def _validate_paths(records):
    seen = set()
    for name in records:
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or '..' in path.parts or
                '\\' in name or ':' in name or str(path) != name or
                name.casefold() in seen):
            raise ValueError('Invalid fixture cache artifact path: ' + name)
        seen.add(name.casefold())


def _toolchains(value):
    return ['MSVC', 'ClangCL'] if value == 'Both' else [value]


def _require_completed(root, kind, toolchain):
    selected = set(_toolchains(toolchain))
    results = json.loads((root / 'results.json').read_text(encoding='utf-8-sig'))
    if (not isinstance(results, list) or not all(isinstance(r, dict) for r in results) or
            {r.get('toolchain') for r in results} != selected):
        raise ValueError('Fixture cache does not contain all requested toolchain results')
    if kind == 'static':
        passed = all(r.get('contractVerified') or r.get('safelyRejected') for r in results)
        binary = 'order/bin/d3d12-order.exe'
    elif kind == 'routes':
        passed = all(r.get('ownedProcessPassed') for r in results)
        binary = 'route-smoke/route-smoke.exe'
    elif kind == 'mixed':
        passed = all(r.get('twoProtocolsOnOneProxy') for r in results)
        binary = 'mixed-smoke.exe'
    else:
        raise ValueError('Unknown fixture cache kind: ' + kind)
    if not passed or any(not (root / name / binary).is_file() for name in selected):
        raise ValueError('Fixture cache was not produced by a completed acceptance run')


def seal(root, kind, toolchain='Both'):
    root = Path(root).resolve(strict=True)
    _require_completed(root, kind, toolchain)
    records = _inventory(root)
    _validate_paths(records)
    document = {
        'schemaVersion': SCHEMA, 'kind': kind, 'toolchain': toolchain,
        'root': str(root), 'identity': os.environ.get('RENDERDOX_FIXTURE_CACHE_KEY', ''),
        'sourceFingerprint': source_fingerprint(), 'files': records,
    }
    temporary = root / (CACHE_FILE + '.tmp')
    temporary.write_text(json.dumps(document, sort_keys=True, indent=2), encoding='utf-8')
    temporary.replace(root / CACHE_FILE)
    return document


def verify(root, kind, toolchain='Both'):
    root = Path(root).resolve(strict=True)
    identity = os.environ.get('RENDERDOX_FIXTURE_CACHE_KEY', '')
    if not identity:
        raise ValueError('Reusing fixtures requires RENDERDOX_FIXTURE_CACHE_KEY')
    document = json.loads((root / CACHE_FILE).read_text(encoding='utf-8'))
    if (not isinstance(document, dict) or document.get('schemaVersion') != SCHEMA or document.get('kind') != kind or
            document.get('toolchain') != toolchain or document.get('root') != str(root) or
            document.get('identity') != identity or
            document.get('sourceFingerprint') != source_fingerprint()):
        raise ValueError('Fixture cache identity, source inputs or absolute output path changed')
    records = document.get('files')
    if not isinstance(records, dict) or not records:
        raise ValueError('Fixture cache artifact inventory is missing')
    _validate_paths(records)
    if _inventory(root) != records:
        raise ValueError('Fixture cache artifact contents or file inventory changed')
    _require_completed(root, kind, toolchain)
    return document


def cached_receipt(output, builder, source, toolchain, host=None, core=None):
    """Recheck export/source contracts on a binary from an already verified root."""
    output = Path(output).resolve(strict=True)
    receipt = json.loads((output / 'build-result.json').read_text(encoding='utf-8'))
    if receipt.get('status') != 'verified' or receipt.get('toolchain') != toolchain:
        raise ValueError('Cached fixture compilation was not verified for this toolchain')
    binary = Path(receipt['dll']).resolve(strict=True)
    if not binary.is_relative_to(output) or builder.digest(binary) != receipt['dllSHA256']:
        raise ValueError('Cached fixture binary path or digest mismatch')
    original = builder.inspect(source)
    if original['sha256'] != receipt['sourceSHA256']:
        raise ValueError('Cached fixture input DLL changed')
    for name, expected in receipt['generatedFiles'].items():
        relative = PurePosixPath(name.replace('\\', '/'))
        if relative.is_absolute() or '..' in relative.parts or ':' in name:
            raise ValueError('Invalid generated source path in cached fixture')
        if builder.digest(output / relative) != expected:
            raise ValueError('Cached generated fixture source changed: ' + name)
    compiled = builder.inspect(binary)
    for field in ('originalCopy', 'coreCopy'):
        if field in receipt:
            copied = Path(receipt[field]['path']).resolve(strict=True)
            if not copied.is_relative_to(output) or builder.digest(copied) != receipt[field]['sha256']:
                raise ValueError('Cached fixture dependency copy changed: ' + field)
    if host:
        if receipt.get('host') != host or set(receipt['exports']) != {
                name for entry in compiled['exports'] for name in entry['names']}:
            raise ValueError('Cached host export contract mismatch')
        if builder.digest(binary.parent / 'dgcore.dll') != original['sha256']:
            raise ValueError('Cached host Core copy changed')
        if receipt.get('asi'):
            deployed = Path(receipt['asi']).resolve(strict=True)
            if not deployed.is_relative_to(output) or builder.digest(deployed) != receipt['dllSHA256']:
                raise ValueError('Cached ASI deployment changed')
        if receipt.get('jar'):
            archive = Path(receipt['jar']).resolve(strict=True)
            if not archive.is_relative_to(output) or builder.digest(archive) != receipt['jarSHA256']:
                raise ValueError('Cached JVM agent archive path or content changed')
    else:
        lock = json.loads((output / 'exports.json').read_text(encoding='utf-8'))
        checked = (builder.routes.verify(original, compiled, lock, builder.verify)
                   if 'routeConfig' in lock else builder.verify(original, compiled))
        if not checked['matches']:
            raise ValueError('Cached fixture export contract differs from its input DLL')
        if lock.get('dataForwarders'):
            builder.routes.verify_data_imports(binary.with_suffix('.lib'), original, lock)
        if core and builder.digest(core) != receipt['coreCopy']['sha256']:
            raise ValueError('Cached fixture Core input changed')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('verify', 'seal'))
    parser.add_argument('--root', required=True)
    parser.add_argument('--kind', required=True, choices=('static', 'routes', 'mixed'))
    parser.add_argument('--toolchain', choices=('MSVC', 'ClangCL', 'Both'), default='Both')
    args = parser.parse_args()
    try:
        result = (verify if args.command == 'verify' else seal)(args.root, args.kind, args.toolchain)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, 'Fixture build cache rejected: ' + str(error) + '\n')
    print(json.dumps({'valid': True, 'kind': args.kind, 'files': len(result['files'])}))
