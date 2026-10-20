"""Recheck signed existing SQL packages under current schema/execution rules.

Retains model-proposed inputs and old task records. Republishes only after
current structural constraints, saved validator and every independent answer
program pass. Never generates replacement answers or bypasses a failing gate.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from local.harness import runner
from local.harness.identity import image_digest
from local.lab import problem_packages as packages,portable_judging as judging,problem_io
from local.lab.behavior import sha
from local.lab.testcase_workflow import save,lock


def main():
    ap=argparse.ArgumentParser(__doc__);ap.add_argument('--qids',type=int,nargs='+',required=True);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--allow-note-refresh',action='store_true',help='Allow documentation-only descriptor changes, after exact structured-contract equality and all execution gates.')
    args=ap.parse_args()
    runner.DOCKER_IMAGE=image_digest();report={'image':runner.DOCKER_IMAGE,'checks':[]}
    for qid in args.qids:
        path=packages.DATA_DIR/f'{qid}.json'
        with lock(qid,packages.DATA_DIR):
            old=json.loads(path.read_text(encoding='utf8'));signed=deepcopy(old);digest=signed.pop('package_sha256',None)
            if digest!=sha(signed) or old['cases_sha256']!=sha(old['cases']) or not old.get('gates_passed'):raise ValueError(f'q{qid} corrupt/unsigned package')
            descriptor=packages.describe(qid)
            same=descriptor==old['descriptor']
            structured=lambda d:{k:v for k,v in d.items() if k not in ('interface_note','warnings')}
            note_refresh=args.allow_note_refresh and structured(descriptor)==structured(old['descriptor'])
            if (not same and not note_refresh) or descriptor['kind']!='database':raise ValueError(f'q{qid} unsupported or changed public contract; explicit migration required')
            current=packages.binding(qid,runner.DOCKER_IMAGE,descriptor)
            for case in old['cases']:
                problem_io.input_valid_shape(case['args'])
                problem_io.check_database_input(qid,case['args'],descriptor['official'][0]['args'])
            check={'qid':qid,'case_count':len(old['cases']),'previous_package_sha256':digest,'gates':[],'primary_key_evidence':problem_io.sql_primary_keys(qid)}
            report['checks'].append(check)
            validation=judging.execute(0,'python3',old['validator']['code'],[{'args':c['args'],'expected':True} for c in old['cases']])
            check['validator_gate']=validation
            if validation['ac_status']!='Accepted':save(args.output,report);raise ValueError('saved constraint validator did not complete all inputs')
            for oracle in old['oracles']:
                if sha(oracle['code'])!=oracle['code_sha256']:raise ValueError('saved oracle source fingerprint mismatch')
                out=judging.execute(qid,oracle['language'],oracle['code'],old['cases'],old['comparison'])
                check['gates'].append({'language':oracle['language'],'verdict':out});save(args.output,report)
                if out['ac_status']!='Accepted':raise ValueError('independent answer gate failed; old package retained')
            check['passed']=True;save(args.output,report)
            if current!=packages.binding(qid,runner.DOCKER_IMAGE,descriptor):raise ValueError('configuration changed during revalidation')
            archive=packages.DATA_DIR/'archive'/str(qid)/(digest+'.json')
            if not archive.exists():save(archive,old)
            row=deepcopy(old);row.pop('package_sha256',None);row['binding']=current;row['gates']=check['gates'];row['descriptor']=descriptor
            row['revalidation']={'previous_package_sha256':digest,'source':'retained_model_generated_inputs','structural_rules':'schema_types_and_explicit_primary_keys',
                                 'primary_key_evidence':check['primary_key_evidence'],'validator_gate':validation,
                                 'descriptor_migration':'notes_only_after_structured_contract_identity' if not same else 'unchanged'}
            row['package_sha256']=sha(row);save(path,row)
            print(qid,len(old['cases']),'PASS',flush=True)
    print('SQL packages revalidated:',len(report['checks']))


if __name__=='__main__':main()
