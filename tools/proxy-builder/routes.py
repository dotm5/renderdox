"""Route-aware generation, independent of third-party proxy implementations."""
import hashlib
import json
import re
import shutil
import subprocess
import struct
from pathlib import Path, PureWindowsPath
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
if not (ROOT / 'templates').is_dir():
    import sys
    ROOT = Path(sys.executable).resolve().parent / 'route-templates'

PROFILES = {
    'generic': 'Exact exports; configurable provider, activation and plugins',
    'aftermath': 'SDK carrier: load-time Core worker independent of lazy Aftermath forwarding',
    'streamline': 'Physical EAT stubs and early Core gate; existing Core provider hooks',
    'ngx': 'NGX/provider proxy with exact SDK exports',
    'nvapi': 'Numeric nvapi_QueryInterface dispatch, preserving unknown/null results',
    'vulkan': 'vkGetInstanceProcAddr/vkGetDeviceProcAddr dispatch with handle passthrough',
    'agility': 'D3D12GetInterface route and explicitly declared DATA forwarders',
}
ACTIVATION = {'worker': 0, 'first-call': 1, 'export': 2, 'entry-point': 3, 'manual': 4, 'module-load': 5}
CONTROL = ['DCompProxyInitialize', 'DCompProxyGetState', 'DCompProxyGetLastError', 'DCompProxyNextProvider', 'DCompProxyCheckProvider']
AFTERMATH_ORIGINAL_NAMES = ('GFSDK_Aftermath_Lib_orig.dll', 'GFSDK_Aftermath_Lib.x64.orig.dll',
                           'GFSDK_Aftermath_Lib_orig.x64.dll')


def aftermath_carrier(manifest):
    module = manifest['module'].lower()
    return (module.startswith('gfsdk_aftermath_lib') and module.endswith('.dll') and
            any(n.startswith('GFSDK_Aftermath_') for e in manifest['exports'] for n in e['names']))


def activation_default(manifest, profile, bootstrap_route=False):
    if aftermath_carrier(manifest) or profile=='aftermath':
        return 'worker', 'sdk-carrier-load-time'
    if bootstrap_route:
        return 'worker', 'bootstrap-route-load-time'
    if profile in ('streamline','vulkan','agility') or manifest['module'].lower() in (
            'dxgi.dll','d3d11.dll','d3d12.dll','opengl32.dll'):
        return 'first-call', 'graphics-first-call'
    # Generic/NGX/NVAPI and non-graphics system slots are load carriers. Their
    # APIs may be unused or called only after a graphics device already exists.
    return 'worker', 'carrier-load-time'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def string(value, wide=False):
    # C++ source uses /utf-8. Escape controls without JSON's invalid \u0000
    # universal character names; strings with NUL are rejected on input.
    value = value.replace('\\', '\\\\').replace('"', '\\"')
    return ('L' if wide else '') + '"' + value + '"'


def path_value(value, allow_absolute=True):
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid provider/plugin path')
    p = PureWindowsPath(value)
    if p.is_absolute():
        if not allow_absolute: raise ValueError('This path must be a DLL basename')
    elif p.name != value or ':' in value or value in ('.', '..'):
        raise ValueError('Relative paths must be basenames; use an explicit absolute path for subdirectories')
    if any(c in p.name for c in '*?"<>|'):
        raise ValueError('Unsafe filename')
    return value


