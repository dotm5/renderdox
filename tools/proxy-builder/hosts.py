"""Build process-local host adapters using the same route runtime."""
import json
import os
import shutil
import subprocess
from pathlib import Path
import routes

KINDS = ('asi','jvm','openxr','vulkan-layer')
VULKAN_EXPORTS = ('VK_LAYER_DCOMP_CaptureGetInstanceProcAddr',
    'VK_LAYER_DCOMP_CaptureGetDeviceProcAddr','VK_LAYER_DCOMP_CaptureNegotiateLoaderLayerInterfaceVersion',
    'VK_LAYER_DCOMP_CaptureEnumerateInstanceExtensionProperties')


def build(builder, kind, output, core, toolchain='MSVC', msbuild=None, config=None, jdk=None):
    if kind not in KINDS: raise ValueError('Unknown host adapter')
    source=Path(core).resolve(strict=True)
    core_manifest=builder.inspect(source)
    names={n for e in core_manifest['exports'] for n in e['names'] if e['kind']=='code'}
    if core_manifest['architecture']!='x64' or 'DCOMP_GetAPI' not in names: raise ValueError('Host requires x64 DCOMP_GetAPI Core')
    module='dcomp_'+kind.replace('-','_')+'.dll'
    synthetic={'architecture':'x64','module':module,'sha256':core_manifest['sha256'],
        'exports':[{'ordinal':1,'names':['HostPlaceholder'],'kind':'code','rva':4096}]}
    host_config=dict(config or {})
    frame=host_config.pop('captureFirstFrame',0)
    count=host_config.pop('captureFrameCount',1)
    if not isinstance(frame,int) or isinstance(frame,bool) or not 0<=frame<2**63 or not isinstance(count,int) or isinstance(count,bool) or not 1<=count<=10000:
        raise ValueError('Invalid OpenXR capture frame range')
    host_config.setdefault('activation','worker' if kind=='asi' else 'manual')
    if host_config['activation']=='export': raise ValueError('Host adapters do not have source trigger exports')
    host_config.setdefault('enableDefault',True)
    host_config['provider']={'kind':'sibling','path':'unused_provider.dll','sha256':''}
    host_config['core']={'path':'dgcore.dll','sha256':core_manifest['sha256']}
    route_config=routes.config_for(synthetic,'generic',host_config)
    if kind=='vulkan-layer':
        if not set(VULKAN_EXPORTS)<=names: raise ValueError('Core lacks the Vulkan layer entry contract')
        synthetic['exports']=[dict(e,ordinal=i+1,names=[name]) for i,name in enumerate(VULKAN_EXPORTS)
            for e in core_manifest['exports'] if name in e['names']]
        route_config['provider']={'kind':'sibling','path':'dgcore.dll','sha256':core_manifest['sha256']}
        route_config['activation']='first-call'
    output=Path(output).resolve()
    compiler=builder.find_msbuild(msbuild)
    java_home=None
    if kind=='jvm':
        if jdk: java_home=Path(jdk).resolve(strict=True)
        elif os.environ.get('JAVA_HOME') and (Path(os.environ['JAVA_HOME'])/'bin/javac.exe').is_file(): java_home=Path(os.environ['JAVA_HOME'])
        else:
            found=shutil.which('javac.exe')
            if not found: raise ValueError('JVM host build requires a JDK; pass --jdk')
            # Oracle's javapath is a symlink; resolve it before finding jar.exe.
            java_home=Path(found).resolve().parents[1]
        if not all((java_home/'bin'/name).is_file() for name in ('javac.exe','jar.exe')): raise ValueError('JDK needs javac and jar')
    lock=routes.generate(synthetic,output,route_config,builder.REPO,builder.digest(source))
    definitions=['LIBRARY '+module,'EXPORTS']+['  '+c for c in routes.CONTROL]
    files={}
    if kind=='openxr':
        definitions.append('  xrNegotiateLoaderApiLayerInterface')
        files['host.cpp']=(routes.ROOT/'templates/openxr_layer.cpp').read_text(encoding='utf-8')
        files['include/host_config.h']='#pragma once\n#define PB_XR_FIRST_FRAME %duLL\n#define PB_XR_FRAME_COUNT %duLL\n'%(frame,count)
        for item in (routes.ROOT/'vendor/openxr').iterdir():
            if item.is_file(): files['include/openxr/'+item.name]=item.read_text(encoding='utf-8-sig')
        files['host-manifest.json']=json.dumps({'file_format_version':'1.0.0','api_layer':{
            'name':'XR_APILAYER_DCOMP_capture','library_path':'.\\'+module,'api_version':'1.0',
            'implementation_version':'1','description':'DComp explicit frame capture layer'}},indent=2)
    elif kind=='jvm':
        definitions.append('  Java_org_dcomp_proxy_Bootstrap_initialize')
        files['host.cpp']='''#include <windows.h>
extern "C" int __cdecl DCompProxyInitialize();
extern "C" int JNICALL_PLACEHOLDER Java_org_dcomp_proxy_Bootstrap_initialize(void *,void *) {
  HMODULE pinned=nullptr;
  GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_PIN,
      reinterpret_cast<LPCWSTR>(&Java_org_dcomp_proxy_Bootstrap_initialize),&pinned);
  return DCompProxyInitialize();
}
'''.replace('JNICALL_PLACEHOLDER','__stdcall')
        files['java/org/dcomp/proxy/Bootstrap.java']='''package org.dcomp.proxy;
import java.nio.file.Path;
import java.lang.instrument.Instrumentation;
public final class Bootstrap {
  private static native int initialize();
  public static void premain(String argument, Instrumentation ignored) throws Exception {
    Path dll = argument == null || argument.isBlank()
        ? Path.of(Bootstrap.class.getProtectionDomain().getCodeSource().getLocation().toURI()).getParent().resolve("dcomp_jvm.dll")
        : Path.of(argument);
    System.load(dll.toAbsolutePath().toString());
    if (initialize() != 1) throw new IllegalStateException("DComp Core bootstrap handshake failed");
  }
}
'''
        files['java/MANIFEST.MF']='Manifest-Version: 1.0\nPremain-Class: org.dcomp.proxy.Bootstrap\n\n'
    elif kind=='vulkan-layer':
        for i,name in enumerate(VULKAN_EXPORTS): definitions.append('  '+name+'=ProxyExport'+str(i)+' @'+str(i+1))
        base=json.loads((builder.REPO/'renderdoc/driver/vulkan/dgcore.json').read_text(encoding='utf-8'))
        base['layer'].update(name='VK_LAYER_DCOMP_Capture',library_path='.\\'+module,implementation_version=1)
        base['layer'].pop('enable_environment',None); base['layer'].pop('disable_environment',None)
        files['host-manifest.json']=json.dumps(base,indent=2)
    else:
        files['host.cpp']='// ASI entry is the route runtime DllMain; activation follows host config.\n'
    if kind!='vulkan-layer': files['proxy.vcxproj']=routes.project(module,['runtime.cpp','host.cpp'])
    if 'proxy.vcxproj' in files:
        files['proxy.vcxproj']=files['proxy.vcxproj'].replace('</ClCompile>',
            '<AdditionalOptions Condition="\'$(Configuration)\'==\'ClangRelease\'">/utf-8 /clang:-Wno-cast-function-type-mismatch %(AdditionalOptions)</AdditionalOptions></ClCompile>')
    files['exports.def']='\n'.join(definitions)+'\n'
    for name,text in files.items():
        target=output/name; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(text,encoding='utf-8',newline='\n')
    generated={str(p.relative_to(output)).replace('\\','/'):builder.digest(p) for p in output.rglob('*') if p.is_file() and p.name!='exports.json'}
    lock.update(host=kind,generatedFiles=generated,additionalExports=routes.CONTROL,
        captureFirstFrame=frame,captureFrameCount=count,sourceSHA256=core_manifest['sha256'])
    (output/'exports.json').write_text(json.dumps(lock,indent=2),encoding='utf-8')
    configuration='ClangRelease' if toolchain=='ClangCL' else 'Release'
    command=[str(compiler),str(output/'proxy.vcxproj'),'/t:Build','/m:4','/v:minimal','/nologo',
        '/p:Configuration='+configuration,'/p:Platform=x64','/p:ImportDirectoryBuildProps=false','/p:ImportDirectoryBuildTargets=false']
    receipt={'schemaVersion':2,'status':'building','host':kind,'toolchain':toolchain,'sourceSHA256':core_manifest['sha256'],
        'command':command,'generatedFiles':generated,'routeConfig':lock['routeConfig'],'captureStatus':'unverified'}
    try:
        with (output/'build.log').open('wb') as log: result=subprocess.run(command,cwd=output,stdout=log,stderr=subprocess.STDOUT)
        if result.returncode: raise ValueError('Host compilation failed: '+str(output/'build.log'))
        binary=output/'bin'/configuration/module
        expected=set(routes.CONTROL) | ({'xrNegotiateLoaderApiLayerInterface'} if kind=='openxr' else
            {'Java_org_dcomp_proxy_Bootstrap_initialize'} if kind=='jvm' else set(VULKAN_EXPORTS) if kind=='vulkan-layer' else set())
        compiled=builder.inspect(binary)
        if {n for e in compiled['exports'] for n in e['names']}!=expected: raise ValueError('Host export contract mismatch')
        for name,h in generated.items():
            if builder.digest(output/name)!=h: raise ValueError('Host source changed during compilation')
        if builder.digest(source)!=core_manifest['sha256']: raise ValueError('Core changed during compilation')
        shutil.copy2(source,binary.parent/'dgcore.dll')
        if builder.digest(binary.parent/'dgcore.dll')!=core_manifest['sha256']: raise ValueError('Core copy hash mismatch')
        if kind=='asi':
            deployed=binary.with_suffix('.asi'); shutil.copy2(binary,deployed)
            receipt['asi']=str(deployed)
        if kind in ('openxr','vulkan-layer'):
            shutil.copy2(output/'host-manifest.json',binary.parent/'host-manifest.json')
            receipt['manifest']=str(binary.parent/'host-manifest.json')
        if kind=='jvm':
            classes=output/'classes'; classes.mkdir()
            with (output/'java-build.log').open('wb') as log:
                subprocess.run([str(java_home/'bin/javac.exe'),'--release','17','-d',str(classes),str(output/'java/org/dcomp/proxy/Bootstrap.java')],check=True,stdout=log,stderr=subprocess.STDOUT)
                jar=binary.parent/'dcomp-bootstrap.jar'
                subprocess.run([str(java_home/'bin/jar.exe'),'--create','--file',str(jar),'--manifest',str(output/'java/MANIFEST.MF'),'-C',str(classes),'.'],check=True,stdout=log,stderr=subprocess.STDOUT)
            receipt.update(jar=str(jar),jarSHA256=builder.digest(jar),jdk=str(java_home),
                jvmArgument='-javaagent:'+str(jar))
        receipt.update(status='verified',dll=str(binary),dllSHA256=builder.digest(binary),
            exports=sorted(expected),scope='Compiled host contract; real host rendering/capture validation pending')
    except (ValueError,OSError,subprocess.SubprocessError) as exc:
        receipt.update(status='failed',error=str(exc)); raise
    finally:
        (output/'build-result.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    return receipt
