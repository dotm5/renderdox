"""Build 0.3 portable service against an explicit, preserved native baseline."""
import argparse
import json
import shutil
from pathlib import Path

from bundle import build, bundle, digest
from developer_tools import prepare
from contracts import VERSION


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--base-package',required=True)
    p.add_argument('--destination',required=True)
    p.add_argument('--build-root',required=True)
    p.add_argument('--native-acceptance',required=True)
    args=p.parse_args()
    source=Path(args.base_package).resolve();destination=Path(args.destination).resolve()
    if destination.exists():
        raise RuntimeError('Use a fresh destination; baseline packages are never overwritten')
    base_hash=digest(source/'dgcore.dll')
    shutil.copytree(source,destination,ignore=shutil.ignore_patterns('__pycache__','*.pyc','developer-tools','mcp-runtime'))
    build_root=Path(args.build_root).resolve();build_root.mkdir(parents=True,exist_ok=True)
    frozen=build(build_root)
    native=Path(args.native_acceptance).resolve()
    developer_tools=prepare(build_root,native)
    manifest=bundle(destination,frozen,build_root,developer_tools)
    if digest(destination/'dgcore.dll')!=base_hash:
        raise RuntimeError('Native baseline changed during packaging')
    proof={'version':VERSION,'nativeBaseline':str(source),'nativeCoreSHA256':base_hash,
           'nativeCoreUnmodified':True,'nativeFixtureAcceptance':str(native/'results.json'),
           'nativeFixtureResults':json.loads((native/'results.json').read_text(encoding='utf-8-sig')),
           'runtimeGameValidation':'Pending: fresh target instance required',
           'sourceTreeDirty':manifest['mcp']['sourceTreeDirty']}
    (destination.parent/'build-proof.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
    print(json.dumps({'package':str(destination),'nativeCoreSHA256':base_hash,'version':VERSION}))


if __name__=='__main__':main()
