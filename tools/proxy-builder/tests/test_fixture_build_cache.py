import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

import fixture_build_cache as cache


class FixtureBuildCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = mock.patch.dict(os.environ, {'RENDERDOX_FIXTURE_CACHE_KEY': 'env-A'})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.inputs = mock.patch.object(cache, 'source_fingerprint', return_value='source-A')
        self.inputs.start()
        self.addCleanup(self.inputs.stop)
        for toolchain in ('MSVC', 'ClangCL'):
            binary = self.root / toolchain / 'order/bin/d3d12-order.exe'
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b'owned fixture build output')
        (self.root / 'results.json').write_text(json.dumps([
            {'toolchain': name, 'contractVerified': True} for name in ('MSVC', 'ClangCL')
        ]))

    def test_complete_cache_round_trip_does_not_depend_on_mtime(self):
        cache.seal(self.root, 'static')
        binary = self.root / 'MSVC/order/bin/d3d12-order.exe'
        os.utime(binary, (1, 1))
        restored = cache.verify(self.root, 'static')
        self.assertEqual(restored['identity'], 'env-A')
        self.assertIn('MSVC/order/bin/d3d12-order.exe', restored['files'])

    def test_same_size_modified_binary_is_rejected_even_with_old_timestamp(self):
        cache.seal(self.root, 'static')
        binary = self.root / 'MSVC/order/bin/d3d12-order.exe'
        previous = binary.stat().st_mtime_ns
        binary.write_bytes(b'x' * binary.stat().st_size)
        os.utime(binary, ns=(previous, previous))
        with self.assertRaisesRegex(ValueError, 'contents'):
            cache.verify(self.root, 'static')

    def test_added_or_deleted_files_are_rejected(self):
        cache.seal(self.root, 'static')
        added = self.root / 'unexpected.dll'
        added.write_bytes(b'new')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            cache.verify(self.root, 'static')
        added.unlink()
        (self.root / 'MSVC/order/bin/d3d12-order.exe').unlink()
        with self.assertRaisesRegex(ValueError, 'inventory'):
            cache.verify(self.root, 'static')

    def test_environment_source_and_kind_must_match(self):
        cache.seal(self.root, 'static')
        with mock.patch.dict(os.environ, {'RENDERDOX_FIXTURE_CACHE_KEY': 'env-B'}):
            with self.assertRaisesRegex(ValueError, 'identity'):
                cache.verify(self.root, 'static')
        with mock.patch.object(cache, 'source_fingerprint', return_value='source-B'):
            with self.assertRaisesRegex(ValueError, 'identity'):
                cache.verify(self.root, 'static')
        with self.assertRaisesRegex(ValueError, 'identity'):
            cache.verify(self.root, 'routes')

    def test_missing_key_and_malformed_inventory_are_rejected(self):
        cache.seal(self.root, 'static')
        with mock.patch.dict(os.environ, {'RENDERDOX_FIXTURE_CACHE_KEY': ''}):
            with self.assertRaisesRegex(ValueError, 'requires'):
                cache.verify(self.root, 'static')
        manifest = self.root / cache.CACHE_FILE
        value = json.loads(manifest.read_text())
        value['files']['../outside.exe'] = {'bytes': 0, 'sha256': 'bad'}
        manifest.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'artifact path'):
            cache.verify(self.root, 'static')

    def test_incomplete_or_relocated_cache_is_rejected(self):
        cache.seal(self.root, 'static')
        manifest = self.root / cache.CACHE_FILE
        value = json.loads(manifest.read_text())
        value['root'] = str(self.root / 'other-checkout')
        manifest.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'absolute output path'):
            cache.verify(self.root, 'static')
        (self.root / 'results.json').write_text('[]')
        with self.assertRaisesRegex(ValueError, 'toolchain results'):
            cache.seal(self.root, 'static')

    def test_source_fingerprint_ignores_bytecode_but_tracks_python_source(self):
        self.inputs.stop()
        repository = self.root / 'repository'
        source = repository / 'tools/proxy-builder/entry.py'
        source.parent.mkdir(parents=True)
        source.write_text('VALUE = 1\n')
        with mock.patch.object(cache, 'REPO', repository):
            original = cache.source_fingerprint()
            bytecode = source.parent / '__pycache__/entry.cpython-314.pyc'
            bytecode.parent.mkdir()
            bytecode.write_bytes(b'first interpreter cache')
            standalone = source.parent / 'legacy.pyc'
            standalone.write_bytes(b'legacy bytecode')
            self.assertEqual(cache.source_fingerprint(), original)
            bytecode.write_bytes(b'updated interpreter cache')
            standalone.write_bytes(b'updated legacy bytecode')
            self.assertEqual(cache.source_fingerprint(), original)
            source.write_text('VALUE = 2\n')
            self.assertNotEqual(cache.source_fingerprint(), original)

    def test_current_export_contract_is_executed_on_reuse(self):
        generated = self.root / 'generated'
        generated.mkdir()
        source = self.root / 'source.dll'
        source.write_bytes(b'original')
        binary = generated / 'fixture.dll'
        binary.write_bytes(b'compiled')
        receipt = {
            'status': 'verified', 'toolchain': 'MSVC', 'dll': str(binary),
            'dllSHA256': cache.digest(binary), 'sourceSHA256': cache.digest(source),
            'generatedFiles': {},
        }
        (generated / 'build-result.json').write_text(json.dumps(receipt))
        (generated / 'exports.json').write_text(json.dumps({'routeConfig': {}}))
        checks = []
        def inspect(path):
            return {'sha256': cache.digest(path), 'exports': []}
        def verify_route(*args):
            checks.append('exports checked again')
            return {'matches': True}
        builder = types.SimpleNamespace(digest=cache.digest, inspect=inspect, verify=None,
            routes=types.SimpleNamespace(verify=verify_route))
        cache.cached_receipt(generated, builder, source, 'MSVC')
        self.assertEqual(checks, ['exports checked again'])
        source.write_bytes(b'changed input')
        with self.assertRaisesRegex(ValueError, 'input DLL changed'):
            cache.cached_receipt(generated, builder, source, 'MSVC')


if __name__ == '__main__':
    unittest.main()
