"""Snapshot real workflow progress and verify completed, frozen evidence.

This verifies this 20-problem protocol batch, never the whole catalog's runtime
coverage or LeetCode equivalence. No model calls or source/result rewrites.
"""
import argparse
import json
from pathlib import Path
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from local.lab.behavior import sha
from local.lab import javascript_references,problem_packages,native_adapters


def main():
    ap=argparse.ArgumentParser(__doc__);ap.add_argument('--directory',type=Path,required=True);args=ap.parse_args()
    path=args.directory;manifest=json.loads((path/'jobs.json').read_text(encoding='utf8'))
    def api(endpoint):return json.load(urllib.request.urlopen('http://127.0.0.1:8090/api/v1/'+endpoint,timeout=60))
    report={'scope':'20_special_javascript_problems_and_two_translation_entries','version':api('version'),'jobs':[],'errors':[],'pending':[]}
    qids=set()
    for name,row in manifest.items():
        job=api('lab/jobs/'+row['id']);terminal=job['state'] not in ('queued','generating','evaluating','cancelling')
        summary={'name':name,'id':job['id'],'state':job['state'],'stage':job['stage'],'error':job['error'],'groups':[]}
        if terminal:(path/(name+'.json')).write_text(json.dumps(job,ensure_ascii=False,indent=2),encoding='utf8')
        else:report['pending'].append(job['id'])
        for group in job.get('result',{}).get('groups',[]):
            qid=group['qid'];result={'qid':qid,'language':group['language'],'judging_state':group.get('judging_state'),'status':[]}
            summary['groups'].append(result)
            if group.get('judging_state')!='completed':
                if terminal:report['errors'].append({'job_id':job['id'],'qid':qid,'reason':group.get('judging_error','judging incomplete')})
                continue
            snapshot=next(x for x in job['result']['inputs'] if x['qid']==qid)
            cases=snapshot['full_corpus'];result['case_count']=len(cases)
            result['execution_protocol']=group['answer_evidence']['execution_protocol']
            for candidate in group['candidates']:
                verdict=candidate['corpus_verdict'];result['status'].append(verdict['ac_status'])
                if candidate['code_sha256']!=sha(candidate['code']) or verdict['cases_sha256']!=sha(cases) or verdict['total_testcases']!=len(cases):
                    report['errors'].append({'job_id':job['id'],'qid':qid,'reason':'source/corpus binding mismatch'})
            if name in ('1','2'):
                qids.add(qid);plan=group['native_adapter'];injection=plan['entry_injection_gate']
                if not native_adapters.native_javascript.observed_entry(injection,native_adapters.SENTINEL) or not any(x['passed'] for x in plan['output_sensitivity_gates']):
                    report['errors'].append({'job_id':job['id'],'qid':qid,'reason':'native observation gates incomplete'})
            else:
                source=group['source_snapshot'];result['source_sha256']=source['code_sha256'];result['source_contract_sha256']=source.get('input_contract',{}).get('sha256')
                if sha(source['code'])!=source['code_sha256'] or not result['source_contract_sha256']:report['errors'].append({'job_id':job['id'],'qid':qid,'reason':'translation source/contract unbound'})
        report['jobs'].append(summary)
        print(json.dumps(summary,ensure_ascii=False))
    report['completed_native_qids']=sorted(qids);report['missing_native_qids']=sorted(set(javascript_references.SOURCES)-qids)
    report['batch_complete']=not report['pending'] and not report['errors'] and not report['missing_native_qids'] and {'translation-generate','translation-candidate'}<=set(manifest)
    metrics=api('stats/overview')['metrics'];report['history']={k:metrics[k] for k in ('comparable_slots','fp','fn')}
    if report['history']!={'comparable_slots':7148,'fp':70,'fn':43}:report['errors'].append({'reason':'historical metrics changed'});report['batch_complete']=False
    report['notice']='Batch completion is finite workflow evidence, not whole-catalog runtime coverage, functional accuracy or LeetCode equivalence.'
    (path/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    raise SystemExit(bool(report['errors']))


if __name__=='__main__':main()
