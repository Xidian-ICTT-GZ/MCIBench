"""Build dashboard assets and a server whose API exposes its source fingerprint."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / 'local/dashboard/packages/server'
WEB = ROOT / 'local/dashboard/packages/web'


def source_hashes():
    files = list(SERVER.rglob('*.go')) + [SERVER/'go.mod', SERVER/'go.sum']
    files += [p for p in (WEB/'src').rglob('*') if p.is_file()]
    files += [p for p in WEB.iterdir() if p.is_file() and p.suffix in ('.json', '.ts', '.html')]
    files += list((ROOT/'local/lab').glob('*.py'))
    files += list((ROOT/'local/lab/data').glob('*.json'))
    files += [ROOT/'local/tools/extend_lab_catalog.py']
    files += [ROOT/'local/tools/llm_testcases.py', ROOT/'local/tools/gap_workflow.py']
    files += [ROOT/'local/tools/verify_judge_correctness.py']
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(set(files)) if p.exists()}


def current_build_id():
    return hashlib.sha256(json.dumps(source_hashes(), sort_keys=True).encode()).hexdigest()


def main():
    before = source_hashes()
    build_id = current_build_id()
    subprocess.run(['npm.cmd', 'run', 'build'], cwd=WEB, check=True)
    subprocess.run(['go', 'test', './...'], cwd=SERVER, check=True)
    binary = SERVER/'local-dashboard-server.exe'
    subprocess.run(['go', 'build', '-ldflags', '-X main.buildID='+build_id,
                    '-o', str(binary), './cmd/server'], cwd=SERVER, check=True)
    if source_hashes() != before:
        raise RuntimeError('Dashboard sources changed during build')
    manifest = {'build_id': build_id, 'sources': before,
                'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                'assets': {p.relative_to(WEB/'dist').as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in sorted((WEB/'dist').rglob('*')) if p.is_file()}}
    (SERVER/'build-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Dashboard build:', build_id)


if __name__ == '__main__':
    main()