def config_for(manifest, profile='generic', config=None, original=None, core=None, bootstrap_route=False):
    if profile == 'auto':
        module = manifest['module'].lower()
        names = {n for e in manifest['exports'] for n in e['names']}
        profile = ('aftermath' if aftermath_carrier(manifest) else 'nvapi' if 'nvapi_QueryInterface' in names else 'vulkan' if
                   {'vkGetInstanceProcAddr', 'vkGetDeviceProcAddr'} <= names else
                   'streamline' if module == 'sl.interposer.dll' else
                   'ngx' if 'nvngx' in module else 'generic')
    if profile not in PROFILES: raise ValueError('Unknown profile: ' + profile)
    if config is None: config = {}
    if not isinstance(config, dict): raise ValueError('Route config must be an object')
    allowed = {'schemaVersion', 'provider', 'activation', 'activateExports', 'plugins', 'dataExports',
               'queryMappings', 'enableDefault', 'core', 'forwarding', 'profile', 'watchModules', 'requireCore', 'dispatch'}
    if set(config) - allowed: raise ValueError('Unknown route options: ' + ', '.join(sorted(set(config)-allowed)))
    if config.get('schemaVersion', 1) != 1: raise ValueError('Unsupported route schema')
    if 'profile' in config and config['profile'] != profile: raise ValueError('Config/profile mismatch')
    exports = manifest['exports']
    if manifest['architecture'] != 'x64' or not exports: raise ValueError('Routes require nonempty x64 exports')
    module = path_value(manifest['module'], False)
    if not module.lower().endswith('.dll'): raise ValueError('Expected a DLL module name')
    names = {n for e in exports for n in e['names']}
    if names & set(CONTROL): raise ValueError('Source collides with route control exports')
    for e in exports:
        if not 1 <= e['ordinal'] <= 65535: raise ValueError('Ordinal outside Win32 range')
        if any(not re.fullmatch(r'[A-Za-z_?@$][A-Za-z0-9_?@$]*', n) for n in e['names']):
            raise ValueError('Unsafe DEF export name')
    default_system = not original and module.lower() in ('dxgi.dll', 'd3d11.dll', 'd3d12.dll', 'opengl32.dll',
        'winmm.dll', 'version.dll', 'winhttp.dll', 'wininet.dll', 'dinput8.dll', 'dsound.dll')
    sdk_carrier = aftermath_carrier(manifest) or profile == 'aftermath'
    default_original = AFTERMATH_ORIGINAL_NAMES[0] if sdk_carrier else module[:-4]+'_orig.dll'
    provider = config.get('provider', {'kind':'system' if default_system else 'sibling',
        'path':module if default_system else original or default_original,
        'sha256':manifest.get('sha256', '')})
    if not isinstance(provider, dict) or set(provider)-{'kind','path','sha256','alternates'}:
        raise ValueError('Invalid provider object')
    provider = dict(provider)
    provider.setdefault('alternates', list(AFTERMATH_ORIGINAL_NAMES[1:]) if sdk_carrier and
                        not original and 'provider' not in config else [])
    if provider.get('kind') not in ('system','sibling','absolute'): raise ValueError('Invalid provider kind')
    provider['path'] = path_value(provider.get('path'), provider['kind']=='absolute')
    if provider['kind']=='absolute' and not PureWindowsPath(provider['path']).is_absolute():
        raise ValueError('Absolute provider requires an absolute path')
    if provider['kind']=='sibling' and provider['path'].lower()==module.lower():
        raise ValueError('Recursive sibling provider')
    alternates = provider['alternates']
    if not isinstance(alternates,list) or len(alternates)>16 or (alternates and provider['kind']!='sibling'):
        raise ValueError('Provider alternates require a sibling list of at most 16 basenames')
    for name in alternates:
        path_value(name,False)
        if name.lower() in (module.lower(),'dgcore.dll'):
            raise ValueError('Alternate provider collides with proxy/Core')
    if len({name.lower() for name in [provider['path']]+alternates}) != len(alternates)+1:
        raise ValueError('Duplicate provider candidates')
    if provider['path'].lower().endswith('dgcore.dll'): raise ValueError('Provider must not alias Core')
    provider.setdefault('sha256', '')
    # An SDK used as a carrier need not be called at all. Preserve the reviewed
    # Aftermath architecture: Core startup and original forwarding are independent.
    default_activation, _ = activation_default(manifest, profile, bootstrap_route)
    activation = config.get('activation', default_activation)
    if activation not in ACTIVATION: raise ValueError('Unknown activation mode')
    triggers = config.get('activateExports', [])
    if not isinstance(triggers, list) or any(n not in names for n in triggers): raise ValueError('Unknown activation export')
    if activation == 'export' and not triggers: raise ValueError('Export activation requires activateExports')
    watches = config.get('watchModules', [])
    if not isinstance(watches,list) or len(watches)>64: raise ValueError('watchModules must be a list of at most 64 names')
    for name in watches: path_value(name,False)
    if activation=='module-load' and not watches: raise ValueError('Module-load activation requires watchModules')
    required = config.get('requireCore',False)
    if not isinstance(required,bool): raise ValueError('requireCore must be boolean')
    core_config = dict(config.get('core', {}))
    if set(core_config)-{'path','sha256'}: raise ValueError('Unknown Core options')
    core_config.setdefault('path', 'dgcore.dll')
    path_value(core_config['path'])
    core_config.setdefault('sha256', sha(core) if core else '')
    if PureWindowsPath(core_config['path']).name.lower() == module.lower(): raise ValueError('Core collides with proxy')
    plugins = config.get('plugins', [])
    if not isinstance(plugins, list): raise ValueError('plugins must be a list')
    for plugin in plugins:
        if not isinstance(plugin, dict) or set(plugin)-{'path','sha256'}: raise ValueError('Invalid plugin')
        path_value(plugin.get('path'))
        if PureWindowsPath(plugin['path']).name.lower() in (module.lower(), 'dgcore.dll', PureWindowsPath(provider['path']).name.lower()):
            raise ValueError('Plugin collides with a route module')
    for target in [provider, core_config] + plugins:
        h = target.get('sha256', '')
        if not isinstance(h, str) or (h and not re.fullmatch('[0-9a-f]{64}', h)): raise ValueError('SHA256 must be lowercase hex')
    data = config.get('dataExports', {})
    if not isinstance(data, dict): raise ValueError('dataExports must be an object')
    data_by_index = {}
    sizes = {'uint32':4, 'uint64':8, 'pointer':8, 'opaque-address':None}
    used = set()
    for i,e in enumerate(exports):
        keys = [n for n in e['names'] if n in data] + ([str(e['ordinal'])] if str(e['ordinal']) in data else [])
        if e['kind'] == 'data_or_unknown':
            if len(keys) != 1: raise ValueError('Data/unknown export requires one explicit typed dataExports declaration: ' + str(e['names'] or e['ordinal']))
            key = keys[0]; spec = data[key]
            if not isinstance(spec,dict) or set(spec)-{'type'} or spec.get('type') not in sizes:
                raise ValueError('DATA type must be uint32/uint64/pointer/opaque-address')
            if sizes[spec['type']] and e.get('fileBackedBytes', 0)<sizes[spec['type']]: raise ValueError('Truncated typed data export')
            used.add(key); data_by_index[i] = spec
        elif keys: raise ValueError('Code/forwarder cannot be declared as DATA')
    if set(data)-used: raise ValueError('Unused DATA declarations')
    # DATA uses loader-resolved forwarders, retaining original address/storage.
    # Absolute/system paths cannot be safely encoded as arbitrary PE forwarder
    # module names. Code routes support them; DATA requires a sibling original.
    if data_by_index and provider['kind'] != 'sibling':
        raise ValueError('DATA forwarding requires a sibling provider; use --original and --copy-original')
    forwarding = config.get('forwarding','physical')
    if forwarding not in ('physical','linker'): raise ValueError('Unknown forwarding architecture')
    if forwarding == 'linker' and (provider['kind']!='sibling' or activation not in ('worker','entry-point','manual')):
        raise ValueError('Linker forwarding needs sibling provider and worker/entry-point/manual activation')
    if (data_by_index or forwarding=='linker') and alternates:
        raise ValueError('Loader forwarders cannot implement alternate provider filenames')
    mappings = config.get('queryMappings', {})
    if not isinstance(mappings,dict): raise ValueError('queryMappings must be an object')
    if profile not in ('vulkan','nvapi') and mappings: raise ValueError('Query mappings need a Vulkan/NVAPI profile')
    if profile=='nvapi' and 'nvapi_QueryInterface' not in names: raise ValueError('Missing nvapi_QueryInterface')
    if profile=='vulkan' and not {'vkGetInstanceProcAddr','vkGetDeviceProcAddr'} <= names:
        raise ValueError('Vulkan profile requires both proc-address exports')
    for key,value in mappings.items():
        if value not in names or any(value in exports[i]['names'] for i in data_by_index): raise ValueError('Mapping target must be a code export')
        if profile=='nvapi':
            try: number = int(key,0)
            except (ValueError,TypeError): raise ValueError('NVAPI query key must be a numeric ID')
            if not 0<=number<=0xffffffff: raise ValueError('NVAPI ID outside uint32')
        elif not re.fullmatch(r'vk[A-Za-z0-9_]+', key): raise ValueError('Invalid Vulkan query name')
    if profile=='nvapi' and len({int(k,0) for k in mappings}) != len(mappings): raise ValueError('Duplicate numeric query IDs')
    protocols = config.get('dispatch', {})
    if not isinstance(protocols,dict) or set(protocols)-{'vulkan','nvapi'}: raise ValueError('Unknown dispatch protocol')
    protocols = dict(protocols)
    if 'nvapi_QueryInterface' in names: protocols.setdefault('nvapi',mappings if profile=='nvapi' else {})
    if {'vkGetInstanceProcAddr','vkGetDeviceProcAddr'} <= names:
        protocols.setdefault('vulkan',mappings if profile=='vulkan' else {name:name for name in names if name.startswith('vk')})
    for protocol, mapping in protocols.items():
        required_names={'nvapi_QueryInterface'} if protocol=='nvapi' else {'vkGetInstanceProcAddr','vkGetDeviceProcAddr'}
        if not required_names<=names or not isinstance(mapping,dict): raise ValueError('Missing/invalid dispatch entry contract')
        for key,target in mapping.items():
            if target not in names or any(target in exports[i]['names'] for i in data_by_index): raise ValueError('Dispatch target must be a code export')
            if protocol=='nvapi':
                try: number=int(key,0)
                except (ValueError,TypeError): raise ValueError('Numeric NVAPI ID required')
                if not 0<=number<=0xffffffff or target=='nvapi_QueryInterface': raise ValueError('Invalid NVAPI mapping')
            elif not re.fullmatch(r'vk[A-Za-z0-9_]+',key): raise ValueError('Invalid Vulkan query name')
        if protocol=='nvapi' and len({int(k,0) for k in mapping})!=len(mapping): raise ValueError('Duplicate numeric dispatch IDs')
    enabled = config.get('enableDefault', False)
    if not isinstance(enabled,bool): raise ValueError('enableDefault must be boolean')
    return {'schemaVersion':1,'profile':profile,'provider':provider,'activation':activation,
        'activateExports':triggers,'core':core_config,'plugins':plugins,'dataExports':data,
        'dataIndices':data_by_index,'queryMappings':mappings,'enableDefault':enabled,'forwarding':forwarding,
        'watchModules':watches,'requireCore':required,'dispatch':protocols}


