"""Read-only reconciliation of raw results, imported SQLite and the served API.

This verifies consistency, not completion: zero current rows may be consistent.
verify_release additionally requires the entire planned evaluation to be current.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote
from urllib.request import urlopen


def slot_key(row):
    return tuple(row.get(k) or '' for k in ('model', 'task', 'qid', 'lang', 'src_lang', 'tgt_lang', 'cand'))


def classify(lc, local, has_corpus):
    if not has_corpus:
        return 'no_corpus'
    if not local:
        return 'pending'
    if not lc:
        return 'no_lc'
    if local == lc:
        return 'agrees'
    if local == 'Accepted':
        return 'false_ac'
    if lc == 'Accepted':
        return 'false_wa'
    return 'same_neg'


def metrics(rows):
    comparable = [r for r in rows if r['has_corpus'] and r['local'] and r['leetcode']]
    classes = Counter(classify(r['leetcode'], r['local'], True) for r in comparable)
    matrix = Counter(('t' if r['leetcode'] == 'Accepted' else 'f',
                      'p' if r['local'] == 'Accepted' else 'n') for r in comparable)
    tp, fn, fp, tn = [matrix[k] for k in [('t', 'p'), ('t', 'n'), ('f', 'p'), ('f', 'n')]]
    n = len(comparable)
    return {'comparable_slots': n, 'agrees': classes['agrees'], 'same_neg': classes['same_neg'],
            'false_ac': fp, 'false_wa': fn, 'no_lc': sum(r['klass'] == 'no_lc' for r in rows),
            'tp': tp, 'fn': fn, 'fp': fp, 'tn': tn,
            'exact_agree_rate': classes['agrees'] / n if n else 0,
            'binary_agree_rate': (tp + tn) / n if n else 0,
            'miss_rate': fp / (fp + tn) if fp + tn else 0,
            'false_reject_rate': fn / (tp + fn) if tp + fn else 0,
            'rejected_but_lc_accepted_rate': fn / (fn + tn) if fn + tn else 0,
            'miss_rate_applicable': bool(fp + tn), 'false_reject_rate_applicable': bool(tp + fn)}


def reconcile(con, source_slots, raw_results, qids, excluded, corpus_counts):
    """Compare authoritative source/raw rows to DB, without rebuilding through importer."""
    errors = []
    con.row_factory = sqlite3.Row
    db_slots = [dict(r) for r in con.execute('SELECT * FROM slots')]
    db_results = [dict(r) for r in con.execute("SELECT * FROM local_results WHERE task='gen' AND run_name=model||'_local'")]
    problems = {r['qid']: dict(r) for r in con.execute('SELECT * FROM problems')}
    actual_ft = {q for q, r in problems.items() if r['in_ft_test']}
    if actual_ft != set(qids):
        errors.append('problems: FT_test set differs from authoritative plan')
    for q in qids:
        if problems.get(q, {}).get('corpus_cases') != corpus_counts.get(q, 0):
            errors.append(f'problem {q}: corpus count differs')
    if dict(con.execute('SELECT model,reason FROM excluded_models')) != excluded:
        errors.append('excluded model policy differs')

    def index(rows, name):
        out = {}
        for row in rows:
            key = slot_key(row)
            if key in out:
                errors.append(f'{name}: duplicate slot {key}')
            out[key] = row
        return out

    source = index([s for s in source_slots if s['model'] not in excluded], 'source')
    scoped = index([s for s in db_slots if s['lc_origin'] == 'submissions' and s['qid'] in qids], 'slots')
    if source.keys() != scoped.keys():
        errors.append(f'submission slot set differs: missing={len(source.keys()-scoped.keys())}, extra={len(scoped.keys()-source.keys())}')
    raw = index(raw_results, 'raw')
    stored = index(db_results, 'local_results')
    if raw.keys() != stored.keys():
        errors.append(f'raw/local_results set differs: missing={len(raw.keys()-stored.keys())}, extra={len(stored.keys()-raw.keys())}')
    result_fields = ('state', 'ac_status', 'total_testcases', 'total_correct', 'runtime', 'memory', 'identity_status')
    for key in raw.keys() & stored.keys():
        for field in result_fields:
            if raw[key].get(field) != stored[key].get(field):
                errors.append(f'local_results {key}: {field} differs')
        try:
            if json.loads(stored[key].get('identity_json') or 'null') != raw[key].get('_identity'):
                errors.append(f'local_results {key}: identity evidence differs')
        except (ValueError, TypeError):
            errors.append(f'local_results {key}: invalid identity JSON')

    for key in source.keys() & scoped.keys():
        s, db = source[key], scoped[key]
        if s['leetcode'] != db['leetcode']:
            errors.append(f'slot {key}: LC verdict differs from source')
        if key in raw:
            expected = raw[key]
            for field, value in [('local', expected['ac_status']), ('local_origin', 'all_models'),
                                 ('identity_status', expected['identity_status'])]:
                if db.get(field) != value:
                    errors.append(f'slot {key}: {field} differs from raw')
        elif db['local_origin'] == 'all_models' or db['identity_status'] == 'current':
            errors.append(f'slot {key}: claims current/all_models without raw evidence')

    for db in db_slots:
        key = slot_key(db)
        if db['identity_status'] == 'current' and (key not in raw or raw[key]['identity_status'] != 'current'):
            errors.append(f'slot {key}: unsupported current status')
        has = int(corpus_counts.get(db['qid'], 0) > 0)
        if db['has_corpus'] != has or db['klass'] != classify(db['leetcode'], db['local'], has):
            errors.append(f'slot {key}: corpus/classification differs')
        if db['stale'] != int(db['identity_status'] != 'current'):
            errors.append(f'slot {key}: stale flag contradicts identity')
    coverage = dict.fromkeys(('planned', 'current', 'stale', 'unverifiable', 'missing'), 0)
    coverage['planned'] = len(scoped)
    for row in scoped.values():
        status = row['identity_status']
        if status not in coverage or status == 'planned':
            errors.append(f'unknown coverage status: {status}')
        else:
            coverage[status] += 1
    current = [s for s in scoped.values() if s['identity_status'] == 'current' and s['local_origin'] == 'all_models']
    return errors, {'coverage': coverage, 'metrics': metrics(current), 'current_rows': current,
                    'source_models': sorted({s['model'] for s in source.values()}), 'qids': sorted(qids),
                    'raw_rows': len(raw), 'stored_raw_rows': len(stored)}


def verify_api(base_url, snapshot):
    errors = []
    def get(path):
        with urlopen(base_url.rstrip('/') + '/api/v1/' + path, timeout=15) as r:
            return json.load(r)
    def check(actual, expected, label):
        for field, value in expected.items():
            got = actual.get(field)
            matches = abs(got - value) < 1e-10 if type(value) is float and type(got) in (float, int) else got == value
            if not matches:
                errors.append(f'API {label}.{field}: expected {value!r}, got {got!r}')
    overview = get('stats/overview')
    check(overview.get('coverage', {}), snapshot['coverage'], 'coverage')
    check(overview.get('metrics', {}), snapshot['metrics'], 'metrics')
    check(overview, {'slots': len(snapshot['current_rows']),
                     'comparable_slots': snapshot['metrics']['comparable_slots'],
                     'agreeing_slots': snapshot['metrics']['agrees'],
                     'agree_rate': snapshot['metrics']['exact_agree_rate']}, 'overview')
    rows = snapshot['current_rows']
    agreement = get('stats/agreement')
    by_model = {r['model_name']: r for r in agreement.get('by_model', [])}
    expected_models = set()
    for model in snapshot['source_models']:
        group = [r for r in rows if r['model'] == model]
        m = metrics(group)
        expected = {'total': m['comparable_slots'], 'agrees': m['agrees'], 'agree_rate': m['exact_agree_rate']}
        check(get('stats/model/' + quote(model, safe='')), expected, 'model/' + model)
        if m['comparable_slots']:
            expected_models.add(model)
            check(by_model.get(model, {}), expected, 'agreement/' + model)
    if by_model.keys() != expected_models:
        errors.append('API agreement model set differs')
    by_problem = {r['qid']: r for r in agreement.get('by_problem', [])}
    expected_problems = set()
    for qid in snapshot['qids']:
        group = [r for r in rows if r['qid'] == qid]
        m = metrics(group)
        detail = get(f'problems/{qid}?page_size=200')
        check(detail, {'total': len(group)}, f'problem/{qid}')
        check(detail.get('metrics', {}), m, f'problem/{qid}/metrics')
        received = list(detail.get('slots', []))
        for page in range(2, (len(group) + 199) // 200 + 1):
            received.extend(get(f'problems/{qid}?page_size=200&page={page}').get('slots', []))
        fields = ('model', 'task', 'lang', 'cand', 'leetcode', 'local', 'klass')
        if Counter(tuple(r.get(k) for k in fields) for r in received) != Counter(tuple(r.get(k) for k in fields) for r in group):
            errors.append(f'API problem/{qid}: paginated rows differ')
        if m['comparable_slots']:
            expected_problems.add(qid)
            check(by_problem.get(qid, {}), {'total': m['comparable_slots'], 'agrees': m['agrees'],
                    'false_ac': m['false_ac'], 'false_wa': m['false_wa']}, f'agreement/problem/{qid}')
    if by_problem.keys() != expected_problems:
        errors.append('API agreement problem set differs')
    return errors


def verify_served_build(base_url):
    import hashlib
    from local.tools.build_dashboard import SERVER, current_build_id
    errors = []
    manifest = json.loads((SERVER/'build-manifest.json').read_text(encoding='utf-8'))
    expected = current_build_id()
    if manifest.get('build_id') != expected:
        errors.append('dashboard build manifest does not match current source')
    binary = SERVER/'local-dashboard-server.exe'
    if hashlib.sha256(binary.read_bytes()).hexdigest() != manifest.get('binary_sha256'):
        errors.append('server binary differs from build manifest')
    with urlopen(base_url.rstrip('/')+'/api/v1/version', timeout=15) as response:
        if json.load(response).get('build_id') != expected:
            errors.append('running server does not expose the current source build ID')
    if not manifest.get('assets') or 'index.html' not in manifest['assets']:
        errors.append('frontend assets missing from build manifest')
    for asset, digest in manifest.get('assets', {}).items():
        with urlopen(base_url.rstrip('/')+'/'+quote(asset, safe='/'), timeout=15) as response:
            if hashlib.sha256(response.read()).hexdigest() != digest:
                errors.append(f'served frontend asset differs from build: {asset}')
    return errors


def audit_database(db_path=None, base_url=None):
    from local.common import LABEL_TO_KEY, TESTCASES_DIR, load_ft_test_qids
    from local.dashboard.scripts import import_local_results as importer
    qids = set(load_ft_test_qids())
    sources, errors = [], []
    with sqlite3.connect(importer.ORIG_DB.resolve().as_uri() + '?mode=ro', uri=True) as source:
        for qid, model, label, src, tgt, cand, lc in source.execute(
                "SELECT qid,model_name,language,src_lang,tgt_lang,attempt_num,ac_status "
                "FROM submissions WHERE attempt_num=1 AND source_type='generation'"):
            if qid in qids and label in LABEL_TO_KEY:
                sources.append(dict(qid=qid, model=model, task='gen', lang=LABEL_TO_KEY[label],
                                    src_lang=src or '', tgt_lang=tgt or '', cand=cand, leetcode=lc or ''))
    raw = []
    pattern = re.compile(r'^(\d+)_([a-zA-Z0-9#]+)_(\d+)\.json$')
    for path in sorted(importer.ALL_MODELS.glob('*/results/*/*.json')):
        match = pattern.fullmatch(path.name)
        if not match:
            continue
        qid, lang, cand = int(match[1]), match[2], int(match[3])
        model = path.parents[2].name
        if path.parent.name != str(qid):
            errors.append(f'raw result in wrong question directory: {path}')
            continue
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
            status, reason = importer.inspect_result(payload, model=model, qid=qid, lang=lang, cand=cand)
            row = dict(payload, qid=qid, model=model, task='gen', lang=lang, src_lang='', tgt_lang='', cand=cand,
                       identity_status=status, identity_reason=reason)
            raw.append(row)
        except Exception as exc:
            errors.append(f'raw result {path}: {exc}')
    corpus_counts = {int(p.parent.name): len(json.loads(p.read_text(encoding='utf-8')))
                     for p in TESTCASES_DIR.glob('*/cases.json') if p.parent.name.isdigit()}
    path = Path(db_path or importer.OUT_DB)
    con = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        con.execute('BEGIN')  # one consistent SQLite snapshot, including committed WAL
        db_errors, snapshot = reconcile(con, sources, raw, qids, importer.EXCLUDED_MODELS, corpus_counts)
        errors.extend(db_errors)
    finally:
        con.close()
    if base_url:
        try:
            errors.extend(verify_api(base_url, snapshot))
            errors.extend(verify_served_build(base_url))
        except Exception as exc:
            errors.append(f'served API unavailable: {exc}')
    return errors, snapshot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', type=Path)
    ap.add_argument('--base-url')
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    errors, snapshot = audit_database(args.db, args.base_url)
    report = {k: v for k, v in snapshot.items() if k != 'current_rows'}
    report.update(errors=errors, consistency_passed=not errors,
                  note='Consistency only; does not prove full evaluation completion.')
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(bool(errors))


if __name__ == '__main__':
    main()
