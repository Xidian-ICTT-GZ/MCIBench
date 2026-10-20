"""Real Docker repair demonstration on an isolated weak corpus, without API calls.

Only the proposal response is a deterministic fixture. All reference, correct
program, faulty program and witness verdicts are actual sandbox executions.
Never points at the live corpus directory or writes formal judge results.
"""
import argparse
import json
from pathlib import Path
from unittest.mock import patch
from local.lab import testcase_workflow as workflow, correctness_audit as audit
from local.lab.behavior import sha
from local.harness import runner
from local.harness.identity import image_digest
from local.tools import verify_judge_correctness as cli


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    folder=args.output.resolve()
    live=workflow.DATA_DIR.resolve()
    if folder==live or live in folder.parents or folder in live.parents:
        raise ValueError('demonstration must be isolated from the live corpus')
    if (folder/'corpus').exists():
        raise ValueError('choose a new output directory; demonstration preserves its artifacts')
    image=image_digest();runner.DOCKER_IMAGE=image
    profile={'id':'fixture-only','name':'reviewed deterministic proposals (no API call)',
             'model_name':'fixture','api_url':'http://localhost:1'}
    proposals=[{'args':{'s':'('*n+')'*n}} if balanced else {'args':{'s':'('*n+']'}}
               for n in range(2,8) for balanced in (True,False)]
    with (patch.object(workflow,'DATA_DIR',folder/'corpus'),
          patch.object(cli,'CORPUS_DIR',folder/'corpus')):
        with patch.object(workflow,'generate',return_value={'code':json.dumps({'cases':proposals}),'finish_reason':'stop'}) as generator:
            old=workflow.build(20,profile,12,['python3','cpp'],image)
            assert generator.call_count==1
        before=audit.audit(20,old['cases'],old['languages'],image,cache_dir=folder/'executions')
        workflow.save(folder/'before.json',before)
        assert before['summary']['survived']==2,before['summary']
        repaired=cli.repair(20,before,image,folder/'executions')
        workflow.save(folder/'after.json',repaired)
        current=workflow.read_bundle(20,image=image)
        assert current and repaired['passed'] and repaired['summary']['killed']==4
        assert current['parent_cases_sha256']==old['cases_sha256']
        summary={'passed':True,'qid':20,'image':image,'api_calls':0,'proposal_source':'repository_fixture',
                 'all_verdicts':'actual_docker_execution','before':before['summary'],'after':repaired['summary'],
                 'added':repaired['repair']['added'],'before_sha256':old['cases_sha256'],
                 'after_sha256':current['cases_sha256'],'live_corpus_unchanged':True}
        workflow.save(folder/'summary.json',summary)
        print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
