"""Proxy Builder 0.4.1: inspect, generate, compile and verify x64 proxy DLLs.

Supports provider chains, activation gates, typed DATA forwarders, NVAPI/Vulkan
dispatch and ASI/JVM/OpenXR/Vulkan Layer hosts. Real capture needs target proof.
"""
import argparse
import hashlib
import json
import re
import struct
import os
import shutil
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape
import routes
import hosts

BASE = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[2]
if not (REPO / 'bootstrap' / 'aftermath_proxy' / 'aftermath_forward.cpp').is_file():
    REPO = BASE / 'runtime-templates'


def inspect(path):
    raw = Path(path).read_bytes()
    def unpack(fmt, offset):
        size = struct.calcsize(fmt)
        if offset < 0 or offset + size > len(raw):
            raise ValueError("Truncated PE structure")
        return struct.unpack_from(fmt, raw, offset)
    if raw[:2] != b"MZ":
        raise ValueError("Missing DOS signature")
    pe = unpack("<I", 0x3c)[0]
    if raw[pe:pe + 4] != b"PE\0\0":
        raise ValueError("Missing PE signature")
    machine, count = unpack("<HH", pe + 4)
    optional_size = unpack("<H", pe + 20)[0]
    optional = pe + 24
    magic = unpack("<H", optional)[0]
    directory = 112 if magic == 0x20b else 96 if magic == 0x10b else None
    if directory is None or optional_size < directory + 8:
        raise ValueError("Unsupported/truncated optional header")
    export_rva, export_size = unpack("<II", optional + directory)
    headers = unpack("<I", optional + 60)[0]
    sections = []
    for i in range(count):
        off = optional + optional_size + 40 * i
        name, virtual_size, rva, size, pointer = unpack("<8sIIII", off)
        characteristics = unpack("<I", off + 36)[0]
        sections.append({"name": name.split(b"\0")[0].decode("ascii", "replace"), "rva": rva,
                         "virtualSize": virtual_size, "size": size, "pointer": pointer,
                         "executable": bool(characteristics & 0x20000000)})
    def location(rva, size=1):
        if rva < headers and rva + size <= min(headers, len(raw)):
            return rva
        for section in sections:
            delta = rva - section["rva"]
            if 0 <= delta and delta + size <= section["size"]:
                off = section["pointer"] + delta
                if off + size <= len(raw):
                    return off
        raise ValueError("RVA has no bounded file-backed range: %x" % rva)
    def string(rva):
        # Every byte stays inside its file-backed section (not an arbitrary
        # search through the remainder of the file).
        data = bytearray()
        for i in range(4096):
            c = raw[location(rva + i)]
            if not c:
                return data.decode("ascii")
            data.append(c)
        raise ValueError("Unterminated PE string")
    if not export_rva or export_size < 40:
        raise ValueError("No export table")
    fields = unpack("<IIHHIIIIIII", location(export_rva, 40))
    _, _, _, _, name_rva, base, functions, names, eat, name_table, ordinal_table = fields
    if functions > 65536 or names > 65536:
        raise ValueError("Excessive export count")
    by_index = {}
    for i in range(names):
        ordinal_index = unpack("<H", location(ordinal_table + i * 2, 2))[0]
        if ordinal_index >= functions:
            raise ValueError("Name ordinal outside EAT")
        name = string(unpack("<I", location(name_table + i * 4, 4))[0])
        by_index.setdefault(ordinal_index, []).append(name)
    exports = []
    for index in range(functions):
        address = unpack("<I", location(eat + index * 4, 4))[0]
        if not address:
            if index in by_index:
                raise ValueError("Named export has null EAT entry")
            continue
        forwarded = export_rva <= address < export_rva + export_size
        section = next((s for s in sections if s["rva"] <= address < s["rva"] + max(s["size"], s["virtualSize"])), None)
        backed = 0
        if section:
            delta = address - section['rva']
            backed = max(0, min(section['size'] - delta, len(raw) - section['pointer'] - delta))
        exports.append({"ordinal": base + index, "names": sorted(by_index.get(index, [])), "rva": address,
                        "fileBackedBytes": backed,
                        "forwarder": string(address) if forwarded else None,
                        "kind": "forwarder" if forwarded else "code" if section and section["executable"] else "data_or_unknown"})
    if len({name for e in exports for name in e["names"]}) != names:
        raise ValueError("Duplicate export names")
    return {"schemaVersion": 1, "sha256": hashlib.sha256(raw).hexdigest(), "machine": machine,
            "architecture": {0x8664: "x64", 0x14c: "x86", 0xaa64: "arm64"}.get(machine, "unknown"),
            "module": string(name_rva), "exports": exports}


