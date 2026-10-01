"""Owned process tests of generated routes; never load a third-party game DLL."""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import proxy_builder as builder
import hosts

TESTS=Path(__file__).resolve().parent


def run(root, toolchains):
    root=Path(root).resolve()
    if root.exists(): raise ValueError('Choose a fresh route acceptance directory')
    root.mkdir(parents=True)
    compiler=builder.find_msbuild()
    results=[]
    def execute(command,log,cwd=None):
        with Path(log).open('wb') as stream:
            result=subprocess.run([str(s) for s in command],cwd=cwd,stdout=stream,stderr=subprocess.STDOUT,timeout=180)
        if result.returncode:
            raise ValueError('Command failed (%s): %s\n%s'%(result.returncode,command,Path(log).read_text(encoding='utf-8',errors='replace')[-7000:]))
    for toolchain in toolchains:
        base=root/toolchain; base.mkdir()
        config='ClangRelease' if toolchain=='ClangCL' else 'Release'
        def native(name,source,kind='DynamicLibrary',definition=None,library=None,include=None,target=None):
            folder=base/name; folder.mkdir()
            command=[compiler,TESTS/'native_route.vcxproj','/t:Build','/nologo','/v:minimal',
                '/p:Configuration='+config,'/p:Platform=x64','/p:ImportDirectoryBuildProps=false','/p:ImportDirectoryBuildTargets=false',
                '/p:FixtureType='+kind,'/p:FixtureSource='+str(source),'/p:OutDir='+str(folder)+'\\',
                '/p:IntDir='+str(folder/'obj')+'\\','/p:TargetName='+(target or name),
                '/p:FixtureInclude='+str(include or builder.REPO/'renderdoc')]
            if definition: command.append('/p:FixtureDef='+str(definition))
            if library: command.append('/p:FixtureLib='+str(library))
            execute(command,folder/'build.log')
            return folder/((target or name)+('.exe' if kind=='Application' else '.dll'))
        full=native('original-data',TESTS/'route_fixture.cpp',definition=TESTS/'route_fixture.def',target='fixture')
        no_data=base/'code.def'; no_data.write_text('\n'.join(line for line in (TESTS/'route_fixture.def').read_text().splitlines() if ' DATA' not in line)+'\n')
        source=native('original-code',TESTS/'route_fixture.cpp',definition=no_data,target='fixture')
        core=native('core',TESTS/'route_core.cpp',target='dgcore')
        plugin=native('plugin-original',TESTS/'route_plugin.cpp',target='owned_plugin')
        smoke=native('route-smoke',TESTS/'route_smoke.cpp','Application',include=builder.routes.ROOT/'vendor')
        def proxy_case(name,profile='generic',options=None,mode=None,input_dll=None,copy=True,default_activation=False):
            folder=base/name
            options=dict(options or {})
            options.setdefault('enableDefault',True)
            if not default_activation: options.setdefault('activation','first-call')
            receipt=builder.build_dll(input_dll or source,folder,template='app-local',toolchain=toolchain,
                copy_original=copy,core=core,profile=profile,config=options)
            binary=Path(receipt['dll'])
            argv=[smoke,mode or name,binary]
            if name=='plugin':
                shutil.copy2(plugin,binary.parent/plugin.name); argv.append(str(binary.parent/plugin.name))
            if name=='module-load':
                shutil.copy2(plugin,binary.parent/plugin.name); argv.append(str(binary.parent/plugin.name))
            execute(argv,folder/'smoke.json')
            results.append({'toolchain':toolchain,'case':name,'compiled':True,'ownedProcessPassed':True,'dllSHA256':receipt['dllSHA256']})
            print(toolchain+': '+name+' passed',flush=True)
            return receipt
        proxy_case('generic')
        proxy_case('streamline','streamline')
        proxy_case('ngx','ngx')
        proxy_case('nvapi','nvapi',{'queryMappings':{'0x1234':'Sum8'}})
        proxy_case('vulkan','vulkan',{'queryMappings':{'vkSum8':'Sum8','vkGetDeviceProcAddr':'vkGetDeviceProcAddr','vkGetInstanceProcAddr':'vkGetInstanceProcAddr'}})
        proxy_case('agility','agility')
        proxy_case('generic-load-only',mode='worker-load-only',default_activation=True)
        proxy_case('ngx-load-only','ngx',mode='worker-load-only',default_activation=True)
        proxy_case('nvapi-load-only','nvapi',mode='worker-load-only',default_activation=True)
        proxy_case('worker-load-only',options={'activation':'worker'})
        proxy_case('worker-no-block',options={'activation':'worker'})
        proxy_case('reentrant-core',options={'requireCore':True})
        for failure_case, options in (
                ('reentrant-core-fail',{'activation':'first-call'}),
                ('required-worker-plugin-fail',{'activation':'worker','plugins':[{'path':'missing_owned_plugin.dll'}]})):
            required_failure=builder.build_dll(source,base/failure_case,template='app-local',toolchain=toolchain,
                copy_original=True,core=core,profile='generic',config=dict(options,enableDefault=True,requireCore=True))
            with (base/failure_case/'smoke.log').open('wb') as log:
                failed=subprocess.run([str(smoke),failure_case,required_failure['dll']],stdout=log,stderr=subprocess.STDOUT,timeout=30)
            if failed.returncode & 0xffffffff != 0xc0000602:
                raise ValueError('Required-Core/plugin failure gate was bypassed: '+str(failed.returncode))
            results.append({'toolchain':toolchain,'case':failure_case,'compiled':True,
                'ownedProcessPassed':True,'expectedFailFast':True,'exitCode':failed.returncode})
            print(toolchain+': '+failure_case+' correctly rejected',flush=True)
        sdk_def=base/'aftermath.def'
        sdk_def.write_text('LIBRARY GFSDK_Aftermath_Lib.x64.dll\nEXPORTS\n  Sum8 @1\n  Float8 @2\n  GFSDK_Aftermath_DX11_Initialize=Sum8 @3\n')
        sdk_source=native('sdk-original',TESTS/'route_fixture.cpp',definition=sdk_def,target='GFSDK_Aftermath_Lib.x64')
        for index,rename in enumerate(builder.routes.AFTERMATH_ORIGINAL_NAMES):
            case='aftermath-rename-'+str(index+1)
            receipt=builder.build_dll(sdk_source,base/case,template='app-local',toolchain=toolchain,
                core=core,profile='auto',config={'enableDefault':True})
            if receipt['route']['profile']!='aftermath' or receipt['route']['activation']!='worker':
                raise ValueError('Aftermath auto policy was not applied')
            binary=Path(receipt['dll']); shutil.copy2(sdk_source,binary.parent/rename)
            execute([smoke,'aftermath',binary],base/case/'smoke.json')
            results.append({'toolchain':toolchain,'case':case,'compiled':True,'ownedProcessPassed':True,'activation':'worker'})
            print(toolchain+': '+case+' passed without an SDK activation call',flush=True)
        proxy_case('aftermath-first-call','auto',{'activation':'first-call'},mode='aftermath-first-call',input_dll=sdk_source)
        rejected=builder.build_dll(sdk_source,base/'aftermath-bad-primary',template='app-local',toolchain=toolchain,
            core=core,profile='auto',config={'enableDefault':True})
        binary=Path(rejected['dll']); shutil.copy2(source,binary.parent/builder.routes.AFTERMATH_ORIGINAL_NAMES[0])
        shutil.copy2(sdk_source,binary.parent/builder.routes.AFTERMATH_ORIGINAL_NAMES[1])
        execute([smoke,'bad-provider',binary],base/'aftermath-bad-primary/smoke.json')
        results.append({'toolchain':toolchain,'case':'aftermath-bad-primary','compiled':True,'ownedProcessPassed':True})
        print(toolchain+': aftermath-bad-primary refused fallback after CRC failure',flush=True)
        data_case=proxy_case('data',options={'dataExports':{'ExportedData':{'type':'uint32'},'DataAlias':{'type':'uint32'}}},input_dll=full)
        data_binary=Path(data_case['dll'])
        data_client=native('data-client',TESTS/'data_client.cpp','Application',library=data_binary.with_suffix('.lib'),target='data-client')
        data_deployed=data_binary.parent/data_client.name; shutil.copy2(data_client,data_deployed)
        execute([data_deployed],base/'data/static-data-import.json',data_binary.parent)
        proxy_case('export',options={'activation':'export','activateExports':['Sum8']})
        proxy_case('plugin',options={'plugins':[{'path':plugin.name,'sha256':builder.digest(plugin)}]})
        proxy_case('module-load',options={'activation':'module-load','watchModules':[plugin.name]})
        bad=proxy_case('bad-provider',options={'activation':'manual','provider':{'kind':'sibling','path':'fixture_orig.dll','sha256':'0'*64}})
        proxy_case('missing-core',options={'activation':'manual','core':{'path':'not-present.dll','sha256':''}})
        proxy_case('linker',options={'forwarding':'linker','activation':'manual'},mode='host')
        entry=builder.build_dll(source,base/'entry-point',template='app-local',toolchain=toolchain,copy_original=True,
            core=core,profile='generic',config={'activation':'entry-point','enableDefault':True})
        binary=Path(entry['dll'])
        entry_exe=native('entry-client',TESTS/'entry_smoke.cpp','Application',library=binary.with_suffix('.lib'),target='entry-smoke')
        deployed=binary.parent/entry_exe.name; shutil.copy2(entry_exe,deployed)
        execute([deployed],base/'entry-point/smoke.json',binary.parent)
        results.append({'toolchain':toolchain,'case':'entry-point','compiled':True,'ownedProcessPassed':True})
        print(toolchain+': entry-point passed',flush=True)
        # A generated intermediary with the same contract; positive chain and
        # a warm/cold cycle rejection are separate, fresh processes.
        middle_def=base/'middle.def'; middle_def.write_text(no_data.read_text().replace('LIBRARY fixture.dll','LIBRARY middle.dll'))
        middle_source=native('middle-original',TESTS/'route_fixture.cpp',definition=middle_def,target='middle')
        for cycle in (False,True):
            name='cycle' if cycle else 'chain'
            middle=builder.build_dll(middle_source,base/(name+'-middle'),template='app-local',toolchain=toolchain,
                core=core,profile='generic',config={'activation':'manual','provider':{'kind':'sibling','path':'fixture.dll' if cycle else 'leaf.dll','sha256':''}})
            upper=builder.build_dll(source,base/name,template='app-local',toolchain=toolchain,core=core,profile='generic',
                config={'activation':'first-call','enableDefault':True,'provider':{'kind':'sibling','path':'middle.dll','sha256':''}})
            binary=Path(upper['dll']); shutil.copy2(middle['dll'],binary.parent/'middle.dll')
            if not cycle: shutil.copy2(source,binary.parent/'leaf.dll')
            execute([smoke,'cycle' if cycle else 'generic',binary],base/name/'smoke.json')
            results.append({'toolchain':toolchain,'case':name,'compiled':True,'ownedProcessPassed':True})
            print(toolchain+': '+name+' passed',flush=True)
        for kind in hosts.KINDS:
            receipt=hosts.build(builder,kind,base/('host-'+kind),core,toolchain)
            binary=Path(receipt.get('asi',receipt['dll']))
            execute([smoke,kind if kind in ('openxr','vulkan-layer') else 'host',binary],base/('host-'+kind)/'smoke.json')
            if kind=='jvm':
                test=base/'OwnedJavaMain.java'; test.write_text('public final class OwnedJavaMain { public static void main(String[] args) { System.out.println("premainPassed=true"); } }')
                java_home=Path(receipt['jdk'])
                execute([java_home/'bin/javac.exe','--release','17',test],base/'java-compile.log')
                execute([java_home/'bin/java.exe','--enable-native-access=ALL-UNNAMED',receipt['jvmArgument'],'-cp',base,'OwnedJavaMain'],base/'jvm-premain.log')
            results.append({'toolchain':toolchain,'case':'host-'+kind,'compiled':True,'ownedProcessPassed':True,'dllSHA256':receipt['dllSHA256']})
            print(toolchain+': host-'+kind+' passed',flush=True)
    (root/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    return results


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--output',required=True)
    p.add_argument('--toolchain',choices=['MSVC','ClangCL','Both'],default='Both')
    args=p.parse_args()
    run(args.output,['MSVC','ClangCL'] if args.toolchain=='Both' else [args.toolchain])
