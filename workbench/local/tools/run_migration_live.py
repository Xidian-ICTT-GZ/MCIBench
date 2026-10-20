"""Run the frozen migration sample through the live API with real model candidates.

One combination is one (problem, language) pair with at least one real generated
candidate. Languages the catalogue never admitted for that problem are recorded as
blocked, not silently skipped. Results are written after every combination so an
interrupted run still leaves usable evidence.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
LANGUAGES = ('python3', 'c', 'cpp', 'java', 'javascript', 'csharp', 'golang', 'rust')


def call(base, method, path, body=None, cookie=None):
    data = json.dumps(body if body is not None else {}).encode() if method != 'GET' else None
    request = urllib.request.Request(base + path, data=data, method=method)
    if data is not None:
        request.add_header('Content-Type', 'application/json')
    if cookie:
        request.add_header('Cookie', cookie)
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            payload = response.read()
            return response.status, json.loads(payload or b'{}'), response.headers.get_all('Set-Cookie') or []
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode('utf-8', 'replace'), error.headers.get_all('Set-Cookie') or []


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8093/api/v1')
    parser.add_argument('--username', default='admin')
    parser.add_argument('--password-file', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', default='')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--job-timeout', type=int, default=600)
    args = parser.parse_args()

    password = args.password_file.read_text(encoding='utf-8').strip()
    status, _, cookies = call(args.base, 'POST', '/auth/login',
                              {'username': args.username, 'password': password})
    if status == 404:
        # Authentication is switched off on this instance: the lab proxy is open.
        cookie = None
        print('authentication disabled on this instance; continuing without a session')
    elif status != 200:
        raise SystemExit('login failed: %s' % status)
    else:
        cookie = next(x.split(';')[0] for x in cookies if x.startswith('mcibench_session='))
    models = call(args.base, 'GET', '/lab/models', cookie=cookie)[1]['data']
    candidates = [m for m in models if m.get('enabled') and m.get('credential_configured')]
    model = next((m for m in candidates if m['id'] == args.model), None) if args.model else None
    if model is None:
        # Prefer the profile with the largest output budget: a reasoning model can
        # spend the whole allowance on deliberation and return no code at all.
        deepseek = [m for m in candidates if 'deepseek' in m['model_name']] or candidates
        model = max(deepseek, key=lambda m: (m.get('max_tokens') or 0,
                                             not m.get('enable_thinking')))

    catalog = json.loads((ROOT / 'local/lab/data/catalog_extension.json').read_text(encoding='utf-8'))
    admitted = {int(row['qid']): list(row.get('languages') or []) for row in catalog['problems']}
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))

    report = {'version': 'migration-live-v1', 'model': {'id': model['id'], 'name': model['name'],
                                                         'model_name': model['model_name']},
              'manifest_sha256': manifest['list_sha256'],
              'started_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'combinations': [], 'blocked': []}
    if args.resume and args.output.exists():
        report = json.loads(args.output.read_text(encoding='utf-8'))
    done = {(row['qid'], row['language']) for row in report['combinations']}
    blocked = {(row['qid'], row['language']) for row in report['blocked']}

    ran = 0
    for item in manifest['selected']:
        qid = item['qid']
        for language in LANGUAGES:
            if (qid, language) in done or (qid, language) in blocked:
                continue
            if language not in admitted.get(qid, []):
                report['blocked'].append({'qid': qid, 'language': language,
                                          'reason': 'language_not_admitted_for_this_problem'})
                continue
            spec = {'qids': [qid], 'model_ids': [model['id']], 'languages': [language],
                    'task': 'gen', 'source_language': 'python3', 'num_candidates': 2,
                    'probe_count': 4, 'temperature': 0.3, 'auto_testcases': False,
                    'probe_strategy': 'balanced'}
            started = time.time()
            status, created, _ = call(args.base, 'POST', '/lab/jobs',
                                      {'title': '迁移 %d/%s' % (qid, language), 'spec': spec}, cookie=cookie)
            if status not in (200, 201):
                report['blocked'].append({'qid': qid, 'language': language,
                                          'reason': 'create_failed: %s' % str(created)[:160]})
                continue
            job_id = created['id']
            call(args.base, 'POST', '/lab/jobs/%s/run' % job_id, {}, cookie=cookie)
            # A job that never reaches a terminal state must not hang the run: the
            # first version of this tool waited forever and had to be killed twice.
            job = None
            deadline = time.time() + args.job_timeout
            while time.time() < deadline:
                time.sleep(3)
                job = call(args.base, 'GET', '/lab/jobs/' + job_id, cookie=cookie)[1]
                if isinstance(job, dict) and job.get('state') in ('completed', 'failed', 'cancelled'):
                    break
            if not isinstance(job, dict) or job.get('state') not in ('completed', 'failed', 'cancelled'):
                job = {'state': 'timed_out', 'error': 'polling timeout', 'result': {}}
            elapsed = round(time.time() - started, 1)
            result = job.get('result') or {}
            groups = result.get('groups') or []
            row = {'qid': qid, 'language': language, 'job_id': job_id, 'state': job.get('state'),
                   'seconds': elapsed, 'error': str(job.get('error'))[:200],
                   'candidates': [
                       {'index': c.get('index'),
                        'ac_status': (c.get('corpus_verdict') or {}).get('ac_status'),
                        'correct': (c.get('corpus_verdict') or {}).get('total_correct'),
                        'total': (c.get('corpus_verdict') or {}).get('total_testcases'),
                        'code_sha256': c.get('code_sha256'),
                        'code_length': len(c.get('code') or '')}
                       for group in groups for c in (group.get('candidates') or [])],
                   'answer_evidence': bool(groups and groups[0].get('answer_evidence'))}
            report['combinations'].append(row)
            ran += 1
            args.output.parent.mkdir(parents=True, exist_ok=True)
            report['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
            print('%d/%s -> %s (%ss) %s' % (qid, language, row['state'], elapsed,
                                            [c['ac_status'] for c in row['candidates']]), flush=True)
            if args.limit and ran >= args.limit:
                break
        if args.limit and ran >= args.limit:
            break

    report['finished_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print('combinations:', len(report['combinations']), '| blocked:', len(report['blocked']))


if __name__ == '__main__':
    main()
