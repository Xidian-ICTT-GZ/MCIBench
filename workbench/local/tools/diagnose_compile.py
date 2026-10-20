"""Compile a generated driver outside the judge and show BOTH output streams.

The judge's docker path reports compile failures from stderr only. For languages
whose compiler writes diagnostics to stdout (dotnet build writes MSBuild output to
stdout), that leaves an empty message -- which is exactly how a one-line
accessibility error looked like an unsolvable mystery for a whole round.

This tool is lab-side only: it never touches the protected judge closure, it just
reproduces the same compile command in the judge image and prints everything.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from local.common import load_reference
from local.harness.identity import image_digest
from local.lab import problem_io, problem_packages as packages

CSPROJ = ('<Project Sdk="Microsoft.NET.Sdk">\n'
          '  <PropertyGroup>\n'
          '    <OutputType>Exe</OutputType>\n'
          '    <TargetFramework>net8.0</TargetFramework>\n'
          '    <Nullable>disable</Nullable>\n'
          '    <ImplicitUsings>disable</ImplicitUsings>\n'
          '    <AssemblyName>driver_bin</AssemblyName>\n'
          '  </PropertyGroup>\n'
          '</Project>\n')

ACTION = {
    'csharp': ('Program.cs', ['dotnet', 'build', '-c', 'Release', '-v', 'q',
                              '--ignore-failed-sources', 'runner.csproj']),
    'java': ('Judge.java', ['javac', '-encoding', 'UTF-8', 'Judge.java']),
    'cpp': ('driver.cpp', ['g++', '-O2', '-o', 'driver_bin', 'driver.cpp']),
    'golang': ('driver.go', ['go', 'build', '-o', 'driver_bin', 'driver.go']),
    'rust': ('driver.rs', ['rustc', '-O', '--edition', '2021', '-o', 'driver_bin', 'driver.rs']),
}


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--qid', type=int, required=True)
    parser.add_argument('--language', required=True)
    parser.add_argument('--file', type=Path, help='driver source to diagnose')
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()

    name, command = ACTION[args.language]
    if args.file:
        code = args.file.read_text(encoding='utf-8')
    else:
        from local.lab import native_structural as ns
        package = json.loads((packages.DATA_DIR / ('%s.json' % args.qid)).read_text(encoding='utf-8'))
        descriptor = {'qid': args.qid, 'kind': problem_io.kind(args.qid),
                      'official': package['cases'],
                      'comparison': package.get('comparison') or {'mode': 'ordered'},
                      'interface_note': None, 'warnings': []}
        bridge = ns.prepare_reference_only(args.qid, args.language, descriptor, package, image_digest())
        if bridge is None:
            raise SystemExit('no deterministic bridge for this shape; nothing to diagnose')
        code = bridge['prefix'] + '\n' + bridge['reference_code'] + '\n' + bridge['suffix']

    folder = tempfile.mkdtemp(prefix='diagnose_%s_%s_' % (args.qid, args.language))
    Path(folder, name).write_text(code, encoding='utf-8')
    if args.language == 'csharp':
        Path(folder, 'runner.csproj').write_text(CSPROJ, encoding='utf-8')
    result = subprocess.run(
        ['docker', 'run', '--rm', '-v', folder + ':/w', '-w', '/w', image_digest(),
         'bash', '-lc', ' '.join(command)],
        capture_output=True, timeout=args.timeout)
    print('exit code:', result.returncode)
    for label, stream in (('stdout', result.stdout), ('stderr', result.stderr)):
        text = stream.decode('utf-8', 'replace').strip()
        print('--- %s (%d bytes) ---' % (label, len(text)))
        print(text[:4000] if text else '(empty)')
    Path(folder, 'source.txt').write_text(code, encoding='utf-8')
    print('workdir:', folder)


if __name__ == '__main__':
    main()