def replace_once(pattern, replacement, source):
    result, count = re.subn(pattern, lambda m: replacement, source, count=1, flags=re.S)
    if count != 1:
        raise ValueError("Bootstrap template changed; review pattern " + pattern)
    return result


def generate(manifest, output, template, original=None):
    exports = manifest["exports"]
    if manifest["architecture"] != "x64" or not exports:
        raise ValueError("Generation requires nonempty x64 exports")
    if any(e["kind"] == "data_or_unknown" for e in exports):
        raise ValueError("Data/unknown export cannot use a function jump stub")
    if any(not 1 <= e["ordinal"] <= 65535 for e in exports):
        raise ValueError("Ordinal outside Win32 GetProcAddress range")
    if any(not re.fullmatch(r"[A-Za-z_?@$][A-Za-z0-9_?@$]*", n) for e in exports for n in e["names"]):
        raise ValueError("Export name cannot be represented safely in DEF")
    module = manifest["module"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.dll", module, re.I):
        raise ValueError("Module must be a plain DLL basename")
    n = len(exports)
    # Use the project's reviewed runtime, not a second generic loader.
    if template == "app-local":
        original = original or module[:-4] + "_orig.dll"
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.dll", original, re.I) or original.lower() == module.lower():
            raise ValueError("Original must be a different plain DLL basename")
        folder = REPO / "bootstrap" / "aftermath_proxy"
        runtime = (folder / "aftermath_forward.cpp").read_text(encoding="utf-8")
        runtime = runtime.replace("[43]", "[%d]" % n).replace("ExportCount = 43", "ExportCount = %d" % n)
        runtime = replace_once(r'const wchar_t \*const OriginalNames\[\] = \{.*?\};', 'const wchar_t *const OriginalNames[] = {L' + json.dumps(original) + '};', runtime)
        lookups = ',\n'.join('    MAKEINTRESOURCEA(%d)' % e["ordinal"] for e in exports)
        runtime = replace_once(r'const char \*const ExportNames\[ExportCount\] = \{.*?\};', 'const char *const ExportNames[ExportCount] = {\n' + lookups + '\n};', runtime)
        dllmain = (folder / "dllmain.cpp").read_text(encoding="utf-8")
        asm = (folder / "aftermath_forward.asm").read_text(encoding="utf-8").split(".code", 1)[0]
        asm += '.code\n' + '\n'.join('AFTERMATH_FWD ProxyExport%d, %d, %d' % (i, i, i * 8) for i in range(n)) + '\nend\n'
    elif template == "system":
        stem = module[:-4].lower()
        if stem not in ("dxgi", "d3d11", "d3d12"):
            raise ValueError("System template supports only existing DXGI/D3D11/D3D12 runtimes")
        folder = REPO / "bootstrap" / (stem + "_proxy")
        runtime = (folder / (stem + "_proxy.cpp")).read_text(encoding="utf-8")
        prefix = stem.upper()
        old_names = re.search(r'const char \*const ExportNames\[.*?\] = \{(.*?)\};', runtime, re.S)
        required = set(re.findall(r'"([^"]+)"', old_names.group(1)))
        actual = {name for e in exports for name in e["names"]}
        if not required <= actual:
            raise ValueError("Runtime baseline exports missing: " + ', '.join(sorted(required - actual)))
        if any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name) for name in actual):
            raise ValueError("System runtime enum requires identifier export names")
        runtime = re.sub(r'ProxyExportTargets\[\d+\]', 'ProxyExportTargets[%d]' % n, runtime)
        entries = []
        for i, e in enumerate(exports):
            entries.extend('  %s = %d,' % (name, i) for name in e["names"])
        entries.append('  %sExportCount = %d,' % (prefix, n))
        runtime = replace_once(r'enum ' + prefix + r'Export : uint32_t\s*\{.*?\};', 'enum %sExport : uint32_t\n{\n%s\n};' % (prefix, '\n'.join(entries)), runtime)
        runtime = re.sub(prefix + r'ExportCount == \d+', prefix + 'ExportCount == %d' % n, runtime)
        labels = ',\n'.join('    ' + json.dumps(e["names"][0] if e["names"] else 'ordinal %d' % e["ordinal"]) for e in exports)
        lookups = ',\n'.join('    ' + (json.dumps(e["names"][0]) if e["names"] else 'MAKEINTRESOURCEA(%d)' % e["ordinal"]) for e in exports)
        table = 'const char *const ExportNames[%sExportCount] = {\n%s\n};\nconst char *const ExportLookups[%sExportCount] = {\n%s\n};' % (prefix, labels, prefix, lookups)
        runtime = replace_once(r'const char \*const ExportNames\[.*?\] = \{.*?\};', table, runtime)
        runtime = runtime.replace('Real%s, ExportNames[i])' % prefix, 'Real%s, ExportLookups[i])' % prefix)
        dllmain = None
        asm_source = (folder / (stem + '_proxy_exports_x64.asm')).read_text(encoding="utf-8")
        macro = stem.upper() + '_EXPORT_STUB'
        asm = asm_source.split(macro + ' ProxyExport0', 1)[0]
        asm += '\n'.join('%s ProxyExport%d, %d' % (macro, i, i) for i in range(n)) + '\nend\n'
    else:
        raise ValueError("Unknown template")
    definitions = ['LIBRARY ' + module, 'EXPORTS']
    alias_targets = {}
    for i, e in enumerate(exports):
        identity = ('forwarder', e['forwarder']) if e.get('forwarder') else ('rva', e.get('rva', e['ordinal']))
        target_index = alias_targets.setdefault(identity, i)
        names = e["names"] or ['Ordinal_%d' % e["ordinal"]]
        for name in names:
            definitions.append('  %s=ProxyExport%d @%d%s' % (name, target_index, e["ordinal"], ' NONAME' if not e["names"] else ''))
    project = '''<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
<ItemGroup Label="ProjectConfigurations"><ProjectConfiguration Include="Release|x64"><Configuration>Release</Configuration><Platform>x64</Platform></ProjectConfiguration><ProjectConfiguration Include="ClangRelease|x64"><Configuration>ClangRelease</Configuration><Platform>x64</Platform></ProjectConfiguration></ItemGroup>
<PropertyGroup Label="Globals"><WindowsTargetPlatformVersion>10.0</WindowsTargetPlatformVersion></PropertyGroup>
<Import Project="$(VCTargetsPath)\\Microsoft.Cpp.Default.props"/><PropertyGroup Label="Configuration"><ConfigurationType>DynamicLibrary</ConfigurationType><PlatformToolset Condition="'$(Configuration)'=='Release'">v143</PlatformToolset><PlatformToolset Condition="'$(Configuration)'=='ClangRelease'">ClangCL</PlatformToolset></PropertyGroup><Import Project="$(VCTargetsPath)\\Microsoft.Cpp.props"/>
<ImportGroup Label="ExtensionSettings"><Import Project="$(VCTargetsPath)\\BuildCustomizations\\masm.props"/></ImportGroup>
<PropertyGroup><OutDir>$(ProjectDir)bin\\$(Configuration)\\</OutDir><IntDir>$(ProjectDir)obj\\$(Configuration)\\</IntDir><TargetName>MODULE</TargetName></PropertyGroup>
<ItemDefinitionGroup><ClCompile><RuntimeLibrary>MultiThreaded</RuntimeLibrary><Optimization>MaxSpeed</Optimization><WarningLevel>Level4</WarningLevel><TreatWarningAsError>true</TreatWarningAsError><AdditionalIncludeDirectories>INCLUDE;%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories><AdditionalOptions>/utf-8 %(AdditionalOptions)</AdditionalOptions></ClCompile><Link><ModuleDefinitionFile>exports.def</ModuleDefinitionFile></Link></ItemDefinitionGroup>
<ItemGroup><ClCompile Include="runtime.cpp"/>DLLMAIN<MASM Include="forward.asm"/></ItemGroup>
<Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets"/><ImportGroup Label="ExtensionTargets"><Import Project="$(VCTargetsPath)\\BuildCustomizations\\masm.targets"/></ImportGroup></Project>'''
    project = project.replace('MODULE', escape(module[:-4])).replace('INCLUDE;', '$(ProjectDir)include;').replace('DLLMAIN', '<ClCompile Include="dllmain.cpp"/>' if dllmain else '')
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output must be empty; generated files never overwrite an existing build")
    output.mkdir(parents=True, exist_ok=True)
    files = {"runtime.cpp": runtime, "forward.asm": asm, "exports.def": '\n'.join(definitions) + '\n', "proxy.vcxproj": project}
    for relative in ('api/app/renderdoc_app.h', 'generated/product_identity.h'):
        files['include/' + relative] = (REPO / 'renderdoc' / relative).read_text(encoding='utf-8')
    if dllmain:
        files["dllmain.cpp"] = dllmain
    for name, data in files.items():
        (output / name).parent.mkdir(parents=True, exist_ok=True)
        (output / name).write_text(data, encoding="utf-8", newline="\n")
    lock = dict(manifest, template=template, original=original,
                generatorVersion=1, templateSHA256=hashlib.sha256(runtime.encode()).hexdigest(),
                generatorSHA256=digest(sys.executable if getattr(sys, 'frozen', False) else __file__),
                generatedFiles={name: hashlib.sha256(data.encode('utf-8')).hexdigest() for name, data in files.items()},
                captureGuarantee="Generated export contract only; per-application early-hook/capture proof required")
    (output / 'exports.json').write_text(json.dumps(lock, indent=2), encoding="utf-8")
    return lock


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def find_msbuild(explicit=None):
    if explicit:
        path = Path(explicit).resolve(strict=True)
    else:
        locator = Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
        if locator.is_file():
            found = subprocess.check_output([str(locator), '-latest', '-products', '*', '-requires',
                'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-find', 'MSBuild/Current/Bin/MSBuild.exe'], text=True).strip().splitlines()
            path = Path(found[0]) if found else None
        else:
            found = shutil.which('MSBuild.exe')
            path = Path(found) if found else None
    if not path or not path.is_file():
        raise ValueError('Visual Studio C++/MSBuild not found; install the C++ workload or pass --msbuild')
    return path


