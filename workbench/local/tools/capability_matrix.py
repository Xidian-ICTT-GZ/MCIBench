"""Capability matrix: what the current judge can actually execute, per problem.

Answers, without running Docker: for every catalog problem, which interface route
it takes, whether the formal harness can parse its signature at all, and in which
languages an independent reference exists. This is what decides whether a
"new problem, same engine" claim is true for a given problem set.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from local.common import load_reference
from local.harness.typespec import UnsupportedProblemError
from local.lab import catalog as catalog_mod, interface_policy, problem_packages as packages
from local.lab.native_adapters import signature

LANGUAGES = ('python3', 'c', 'cpp', 'java', 'javascript', 'csharp', 'golang', 'rust')


def kind_of(problem):
    tags = {str(t).lower() for t in (problem.get('tags') or [])}
    if 'design' in tags:
        return 'design'
    if tags & {'tree', 'binary tree', 'binary search tree'}:
        return 'tree'
    if 'linked list' in tags:
        return 'linked_list'
    if problem.get('problem_kind') == 'database':
        return 'database'
    if problem.get('problem_kind') == 'shell':
        return 'shell'
    if problem.get('problem_kind') == 'dataframe':
        return 'dataframe'
    return 'function'


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=0)
    args = parser.parse_args()

    problems = catalog_mod.catalog()['problems']
    if args.limit:
        problems = problems[:args.limit]
    rows = []
    for problem in problems:
        qid = problem['qid']
        kind = kind_of(problem)
        try:
            iface = packages.code_interface(qid, 'python3')
            route = interface_policy.route(iface)
            interface_note = None
        except interface_policy.UnknownInterface as error:
            iface, route, interface_note = None, 'blocked', str(error)
        except Exception as error:                                  # noqa: BLE001
            iface, route, interface_note = None, 'blocked', type(error).__name__
        supported, reason = True, None
        try:
            signature(qid)
        except UnsupportedProblemError as error:
            supported, reason = False, str(error)[:200]
        except Exception as error:                                  # noqa: BLE001
            supported, reason = False, '%s: %s' % (type(error).__name__, str(error)[:150])
        references = []
        if supported:
            for language in LANGUAGES:
                try:
                    load_reference(qid, language)
                    references.append(language)
                except (OSError, ValueError, KeyError):
                    continue
        rows.append({'qid': qid, 'kind': kind, 'scope': problem.get('scope'),
                     'interface': iface, 'route': route, 'interface_note': interface_note,
                     'signature_supported': supported, 'reason': reason,
                     'reference_languages': references,
                     'packageable': (packages.DATA_DIR / ('%s.json' % qid)).exists()})

    by_kind = Counter(row['kind'] for row in rows)
    supported = [row for row in rows if row['signature_supported']]
    matrix = Counter(len(row['reference_languages']) for row in supported)
    out = {
        'version': 'capability-matrix-v1',
        'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'problems': len(rows),
        'by_kind': dict(by_kind),
        'signature_supported': len(supported),
        'signature_unsupported': len(rows) - len(supported),
        'supported_by_kind': dict(Counter(row['kind'] for row in supported)),
        'reference_language_histogram': dict(sorted(matrix.items())),
        'eight_language_ready': sum(1 for row in supported if len(row['reference_languages']) >= 8),
        'packaged': sum(1 for row in rows if row['packageable']),
        'blocked_routes': sum(1 for row in rows if row['route'] == 'blocked'),
        'rows': rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')

    print('problems:', out['problems'])
    print('kinds:', out['by_kind'])
    print('signature supported:', out['signature_supported'], '| unsupported:', out['signature_unsupported'])
    print('supported by kind:', out['supported_by_kind'])
    print('reference languages per supported problem:', out['reference_language_histogram'])
    print('eight-language ready:', out['eight_language_ready'])
    print('packaged:', out['packaged'], '| blocked routes:', out['blocked_routes'])
    print('output ->', args.output)


if __name__ == '__main__':
    main()