def project(module, sources, asm=True):
    items = ''.join('<ClCompile Include="'+escape(s)+'"/>' for s in sources)
    if asm: items += '<MASM Include="forward.asm"/>'
    return '''<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
<ItemGroup Label="ProjectConfigurations"><ProjectConfiguration Include="Release|x64"><Configuration>Release</Configuration><Platform>x64</Platform></ProjectConfiguration><ProjectConfiguration Include="ClangRelease|x64"><Configuration>ClangRelease</Configuration><Platform>x64</Platform></ProjectConfiguration></ItemGroup>
<PropertyGroup Label="Globals"><WindowsTargetPlatformVersion>10.0</WindowsTargetPlatformVersion></PropertyGroup>
<Import Project="$(VCTargetsPath)\\Microsoft.Cpp.Default.props"/>
<PropertyGroup Label="Configuration"><ConfigurationType>DynamicLibrary</ConfigurationType><PlatformToolset Condition="'$(Configuration)'=='Release'">v143</PlatformToolset><PlatformToolset Condition="'$(Configuration)'=='ClangRelease'">ClangCL</PlatformToolset></PropertyGroup>
<Import Project="$(VCTargetsPath)\\Microsoft.Cpp.props"/>
<ImportGroup Label="ExtensionSettings"><Import Project="$(VCTargetsPath)\\BuildCustomizations\\masm.props"/></ImportGroup>
<PropertyGroup><OutDir>$(ProjectDir)bin\\$(Configuration)\\</OutDir><IntDir>$(ProjectDir)obj\\$(Configuration)\\</IntDir><TargetName>''' + escape(module[:-4]) + '''</TargetName></PropertyGroup>
<ItemDefinitionGroup><ClCompile><RuntimeLibrary>MultiThreaded</RuntimeLibrary><Optimization>MaxSpeed</Optimization><FunctionLevelLinking>true</FunctionLevelLinking><LanguageStandard>stdcpp17</LanguageStandard><ExceptionHandling>Sync</ExceptionHandling><WarningLevel>Level4</WarningLevel><TreatWarningAsError>true</TreatWarningAsError><AdditionalIncludeDirectories>$(ProjectDir)include;%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories><AdditionalOptions>/utf-8 %(AdditionalOptions)</AdditionalOptions></ClCompile><Link><ModuleDefinitionFile>exports.def</ModuleDefinitionFile><OptimizeReferences>true</OptimizeReferences><EnableCOMDATFolding>true</EnableCOMDATFolding></Link></ItemDefinitionGroup>
<ItemGroup>''' + items + '''</ItemGroup><Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets"/>
<ImportGroup Label="ExtensionTargets"><Import Project="$(VCTargetsPath)\\BuildCustomizations\\masm.targets"/></ImportGroup></Project>
'''


