"""Checkpointed full-bank readiness and LLM-generated test admission; no LC submissions."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from local.common import DESCRIPTIONS_DIR, REPO_ROOT, LANGS
from local.harness import runner
from local.harness.identity import image_digest
from local.lab.generation import GenerationError
from local.lab.storage import Store
from local.lab.testcase_workflow import preflight, build, save, VERSION, read_bundle


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['plan', 'run', 'status'])
    ap.add_argument('--folder', type=Path, required=True)
    ap.add_argument('--qids', default='')
    ap.add_argument('--profile', default='')
    ap.add_argument('--target', type=int, default=30)
    ap.add_argument('--limit', type=int, default=3, help='question budget per invocation; at most three model calls per question')
    ap.add_argument('--languages', nargs='+', choices=LANGS, default=['python3', 'cpp'])
    ap.add_argument('--retry-failed', action='store_true')
    args = ap.parse_args()
    if not 12 <= args.target <= 100 or not 1 <= args.limit <= 20:
        ap.error('target must be 12–100; limit must be 1–20')
    path = args.folder / 'plan.json'
    args.folder.mkdir(parents=True, exist_ok=True)
    selected = {int(q.strip()) for q in args.qids.split(',') if q.strip()}
    if args.action == 'plan':
        if path.exists():
            raise SystemExit('Plan exists; use a new folder or continue the existing plan.')
        tasks = []
        for folder in sorted(DESCRIPTIONS_DIR.iterdir(), key=lambda p: int(p.name)):
            qid = int(folder.name)
            if selected and qid not in selected:
                continue
            row = {'qid': qid, 'state': 'pending', 'leetcode_alignment': 'not_measured'}
            try:
                preflight(qid, args.languages)
            except (ValueError, OSError) as error:
                row.update(state='blocked_review', reason=str(error))
            tasks.append(row)
        plan = {'version': VERSION, 'target': args.target, 'languages': args.languages, 'tasks': tasks,
                'notice': 'Only verified generated tests are published. Full LeetCode alignment is not established.'}
        save(path, plan)
    else:
        plan = json.loads(path.read_text(encoding='utf-8'))
    if args.action == 'run':
        store = Store(REPO_ROOT / 'local/dashboard/packages/server/data/lab.sqlite3')
        profiles = [p for p in store.profiles() if p['enabled']]
        profile_id = args.profile or (profiles[-1]['id'] if profiles else '')
        profile = store.profile(profile_id, private=True)
        if not profile['enabled']:
            raise SystemExit('Model profile is disabled')
        runner.DOCKER_IMAGE = image_digest()
        done = 0
        for task in plan['tasks']:
            qid = task['qid']
            if selected and qid not in selected:
                continue
            if task['state'] == 'blocked_review':
                if not args.retry_failed:
                    continue
            elif task['state'] not in ('pending', 'running') and not args.retry_failed:
                continue
            if done >= args.limit:
                break
            task.update(state='running')
            task.pop('reason', None)
            task.pop('code', None)
            save(path, plan)
            def event(update):
                task['stage'] = update['stage']
                task['generated_count'] = update.get('generated_count', task.get('generated_count', 0))
                save(path, plan)
                if update['stage'] not in ('test_input_progress', 'test_input_response'):
                    print(qid, update['stage'], flush=True)
            try:
                result = build(qid, profile, plan['target'], plan['languages'], runner.DOCKER_IMAGE, on_event=event)
                task.update(state='verified', generated_count=len(result['generated_cases']),
                            cases_sha256=result['cases_sha256'], leetcode_alignment='not_measured')
            except GenerationError as error:
                task.update(state='blocked_api', reason=str(error), code=error.code)
                save(path, plan)
                print(qid, 'blocked_api', error.code, flush=True)
                # Provider-wide failure is a circuit breaker, not a reason to bill every question.
                break
            except (ValueError, OSError) as error:
                task.update(state='blocked_verification', reason=str(error))
            save(path, plan)
            done += 1
        save(path, plan)
    print(json.dumps({'total': len(plan['tasks']), 'states': dict(Counter(t['state'] for t in plan['tasks'])),
                      'target': plan['target'], 'checkpoint': str(path)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
