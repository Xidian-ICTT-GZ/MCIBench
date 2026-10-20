"""Re-execute frozen real model candidates under the current lab checker.

No model calls. Original task records and their original verdicts stay unchanged.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from local.lab.pipeline_jobs import execute
from local.lab.behavior import sha
from local.harness import runner
from local.harness.identity import image_digest
from local.lab import portable_drivers,portable_judging,native_adapters,native_python,result_semantics

FILES={
    'generated-source-chain':'524212eeb74b46ebaeec80d218ff23c8.json',
    'native-source-chain':'c395dd7b082c40cb95973a9123b7e51c.json',
    'saved-translation':'real-v2/saved-translation.json',
    'linked-list':'real-v4/linked-list.json','tree':'real-v6/tree.json',
    'design-error-detected':'real-v2/design.json','counted-mutation':'real-v3/mutation.json',
    'callback':'real-v3/callback.json','hidden-api':'real-v4/hidden-api.json',
    'dataframe':'real-v5/dataframe.json','database':'real-v5/database.json',
    'shell':'real-v4/shell.json','void':'real-v4/void.json',
}


def main():
    ap=argparse.ArgumentParser(__doc__)
    ap.add_argument('--directory',type=Path,required=True)
    ap.add_argument('--output',type=Path)
    ap.add_argument('--contracts-directory',type=Path)
    args=ap.parse_args();runner.DOCKER_IMAGE=image_digest()
    files=dict(FILES)
    if args.contracts_directory:
        for label,relative in {'cycle-entry':'retry/cycle-entry.json','intersection':'retry/intersection.json',
            'master-api':'real/master-api.json','next-pointer':'real/next-pointer.json',
            'dataframe-dtype':'real/dataframe-dtype.json','legacy-clone':'legacy/legacy-clone.json'}.items():
            files[label]=str((args.contracts_directory/relative).resolve())
    output=args.output or args.directory/'final-replay.json';output.parent.mkdir(parents=True,exist_ok=True)
    report={'image':runner.DOCKER_IMAGE,'sources':{Path(m.__file__).name:sha(Path(m.__file__).read_text(encoding='utf8'))
                for m in (portable_drivers,portable_judging,native_adapters,native_python,result_semantics)},'checks':[]}
    failures=0
    for label,relative in files.items():
        job=json.loads((args.directory/relative).read_text(encoding='utf8'))
        for group in job['result']['groups']:
            snapshot=next(r for r in job['result']['inputs'] if r['qid']==group['qid'])
            for candidate in group['candidates']:
                if sha(candidate['code'])!=candidate['code_sha256']:raise ValueError('candidate source drift')
                old=candidate['corpus_verdict']
                result=execute(group['qid'],group['language'],candidate['code'],snapshot['full_corpus'],snapshot['comparison'],
                    group.get('native_adapter'),full=True)
                passed=result['ac_status']==old['ac_status']
                report['checks'].append({'label':label,'job_id':job['id'],'qid':group['qid'],'language':group['language'],
                    'candidate_id':candidate['id'],'source_sha256':candidate['code_sha256'],
                    'frozen_cases_sha256':sha(snapshot['full_corpus']),'original_status':old['ac_status'],
                    'replay_status':result['ac_status'],'verdict':result,'passed':passed})
                failures+=not passed
                output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
                print(label,group['language'],len(snapshot['full_corpus']),result['ac_status'],'PASS' if passed else 'FAIL',flush=True)
    print('replay failures:',failures)
    raise SystemExit(bool(failures))


if __name__=='__main__':main()
