"""Admit official examples to the lab only after independent language reference gates.

Does not write the FT100 corpus, benchmark DB, judge or reference implementations.
Example: python -m local.tools.extend_lab_catalog --limit 100 --languages python3 cpp
Run again with a larger limit, or --qids 20,125,151 to extend without a fixed cap.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import re
import tempfile

from local.common import DESCRIPTIONS_DIR, KEY_TO_LABEL, LANGS, load_reference, load_snippet, save_json
from local.harness import runner
from local.harness.identity import image_digest, judge_source_closure
from local.harness.typespec import parse_python_snippet, Int, Bool, Str
from local.judge import judge_one
from local.lab.behavior import sha, partition_cases
from local.lab.catalog import _fresh
from local.gen_testcases.extract_examples import extract_from_prompt
from local.gen_testcases.constraints import check
from local.tools.inspect_lab_catalog import inventory

OUTPUT = Path(__file__).resolve().parents[1] / 'lab/data/catalog_extension.json'
POLICY = 'official-examples-scalar-dual-reference-v1'


def eligible(row, allow_non_scalar=False):
    """Conservative first adapter tier: scalar answers, deterministic plain methods.

    allow_non_scalar lifts only the return-type restriction: the gates are the same,
    and the ambiguous-answer text check still applies, because an answer that is not
    unique cannot be gated by comparing outputs.
    """
    sig = parse_python_snippet(load_snippet(row['qid'], 'python3'))
    text = (DESCRIPTIONS_DIR / row['source']).read_text(encoding='utf-8')
    unique_answer = not re.search(
        r'in.place|modify|random|any (?:valid |possible )?answer|return any|any order', text, re.I)
    return ((allow_non_scalar or isinstance(sig.ret, (Int, Bool, Str)))
            and 'python3' in row['languages'] and 'cpp' in row['languages']
            and unique_answer)


def ineligible_reason(row, allow_non_scalar=False):
    """Why a candidate cannot be admitted, so the skip gets recorded.

    The loop used to continue silently, which left combinations unaccounted for when
    reconciling a migration run: a problem dropped for a non-unique answer was
    indistinguishable from one that was never considered.
    """
    try:
        sig = parse_python_snippet(load_snippet(row['qid'], 'python3'))
    except (OSError, ValueError, KeyError, StopIteration, TypeError):
        return 'unparseable_signature'
    text = (DESCRIPTIONS_DIR / row['source']).read_text(encoding='utf-8')
    if re.search(r'in.place|modify|random|any (?:valid |possible )?answer|return any|any order', text, re.I):
        return 'non_unique_answer'
    if not allow_non_scalar and not isinstance(sig.ret, (Int, Bool, Str)):
        return 'unsupported_return_type'
    if not ('python3' in row['languages'] and 'cpp' in row['languages']):
        return 'missing_required_reference_language'
    return None


def bindings(qid, source, languages):
    return {'description_sha256': sha((DESCRIPTIONS_DIR / source).read_text(encoding='utf-8')),
            'snippets_sha256': {lang: sha(load_snippet(qid, lang)) for lang in LANGS},
            'references_sha256': {lang: sha(load_reference(qid, lang)) for lang in languages}}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--limit', type=int, default=100, help='maximum admitted questions for this batch; no platform cap')
    ap.add_argument('--qids', default='')
    ap.add_argument('--languages', nargs='+', choices=LANGS, default=['python3', 'cpp'])
    ap.add_argument('--refresh', action='store_true', help='re-run gates for selected existing questions, including additional languages')
    ap.add_argument('--allow-non-scalar', action='store_true',
                    help='also admit problems whose return type is not a scalar; gates are unchanged')
    args = ap.parse_args()
    if args.limit < 1 or not {'python3', 'cpp'} <= set(args.languages):
        ap.error('limit must be positive and gates must include python3 and cpp')
    cache = Path('local/results/catalog-inventory.json')
    data = json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else inventory()
    chosen = set(map(int, args.qids.split(','))) if args.qids else None
    runner.DOCKER_IMAGE = image_digest()
    closure = dict(judge_source_closure())
    identity = {'judge_closure': closure, 'image': runner.DOCKER_IMAGE, 'host_python': platform.python_version(),
                'policy': POLICY, 'builder_sha256': sha(Path(__file__).read_text(encoding='utf-8'))}
    out = {'version': 1, 'identity': identity, 'created_at': datetime.now(timezone.utc).isoformat(),
           'problems': [], 'rejected': [], 'notice': '仅官方示例；通过不代表 LeetCode 隐藏测试通过；不进入历史 FT100 统计'}
    if OUTPUT.exists():
        old = json.loads(OUTPUT.read_text(encoding='utf-8'))
        # Changing this admission utility is not a new judge execution. Preserve
        # the original tool hash per row, while rechecking actual input bindings.
        same_environment = {k: v for k, v in old['identity'].items() if k != 'builder_sha256'} == {k: v for k, v in identity.items() if k != 'builder_sha256'}
        if same_environment:
            out['problems'] = [{**r, 'admission_builder_sha256': r.get('admission_builder_sha256', old['identity']['builder_sha256'])}
                               for r in old['problems'] if _fresh(r)]
            out['rejected'] = old.get('rejected', [])
    if args.refresh:
        out['problems'] = [r for r in out['problems'] if chosen is not None and r['qid'] not in chosen]
    existing = {r['qid'] for r in out['problems']}
    admitted = 0
    with tempfile.TemporaryDirectory(prefix='mci_extension_gates_') as tmp:
        for row in data['candidates']:
            qid = row['qid']
            if qid in existing or (chosen is not None and qid not in chosen):
                continue
            try:
                reason = ineligible_reason(row, args.allow_non_scalar)
                if reason:
                    if not any(r.get('qid') == qid for r in out['rejected']):
                        out['rejected'].append({'qid': qid, 'reason': reason})
                    continue
                # Inventory is only a candidate index; never publish cached
                # answers under a newly changed description's checksum.
                sig = parse_python_snippet(load_snippet(qid, 'python3'))
                text = (DESCRIPTIONS_DIR / row['source']).read_text(encoding='utf-8')
                cases = extract_from_prompt(text)
                unique = {sha(c['args']): c for c in cases if set(c['args']) == {p.name for p in sig.params} and not check(qid, c)}
                row = {**row, 'cases': list(unique.values())}
                partition_cases(qid, row['cases'], 8)
                bound = bindings(qid, row['source'], [])
                passed, gates = [], []
                for lang in args.languages:
                    if lang not in row['languages']:
                        continue
                    code = load_reference(qid, lang)
                    path = Path(tmp) / f'{qid}_{KEY_TO_LABEL[lang]}_1.txt'
                    path.write_text(code, encoding='utf-8')
                    verdict = judge_one(path, 'gen', len(row['cases']), 'docker', cases_override=row['cases'])
                    gate = {'language': lang, 'state': verdict['state'], 'status': verdict['ac_status'],
                            'total': verdict['total_testcases'], 'correct': verdict['total_correct'],
                            'dropped_unrepresentable': verdict['_meta'].get('dropped_unrepresentable', 0),
                            'error': verdict['_meta'].get('error', '')[:500]}
                    gates.append(gate)
                    if gate['state'] == 'SUCCESS' and gate['status'] == 'Accepted' and gate['total'] == len(row['cases']) and gate['correct'] == gate['total'] and not gate['dropped_unrepresentable']:
                        passed.append(lang)
                if {'python3', 'cpp'} <= set(passed):
                    bound['references_sha256'] = {lang: sha(load_reference(qid, lang)) for lang in passed}
                    out['problems'].append({**row, 'languages': passed, 'gates': gates, 'bindings': bound,
                                            'admission_builder_sha256': identity['builder_sha256'],
                                            'cases_sha256': sha(row['cases']), 'evidence_level': 'official_examples_only'})
                    existing.add(qid)
                    admitted += 1
                    print(f'admitted q{qid} cases={len(row["cases"])} languages={passed} total={len(existing)}', flush=True)
                else:
                    out['rejected'].append({'qid': qid, 'gates': gates, 'reason': 'dual-reference gate failed'})
                    print(f'held q{qid}: reference gate failed', flush=True)
            except (OSError, ValueError, KeyError, TypeError) as error:
                out['rejected'].append({'qid': qid, 'reason': str(error)[:500]})
                print(f'held q{qid}: {type(error).__name__}', flush=True)
            publish(out)
            if admitted >= args.limit:
                break
    publish(out)
    print(f'Extension ready: {len(out["problems"])} questions; rejected {len(out["rejected"])}', flush=True)


def publish(data):
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pending = OUTPUT.with_suffix('.json.tmp')
    save_json(pending, data)
    pending.replace(OUTPUT)


if __name__ == '__main__':
    main()
