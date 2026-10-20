"""Read-only coverage audit of public example serialization, not correctness."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from local.lab import problem_io as io,public_literals
from local.lab.behavior import sha
from local.harness.identity import judge_source_closure


def main():
    ap=argparse.ArgumentParser(__doc__);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    index=json.loads((ROOT/'local/lab/data/problem_index.json').read_text(encoding='utf8'));rows=[]
    for problem in index:
        qid=problem['qid'];text=io.description(qid);cases,comparison,warnings=io.official(qid)
        normalized=text
        for old,new in (('示例','Example'),('输入','Input'),('输出','Output')):
            normalized=re.sub(r'(?m)^([ \t]*)'+old+r'(\s*\d*)[：:]',lambda m:m[1]+new+m[2]+':',normalized)
        # Explanatory prose can itself contain numbered examples. Count the
        # actual worked input/output pairs, including inline example headers.
        declared=sum(bool(re.search(r'\bInput(?:\s*:|\s*\n)',block)) and bool(re.search(r'\bOutput(?:\s*:|\s*\n)',block)) for block in io.example_blocks(normalized))
        if io.kind(qid)=='shell':declared=len(cases)  # Four separately reviewed file examples have no numbered headers.
        state='model_normalization_required' if not cases else 'public_complete' if declared==len(cases) and not warnings else 'public_partial'
        rows.append({'qid':qid,'title':problem['title'],'kind':io.kind(qid),'state':state,
            'declared_examples':declared,'parsed_examples':len(cases),'warnings':warnings,
            'description_sha256':sha(text),'public_cases_sha256':sha(cases),'comparison':comparison,
            'reviewed_controller':qid in (142,160,843),'trusted_python_adapter':qid in (116,117,142,160,843)})
    baseline=json.loads((ROOT/'local/docs/reviews/20261015-correctness-15/baseline.json').read_text(encoding='utf8'))
    unchanged=dict(judge_source_closure())==baseline['judge_closure']
    report={'scope':'all_2944_catalog_entries_public_serialization_only','counts':dict(Counter(r['state'] for r in rows)),
        'notice':'Public serialization completeness does not certify answer algorithms, generated-input constraints, language adapters or LeetCode compatibility.',
        'sources':{Path(m.__file__).name:sha(Path(m.__file__).read_text(encoding='utf8')) for m in (io,public_literals)},
        'formal_source_closure_unchanged':unchanged,'problems':rows}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('problems','sources')},ensure_ascii=False))
    print('partial:',[r['qid'] for r in rows if r['state']=='public_partial'])
    if len(rows)!=2944 or not unchanged:raise SystemExit(1)


if __name__=='__main__':main()
