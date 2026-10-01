"""Freeze the builder CLI; Visual Studio remains an explicit build dependency."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
import routes

ROOT = Path(__file__).resolve().parent


def package(destination, build_root):
    destination, build_root = Path(destination).resolve(), Path(build_root).resolve()
    if (destination / 'proxy-builder.exe').exists():
        raise ValueError('Use a fresh builder destination')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
        '--name', 'proxy-builder', '--contents-directory', 'builder-runtime',
        '--distpath', str(build_root / 'dist'), '--workpath', str(build_root / 'work'), '--specpath', str(build_root),
        '--exclude-module', 'numpy', '--exclude-module', 'PIL', '--exclude-module', 'tkinter',
        str(ROOT / 'proxy_builder.py')], check=True)
    shutil.copytree(build_root / 'dist' / 'proxy-builder', destination, dirs_exist_ok=True)
    templates = destination / 'runtime-templates'
    repo = ROOT.parents[1]
    for slot in ('aftermath', 'dxgi', 'd3d11', 'd3d12'):
        folder = repo / 'bootstrap' / (slot + '_proxy')
        target = templates / 'bootstrap' / folder.name
        target.mkdir(parents=True, exist_ok=True)
        for pattern in ('*.cpp', '*.asm'):
            for file in folder.glob(pattern):
                shutil.copy2(file, target / file.name)
    for relative in ('api/app/renderdoc_app.h', 'generated/product_identity.h'):
        target = templates / 'renderdoc' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / 'renderdoc' / relative, target)
    vulkan = templates / 'renderdoc/driver/vulkan/dgcore.json'
    vulkan.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(repo/'renderdoc/driver/vulkan/dgcore.json',vulkan)
    for name in ('templates','vendor','examples'):
        if (ROOT/name).is_dir(): shutil.copytree(ROOT/name,destination/'route-templates'/name)
    (destination/'VERSION.json').write_text(json.dumps({'version':'0.4.1','architecture':'x64',
        'nativeProfiles':list(routes.PROFILES),
        'hosts':['asi','jvm','openxr','vulkan-layer'],'runtimeValidation':'per-application required'},indent=2),encoding='utf-8')
    shutil.copy2(ROOT / 'README.md', destination / 'README.md')
    shutil.copy2(ROOT / 'ROUTES.md', destination / 'ROUTES.md')
    subprocess.run([str(destination / 'proxy-builder.exe'), '--help'], check=True, stdout=subprocess.DEVNULL)
    return destination


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--destination', required=True); p.add_argument('--build-root', required=True)
    a = p.parse_args()
    print(json.dumps({'package': str(package(a.destination, a.build_root))}))
