"""Migrate typed DATE inputs, reject an illegal flag case and add a legal bonus witness.

Retain original artifacts and candidate sources. Incomplete input targets seed
the existing bounded model-input workflow; they are not padded with constants.
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

PRIMARY_VALIDATOR='''def solve(data):
 if type(data) is not dict or set(data)!={'tables'}:return False
 tables=data['tables']
 if type(tables) is not dict or set(tables)!={'Employee'}:return False
 table=tables['Employee']
 if type(table) is not dict or not {'columns','rows'}<=set(table)<={'columns','rows','types'}:return False
 if table['columns']!=['employee_id','department_id','primary_flag']:return False
 if table.get('types',['INTEGER','INTEGER','TEXT'])!=['INTEGER','INTEGER','TEXT']:return False
 rows=table['rows']
 if type(rows) is not list or len(rows)>2000:return False
 keys=set();counts={};primary={}
 for row in rows:
  if type(row) is not list or len(row)!=3:return False
  employee,department,flag=row
  if type(employee) is not int or not -(2**31)<=employee<2**31:return False
  if type(department) is not int or not -(2**31)<=department<2**31:return False
  if flag not in ('Y','N') or (employee,department) in keys:return False
  keys.add((employee,department));counts[employee]=counts.get(employee,0)+1
  primary[employee]=primary.get(employee,0)+(flag=='Y')
 return all(primary[e]==(0 if n==1 else 1) for e,n in counts.items())
'''


def main():
    ap=argparse.ArgumentParser(__doc__);ap.add_argument('--output',required=True,type=Path);args=ap.parse_args()
    runner.DOCKER_IMAGE=image_digest();report={'version':sql.VERSION,'checks':[],'model_calls_in_this_command':0,'historical_jobs_unchanged':True}
    for qid in (1693,1789,1873):
        with lock(qid,packages.DATA_DIR):
            path=packages.DATA_DIR/f'{qid}.json';old=json.loads(path.read_text(encoding='utf8'))
            if old.get('reviewed_migration',{}).get('version')==sql.VERSION:
                assert packages.read(qid,runner.DOCKER_IMAGE)
                print(qid,'already migrated; existing checkpoint retained',flush=True);continue
            unsigned=deepcopy(old);digest=unsigned.pop('package_sha256');assert digest==sha(unsigned)
            save(packages.DATA_DIR/'archive'/str(qid)/(digest+'.json'),old)
            archive=args.output.parent/'before'/'attempts';archive.mkdir(parents=True,exist_ok=True)
            for folder in (packages.DATA_DIR/'attempts',ROOT/'local/dashboard/packages/server/data/lab_mysql_gates/attempts'):
                for evidence in folder.glob(f'{qid}-*.json'):shutil.copy2(evidence,archive/(folder.parent.name+'-'+evidence.name))
            checkpoint=packages.DATA_DIR/'pending'/f'{qid}.json'
            if checkpoint.exists():shutil.copy2(checkpoint,archive/f'{qid}-pending.json')
            descriptor=packages.describe(qid);binding=packages.binding(qid,runner.DOCKER_IMAGE,descriptor)
            inputs=[];removed=[];normalizations=[];seen={sha(c['args']) for c in descriptor['official']}
            for index,case in enumerate(old['cases'][len(old['descriptor']['official']):],len(old['descriptor']['official'])):
                migrated=deepcopy(case);before=sha(migrated['args'])
                if qid==1693:
                    table=migrated['args']['tables']['DailySales'];position=table['columns'].index('date_id')
                    for row in table['rows']:row[position]=sql.canonical_day(row[position])
                    if before!=sha(migrated['args']):normalizations.append({'old_case_index':index,'old_input_sha256':before,'canonical_input_sha256':sha(migrated['args']),'calendar_values_unchanged':True})
                if sql.valid(qid,migrated['args']) is not True:
                    if qid!=1789:raise ValueError('unexpected retained input rule failure')
                    removed.append({'case_index':index,'args':case['args'],'reason':'explicit_single_department_N_or_unique_primary_guarantee'});continue
                io.check_database_input(qid,migrated['args'],descriptor['official'][0]['args'])
                if sha(migrated['args']) in seen:
                    removed.append({'case_index':index,'reason':'duplicate_after_explicit_semantics_preserving_DATE_normalization','old_input_sha256':before});continue
                seen.add(sha(migrated['args']));migrated['expected']=sql.answer(qid,migrated['args'])
                inputs.append(migrated)
            retained=[sha(c['args']) for c in inputs];extras=[]
            if qid==1873:
                extra=deepcopy(descriptor['official'][0]['args'])
                extra['tables']['Employees']['rows']=[[1,'mario',100],[2,'Alice',200],[3,'Mary',300],[5,'M',400],[7,'Bob',0],[9,'Zed',900]]
                extras=[{'args':extra,'expected':sql.answer(qid,extra),'origin':'reviewed_literal_uppercase_prefix_boundary'}]
            cases=deepcopy(descriptor['official'])+inputs+extras
            for case in cases:
                io.input_valid_shape(case['args']);io.check_database_input(qid,case['args'],descriptor['official'][0]['args'])
                assert judging.compare(qid,sql.answer(qid,case['args']),case,descriptor['comparison'])
            validator=deepcopy(old['validator'])
            if qid==1789:validator={'code':PRIMARY_VALIDATOR,'code_sha256':sha(PRIMARY_VALIDATOR),'origin':'reviewed_primary_department_validator'}
            validator_cases=[{'args':c['args'],'expected':True} for c in cases]
            if qid==1789:
                invalid=deepcopy(descriptor['official'][0]['args']);invalid['tables']['Employee']['rows']=[[5,7,'Y']]
                validator_cases.append({'args':invalid,'expected':False})
            constraint_gate=judging.execute(0,'python3',validator['code'],validator_cases)
            if constraint_gate['ac_status']!='Accepted':raise ValueError(f'q{qid} constraint gate failed; not published')
            validator['gate']=constraint_gate;oracles=[];gates=[]
            for language in ('python3','sqlite','mysql'):
                code=sql.reference(qid,language);assert code
                gate=judging.execute(qid,language,code,cases,descriptor['comparison'])
                oracles.append({'language':language,'code':code,'code_sha256':sha(code),'origin':'reviewed_sql_reference','controller_version':sql.VERSION})
                gates.append({'language':language,'verdict':gate});save(args.output,{'checks':report['checks'],'in_progress':{'qid':qid,'gates':gates}})
                if gate['ac_status']!='Accepted':raise ValueError(f'q{qid} {language} gate failed; not published')
            assert binding==packages.binding(qid,runner.DOCKER_IMAGE,descriptor)
            migration={'version':sql.VERSION,'previous_package_sha256':digest,'removed_inputs':removed,
                'DATE_normalizations':normalizations,'retained_model_input_sha256':retained,
                'target_model_input_count':12,'retained_model_input_count':len(inputs),
                'needs_model_input_resume':len(inputs)<12,'historical_result_unchanged':True}
            row={**deepcopy(old),'binding':binding,'descriptor':descriptor,'comparison':descriptor['comparison'],
                'cases':cases,'cases_sha256':sha(cases),'generated_count':len(inputs),'validator':validator,
                'oracles':oracles,'gates':gates,'gates_passed':True,'reference_languages':[o['language'] for o in oracles],
                'reviewed_migration':migration,'reviewed_added_case_count':len(extras),
                'evidence_level':'reviewed_sql_controller_and_executed_oracles','constraint_evidence':'reviewed_sql_input_scope',
                'oracle_scope':{'max_rows':sql.MAX_ROWS[qid],'version':sql.VERSION,'description':sql.note(qid)},
                'limitations':['finite_tests_not_proof','explicit_reviewed_input_scope','LC_environment_equivalence_not_established']}
            row.pop('package_sha256',None);row['package_sha256']=sha(row);save(path,row)
            if len(inputs)<12:
                assert not extras
                draft={'version':packages.VERSION,'qid':qid,'binding':binding,'descriptor':descriptor,'oracles':oracles,
                    'validator':validator,'accepted':inputs,'attempts':[],'rejected':[],
                    'state':'building','profile':{},'reviewed_migration':migration}
                save(checkpoint,draft)
            report['checks'].append({'qid':qid,'retained_model_inputs':len(inputs),'reviewed_added_inputs':len(extras),
                'needs_model_input_resume':len(inputs)<12,'removed_inputs':removed,'DATE_normalizations':normalizations,
                'case_count':len(cases),'gates':gates,'validator_gate':constraint_gate,'passed':True})
            save(args.output,report);print(qid,'retained',len(inputs),'removed',len(removed),'resume',len(inputs)<12,'PASS',flush=True)
    print('Reviewed migration gates completed; model-input gaps remain explicit',flush=True)


if __name__=='__main__':main()
