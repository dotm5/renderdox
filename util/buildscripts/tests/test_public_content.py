import contextlib
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_public_content as public


def policy():
    return {'version': 1, 'retired_content_sha256': [], 'reserved_identifier_sha256': []}


def native_image(subsystem=1):
    data = bytearray(256)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 60, 64)
    data[64:68] = b'PE\0\0'
    struct.pack_into('<H', data, 64 + 24, 0x20b)
    struct.pack_into('<H', data, 64 + 24 + 68, subsystem)
    return bytes(data)


def archive(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as output:
        for name, content in entries:
            output.writestr(name, content)
    return stream.getvalue()


class ContentTests(unittest.TestCase):
    def test_user_mode_integration_and_product_skills_pass(self):
        checker = public.Checker(policy())
        checker.content('bootstrap/loader.cpp', b'LoadLibraryW(path); SetThreadContext(t, &ctx);')
        checker.content('tools/product/skills/analysis/SKILL.md', b'# Public analysis instructions\n')
        checker.content('runtime.dll', native_image(2))
        self.assertFalse(checker.findings)

    def test_excluded_names_are_case_insensitive_and_nested(self):
        checker = public.Checker(policy())
        for path in ['AGENTS.md', 'nested/aGeNtS.mD', '.codex/config.toml',
                     'docs/internal/design.md', '.env.production', 'capture.SYS', 'nested/sign.P12']:
            checker.content(path, b'fixture')
        self.assertEqual(len(checker.findings), 7)

    def test_complete_private_key_is_detected_without_rejecting_parser_labels(self):
        label = b'RSA ' + b'PRIVATE KEY'
        begin = b'-' * 5 + b'BEGIN ' + label + b'-' * 5
        end = b'-' * 5 + b'END ' + label + b'-' * 5
        checker = public.Checker(policy())
        checker.content('parser.dll', begin + b'\0' + end + b'\0')
        self.assertFalse(checker.findings)
        checker.content('renamed.txt', begin + b'\n' + b'A' * 64 + b'\n' + end)
        self.assertIn(('renamed.txt', 'credential-content'), checker.findings)

    def test_retired_content_stays_blocked_after_rename_or_crlf_conversion(self):
        data = b'Private historical fixture\nsecond line\n'
        rules = policy()
        rules['retired_content_sha256'] = [public.normalized_digest(data)]
        checker = public.Checker(rules)
        checker.content('restored/readme.md', data.replace(b'\n', b'\r\n'))
        self.assertIn(('restored/readme.md', 'retired-content'), checker.findings)

    def test_reserved_identifiers_are_compared_by_digest(self):
        rules = policy()
        rules['reserved_identifier_sha256'] = [hashlib.sha256(b'private_fixture_name').hexdigest()]
        checker = public.Checker(rules)
        checker.content('readme.txt', b'PRIVATE_FIXTURE_NAME\n')
        self.assertIn(('readme.txt', 'reserved-identifier'), checker.findings)

    def test_kernel_source_and_embedded_images_are_detected(self):
        checker = public.Checker(policy())
        checker.content('helper.cpp', b'Nt' + b'LoadDriver(path);')
        checker.content('renamed.bin', native_image())
        checker.content('tool.exe', native_image(2) + b'padding' + native_image())
        self.assertEqual({rule for _, rule in checker.findings}, {'kernel-source', 'kernel-image'})

    def test_reusing_content_under_a_source_suffix_still_checks_source_rules(self):
        checker = public.Checker(policy())
        data = b'Nt' + b'LoadDriver(path);'
        checker.content('sample.txt', data)
        checker.content('helper.cpp', data)
        self.assertIn(('helper.cpp', 'kernel-source'), checker.findings)

    def test_vendor_allowlist_applies_only_to_exact_kernel_source_content(self):
        data = b'#include <' + b'ntddk.h>\n'
        rules = policy()
        rules['allowed_kernel_source_sha256'] = [hashlib.sha256(data).hexdigest()]
        checker = public.Checker(rules)
        checker.content('vendor/compat.h', data)
        self.assertFalse(checker.findings)
        checker.content('vendor/modified.h', data + b'// modified\n')
        self.assertIn(('vendor/modified.h', 'kernel-source'), checker.findings)

    def test_signing_password_rule_requires_a_literal(self):
        checker = public.Checker(policy())
        checker.content('scanner.py', b'SIGNING_' + b'PASSWORD = re.compile(pattern)')
        self.assertFalse(checker.findings)
        checker.content('unsafe.py', b'signing_' + b'password = "' + b'synthetic_value' + b'"')
        self.assertIn(('unsafe.py', 'credential-content'), checker.findings)

    def test_renamed_der_private_containers_are_detected(self):
        def tlv(tag, value):
            return bytes([tag, len(value)]) + value
        private = tlv(0x30, tlv(2, b'\0') + tlv(0x30, tlv(6, b'\x2a\x03')) + tlv(4, b'A' * 32))
        pfx = tlv(0x30, tlv(2, b'\3') + tlv(0x30, tlv(6, bytes.fromhex('2a864886f70d010701'))))
        checker = public.Checker(policy())
        checker.content('key.dat', private)
        checker.content('container.bin', pfx)
        self.assertEqual(len(checker.findings), 2)

    def test_public_der_structure_and_malformed_der_pass(self):
        self.assertFalse(public.der_private_material(b'\x30\x03\x02\x01\x02'))
        self.assertFalse(public.der_private_material(b'\x30\x82\x00'))

    def test_nested_archive_checks_windows_paths_and_hidden_driver(self):
        checker = public.Checker(policy())
        inner = archive([('notes\\AGENTS.md', b'fixture'), ('renamed.dat', native_image())])
        checker.content('package.zip', archive([('runtime/inner.zip', inner)]))
        self.assertEqual({rule for _, rule in checker.findings}, {'local-file', 'kernel-image'})

    def test_archive_path_traversal_and_symlinks_are_rejected(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as output:
            output.writestr('../escape.txt', b'fixture')
            link = zipfile.ZipInfo('link')
            link.external_attr = (0o120777 << 16)
            output.writestr(link, b'outside')
        checker = public.Checker(policy())
        checker.content('package.zip', stream.getvalue())
        self.assertEqual({rule for _, rule in checker.findings}, {'unsafe-path', 'archive-symlink'})

    def test_archive_budget_is_a_failure(self):
        checker = public.Checker(policy())
        with self.assertRaises(public.InspectionError):
            checker.content('inner.zip', archive([('file.txt', b'fixture')]), depth=public.MAX_ARCHIVE_DEPTH)


class GitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        (self.root / 'README.md').write_text('Public fixture\n')
        self.base = self.commit()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.DEVNULL).decode().strip()

    def commit(self):
        self.git('add', '--all')
        self.git('commit', '-qm', 'Synthetic fixture')
        return self.git('rev-parse', 'HEAD')

    def test_staged_index_checks_forced_ignored_files(self):
        (self.root / '.gitignore').write_text('AGENTS.md\n')
        (self.root / 'AGENTS.md').write_text('fixture\n')
        self.git('add', '.gitignore')
        self.git('add', '-f', 'AGENTS.md')
        checker = public.Checker(policy())
        public.inspect_git(checker, self.root, staged=True)
        self.assertIn(('AGENTS.md', 'local-file'), checker.findings)

    def test_add_then_delete_commits_are_checked(self):
        secret = 'gh' + 'p_' + 'B' * 36
        (self.root / 'temporary.txt').write_text(secret)
        self.commit()
        (self.root / 'temporary.txt').unlink()
        self.commit()
        checker = public.Checker(policy())
        public.inspect_git(checker, self.root, base=self.base)
        self.assertIn(('temporary.txt', 'credential-content'), checker.findings)
        self.assertEqual(checker.commits, 2)

    def test_restore_existing_blob_then_delete_is_checked(self):
        # The content object already existed in the base; diff-tree must still
        # inspect its new path instead of relying on new-object enumeration.
        (self.root / 'AGENTS.md').write_text('Public fixture\n')
        self.commit()
        (self.root / 'AGENTS.md').unlink()
        self.commit()
        checker = public.Checker(policy())
        public.inspect_git(checker, self.root, base=self.base)
        self.assertIn(('AGENTS.md', 'local-file'), checker.findings)

    def test_new_branch_and_merge_history_are_checked(self):
        main = self.git('symbolic-ref', '--short', 'HEAD')
        self.git('checkout', '-qb', 'fixture-branch')
        (self.root / 'AGENTS.md').write_text('fixture\n')
        self.commit()
        (self.root / 'AGENTS.md').unlink()
        self.commit()
        self.git('checkout', '-q', main)
        self.git('merge', '--no-ff', '-qm', 'Synthetic merge', 'fixture-branch')
        checker = public.Checker(policy())
        public.inspect_git(checker, self.root, base='0' * 40)
        self.assertIn(('AGENTS.md', 'local-file'), checker.findings)

    def test_cli_redacts_secret_values_and_fails_for_missing_base(self):
        secret = 'gh' + 'p_' + 'C' * 36
        (self.root / 'temporary.txt').write_text(secret)
        self.commit()
        policy_file = self.root / 'policy.json'
        policy_file.write_text(json.dumps(policy()))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = public.main(['--repo', str(self.root), '--policy', str(policy_file)])
        self.assertEqual(status, 1)
        self.assertNotIn(secret, output.getvalue())
        self.assertIn('credential-content', output.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            status = public.main(['--repo', str(self.root), '--policy', str(policy_file), '--base', 'missing-ref'])
        self.assertEqual(status, 2)

    def test_new_tag_reuses_default_branch_baseline(self):
        (self.root / 'AGENTS.md').write_text('historical fixture\n')
        self.commit()
        (self.root / 'AGENTS.md').unlink()
        head = self.commit()
        self.git('update-ref', 'refs/remotes/origin/dgcore-main', head)
        checker = public.Checker(policy())
        public.inspect_git(checker, self.root, base='0' * 40)
        self.assertFalse(checker.findings)
        self.assertEqual(checker.commits, 0)

    def test_annotated_tag_message_is_checked(self):
        secret = 'gh' + 'p_' + 'D' * 36
        self.git('tag', '-a', 'fixture-tag', '-m', secret)
        checker = public.Checker(policy())
        public.inspect_git(checker, self.root, revision='fixture-tag', base=self.base)
        self.assertIn(('<tag>', 'credential-content'), checker.findings)


if __name__ == '__main__':
    unittest.main()
