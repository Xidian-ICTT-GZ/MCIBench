"""Lab-only compile artifact transport. Run always uses a new Docker container."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

spec = importlib.util.spec_from_file_location('trusted_supervisor', '/mci-supervisor.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
CAP = 64 * 1024 * 1024


def prepare(lang):
    for name in [base.SOURCES[lang]] + (['runner.csproj'] if lang == 'csharp' else []):
        shutil.copyfile(Path('/input') / name, Path('/w') / name)
        os.chown(Path('/w') / name, base.UID, base.UID)
    config = Path('/w/NuGet.Config')
    config.write_text('<configuration><packageSources><clear /></packageSources></configuration>')
    os.chown(config, base.UID, base.UID)
    os.chown('/w', base.UID, base.UID)


def artifact_paths(lang):
    if lang in ('c', 'cpp', 'golang', 'rust'):
        return [Path('/w/driver_bin')]
    if lang == 'java':
        return sorted(Path('/w').rglob('*.class'))
    if lang == 'csharp':
        return sorted(p for p in Path('/w/bin/Release/net8.0').iterdir() if p.suffix in ('.dll', '.json', '.pdb'))
    return []


def artifacts(lang):
    items, size = [], 0
    paths = artifact_paths(lang)
    if not paths or len(paths) > 512:
        raise ValueError('invalid compiled artifact count')
    for path in paths:
        if path.is_symlink() or not path.is_file() or any(p.is_symlink() for p in path.parents):
            raise ValueError('compiled artifact must be a regular file')
        size += path.stat().st_size
        if size > CAP:
            raise ValueError('compiled artifacts exceed transport cap')
        data = path.read_bytes()
        items.append({'name': path.relative_to('/w').as_posix(), 'sha256': hashlib.sha256(data).hexdigest(),
                      'bytes': len(data), 'data': base64.b64encode(data).decode('ascii')})
    return items


def restore():
    os.chown('/w', 0, 0)
    manifest = json.loads(Path('/artifacts/manifest.json').read_text())
    for item in manifest['files']:
        name = item['name']
        # Host already verifies the manifest; the privileged copy also confines paths.
        if not name or Path(name).is_absolute() or '..' in Path(name).parts or '\\' in name:
            raise ValueError('unsafe artifact path')
        src = Path('/artifacts') / name
        dst = Path('/w') / name
        if src.is_symlink() or not src.is_file():
            raise ValueError('invalid mounted artifact')
        data = src.read_bytes()
        if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256']:
            raise ValueError('mounted artifact integrity failure')
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        os.chmod(dst, 0o755 if name == 'driver_bin' else 0o644)
        os.chown(dst, base.UID, base.UID)
    os.chown('/w', base.UID, base.UID)


def main():
    lang, compile_s, run_s, limit, mode = sys.argv[1:]
    if lang not in base.SOURCES or mode not in ('cold', 'warm', 'uncached') or os.getuid() != 0:
        raise ValueError('invalid lab execution profile')
    compile_s, run_s = float(compile_s), float(run_s)
    if not all(base.math.isfinite(x) and x > 0 for x in (compile_s, run_s)):
        raise ValueError('invalid stage budget')
    prepare(lang)
    report = {'protocol': base.PROTOCOL, 'compile': None, 'run': None, 'cache_mode': mode}
    if mode == 'warm':
        restore()
        report['compile'] = {'exit_code': 0, 'reason': None, 'runtime_ms': 0, 'memory_mb': None, 'stdout': '', 'stderr': ''}
    else:
        report['compile'] = base.measure(['/judge_exec.sh', 'compile', lang, '0', ''], compile_s, CAP, 4*1024*1024)
    compiled = report['compile']
    if compiled['exit_code'] == 0 and compiled['reason'] is None:
        # Export before executing user code; execution cannot poison this snapshot.
        if mode == 'cold':
            report['artifacts'] = artifacts(lang)
        commands = {'python3': ['python3', 'driver.py'], 'javascript': ['node', 'driver.js'],
                    'java': ['java', '-cp', '.', 'Judge'], 'csharp': ['dotnet', 'bin/Release/net8.0/driver_bin.dll']}
        report['run'] = base.measure(commands.get(lang, ['./driver_bin']) + [limit], run_s, CAP, 4*1024*1024, stream_output=True)
    print(json.dumps({'event': 'result', 'report': report}, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