def forwarder_placeholders(names):
    """An inert AMD64 COFF section for LINK's ordinal-forwarder name lookup.

    Symbols never become export addresses: the compiled representation check
    requires each of these entries to be an actual PE forwarder. COFF avoids
    C++/MASM identifier restrictions on arbitrary decorated export names.
    """
    strings = bytearray(b'\0\0\0\0')
    symbols = bytearray()
    for name in sorted(set(names)):
        encoded=name.encode('ascii')
        if len(encoded)<=8: field=encoded.ljust(8,b'\0')
        else:
            field=struct.pack('<II',0,len(strings)); strings.extend(encoded+b'\0')
        symbols.extend(struct.pack('<8sIhHBB',field,0,1,0,2,0))
    struct.pack_into('<I',strings,0,len(strings))
    header=struct.pack('<HHIIIHH',0x8664,1,0,61,len(set(names)),0,0)
    section=struct.pack('<8sIIIIIIHHI',b'.data\0\0\0',0,0,1,60,0,0,0,0,0xc0100040)
    return header+section+b'\0'+symbols+strings


def generate(manifest, output, config, repo, generator_hash):
    output = Path(output)
    if output.exists() and any(output.iterdir()): raise ValueError('Output must be empty')
    exports = manifest['exports']; n = len(exports)
    names = {name:i for i,e in enumerate(exports) for name in e['names']}
    provider = config['provider']; data = config['dataIndices']
    canonical = {}
    indices = []
    for i,e in enumerate(exports):
        identity = ('f',e['forwarder']) if e.get('forwarder') else ('r',e.get('rva',e['ordinal']))
        indices.append(canonical.setdefault(identity,i))
    header = '#pragma once\n#include <windows.h>\n'
    header += '#define PB_EXPORT_COUNT %d\n#define PB_SELF_NAME %s\n' % (n,string(manifest['module'],True))
    header += '#define PB_PROVIDER_PATH %s\n#define PB_PROVIDER_SYSTEM %s\n#define PB_PROVIDER_HASH %s\n' % (
        string(provider['path'],True),'true' if provider['kind']=='system' else 'false',string(provider.get('sha256','')))
    candidates = [provider['path']] + provider.get('alternates', [])
    header += '#define PB_PROVIDER_COUNT %d\nstatic const wchar_t *const PB_PROVIDER_CANDIDATES[PB_PROVIDER_COUNT] = {%s};\n' % (
        len(candidates), ','.join(string(name,True) for name in candidates))
    header += '#define PB_CORE_PATH %s\n#define PB_CORE_HASH %s\n#define PB_ENABLE_DEFAULT %s\n#define PB_ACTIVATION %d\n' % (
        string(config['core']['path'],True),string(config['core']['sha256']),str(config['enableDefault']).lower(),ACTIVATION[config['activation']])
    header += '#define PB_REQUIRE_CORE %s\n#define PB_WATCH_COUNT %d\nstatic const wchar_t *const PB_WATCH_MODULES[%d] = {%s};\n' % (
        str(config['requireCore']).lower(),len(config['watchModules']),max(1,len(config['watchModules'])),
        ','.join(string(name,True) for name in config['watchModules']) or 'L""')
    # Export-trigger activation must still see a trigger after an earlier
    # untriggered call. Other modes can publish the reviewed ASM fast path.
    header += '#define PB_FAST_FORWARD %s\n' % str(config['activation']!='export').lower()
    lookups = [string(e['names'][0]) if e['names'] else 'MAKEINTRESOURCEA(%d)' % e['ordinal'] for e in exports]
    header += 'static const char *const PB_LOOKUPS[PB_EXPORT_COUNT] = {'+','.join(lookups)+'};\n'
    header += 'static const bool PB_ACTIVATE_EXPORT[PB_EXPORT_COUNT] = {'+','.join(str(bool(set(e['names'])&set(config['activateExports']))).lower() for e in exports)+'};\n'
    header += 'struct PBPlugin { const wchar_t *path; const char *hash; };\n'
    header += '#define PB_PLUGIN_COUNT %d\nstatic const PBPlugin PB_PLUGINS[%d] = {%s};\n' % (
        len(config['plugins']),max(1,len(config['plugins'])),','.join('{%s,%s}'%(string(p['path'],True),string(p.get('sha256',''))) for p in config['plugins']) or '{L"",""}')
    assembly = (repo/'bootstrap/aftermath_proxy/aftermath_forward.asm').read_text(encoding='utf-8').split('.code',1)[0]
    assembly += '.code\n'+'\n'.join('AFTERMATH_FWD ProxyExport%d, %d, %d'%(i,i,i*8) for i in range(n))+'\nend\n'
    definitions = ['LIBRARY '+manifest['module'],'EXPORTS']
    import_definitions = ['LIBRARY '+manifest['module'],'EXPORTS']
    query_names = (['nvapi_QueryInterface'] if 'nvapi' in config['dispatch'] else []) + (['vkGetInstanceProcAddr','vkGetDeviceProcAddr'] if 'vulkan' in config['dispatch'] else [])
    query_indices = {names[k] for k in query_names if k in names}
    declarations = []
    representation = []
    forwarded_names = []
    for i,e in enumerate(exports):
        idx = indices[i]
        if idx in data or config['forwarding']=='linker':
            # Use a canonical ordinal for aliases; the loader resolves DATA to
            # original storage rather than manufacturing a copied variable.
            target = PureWindowsPath(provider['path']).stem + '.#' + str(exports[idx]['ordinal'])
        elif idx in query_indices: target = 'PBQuery'+str(idx)
        else: target = 'ProxyExport'+str(idx)
        representation.append({'ordinal':e['ordinal'],'kind':'forwarder' if idx in data or config['forwarding']=='linker' else 'code',
            'forwarder':target if idx in data or config['forwarding']=='linker' else None})
        for name in e['names'] or ['Ordinal_'+str(e['ordinal'])]:
            definitions.append('  %s=%s @%d%s'%(name,target,e['ordinal'],' NONAME' if not e['names'] else ''))
            if idx in data or config['forwarding']=='linker': forwarded_names.append(name)
            import_definitions.append('  %s @%d%s%s'%(name,e['ordinal'],' NONAME' if not e['names'] else '', ' DATA' if idx in data else ''))
        if idx not in data: declarations.append('extern "C" void ProxyExport%d();'%idx)
    occupied = {e['ordinal'] for e in exports}
    free = (ordinal for ordinal in range(1,65536) if ordinal not in occupied)
    for control in CONTROL:
        ordinal=next(free,None)
        if ordinal is None: raise ValueError('No ordinal slots for route controls')
        definitions.append('  '+control+' @'+str(ordinal)); import_definitions.append('  '+control+' @'+str(ordinal))
    dispatch = '#include <windows.h>\n#include <cstdint>\n#include <cstring>\n'+ '\n'.join(sorted(set(declarations)))+'\nextern "C" intptr_t ResolveAftermathExport(int);\n'
    if 'vulkan' in config['dispatch']:
        mappings = config['dispatch']['vulkan']
        for name in ('vkGetInstanceProcAddr','vkGetDeviceProcAddr'):
            i = names[name]
            dispatch += 'extern "C" FARPROC WINAPI PBQuery%d(void *handle, const char *name) {\n'%i
            dispatch += 'using Query = FARPROC (WINAPI *)(void *,const char *); auto query = reinterpret_cast<Query>(ResolveAftermathExport(%d));\n'%i
            dispatch += 'FARPROC result = query(handle,name); if(!result || !name) return result;\n'
            for key,target in sorted(mappings.items()):
                t = indices[names[target]]
                dest = 'PBQuery'+str(t) if t in query_indices else 'ProxyExport'+str(t)
                dispatch += 'if(!strcmp(name,%s) && result == reinterpret_cast<FARPROC>(ResolveAftermathExport(%d))) return reinterpret_cast<FARPROC>(%s);\n'%(string(key),t,dest)
            dispatch += 'return result; }\n'
        # Query functions may refer to each other.
        dispatch = dispatch.replace('#include <cstring>\n','#include <cstring>\n'+''.join('extern "C" FARPROC WINAPI PBQuery%d(void *,const char *);\n'%names[name] for name in ('vkGetInstanceProcAddr','vkGetDeviceProcAddr')))
    if 'nvapi' in config['dispatch']:
        mappings = config['dispatch']['nvapi']
        i=names['nvapi_QueryInterface']
        dispatch=dispatch.replace('#include <cstdint>\n','#include <cstdint>\nextern "C" FARPROC __cdecl PBQuery%d(uint32_t);\n'%i)
        dispatch += 'extern "C" FARPROC __cdecl PBQuery%d(uint32_t id) { using Query = FARPROC (__cdecl *)(uint32_t);\n'%i
        dispatch += 'auto query = reinterpret_cast<Query>(ResolveAftermathExport(%d)); FARPROC result = query(id); if(!result) return result;\n'%i
        for key,target in sorted(mappings.items()):
            t=indices[names[target]]
            if t==i: raise ValueError('NVAPI query cannot map itself')
            dispatch += 'if(id == %du && result == reinterpret_cast<FARPROC>(ResolveAftermathExport(%d))) return reinterpret_cast<FARPROC>(ProxyExport%d);\n'%(int(key,0),t,t)
        dispatch += 'return result; }\n'
    runtime = (ROOT/'templates/route_runtime.cpp').read_text(encoding='utf-8')
    files = {'runtime.cpp':runtime,'dispatch.cpp':dispatch,'include/route_config.h':header,'forward.asm':assembly,
        'exports.def':'\n'.join(definitions)+'\n','proxy.vcxproj':project(manifest['module'],['runtime.cpp','dispatch.cpp'])}
    if forwarded_names:
        files['forwarder-placeholders.obj']=forwarder_placeholders(forwarded_names)
        files['proxy.vcxproj']=files['proxy.vcxproj'].replace('<Link>',
            '<Link><AdditionalDependencies>$(ProjectDir)forwarder-placeholders.obj;%(AdditionalDependencies)</AdditionalDependencies>')
    if data:
        # LINK's DATA + external forwarder handling requires imported data
        # symbols. The image itself has no DATA bit: emit valid PE forwarders,
        # then create the correctly typed client import library separately.
        files['imports.def']='\n'.join(import_definitions)+'\n'
        event='<PostBuildEvent><Command>&quot;$(VCToolsInstallDir)bin\\Hostx64\\x64\\lib.exe&quot; /nologo /machine:x64 /def:&quot;$(ProjectDir)imports.def&quot; /out:&quot;$(OutDir)$(TargetName).lib&quot;</Command></PostBuildEvent>'
        files['proxy.vcxproj']=files['proxy.vcxproj'].replace('</ItemDefinitionGroup>',event+'</ItemDefinitionGroup>')
    # Windows proc-address APIs intentionally traffic in opaque function
    # addresses. Specific signatures are exercised by native ABI tests.
    files['proxy.vcxproj']=files['proxy.vcxproj'].replace('</ClCompile>',
        '<AdditionalOptions Condition="\'$(Configuration)\'==\'ClangRelease\'">/utf-8 /clang:-Wno-cast-function-type-mismatch %(AdditionalOptions)</AdditionalOptions></ClCompile>')
    files['include/api/app/renderdoc_app.h']=(repo/'renderdoc/api/app/renderdoc_app.h').read_text(encoding='utf-8')
    output.mkdir(parents=True,exist_ok=True)
    for name,source in files.items():
        path=output/name; path.parent.mkdir(parents=True,exist_ok=True)
        if isinstance(source,bytes): path.write_bytes(source)
        else: path.write_text(source,encoding='utf-8',newline='\n')
    clean_config = {k:v for k,v in config.items() if k!='dataIndices'}
    lock = dict(manifest,template='routes',original=provider['path'],generatorVersion=2,
        generatorSHA256=generator_hash,routeConfig=clean_config,additionalExports=CONTROL,
        representations=representation,
        dataForwarders=[{'ordinal':exports[i]['ordinal'],'type':spec['type']} for i,spec in data.items()],
        generatedFiles={name:hashlib.sha256(source if isinstance(source,bytes) else source.encode()).hexdigest() for name,source in files.items()},
        captureGuarantee='Owned forwarding/route tests only; per-application capture evidence required')
    (output/'exports.json').write_text(json.dumps(lock,indent=2),encoding='utf-8')
    return lock


