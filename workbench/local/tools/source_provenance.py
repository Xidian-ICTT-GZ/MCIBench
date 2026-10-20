"""Audit stored LC verdict provenance without changing code or formal results."""
import argparse
import csv
import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

from local.common import KEY_TO_LABEL
from local.dashboard.scripts.judge_all_models import ORIG_DB
from local.harness.identity import normalize_code
from local.tools.gap_workflow import ROOT, code_path, save, sha


def audit(slot, con):
    label = KEY_TO_LABEL[slot['lang']]
    code = code_path(slot).read_bytes()
    records = [dict(r) for r in con.execute(
        'SELECT code,file_path FROM gen_codes WHERE qid=? AND model_name=? '
        'AND language=? AND attempt_num=?',
        [slot['qid'], slot['model'], label, slot['cand']])]
    lc = [dict(r) for r in con.execute(
        'SELECT submit_id,source_type,source_dir,ac_status FROM submissions '
        'WHERE qid=? AND model_name=? AND language=? AND attempt_num=? '
        "AND source_type='generation'",
        [slot['qid'], slot['model'], label, slot['cand']])]
    stored_codes = {normalize_code(r['code']) for r in records if r['code']}
    originals = []
    for record in records:
        relative = Path(record['file_path'])
        candidates = [ROOT / relative, ROOT / 'MCIBench-test' / relative]
        parts = relative.parts
        if 'generation' in parts:
            candidates.append(ROOT / 'MCIBench-test' / Path(*parts[parts.index('generation'):]))
        for path in dict.fromkeys(candidates):
            if path.is_file():
                raw = path.read_bytes()
                originals.append({'path': str(path), 'sha256': sha(raw),
                    'matches_local_normalized': normalize_code(raw.decode('utf-8')) == normalize_code(code.decode('utf-8'))})
    payloads = []
    for record in lc:
        filename = f"{slot['qid']}_{slot['lang']}_{slot['cand']}.json"
        bases = [ROOT / 'MCIBench-test/generation/submissions',
                 ROOT / 'MCIBench-test/generation/submissions/submissions']
        for base in bases:
            path = base / record['source_dir'] / str(slot['qid']) / filename
            if not path.is_file():
                continue
            raw = path.read_bytes()
            payload = json.loads(raw)
            submitted = payload.get('typed_code') or payload.get('submitted_code') or payload.get('code')
            item = {'path': str(path), 'sha256': sha(raw), 'keys': sorted(payload),
                    'submit_id': payload.get('submit_id', payload.get('submission_id')),
                    'record_submit_id': record['submit_id'],
                    'status': payload.get('ac_status'), 'record_status': record['ac_status']}
            item['verdict_record_matches'] = (str(item['submit_id']) == str(record['submit_id'])
                                                and item['status'] == record['ac_status'])
            item['submitted_code_sha256'] = sha(submitted.encode()) if isinstance(submitted, str) else None
            item['submitted_code_matches_local'] = (normalize_code(submitted) == normalize_code(code.decode('utf-8'))
                                                    if isinstance(submitted, str) else None)
            payloads.append(item)
    confirmed = any(p['verdict_record_matches'] and p['submitted_code_matches_local'] is True for p in payloads)
    return {'id': f"{slot['qid']}-{slot['model']}-{slot['lang']}-{slot['cand']}",
            'qid': slot['qid'], 'model': slot['model'], 'lang': slot['lang'], 'cand': slot['cand'],
            'class': slot['klass'], 'lc_status': slot['leetcode'], 'local_status': slot['local'],
            'local_code_sha256': sha(code),
            'db_source_matches_local': len(stored_codes) == 1 and next(iter(stored_codes)) == normalize_code(code.decode('utf-8')),
            'db_source_count': len(records), 'original_files': originals,
            'lc_records': lc, 'lc_payloads': payloads, 'same_lc_source_confirmed': confirmed,
            'state': 'source_confirmed' if confirmed else 'blocked_source_evidence',
            'next_action': 'Export the actual submitted code for the recorded generation submit_id and bind its hash; '
                           'a stored verdict or a current submitter script does not prove historical source identity.'}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--job', type=Path, required=True)
    args = ap.parse_args()
    job = json.loads((args.job / 'job.json').read_bytes())
    slots = [t['slot'] for t in job['tasks']
             if t['slot']['klass'] == 'false_wa' or t['branch'] == 'environment']
    with closing(sqlite3.connect(ORIG_DB.resolve().as_uri() + '?mode=ro', uri=True)) as con:
        con.row_factory = sqlite3.Row
        rows = [audit(slot, con) for slot in slots]
    scripts = []
    for relative in ['MCIBench-test/scripts/CodeTest4.py', 'SFT/scripts/clean_submit_outputs.py']:
        path = ROOT / relative
        scripts.append({'path': str(path), 'sha256': sha(path.read_bytes()),
                        'scope': 'Current script evidence only; not proof of the historical submission path.'})
    save(args.job / 'source-provenance.json', {'items': rows, 'scripts': scripts,
         'states': dict(Counter(r['state'] for r in rows)), 'formal_results_modified': False})
    columns = ['id','qid','model','lang','cand','class','lc_status','local_status',
               'local_code_sha256','db_source_matches_local','same_lc_source_confirmed','state','submit_ids','next_action']
    with (args.job / 'source-provenance.csv').open('w', encoding='utf-8-sig', newline='') as out:
        writer = csv.DictWriter(out, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({**{k: row[k] for k in columns if k != 'submit_ids'},
                             'submit_ids': ';'.join(str(r['submit_id']) for r in row['lc_records'])})
    print(json.dumps({'slots': len(rows), 'states': dict(Counter(r['state'] for r in rows)),
                      'payloads_matching_verdict': sum(any(p['verdict_record_matches'] for p in r['lc_payloads']) for r in rows),
                      'db_source_matches_local': sum(r['db_source_matches_local'] for r in rows)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
