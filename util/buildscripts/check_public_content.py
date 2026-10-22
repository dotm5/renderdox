#!/usr/bin/env python3
"""Check Git snapshots and release files without printing matched content."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_DEPTH = 4
MAX_FILES = 100000
LOCAL_NAMES = {
    'agents.md', 'agents.local.md', 'claude.md', 'gemini.md',
    '.env', 'key.pass', 'key.name', 'id_rsa', 'id_ed25519',
}
LOCAL_FOLDERS = {'.codex', '.claude', '.cursor', '.aider', '.continue'}
SENSITIVE_SUFFIXES = {
    '.pfx', '.p12', '.pvk', '.pem', '.der', '.key', '.cer', '.crt', '.p7b', '.p7c',
    '.jks', '.keystore', '.sys', '.cat',
}
SOURCE_SUFFIXES = {'.c', '.h', '.cc', '.hh', '.cpp', '.hpp', '.cxx', '.hxx'}
IDENTIFIERS = re.compile(rb'[A-Za-z_][A-Za-z0-9_-]{3,127}')
PEM_KEY = re.compile(
    rb'-----BEGIN (?:RSA |DSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----'
    rb'[ \t]*\r?\n(?:[A-Za-z0-9+/=]{16,}[ \t]*\r?\n)+'
    rb'-----END (?:RSA |DSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----')
TOKEN = re.compile(
    rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,255}|github_pat_[A-Za-z0-9_]{50,255}'
    rb'|(?:AKIA|ASIA)[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{35}'
    rb'|xox[baprs]-[A-Za-z0-9-]{20,255}'
    rb'|sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,255})\b')
SIGNING_PASSWORD = re.compile(
    rb'(?i)\b(?:pfx|cert|signing)[a-z_]*(?:password|passphrase|secret)'
    rb'\s*[:=]\s*[\"\x27][A-Za-z0-9+/!@#%^&*_.-]{8,}[\"\x27]')
KERNEL_SOURCE = re.compile(
    rb'\b(?:DriverEntry|NtLoadDriver|NtUnloadDriver|ZwLoadDriver|SERVICE_KERNEL_DRIVER'
    rb'|MmMapIoSpace|MmCopyVirtualMemory|PsLookupProcessByProcessId'
    rb'|IoCreateDevice|KeStackAttachProcess)\b'
    rb'|#[ \t]*include[ \t]*[<\"](?:ntddk|ntifs|wdm|wdf)\.h[>\"]')
INTERNAL_REFERENCE = re.compile(rb'\bagent/[0-9a-f]{16,40}\b')


class InspectionError(Exception):
    pass


def normalized_digest(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n').strip()).hexdigest()


def der_private_material(data):
    """Recognize standard private-key/PFX containers even after a rename."""
    def fields(value):
        result = []
        offset = 0
        while offset < len(value):
            if offset + 2 > len(value):
                return []
            tag, size = value[offset:offset + 2]
            offset += 2
            if size & 0x80:
                count = size & 0x7f
                if not 1 <= count <= 4 or offset + count > len(value):
                    return []
                size = int.from_bytes(value[offset:offset + count], 'big')
                offset += count
            if offset + size > len(value):
                return []
            result.append((tag, value[offset:offset + size]))
            offset += size
        return result
    if not data.startswith(b'\x30'):
        return False
    outer = fields(data)
    if len(outer) != 1 or outer[0][0] != 0x30:
        return False
    items = fields(outer[0][1])
    tags = [tag for tag, _ in items]
    if len(items) >= 9 and tags[:9] == [2] * 9 and items[0][1] in (b'\0', b'\1'):
        return True
    if len(items) >= 2 and items[0] == (2, b'\1') and items[1][0] == 4:
        return 16 <= len(items[1][1]) <= 132
    if len(items) >= 3 and items[0][0] == 2 and items[0][1] in (b'\0', b'\1') and tags[1:3] == [0x30, 4]:
        return True
    if len(items) == 2 and tags == [0x30, 4]:
        algorithm = fields(items[0][1])
        return bool(algorithm and algorithm[0][0] == 6 and len(items[1][1]) >= 16)
    if len(items) >= 2 and items[0] == (2, b'\3') and items[1][0] == 0x30:
        content = fields(items[1][1])
        return bool(content and content[0] == (6, bytes.fromhex('2a864886f70d010701')))
    return False


class Checker:
    def __init__(self, policy):
        if policy.get('version') != 1:
            raise InspectionError('Unsupported content policy')
        self.retired = set(policy['retired_content_sha256'])
        self.reserved = set(policy['reserved_identifier_sha256'])
        self.kernel_source_allowlist = set(policy.get('allowed_kernel_source_sha256', []))
        if any(not re.fullmatch(r'[0-9a-f]{64}', value)
               for value in self.retired | self.reserved | self.kernel_source_allowlist):
            raise InspectionError('Invalid content policy digest')
        self.findings = set()
        self.files = 0
        self.bytes = 0
        self.commits = 0
        self._seen = set()
        self._identifier_cache = {}

    def report(self, location, rule):
        self.findings.add((location, rule))

    def path(self, name, location):
        name = name.replace('\\', '/')
        path = PurePosixPath(name)
        parts = [part.lower() for part in path.parts]
        leaf = parts[-1] if parts else ''
        if path.is_absolute() or '..' in parts or ':' in name or '\x00' in name:
            self.report(location, 'unsafe-path')
        if (leaf in LOCAL_NAMES or any(part in LOCAL_FOLDERS for part in parts)
                or leaf.startswith('.env.') and leaf != '.env.example'
                or leaf.startswith('.aider') or leaf.endswith(('.local.md', '.local.json'))
                or parts[:1] in (['notes'], ['prompts'])
                or parts[:2] in (['docs', 'internal'], ['docs', 'notes'],
                                  ['docs', 'plans'], ['docs', 'audit'])
                or leaf in {'followup-feature-selection.md', 'followup-dependency-graph.md'}):
            self.report(location, 'local-file')
        if path.suffix.lower() in SENSITIVE_SUFFIXES:
            self.report(location, 'signing-or-kernel-file')
        self.identifiers(name.encode('utf-8', errors='replace'), location)

    def identifiers(self, data, location):
        for match in IDENTIFIERS.finditer(data):
            token = match.group().lower()
            if len(token) > 64:
                continue
            forbidden = self._identifier_cache.get(token)
            if forbidden is None:
                forbidden = hashlib.sha256(token).hexdigest() in self.reserved
                if len(self._identifier_cache) < 100000:
                    self._identifier_cache[token] = forbidden
            if forbidden:
                self.report(location, 'reserved-identifier')
                return

    def content(self, name, data, location=None, depth=0):
        location = location or name
        self.path(name, location)
        self.files += 1
        self.bytes += len(data)
        if (len(data) > MAX_FILE_BYTES or self.bytes > MAX_TOTAL_BYTES
                or self.files > MAX_FILES):
            raise InspectionError('Inspection budget exceeded')
        digest = hashlib.sha256(data).digest()
        # Path checks still run when identical content is copied or renamed.
        content_key = (digest, PurePosixPath(name).suffix.lower())
        if content_key in self._seen:
            return
        self._seen.add(content_key)
        if normalized_digest(data) in self.retired:
            self.report(location, 'retired-content')
        if (PEM_KEY.search(data) or TOKEN.search(data) or SIGNING_PASSWORD.search(data)
                or der_private_material(data)):
            self.report(location, 'credential-content')
        self.identifiers(data, location)
        if b'\x00' not in data[:8192]:
            if INTERNAL_REFERENCE.search(data):
                self.report(location, 'internal-reference')
            if (PurePosixPath(name).suffix.lower() in SOURCE_SUFFIXES
                    and digest.hex() not in self.kernel_source_allowlist and KERNEL_SOURCE.search(data)):
                self.report(location, 'kernel-source')
        else:
            # Text stored in native resources can use UTF-16LE.
            for match in re.finditer(rb'(?:[A-Za-z0-9_/-]\x00){4,128}', data):
                self.identifiers(match.group()[::2], location)
        self.pe_images(data, location)
        if data.startswith(b'PK\x03\x04') or name.lower().endswith(('.zip', '.jar', '.pyz')):
            if depth >= MAX_ARCHIVE_DEPTH:
                raise InspectionError('Archive nesting limit exceeded')
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for member in archive.infolist():
                    member_location = location + '!' + member.filename
                    self.path(member.filename, member_location)
                    if member.is_dir():
                        continue
                    if member.flag_bits & 1:
                        self.report(member_location, 'encrypted-archive-member')
                        continue
                    if member.file_size > MAX_FILE_BYTES or self.bytes + member.file_size > MAX_TOTAL_BYTES:
                        raise InspectionError('Archive inspection budget exceeded')
                    if (member.external_attr >> 16) & 0o170000 == 0o120000:
                        self.report(member_location, 'archive-symlink')
                        continue
                    self.content(member.filename, archive.read(member), member_location, depth + 1)

    def pe_images(self, data, location):
        offset = 0
        while True:
            offset = data.find(b'MZ', offset)
            if offset < 0:
                return
            if offset + 64 <= len(data):
                pe = offset + struct.unpack_from('<I', data, offset + 60)[0]
                if (offset + 64 <= pe <= offset + 1048576 and pe + 94 <= len(data)
                        and data[pe:pe + 4] == b'PE\x00\x00'
                        and struct.unpack_from('<H', data, pe + 24)[0] in (0x10b, 0x20b)):
                    subsystem = struct.unpack_from('<H', data, pe + 24 + 68)[0]
                    characteristics = struct.unpack_from('<H', data, pe + 22)[0]
                    if subsystem == 1 or characteristics & 0x1000:
                        self.report(location, 'kernel-image')
            offset += 2

    def directory(self, root):
        root = Path(root)
        if not root.is_dir():
            raise InspectionError('Package directory is missing')
        for path in sorted(root.rglob('*')):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                self.report(relative, 'package-symlink')
            elif path.is_file():
                if path.stat().st_size > MAX_FILE_BYTES:
                    raise InspectionError('Package file size limit exceeded')
                self.content(relative, path.read_bytes())


def git(repo, *args, input_data=None, required=True):
    result = subprocess.run(['git', '-C', str(repo), *args], input=input_data,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if required and result.returncode:
        raise InspectionError('Unable to read the requested Git objects')
    return result.stdout if result.returncode == 0 else b''


def resolve(repo, ref, commit=False):
    suffix = '^{commit}' if commit else ''
    return git(repo, 'rev-parse', '--verify', '--end-of-options', ref + suffix).decode().strip()


def tree(repo, revision):
    result = []
    for row in git(repo, 'ls-tree', '-r', '-z', revision).split(b'\x00'):
        if not row:
            continue
        metadata, path = row.split(b'\t', 1)
        _mode, kind, oid = metadata.split()
        if kind == b'blob':
            result.append((oid.decode(), os.fsdecode(path)))
    return result


def commit_range(repo, head, base):
    if not base:
        return []
    if set(base) == {'0'}:
        remote = git(repo, 'symbolic-ref', 'refs/remotes/origin/HEAD', required=False).decode().strip()
        remote = remote or 'refs/remotes/origin/dgcore-main'
        candidate = git(repo, 'merge-base', head, remote, required=False).decode().strip()
        base = candidate or None
    if base:
        base = resolve(repo, base, commit=True)
    args = ['rev-list', '--reverse', '--topo-order', head]
    if base:
        args.append('^' + base)
    return git(repo, *args).decode().splitlines()


def changed_blobs(repo, commits):
    if not commits:
        return []
    # Inspect every introduced version, including add-then-delete sequences,
    # merge parents and restorations of blobs already present in old history.
    raw = git(repo, 'diff-tree', '--stdin', '--root', '--no-commit-id', '-m', '-r',
              '--raw', '--no-renames', '--diff-filter=ACMRT', '-z',
              input_data=('\n'.join(commits) + '\n').encode()).split(b'\x00')
    result = []
    index = 0
    while index < len(raw):
        row = raw[index].lstrip(b'\n')
        if row.startswith(b':'):
            fields = row[1:].split()
            if len(fields) != 5 or index + 1 >= len(raw):
                raise InspectionError('Unexpected Git change record')
            if fields[1] != b'160000':
                result.append((fields[3].decode(), os.fsdecode(raw[index + 1])))
            index += 2
        else:
            index += 1
    return result


def inspect_git(checker, repo, revision=None, base=None, staged=False):
    pairs = []
    if staged:
        for row in git(repo, 'ls-files', '--stage', '-z').split(b'\x00'):
            if not row:
                continue
            metadata, path = row.split(b'\t', 1)
            mode, oid, stage = metadata.split()
            if stage != b'0':
                raise InspectionError('Resolve index conflicts before checking')
            if mode != b'160000':
                pairs.append((oid.decode(), os.fsdecode(path)))
    else:
        raw_revision = resolve(repo, revision or 'HEAD')
        head = resolve(repo, revision or 'HEAD', commit=True)
        pairs.extend(tree(repo, head))
        commits = commit_range(repo, head, base)
        checker.commits += len(commits)
        pairs.extend(changed_blobs(repo, commits))
        pairs.extend((oid, '<commit-' + oid[:12] + '>') for oid in commits)
        if raw_revision != head:
            pairs.append((raw_revision, '<tag>'))
    process = subprocess.Popen(['git', '-C', str(repo), 'cat-file', '--batch'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        for oid, path in dict.fromkeys(pairs):
            checker.path(path, path)
            process.stdin.write((oid + '\n').encode())
            process.stdin.flush()
            header = process.stdout.readline().split()
            if len(header) != 3 or header[1] not in (b'blob', b'commit', b'tag'):
                raise InspectionError('Missing Git content')
            size = int(header[2])
            if size > MAX_FILE_BYTES or checker.bytes + size > MAX_TOTAL_BYTES:
                raise InspectionError('Git inspection budget exceeded')
            data = process.stdout.read(size)
            if len(data) != size or process.stdout.read(1) != b'\n':
                raise InspectionError('Incomplete Git content')
            checker.content(path, data)
    finally:
        process.stdin.close()
        process.stdout.close()
        process.wait()
    if process.returncode:
        raise InspectionError('Git object reader failed')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=HERE.parents[1])
    parser.add_argument('--policy', type=Path, default=HERE / 'public_content_policy.json')
    parser.add_argument('--revision')
    parser.add_argument('--base')
    parser.add_argument('--staged', action='store_true')
    parser.add_argument('--directory', type=Path, action='append', default=[])
    parser.add_argument('--archive', type=Path, action='append', default=[])
    args = parser.parse_args(argv)
    try:
        checker = Checker(json.loads(args.policy.read_text(encoding='utf-8')))
        if args.directory or args.archive:
            if args.staged or args.revision or args.base:
                raise InspectionError('Choose Git content or package inputs')
            for directory in args.directory:
                checker.directory(directory)
            for archive in args.archive:
                if archive.stat().st_size > MAX_FILE_BYTES:
                    raise InspectionError('Archive file size limit exceeded')
                checker.content(archive.name, archive.read_bytes())
        else:
            if args.staged and (args.revision or args.base):
                raise InspectionError('Choose index or revision inputs')
            inspect_git(checker, args.repo, args.revision, args.base, args.staged)
        for location, rule in sorted(checker.findings):
            print(json.dumps({'location': location, 'rule': rule}, ensure_ascii=True))
        print('Public content check: %d finding(s), %d files, %d commits' %
              (len(checker.findings), checker.files, checker.commits))
        return 1 if checker.findings else 0
    except Exception as error:
        # Exception text can contain a path, credential, archive member or Git
        # data. Keep failure diagnostics limited to the exception category.
        print('Public content check could not complete (%s)' % type(error).__name__, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