def verify(original, proxy, lock, legacy_verify):
    extra = set(lock.get('additionalExports',[]))
    filtered = dict(proxy,exports=[e for e in proxy['exports'] if not set(e['names']) <= extra or not e['names']])
    result = legacy_verify(original,filtered)
    original_data = {e['ordinal'] for e in original['exports'] if e['kind']=='data_or_unknown'}
    proxy_data = {e['ordinal'] for e in filtered['exports'] if e['kind']=='forwarder'}
    extra_found = {n for e in proxy['exports'] for n in e['names'] if n in extra}
    by_ordinal = {e['ordinal']:e for e in filtered['exports']}
    representation_ok = all(expected['ordinal'] in by_ordinal and
        by_ordinal[expected['ordinal']]['kind']==expected['kind'] and
        by_ordinal[expected['ordinal']].get('forwarder')==expected['forwarder'] for expected in lock.get('representations',[]))
    result['matches'] = result['matches'] and original_data <= proxy_data and extra_found == extra and representation_ok
    result['representationsVerified']=representation_ok
    result['additionalExports'] = sorted(extra_found)
    result['dataForwarding'] = lock.get('dataForwarders',[])
    result['scope'] += '; declared route controls and DATA loader forwarders'
    return result


def verify_data_imports(path, original, lock):
    raw=Path(path).read_bytes()
    if not raw.startswith(b'!<arch>\n'): raise ValueError('Invalid COFF import archive')
    position=8; imports={}
    while position<len(raw):
        if position+60>len(raw) or raw[position+58:position+60]!=b'`\n': raise ValueError('Truncated COFF archive')
        size=int(raw[position+48:position+58].decode('ascii').strip())
        data=raw[position+60:position+60+size]
        if len(data)!=size: raise ValueError('Truncated COFF member')
        if len(data)>=20 and data[:4]==b'\0\0\xff\xff':
            machine=struct.unpack_from('<H',data,6)[0]
            flags=struct.unpack_from('<H',data,18)[0]
            name=data[20:].split(b'\0',1)[0].decode('ascii')
            if machine!=0x8664: raise ValueError('Import library architecture mismatch')
            imports[name]=flags&3
        position+=60+size+(size&1)
    data_ordinals={item['ordinal'] for item in lock.get('dataForwarders',[])}
    required={name for e in original['exports'] if e['ordinal'] in data_ordinals for name in e['names'] or ['Ordinal_'+str(e['ordinal'])]}
    if any(imports.get(name)!=1 for name in required): raise ValueError('DATA import library type mismatch')
    return {'typedDataImportsVerified':True,'dataNames':sorted(required),'sha256':sha(path)}
