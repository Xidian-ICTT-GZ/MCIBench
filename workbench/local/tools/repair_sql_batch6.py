"""Explicitly migrate retained SQL inputs after reviewed numeric/email fixes.

No model calls, candidate repairs, historical result rewrites, or gate bypasses.
Each publication retains original evidence and requires every execution gate.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from local.harness import runner
from local.harness.identity import image_digest
from local.lab import problem_packages as packages,problem_io as io,sql_answers as sql,portable_judging as judging
from local.lab.behavior import sha
from local.lab.testcase_workflow import lock,save


def fixtures(qid,base):
    result=[]
    def add(args):result.append({'args':args,'expected':sql.answer(qid,args),'origin':'reviewed_numeric_or_email_boundary'})
    if qid==1517:
        args=deepcopy(base)
        mails=['a@leetcode.com','A.z_-9@leetcode.com','a@LeetCode.com','é@leetcode.com','a@leetcode.com\n','a@leetcode.com\r\n','a@leetcode.com ','1a@leetcode.com','a@@leetcode.com','a@leetcodeXcom','A@leetcode.com']
        args['tables']['Users']['rows']=[[i+1,'User'+str(i+1),mail] for i,mail in enumerate(mails)];add(args)
    elif qid==1633:
        for n in (3,6,7,16,32,64,128,201,512,800,1001,1999,2000):
            args=deepcopy(base)
            args['tables']['Users']['rows']=[[i,'User'+str(i)] for i in range(1,n+1)]
            args['tables']['Register']['rows']=[[contest,i] for contest,count in enumerate(sorted({1,max(1,n//2),n-1,n}),1) for i in range(1,count+1)]
            add(args)
    else:
        for start,end in ((1,1.0005),(0,.0045),(1,1.0015),(0,.0005),(10,10.0045),(0,.0001),(0,.001),(1,2)):
            args=deepcopy(base);args['tables']['Activity']['rows']=[[0,0,'start',start],[0,0,'end',end]];add(args)
        for seed in range(1,31):
            args=deepcopy(base)
            args['tables']['Activity']['rows']=[[0,i,k,t] for i in range(1+seed%10) for k,t in (('start',i/1000),('end',(i+seed)/1000))];add(args)
    return result


def main():
    ap=argparse.ArgumentParser(__doc__);ap.add_argument('--output',required=True,type=Path);args=ap.parse_args()
    runner.DOCKER_IMAGE=image_digest();report={'version':sql.VERSION,'checks':[],'no_models_called':True,'historical_jobs_unchanged':True}
    for qid in (1517,1633,1661):
        with lock(qid,packages.DATA_DIR):
            path=packages.DATA_DIR/f'{qid}.json';old=json.loads(path.read_text(encoding='utf8'))
            unsigned=deepcopy(old);digest=unsigned.pop('package_sha256');assert sha(unsigned)==digest
            if old.get('reviewed_migration',{}).get('version')==sql.VERSION:
                assert packages.read(qid,runner.DOCKER_IMAGE) is not None
                print(qid,'already migrated; not republished',flush=True);continue
            save(packages.DATA_DIR/'archive'/str(qid)/(digest+'.json'),old)
            archive=args.output.parent/'before'/'attempts';archive.mkdir(parents=True,exist_ok=True)
            for folder in (packages.DATA_DIR/'attempts',ROOT/'local/dashboard/packages/server/data/lab_mysql_gates/attempts'):
                for evidence in folder.glob(f'{qid}-*.json'):
                    shutil.copy2(evidence,archive/(folder.parent.name+'-'+evidence.name))
            descriptor=packages.describe(qid);binding=packages.binding(qid,runner.DOCKER_IMAGE,descriptor)
            cases=deepcopy(descriptor['official']);changes=[]
            for i,case in enumerate(old['cases'][1:],1):
                expected=sql.answer(qid,case['args'])
                if not judging.compare(qid,expected,case,old['comparison']):changes.append({'old_case_index':i,'args':case['args'],'old_expected':case['expected'],'reviewed_expected':expected})
                cases.append({**deepcopy(case),'expected':expected})
            existing={sha(c['args']) for c in cases};added=[]
            for case in fixtures(qid,descriptor['official'][0]['args']):
                if sha(case['args']) in existing:continue
                cases.append(case);added.append(sha(case['args']));existing.add(sha(case['args']))
            for case in cases:
                io.input_valid_shape(case['args']);io.check_database_input(qid,case['args'],descriptor['official'][0]['args'])
                assert sql.valid(qid,case['args']) is True
                assert judging.compare(qid,sql.answer(qid,case['args']),case,descriptor['comparison'])
            validator=judging.execute(0,'python3',old['validator']['code'],[{'args':c['args'],'expected':True} for c in cases])
            if validator['ac_status']!='Accepted':raise ValueError(f'q{qid} retained validator rejected reviewed boundary input; no publication')
            oracles=[];gates=[]
            for language in ('python3','sqlite','mysql') if qid==1517 else ('python3','mysql'):
                code=sql.reference(qid,language);assert code
                gate=judging.execute(qid,language,code,cases,descriptor['comparison'])
                record={'language':language,'code':code,'code_sha256':sha(code),'origin':'reviewed_sql_reference','controller_version':sql.VERSION}
                oracles.append(record);gates.append({'language':language,'verdict':gate})
                save(args.output,{'checks':report['checks'],'in_progress':{'qid':qid,'gates':gates,'changed_answers':changes}})
                if gate['ac_status']!='Accepted':raise ValueError(f'q{qid} {language} failed full migration gate; no publication')
            assert binding==packages.binding(qid,runner.DOCKER_IMAGE,descriptor)
            migration={'version':sql.VERSION,'previous_package_sha256':digest,'retained_model_input_count':old['generated_count'],
                'retained_model_input_sha256':[sha(c['args']) for c in old['cases'][1:]],'reviewed_added_input_sha256':added,
                'changed_answers':changes,'validator_gate':validator}
            row={**deepcopy(old),'binding':binding,'descriptor':descriptor,'cases':cases,'cases_sha256':sha(cases),
                'comparison':descriptor['comparison'],'oracles':oracles,'gates':gates,'gates_passed':True,
                'reference_languages':[o['language'] for o in oracles],'evidence_level':'reviewed_sql_controller_and_executed_oracles',
                'constraint_evidence':'reviewed_sql_input_scope_and_retained_validator',
                'oracle_scope':{'max_rows':sql.MAX_ROWS[qid],'version':sql.VERSION,'description':sql.note(qid)},
                'reviewed_migration':migration,'reviewed_added_case_count':len(added),
                'limitations':['finite_tests_not_proof','explicit_native_numeric_or_email_scope_not_global_lc_equivalence']}
            row.pop('package_sha256',None);row['package_sha256']=sha(row);save(path,row)
            report['checks'].append({'qid':qid,'case_count':len(cases),'retained_generated_count':old['generated_count'],
                'reviewed_added_count':len(added),'changed_answers':changes,'gates':gates,'package_sha256':row['package_sha256'],'passed':True})
            save(args.output,report);print(qid,len(cases),'cases; revised answers',len(changes),'PASS',flush=True)
    print('Reviewed migration completed without model calls or historical result rewrites',flush=True)


if __name__=='__main__':main()
