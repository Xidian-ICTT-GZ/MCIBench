"""Migrate q602's unfinished input checkpoint only after independent review.

This is deliberately specific: q602 has a repository-owned answer/controller.
Other unfinished model-derived checkpoints cannot bypass source invalidation.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from local.harness import runner
from local.harness.identity import image_digest
from local.lab import problem_packages as packages,problem_io,portable_judging as judging
from local.lab.behavior import sha
from local.lab.testcase_workflow import save,lock


def main():
    ap=argparse.ArgumentParser(__doc__);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    runner.DOCKER_IMAGE=image_digest();qid=602;path=packages.DATA_DIR/'pending/602.json'
    with lock(qid,packages.DATA_DIR):
        draft=json.loads(path.read_text(encoding='utf8'));old=deepcopy(draft);digest=sha(old);descriptor=packages.describe(qid)
        if draft['descriptor']!=descriptor or draft['binding']['description_sha256']!=sha(problem_io.description(qid)):raise ValueError('public contract/statement changed; automatic migration forbidden')
        accepted=draft['accepted'];seen={sha(c['args']) for c in descriptor['official']}
        for case in accepted:
            problem_io.input_valid_shape(case['args']);problem_io.check_database_input(qid,case['args'],descriptor['official'][0]['args'])
            key=sha(case['args'])
            if key in seen:raise ValueError('duplicate/public checkpoint input')
            seen.add(key);known,answer=problem_io.controller_answer(qid,case['args'])
            if not known or not judging.compare(qid,answer,case,descriptor['comparison']):raise ValueError('reviewed answer disagrees with unfinished checkpoint')
        cases=descriptor['official']+accepted;report={'qid':qid,'previous_checkpoint_sha256':digest,'retained_input_count':len(accepted),'gates':[]}
        current=packages.binding(qid,runner.DOCKER_IMAGE,descriptor)
        validation=judging.execute(0,'python3',draft['validator']['code'],[{'args':c['args'],'expected':True} for c in cases])
        report['validator_gate']=validation
        if validation['ac_status']!='Accepted':save(args.output,report);raise ValueError('validator gate failed')
        if {o['language'] for o in draft['oracles']}!={'python3','sqlite'}:raise ValueError('both independent answer programs required')
        for oracle in draft['oracles']:
            if sha(oracle['code'])!=oracle['code_sha256']:raise ValueError('oracle fingerprint mismatch')
            verdict=judging.execute(qid,oracle['language'],oracle['code'],cases,descriptor['comparison'])
            report['gates'].append({'language':oracle['language'],'verdict':verdict});save(args.output,report)
            if verdict['ac_status']!='Accepted':raise ValueError('oracle gate failed; old checkpoint retained')
        if current!=packages.binding(qid,runner.DOCKER_IMAGE,descriptor):raise ValueError('configuration changed during checkpoint review')
        save(packages.DATA_DIR/'archive/602'/(digest+'.pending.json'),old)
        draft['binding']=current;draft.setdefault('checkpoint_revalidations',[]).append(report);save(path,draft)
        report['published_package']=False;report['passed']=True;save(args.output,report)
        print('Retained',len(accepted),'reviewed q602 inputs; unfinished checkpoint rebound, not published')


if __name__=='__main__':main()
