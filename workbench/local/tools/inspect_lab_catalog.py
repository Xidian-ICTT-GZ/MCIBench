"""Read-only inventory for extending the interactive question bank."""
from collections import Counter
import json

from local.common import DESCRIPTIONS_DIR, LANGS, load_ft_test_qids, load_reference, load_snippet
from local.harness.typespec import parse_python_snippet, PlainSig
from local.gen_testcases.extract_examples import extract_from_prompt
from local.gen_testcases.constraints import check


def write_index():
    from local.common import REPO_ROOT, save_json
    tags = {int(r['qid']): r for r in json.loads((REPO_ROOT / 'MCIBench-test/metadata/question_tags.json').read_text(encoding='utf-8'))}
    rows = []
    for folder in sorted(DESCRIPTIONS_DIR.iterdir(), key=lambda p: int(p.name)):
        qid = int(folder.name)
        files = sorted(folder.glob('*.txt'))
        title = next((p for p in files if 'English' not in p.name), files[0] if files else None)
        rows.append({'qid': qid, 'title': title.stem.split(' [')[0] if title else f'q{qid}',
                     'difficulty': tags.get(qid, {}).get('difficulty', 'Unknown'), 'tags': tags.get(qid, {}).get('tags', [])})
    save_json(REPO_ROOT / 'local/lab/data/problem_index.json', rows)
    return rows


def inventory():
    counts, sizes, ready = Counter(), Counter(), []
    ft = set(load_ft_test_qids())
    for folder in sorted(DESCRIPTIONS_DIR.iterdir(), key=lambda p: int(p.name)):
        qid = int(folder.name)
        counts['all'] += 1
        try:
            sig = parse_python_snippet(load_snippet(qid, 'python3'))
            if not isinstance(sig, PlainSig):
                continue
            counts['plain'] += 1
            path = next(folder.glob('*English*.txt'))
            cases = extract_from_prompt(path.read_text(encoding='utf-8'))
            cases = [c for c in cases if set(c['args']) == {p.name for p in sig.params} and not check(qid, c)]
            n = len({json.dumps(c['args'], sort_keys=True) for c in cases})
            sizes[n] += 1
            if n < 3 or qid in ft:
                continue
            languages = []
            for lang in LANGS:
                try:
                    load_snippet(qid, lang)
                    load_reference(qid, lang)
                    languages.append(lang)
                except (OSError, ValueError):
                    pass
            if languages:
                ready.append({'qid': qid, 'languages': languages, 'cases': cases,
                              'source': path.relative_to(DESCRIPTIONS_DIR).as_posix()})
        except (OSError, ValueError, KeyError, StopIteration, TypeError):
            continue
    return {'counts': dict(counts), 'case_counts': dict(sizes), 'candidates': ready}


if __name__ == '__main__':
    from pathlib import Path
    write_index()
    data = inventory()
    path = Path('local/results/catalog-inventory.json')
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'counts': data['counts'], 'case_counts': data['case_counts'],
                      'candidates': len(data['candidates']), 'output': str(path)}, ensure_ascii=False))
