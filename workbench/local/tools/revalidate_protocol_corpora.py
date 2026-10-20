"""Re-execute existing protocol corpora after a lab source/config change.

No model calls, no weakened checks, no old task rewrites. Archive the old signed
package, recompute every answer, run the native reference and observability
gates, and only then publish a package bound to the current implementation.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from local.harness import runner
from local.harness.identity import image_digest
from local.lab import problem_packages as packages,native_adapters as adapters,native_javascript as native
from local.lab import javascript_answers as answers,javascript_references as references,portable_judging as judging
from local.lab.behavior import sha
from local.lab.testcase_workflow import save,lock


def main():
    ap=argparse.ArgumentParser(__doc__);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    runner.DOCKER_IMAGE=image_digest();report={'image':runner.DOCKER_IMAGE,'checks':[]}
    for qid in sorted(references.SOURCES):
        path=packages.DATA_DIR/f'{qid}.json'
        if not path.exists():continue
        with lock(qid,packages.DATA_DIR):
            old=json.loads(path.read_text(encoding='utf8'));signed=deepcopy(old);digest=signed.pop('package_sha256',None)
            if old.get('evidence_level')!='reviewed_protocol_oracles':continue
            if digest!=sha(signed) or old['cases_sha256']!=sha(old['cases']):raise ValueError(f'q{qid} old package is unsigned or corrupt')
            descriptor=packages.describe(qid)
            if old['descriptor']!=descriptor:raise ValueError(f'q{qid} public contract changed: explicit migration required')
            current=packages.binding(qid,runner.DOCKER_IMAGE,descriptor)
            for case in old['cases']:
                answer=answers.answer(qid,case['args'])
                if not judging.compare(qid,answer,case,old['comparison']):raise ValueError(f'q{qid} old answer disagrees with current independent algorithm')
            adapter=native.bridge(qid,descriptor);plan={'kind':'bridge',**adapter,'adapter_sha256':sha(adapter)}
            reference=adapters.execute(qid,'javascript',references.SOURCES[qid],old['cases'],old['comparison'],plan)
            injection=adapters.execute(qid,'javascript',native.negative_source(qid,adapters.SENTINEL),descriptor['official'],descriptor['comparison'],plan,collect=True)
            sensitivity=adapters.sensitivity_gate(qid,'javascript',native.sensitivity_source(qid),old['cases'],old['comparison'],plan)
            passed=reference['ac_status']=='Accepted' and native.observed_entry(injection,adapters.SENTINEL) and sensitivity['passed']
            check={'qid':qid,'case_count':len(old['cases']),'previous_package_sha256':digest,'passed':passed,
                   'reference':reference,'entry_injection':injection,'output_sensitivity':sensitivity}
            report['checks'].append(check);args.output.parent.mkdir(parents=True,exist_ok=True);save(args.output,report)
            print(qid,len(old['cases']),'PASS' if passed else 'FAIL',flush=True)
            if not passed:raise SystemExit(1)
            if current!=packages.binding(qid,runner.DOCKER_IMAGE,descriptor):raise ValueError('configuration changed during revalidation')
            archive=packages.DATA_DIR/'archive'/str(qid)/(digest+'.json')
            if not archive.exists():save(archive,old)
            row=deepcopy(old);row.pop('package_sha256',None);row['binding']=current
            row['gates']=[{'language':'javascript','verdict':reference}]
            row['revalidation']={'previous_package_sha256':digest,'source':'retained_model_generated_inputs',
                'independent_answers_recomputed':len(old['cases']),'entry_injection_gate':injection,'output_sensitivity_gate':sensitivity}
            row['package_sha256']=sha(row);save(path,row)
    print('revalidated protocol corpora:',len(report['checks']))


if __name__=='__main__':main()
