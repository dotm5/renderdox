import importlib.util
import tempfile
import unittest
import hashlib
import json
import sys
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

path=Path(__file__).resolve().parents[1]/"proxy_builder.py"
sys.path.insert(0,str(path.parent))
spec=importlib.util.spec_from_file_location("proxy_builder",path)
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)


class BuilderTests(unittest.TestCase):
    def manifest(self):
        return {"architecture":"x64","module":"fixture.dll","exports":[{"ordinal":7,"names":[],"kind":"code"},{"ordinal":15,"names":["Forward"],"kind":"forwarder","forwarder":"KERNEL32.Sleep"}]}

    def test_refuses_data_architecture_names_and_recursive_original(self):
        with tempfile.TemporaryDirectory() as d:
            for mutate in (lambda m:m.update(architecture="x86"),lambda m:m["exports"][0].update(kind="data_or_unknown"),lambda m:m["exports"][1].update(names=['bad"name'])):
                m=self.manifest();mutate(m)
                with self.assertRaises(ValueError):builder.generate(m,Path(d)/"out","app-local")
            with self.assertRaises(ValueError):builder.generate(self.manifest(),Path(d)/"out","app-local","fixture.dll")

    def test_deterministic_generation_and_ordinal_contract(self):
        with tempfile.TemporaryDirectory() as d:
            m=self.manifest()
            builder.generate(m,Path(d)/"a","app-local")
            builder.generate(m,Path(d)/"b","app-local")
            for path in (Path(d)/"a").rglob('*'):
                if path.is_file():
                    self.assertEqual(path.read_bytes(),(Path(d)/"b"/path.relative_to(Path(d)/'a')).read_bytes())
            self.assertIn("@7 NONAME",(Path(d)/"a"/"exports.def").read_text())
            self.assertIn("MAKEINTRESOURCEA(7)",(Path(d)/"a"/"runtime.cpp").read_text())
            with self.assertRaises(ValueError):builder.generate(m,Path(d)/"a","app-local")
            self.assertNotIn(str(builder.REPO),(Path(d)/'a'/'proxy.vcxproj').read_text())

    def test_build_rejects_incompatible_route_and_activation_before_generation(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'input.dll';source.write_bytes(b'original')
            with patch.object(builder,'find_msbuild',return_value=source), patch.object(builder,'inspect',return_value=self.manifest()):
                for extra in ({'route':'system-dll'}, {'enable_core':True}, {'template':'system','copy_original':True}):
                    with self.assertRaises(ValueError):builder.build_dll(source,Path(d)/'out',**extra)
                    self.assertFalse((Path(d)/'out').exists())

    def test_malformed_file_and_contract_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"bad.dll";p.write_bytes(b'MZ'+b'\0'*80)
            with self.assertRaises(ValueError):builder.inspect(p)
        m=self.manifest();m.update(sha256="a")
        other=self.manifest();other.update(sha256="b");other["exports"][0]["ordinal"]=8
        self.assertFalse(builder.verify(m,other)["matches"])

    def test_build_failure_and_changed_generated_source_are_not_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'input.dll';source.write_bytes(b'original')
            manifest=self.manifest();manifest['sha256']=builder.digest(source)
            for mode in ('compiler_failure','changed_source'):
                output=Path(d)/mode
                def compile(*a,**kw):
                    if mode=='changed_source':(output/'runtime.cpp').write_text('changed')
                    return SimpleNamespace(returncode=1 if mode=='compiler_failure' else 0)
                with patch.object(builder,'find_msbuild',return_value=source), patch.object(builder,'inspect',return_value=manifest), patch.object(builder.subprocess,'run',side_effect=compile):
                    with self.assertRaises(ValueError):builder.build_dll(source,output)
                self.assertEqual(json.loads((output/'build-result.json').read_text())['status'],'failed')


if __name__=="__main__": unittest.main()
