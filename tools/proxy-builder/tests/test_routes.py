import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import proxy_builder as builder
import routes


class RouteTests(unittest.TestCase):
    def manifest(self):
        return {'architecture':'x64','module':'sample.dll','sha256':'a'*64,'exports':[
            {'ordinal':3,'names':['Code'],'kind':'code','rva':4096},
            {'ordinal':7,'names':[],'kind':'code','rva':4096},
            {'ordinal':10,'names':['nvapi_QueryInterface'],'kind':'code','rva':4128},
            {'ordinal':11,'names':['vkGetInstanceProcAddr'],'kind':'code','rva':4160},
            {'ordinal':12,'names':['vkGetDeviceProcAddr'],'kind':'code','rva':4192}]}
    def reject(self,config,profile='generic',manifest=None):
        with self.assertRaises(ValueError): routes.config_for(manifest or self.manifest(),profile,config)
    def test_strict_config(self):
        for c in ({'typo':True},{'schemaVersion':2},{'activation':'guess'},{'enableDefault':'true'},
                  {'requireCore':1},{'plugins':'x'},{'watchModules':'x'},{'profile':'ngx'}): self.reject(c)
    def test_provider_path_validation(self):
        for path in ('sample.dll','..\\original.dll','relative\\original.dll','bad\x00.dll','bad?.dll'):
            self.reject({'provider':{'kind':'sibling','path':path}})
        self.reject({'provider':{'kind':'absolute','path':'original.dll'}})
        self.reject({'provider':{'kind':'invalid','path':'original.dll'}})
    def test_absolute_and_unc_paths(self):
        for path in (r'D:\path with spaces\代理.dll',r'\\server\share\original.dll'):
            self.assertEqual(routes.config_for(self.manifest(),'generic',{'provider':{'kind':'absolute','path':path}})['provider']['path'],path)
    def test_hash_validation(self):
        for h in ('abc','A'*64,'0'*63): self.reject({'provider':{'kind':'sibling','path':'original.dll','sha256':h}})
    def test_trigger_and_watches(self):
        self.reject({'activation':'export'})
        self.reject({'activation':'export','activateExports':['missing']})
        self.reject({'activation':'module-load'})
        self.reject({'activation':'module-load','watchModules':[r'..\x.dll']})
        self.assertEqual(routes.config_for(self.manifest(),'generic',{'activation':'export','activateExports':['Code']})['activation'],'export')
    def test_plugin_collisions(self):
        for p in ('sample.dll','sample_orig.dll','dgcore.dll'):
            self.reject({'plugins':[{'path':p}]})
    def test_auto_profiles(self):
        self.assertEqual(routes.config_for(self.manifest(),'auto')['profile'],'nvapi')
        m=self.manifest(); m['exports']=[e for e in m['exports'] if 'nvapi_QueryInterface' not in e['names']]
        self.assertEqual(routes.config_for(m,'auto')['profile'],'vulkan')
    def test_aftermath_carrier_defaults_to_independent_worker(self):
        m=self.manifest(); m['module']='GFSDK_Aftermath_Lib.x64.dll'
        m['exports'][0]['names']=['GFSDK_Aftermath_DX11_Initialize']
        c=routes.config_for(m,'auto')
        self.assertEqual((c['profile'],c['activation']),('aftermath','worker'))
        self.assertEqual([c['provider']['path']]+c['provider']['alternates'],list(routes.AFTERMATH_ORIGINAL_NAMES))
        # The old explicit Streamline recipe still carries an Aftermath DLL.
        self.assertEqual(routes.config_for(m,'streamline')['activation'],'worker')
    def test_graphics_query_profile_does_not_select_startup_timing(self):
        m=self.manifest(); m['module']='sl.interposer.dll'
        self.assertEqual(routes.config_for(m,'streamline')['activation'],'first-call')
        self.assertEqual(routes.config_for(self.manifest(),'generic',bootstrap_route=True)['activation'],'worker')
        self.assertEqual(routes.config_for(self.manifest(),'generic',{'activation':'manual'},bootstrap_route=True)['activation'],'manual')
    def test_aftermath_explicit_activation_and_rename_override(self):
        m=self.manifest(); m['module']='GFSDK_Aftermath_Lib.x64.dll'
        m['exports'][0]['names']=['GFSDK_Aftermath_DX11_Initialize']
        c=routes.config_for(m,'auto',{'activation':'first-call'},original='owned_original.dll')
        self.assertEqual(c['activation'],'first-call')
        self.assertEqual(c['provider']['path'],'owned_original.dll')
        self.assertEqual(c['provider']['alternates'],[])
    def test_provider_alternates_cannot_bypass_path_or_loader_contracts(self):
        for alternates in ('original.dll',[r'..\other.dll'],['sample.dll'],['dgcore.dll'],['original.dll']):
            self.reject({'provider':{'kind':'sibling','path':'original.dll','alternates':alternates}})
        self.reject({'provider':{'kind':'system','path':'original.dll','alternates':['other.dll']}})
        self.reject({'activation':'worker','forwarding':'linker','provider':{'kind':'sibling','path':'original.dll','alternates':['other.dll']}})
    def test_data_forwarders_reject_alternate_provider_contract(self):
        m=self.manifest(); m['exports'][0].update(kind='data_or_unknown',fileBackedBytes=4)
        self.reject({'provider':{'kind':'sibling','path':'original.dll','alternates':['other.dll']},
                     'dataExports':{'Code':{'type':'uint32'}}},manifest=m)
    def test_query_preserves_contract_and_checks_ids(self):
        self.reject({'queryMappings':{'id':'Code'}},'nvapi')
        self.reject({'queryMappings':{'0x100000000':'Code'}},'nvapi')
        self.reject({'queryMappings':{'1':'Code','0x1':'Code'}},'nvapi')
        self.reject({'queryMappings':{'0':'missing'}},'nvapi')
        self.reject({'queryMappings':{'vkSomething':'Code'}})
        self.reject({'queryMappings':{'notVk':'Code'}},'vulkan')
    def test_data_requires_explicit_type_and_bounded_range(self):
        m=self.manifest(); m['exports'].append({'ordinal':20,'names':['Data'],'kind':'data_or_unknown','rva':8192,'fileBackedBytes':4})
        self.reject({},manifest=m)
        self.reject({'dataExports':{'Data':{'type':'guess'}}},manifest=m)
        self.reject({'dataExports':{'Data':{'type':'uint64'}}},manifest=m)
        self.reject({'dataExports':{'Code':{'type':'uint32'}}},manifest=m)
        c=routes.config_for(m,'generic',{'dataExports':{'Data':{'type':'uint32'}}})
        self.assertEqual(c['dataIndices'][5]['type'],'uint32')
    def test_data_cannot_use_system_or_absolute_forwarder(self):
        m=self.manifest(); m['exports'][0].update(kind='data_or_unknown',fileBackedBytes=4)
        self.reject({'provider':{'kind':'system','path':'sample.dll'},'dataExports':{'Code':{'type':'uint32'}}},manifest=m)
    def test_linker_requires_compatible_activation(self):
        self.reject({'forwarding':'linker','activation':'first-call'})
        self.reject({'forwarding':'linker','activation':'worker','provider':{'kind':'system','path':'sample.dll'}})
        self.assertEqual(routes.config_for(self.manifest(),'generic',{'forwarding':'linker','activation':'manual'})['forwarding'],'linker')
    def test_startup_default_distinguishes_carriers_from_graphics_providers(self):
        for profile in ('generic','ngx','nvapi'):
            self.assertEqual(routes.config_for(self.manifest(),profile)['activation'],'worker')
        for name in ('version.dll','winhttp.dll','winmm.dll'):
            m=self.manifest(); m['module']=name
            self.assertEqual(routes.config_for(m,'generic')['activation'],'worker')
        for name in ('dxgi.dll','d3d11.dll','d3d12.dll','opengl32.dll'):
            m=self.manifest(); m['module']=name
            self.assertEqual(routes.config_for(m,'generic')['activation'],'first-call')
    def test_control_collision(self):
        m=self.manifest(); m['exports'][0]['names']=['DCompProxyInitialize']; self.reject({},manifest=m)
    def test_multiple_query_protocols_on_one_proxy(self):
        config=routes.config_for(self.manifest(),'generic',{'dispatch':{'nvapi':{'0x1234':'Code'},'vulkan':{'vkCode':'Code'}}})
        self.assertEqual(set(config['dispatch']),{'nvapi','vulkan'})
        self.assertEqual(config['dispatch']['vulkan']['vkCode'],'Code')
    def test_self_contained_deterministic_route_project(self):
        with tempfile.TemporaryDirectory() as d:
            m=self.manifest(); c=routes.config_for(m,'nvapi',{'queryMappings':{'0x1234':'Code'}})
            a,b=Path(d)/'a',Path(d)/'b'
            routes.generate(m,a,c,builder.REPO,'b'*64); routes.generate(m,b,c,builder.REPO,'b'*64)
            for f in a.rglob('*'):
                if f.is_file(): self.assertEqual(f.read_bytes(),(b/f.relative_to(a)).read_bytes())
            text=(a/'dispatch.cpp').read_text()
            self.assertIn('if(!result) return result',text)
            self.assertIn('id == 4660u',text)
            self.assertNotIn(str(builder.REPO),(a/'proxy.vcxproj').read_text())
            with self.assertRaises(ValueError): routes.generate(m,a,c,builder.REPO,'b'*64)


if __name__=='__main__': unittest.main()