def build_dll(dll, output, template='auto', original=None, toolchain='MSVC', msbuild=None, copy_original=False,
              route='auto', core=None, enable_core=False, profile=None, config=None):
    source = Path(dll).resolve(strict=True)
    output = Path(output).resolve()
    compiler = find_msbuild(msbuild)
    manifest = inspect(source)
    if template == 'auto':
        template = 'system' if manifest['module'].lower() in ('dxgi.dll', 'd3d11.dll', 'd3d12.dll') else 'app-local'
    if route == 'auto':
        route = 'system-dll' if template == 'system' else 'app-local'
    if (route == 'system-dll') != (template == 'system'):
        raise ValueError('Selected route does not match the runtime template')
    if enable_core and not core:
        raise ValueError('--enable-core requires --core')
    core_path = Path(core).resolve(strict=True) if core else None
    core_hash = None
    if core_path:
        if manifest['module'].lower() == 'dgcore.dll' or (original or manifest['module'][:-4] + '_orig.dll').lower() == 'dgcore.dll':
            raise ValueError('Core output name collides with the proxy or renamed original')
        core_manifest = inspect(core_path)
        if core_manifest['architecture'] != 'x64' or not any('DCOMP_GetAPI' in e['names'] and e['kind'] == 'code' for e in core_manifest['exports']):
            raise ValueError('Core must be an x64 DLL with the DCOMP_GetAPI entry')
        core_hash = core_manifest['sha256']
    if copy_original and template != 'app-local' and not (profile or config is not None):
        raise ValueError('--copy-original is only valid for app-local')
    route_config = routes.config_for(manifest, profile or 'auto', config, original, core,
                                    bootstrap_route=route=='streamline-bootstrap') if profile or config is not None else None
    if route_config:
        provider = route_config['provider']
        if copy_original and provider['kind'] != 'sibling':
            raise ValueError('--copy-original requires a sibling provider')
        # Resolve declared absolute providers without loading their code. Their
        # names/ordinal-only entries must satisfy the original export contract.
        if provider['kind'] == 'absolute':
            candidate = inspect(provider['path'])
            if candidate['architecture'] != 'x64': raise ValueError('Provider architecture mismatch')
            target_names = {n for e in candidate['exports'] for n in e['names']}
            target_ordinals = {e['ordinal'] for e in candidate['exports']}
            if any(not set(e['names']) <= target_names if e['names'] else e['ordinal'] not in target_ordinals for e in manifest['exports']):
                raise ValueError('Provider does not satisfy the input contract')
            if provider.get('sha256') and provider['sha256'] != candidate['sha256']:
                raise ValueError('Provider hash mismatch')
            provider['sha256'] = candidate['sha256']
            if Path(provider['path']).resolve() == output / 'bin' / ('ClangRelease' if toolchain == 'ClangCL' else 'Release') / manifest['module']:
                raise ValueError('Provider output recursion')
        lock = routes.generate(manifest, output, route_config, REPO, digest(sys.executable if getattr(sys,'frozen',False) else __file__))
    else:
        lock = generate(manifest, output, template, original)
    config = 'ClangRelease' if toolchain == 'ClangCL' else 'Release'
    command = [str(compiler), str(output / 'proxy.vcxproj'), '/t:Build', '/m:4', '/v:minimal', '/nologo',
        '/p:Configuration=' + config, '/p:Platform=x64', '/p:ImportDirectoryBuildProps=false', '/p:ImportDirectoryBuildTargets=false']
    log = output / 'build.log'
    receipt = {'schemaVersion': 1, 'status': 'building', 'source': str(source), 'sourceSHA256': manifest['sha256'],
        'template': template, 'original': lock['original'], 'toolchain': toolchain, 'msbuild': str(compiler),
        'msbuildSHA256': digest(compiler), 'command': command, 'buildLog': str(log), 'generatedFiles': lock['generatedFiles']}
    receipt['route'] = {'selected': route, 'exportEntry': 'Physical x64 export stubs support imports, GetProcAddress and raw EAT address lookup',
        'coreActivation': 'Worker thread after loader unlock' if template == 'app-local' else 'Existing system proxy first-call handshake',
        'captureStatus': 'unverified', 'streamline': 'Core inline/provider routing and object creation order require separate runtime evidence' if route == 'streamline-bootstrap' else None}
    if route_config:
        receipt['route'] = dict(lock['routeConfig'],captureStatus='unverified',
            selected=route,activationSelection='explicit-config' if config and 'activation' in config else
                routes.activation_default(manifest,route_config['profile'],route=='streamline-bootstrap')[1],
            dataEntry='Loader-resolved DATA forwarders; raw EAT callers must implement forwarder resolution',
            exportEntry='Physical x64 stubs' if route_config['forwarding']=='physical' else 'PE loader forwarders')
    def save():
        (output / 'build-result.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    save()
    try:
        with log.open('wb') as stream:
            result = subprocess.run(command, cwd=str(output), stdout=stream, stderr=subprocess.STDOUT)
        receipt['exitCode'] = result.returncode
        if result.returncode:
            raise ValueError('MSBuild failed; inspect ' + str(log))
        if digest(source) != manifest['sha256']:
            raise ValueError('Original DLL changed during compilation; build not accepted')
        for name, expected in lock['generatedFiles'].items():
            if digest(output / name) != expected:
                raise ValueError('Generated source changed during compilation: ' + name)
        binary = output / 'bin' / config / manifest['module']
        verification = routes.verify(manifest, inspect(binary), lock, verify) if route_config else verify(manifest, inspect(binary))
        if not verification['matches']:
            raise ValueError('Compiled export contract differs from input DLL')
        receipt.update(verification=verification, dll=str(binary), dllSHA256=digest(binary))
        if route_config and lock.get('dataForwarders'):
            receipt['importLibrary']=routes.verify_data_imports(binary.with_suffix('.lib'),manifest,lock)
        if copy_original:
            sibling = binary.parent / lock['original']
            shutil.copyfile(source, sibling)
            if digest(sibling) != manifest['sha256']:
                raise ValueError('Renamed original copy hash mismatch')
            receipt['originalCopy'] = {'path': str(sibling), 'sha256': manifest['sha256']}
        if core_path:
            core_copy = binary.parent / 'dgcore.dll'
            shutil.copyfile(core_path, core_copy)
            if digest(core_path) != core_hash or digest(core_copy) != core_hash:
                raise ValueError('Core changed during build/copy')
            receipt['coreCopy'] = {'path': str(core_copy), 'sha256': core_hash}
        if enable_core:
            (binary.parent / 'dgcore.enable').write_bytes(b'')
        receipt['activationRequested'] = enable_core
        receipt['status'] = 'verified'
        receipt['scope'] = 'Compiled export contract only; application runtime validation remains required'
    except (ValueError, OSError) as exc:
        receipt.update(status='failed', error=str(exc))
        raise
    finally:
        save()
    return receipt


def verify(original, proxy):
    def contract(m):
        return [(e["ordinal"], e["names"]) for e in m["exports"]]
    original_groups, proxy_groups = {}, {}
    for source, groups in ((original, original_groups), (proxy, proxy_groups)):
        for e in source['exports']:
            identity = ('forwarder', e['forwarder']) if e.get('forwarder') else ('rva', e.get('rva', e['ordinal']))
            groups.setdefault(identity, []).append(e['ordinal'])
    aliases = lambda groups: sorted(sorted(v) for v in groups.values() if len(v) > 1)
    ok = original["architecture"] == proxy["architecture"] and contract(original) == contract(proxy) and aliases(original_groups) == aliases(proxy_groups)
    return {"matches": ok, "originalSHA256": original["sha256"], "proxySHA256": proxy["sha256"],
            "originalContract": contract(original), "proxyContract": contract(proxy),
            "originalAliasGroups": aliases(original_groups), "proxyAliasGroups": aliases(proxy_groups),
            "scope": "Names, ordinals, RVA/forwarder alias groups and architecture; absolute jump RVAs differ"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    a = sub.add_parser('inspect'); a.add_argument('dll')
    a = sub.add_parser('generate'); a.add_argument('dll'); a.add_argument('--output', required=True); a.add_argument('--template', choices=('system', 'app-local'), required=True); a.add_argument('--original')
    a.add_argument('--profile', choices=('auto',*routes.PROFILES)); a.add_argument('--config')
    a = sub.add_parser('verify'); a.add_argument('dll'); a.add_argument('proxy')
    a.add_argument('--lock', help='exports.json for declared route controls/DATA representation')
    sub.add_parser('profiles', help='List native profiles and host adapters')
    a = sub.add_parser('host', help='Compile a local ASI/JVM/OpenXR/Vulkan-layer adapter')
    a.add_argument('kind', choices=hosts.KINDS); a.add_argument('--output', required=True); a.add_argument('--core', required=True)
    a.add_argument('--config'); a.add_argument('--msbuild'); a.add_argument('--jdk')
    a.add_argument('--toolchain', choices=('MSVC','ClangCL'), default='MSVC')
    a = sub.add_parser('build', help='Inspect, generate, compile and verify a proxy DLL in one command')
    a.add_argument('dll'); a.add_argument('--output', required=True)
    a.add_argument('--template', choices=('auto', 'system', 'app-local'), default='auto')
    a.add_argument('--original'); a.add_argument('--toolchain', choices=('MSVC', 'ClangCL'), default='MSVC')
    a.add_argument('--msbuild'); a.add_argument('--copy-original', action='store_true')
    a.add_argument('--route', choices=('auto', 'system-dll', 'app-local', 'streamline-bootstrap'), default='auto')
    a.add_argument('--core', help='Copy a verified x64 DCOMP_GetAPI Core beside the generated DLL')
    a.add_argument('--enable-core', action='store_true', help='Create dgcore.enable in the output folder')
    a.add_argument('--profile', choices=('auto',*routes.PROFILES), default='auto', help='Unified route runtime (default auto)')
    a.add_argument('--config', help='Strict route config JSON (provider/activation/plugins/DATA/query mappings)')
    args = p.parse_args()
    try:
        config = json.loads(Path(args.config).read_text(encoding='utf-8-sig')) if getattr(args,'config',None) else None
        if args.command == 'build':
            result = build_dll(args.dll, args.output, args.template, args.original, args.toolchain, args.msbuild, args.copy_original, args.route, args.core, args.enable_core, args.profile, config)
        elif args.command == 'profiles':
            result = {'native':routes.PROFILES,'activation':list(routes.ACTIVATION),'hosts':['asi','jvm','openxr','vulkan-layer']}
        elif args.command == 'host':
            result = hosts.build(sys.modules[__name__], args.kind, args.output, args.core, args.toolchain, args.msbuild, config, args.jdk)
        else:
            manifest = inspect(args.dll)
            if args.command == 'inspect': result = manifest
            elif args.command == 'generate':
                result = routes.generate(manifest, args.output, routes.config_for(manifest,args.profile or 'auto',config,args.original),REPO,digest(sys.executable if getattr(sys,'frozen',False) else __file__)) if args.profile or config is not None else generate(manifest,args.output,args.template,args.original)
            else:
                lock_path = Path(args.lock) if args.lock else Path(args.proxy).resolve().parents[2] / 'exports.json'
                lock = json.loads(lock_path.read_text(encoding='utf-8-sig')) if lock_path.is_file() else None
                result = routes.verify(manifest,inspect(args.proxy),lock,verify) if lock and lock.get('generatorVersion')==2 else verify(manifest,inspect(args.proxy))
        print(json.dumps(result, indent=2))
        return 1 if result.get('matches') is False else 0
    except (ValueError, OSError, UnicodeError, struct.error, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
