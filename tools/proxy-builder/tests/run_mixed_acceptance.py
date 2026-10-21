"""Focused two-protocol test, using the compiled owned route fixtures."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import proxy_builder as builder
import fixture_build_cache as build_cache

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--fixtures',required=True); p.add_argument('--output',required=True)
    p.add_argument('--reuse-builds',action='store_true',help='Reuse verified binaries while rerunning mixed-protocol processes')
    args=p.parse_args(); output=Path(args.output).resolve()
    if args.reuse_builds:
        build_cache.verify(output,'mixed')
        (output/'results.json').unlink()
    elif output.exists(): raise ValueError('Choose a fresh output')
    output.mkdir(parents=True,exist_ok=args.reuse_builds); results=[]
    for toolchain in ('MSVC','ClangCL'):
        source=Path(args.fixtures)/toolchain
        root=output/toolchain; root.mkdir(exist_ok=args.reuse_builds)
        config='Release' if toolchain=='MSVC' else 'ClangRelease'
        command=[str(builder.find_msbuild()),str(Path(__file__).with_name('native_route.vcxproj')),'/t:Build','/nologo','/v:minimal',
            '/p:Configuration='+config,'/p:Platform=x64','/p:ImportDirectoryBuildProps=false','/p:ImportDirectoryBuildTargets=false',
            '/p:FixtureType=Application','/p:FixtureSource='+str(Path(__file__).with_name('route_smoke.cpp')),
            '/p:FixtureInclude='+str(builder.routes.ROOT/'vendor'),'/p:OutDir='+str(root)+'\\','/p:IntDir='+str(root/'obj')+'\\',
            '/p:TargetName=mixed-smoke']
        if not args.reuse_builds:
            with (root/'smoke-build.log').open('wb') as log: subprocess.run(command,check=True,stdout=log,stderr=subprocess.STDOUT)
            receipt=builder.build_dll(source/'original-code/fixture.dll',root/'generated',template='app-local',toolchain=toolchain,
                core=source/'core/dgcore.dll',copy_original=True,profile='generic',config={'activation':'first-call','enableDefault':True,
                    'dispatch':{'nvapi':{'0x1234':'Sum8'},'vulkan':{'vkSum8':'Sum8'}}})
        else:
            receipt=build_cache.cached_receipt(root/'generated',builder,source/'original-code/fixture.dll',toolchain,
                core=source/'core/dgcore.dll')
        with (root/'mixed.json').open('wb') as log: subprocess.run([str(root/'mixed-smoke.exe'),'mixed',receipt['dll']],check=True,stdout=log,stderr=subprocess.STDOUT)
        results.append({'toolchain':toolchain,'twoProtocolsOnOneProxy':True,'dllSHA256':receipt['dllSHA256']})
        print(toolchain+': mixed dispatch passed',flush=True)
    (output/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    build_cache.seal(output,'mixed')

