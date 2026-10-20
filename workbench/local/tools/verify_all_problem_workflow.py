"""Resumable real API smoke runs; retain job IDs before starting work.

No credentials are accepted or exported. A terminal job is evidence of a run,
not proof of correctness for every problem in its family.
"""
import argparse
import json
from pathlib import Path
import urllib.request
import urllib.error

CASES={
    'linked-list':(2,'python3'), 'tree':(94,'python3'),
    'design':(146,'python3'), 'mutation':(443,'python3'), 'void':(344,'python3'),
    'database':(175,'sqlite'), 'shell':(193,'bash'),
    'dataframe':(2877,'python3'), 'callback':(2620,'javascript'),
    'hidden-api':(278,'python3'), 'saved-translation':(42,'cpp'),
    'probe-strategy':(3,'python3'),
    'cycle-entry':(142,'python3'),'intersection':(160,'python3'),'master-api':(843,'python3'),
    'next-pointer':(117,'python3'),'dataframe-dtype':(2886,'python3'),
    'instance-of':(2618,'javascript'),'counter':(2620,'javascript'),
    'timed-cache':(2622,'javascript'),'reduce':(2626,'javascript'),'debounce':(2627,'javascript'),
    'compose':(2629,'javascript'),'memoize-identity':(2630,'javascript'),'group-by':(2631,'javascript'),
    'filter':(2634,'javascript'),'map':(2635,'javascript'),'time-limit':(2637,'javascript'),
    'generator-cancel':(2650,'javascript'),'once':(2666,'javascript'),'call-polyfill':(2693,'javascript'),
    'expect':(2704,'javascript'),'timeout-cancel':(2715,'javascript'),'promise-all':(2721,'javascript'),
    'two-promises':(2723,'javascript'),'sort-by':(2724,'javascript'),'interval-cancel':(2725,'javascript'),
}


def main():
    ap=argparse.ArgumentParser(__doc__)
    ap.add_argument('--base-url',default='http://127.0.0.1:8090')
    ap.add_argument('--directory',type=Path,required=True)
    ap.add_argument('--profile')
    ap.add_argument('--queue',nargs='*',choices=CASES)
    ap.add_argument('--poll',action='store_true')
    args=ap.parse_args();args.directory.mkdir(parents=True,exist_ok=True)
    manifest_path=args.directory/'smoke-jobs.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf8')) if manifest_path.exists() else {}
    def request(path,body=None):
        req=urllib.request.Request(args.base_url+'/api/v1/lab/'+path,
            data=json.dumps(body).encode('utf8') if body is not None else None,
            headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=60) as response:return json.load(response)
    def save():manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    if args.queue:
        if not args.profile:ap.error('--profile is required to create real tasks')
        for name in args.queue:
            if name in manifest:
                recorded=request('jobs/'+manifest[name]['id'])
                if recorded['state']=='draft':
                    started=request('jobs/'+recorded['id']+'/run',{})
                    manifest[name]['state']=started['state'];save()
                print(name,manifest[name]['id'],'already recorded; not duplicated');continue
            qid,language=CASES[name]
            spec={'workflow_version':'generate-translate-local-v1','qids':[qid],
                'model_ids':[args.profile],'languages':[language],'num_candidates':1,
                'probe_count':2,'temperature':.7,'metamorphic_checks':False,
                'auto_testcases':True,'testcase_count':12,'task':'gen'}
            if name=='probe-strategy':spec.update(num_candidates=2,probe_count=4,probe_strategy='balanced',auto_testcases=False)
            if name=='saved-translation':
                sources=request('sources?qid=42&language=python3')['data']
                if not sources:raise SystemExit('no real generated Python source for q42')
                source=sources[0]
                spec.update(task='trans',source_mode='candidate',source_language='python3',
                    source_candidates={'42':{'job_id':source['job_id'],'candidate_id':source['candidate_id']}})
            job=request('jobs',{'title':'全题库流程验收 · '+name,'spec':spec})
            manifest[name]={'id':job['id'],'qid':qid,'language':language,'state':'draft'};save()
            try:
                started=request('jobs/'+job['id']+'/run',{})
                manifest[name]['state']=started['state'];save()
                print(name,job['id'],started['state'])
            except (urllib.error.URLError,TimeoutError) as error:
                print(name,job['id'],'start not confirmed:',str(error));break
    if args.poll:
        for name,row in manifest.items():
            job=request('jobs/'+row['id']);row['state']=job['state'];save()
            summary={'case':name,'id':job['id'],'state':job['state'],'stage':job['stage'],'error':job['error'],
                'groups':[{'qid':g['qid'],'language':g['language'],'interface':g.get('interface'),
                           'judging_state':g.get('judging_state'),'corpus_count':g.get('corpus_count'),
                           'answer_evidence':g.get('answer_evidence'),
                           'verdicts':[c.get('corpus_verdict') for c in g['candidates']]} for g in job.get('result',{}).get('groups',[])]}
            print(json.dumps(summary,ensure_ascii=False))
            if job['state'] not in ('queued','generating','evaluating','cancelling'):
                # Public API model records never include api_key.
                (args.directory/(name+'.json')).write_text(json.dumps(job,ensure_ascii=False,indent=2),encoding='utf8')


if __name__=='__main__':main()
