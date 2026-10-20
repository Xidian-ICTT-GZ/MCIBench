"""Re-execute frozen task candidates without modifying stored tasks or sources."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from local.harness import runner
from local.harness.identity import image_digest
from local.lab.pipeline_jobs import execute
from local.lab.behavior import sha
from local.lab.evidence_advisories import for_job


def main():
    ap=argparse.ArgumentParser(__doc__);ap.add_argument('--jobs',nargs='+',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--completed-only',action='store_true',help='Replay completed groups only; explicitly retain all excluded/ungraded groups in the report.')
    ap.add_argument('--exclude-invalidated',action='store_true',help='Exclude invalidated corpus/execution evidence explicitly, never count it as passed quality evidence.')
    args=ap.parse_args()
    runner.DOCKER_IMAGE=image_digest();report={'image':runner.DOCKER_IMAGE,'checks':[],'ungraded_groups':[],'invalidated_groups':[]}
    for path in args.jobs:
        job=json.loads(path.read_text(encoding='utf8'))
        invalid={x['qid']:x for x in for_job(job)}
        for group in job['result']['groups']:
            if group['qid'] in invalid:
                if not args.exclude_invalidated:raise ValueError('known invalidated judging evidence; this historical verdict is not quality evidence')
                report['invalidated_groups'].append({'job_id':job['id'],'qid':group['qid'],'language':group['language'],'advisory':invalid[group['qid']]})
                print(group['qid'],group['language'],'SKIPPED invalidated corpus',flush=True);continue
            if group.get('judging_state')!='completed':
                if not args.completed_only:raise ValueError('task contains ungraded groups; use explicit --completed-only for a partial replay')
                report['ungraded_groups'].append({'job_id':job['id'],'qid':group['qid'],'language':group['language'],'reason':group.get('judging_error')})
                continue
            snapshot=next(s for s in job['result']['inputs'] if s['qid']==group['qid'])
            for candidate in group['candidates']:
                if candidate['code_sha256']!=sha(candidate['code']):raise ValueError('candidate source fingerprint mismatch')
                verdict=execute(group['qid'],group['language'],candidate['code'],snapshot['full_corpus'],snapshot['comparison'],group.get('native_adapter'),full=True)
                old=candidate['corpus_verdict'];passed=verdict['ac_status']==old['ac_status']
                report['checks'].append({'job_id':job['id'],'qid':group['qid'],'language':group['language'],'candidate_id':candidate['id'],
                    'source_sha256':candidate['code_sha256'],'cases_sha256':sha(snapshot['full_corpus']),'original_status':old['ac_status'],
                    'current_status':verdict['ac_status'],'passed':passed,'verdict':verdict})
                args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
                print(group['qid'],group['language'],verdict['ac_status'],'PASS' if passed else 'FAIL',flush=True)
                if not passed:raise SystemExit(1)
    print('frozen replay failures: 0; candidates:',len(report['checks']))


if __name__=='__main__':main()
