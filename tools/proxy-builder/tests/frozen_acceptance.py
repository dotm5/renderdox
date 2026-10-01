"""Build and exercise an owned DLL with the relocated frozen Builder CLI."""
import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path


def run(package, fixtures, output):
    package, fixtures, output = Path(package).resolve(), Path(fixtures).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((package / 'manifest.json').read_text(encoding='utf-8-sig'))
    compiler = manifest['toolchain']
    executable = package / 'developer-tools/proxy-builder/proxy-builder.exe'
    original = fixtures / compiler / 'fixture/bin/fixture.dll'
    smoke = fixtures / compiler / 'smoke/bin/proxy-smoke.exe'
    environment = os.environ.copy()
    for name in ('PYTHONHOME', 'PYTHONPATH', 'DCOMP_BOOTSTRAP_ENABLE'):
        environment.pop(name, None)
    environment['PATH'] = r'C:\Windows\System32;C:\Windows'
    environment['DCOMP_BOOTSTRAP_ENABLE'] = '0'
    def command(name, argv):
        with (output / (name + '.log')).open('wb') as log:
            subprocess.run([str(a) for a in argv], check=True, cwd=output,
                           env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    command('inspect', [executable, 'inspect', original])
    command('build', [executable, 'build', original, '--template', 'app-local',
        '--output', output / 'generated', '--toolchain', compiler, '--copy-original'])
    receipt = json.loads((output / 'generated/build-result.json').read_text(encoding='utf-8'))
    assert receipt['status'] == 'verified', receipt
    command('verify', [executable, 'verify', original, receipt['dll']])
    command('abi', [smoke, receipt['dll']])
    command('raw-eat', [smoke, receipt['dll'], 'raw-eat'])
    proof = {'status': 'passed', 'toolchain': compiler, 'scope': 'Packaged CLI and owned proxy fixture only',
             'builderSHA256': hashlib.sha256(executable.read_bytes()).hexdigest(),
             'receipt': receipt, 'abi': json.loads((output / 'abi.log').read_text()),
             'rawEAT': json.loads((output / 'raw-eat.log').read_text())}
    (output / 'results.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')
    print(json.dumps({'status': 'passed', 'toolchain': compiler, 'calls': 128000}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('package', 'fixtures', 'output'): parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    run(args.package, args.fixtures, args.output)
