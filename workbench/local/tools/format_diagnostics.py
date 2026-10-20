"""Read-only controlled formatting variants. Never publish transformed code."""
import argparse
import ast
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from local.tools.gap_workflow import save,sha,code_path,assert_current


def variant(source):
    try:ast.parse(source)
    except IndentationError:pass
    except SyntaxError:return None
    else:return None
    stripped=source.lstrip()
    try:ast.parse(stripped)
    except SyntaxError:return None
    return stripped


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--job',type=Path,required=True)
    args=ap.parse_args()
    from local.harness import runner
    from local.harness.identity import image_digest,result_errors
    from local.judge import judge_one
    runner.DOCKER_IMAGE=image_digest()
    job=json.loads((args.job/'job.json').read_bytes());items=[]
    for t in job['tasks']:
        if t['slot']['klass']!='false_wa' or t['slot']['lang']!='python3':continue
        path=args.job/t['id']/'diagnostic.json'
        if not path.exists():continue
        prior=json.loads(path.read_bytes())
        if 'IndentationError' not in str(prior['result'].get('_meta',{}).get('error','')):continue
        s=t['slot'];assert_current(s);source=code_path(s);raw=source.read_bytes()
        text=source.read_text(encoding='utf-8');changed=variant(text)
        outdir=args.job/'format-variants'/t['id'];outdir.mkdir(parents=True,exist_ok=True)
        info={'task':t['id'],'raw_sha256':sha(raw),'same_lc_source_confirmed':False,
              'policy':'diagnostic_lstrip_only; not production normalization','formal_results_modified':False}
        if changed is None:info['status']='cannot_isolate_leading_whitespace'
        else:
            cf=outdir/f"{s['qid']}_Python3_{s['cand']}.txt";cf.write_text(changed,encoding='utf-8')
            cases=json.loads((args.job/t['id']/'cases.json').read_bytes())
            current=(ROOT/'local/testcases'/str(s['qid'])/'cases.json').read_bytes()
            if json.loads(current)!=cases:raise RuntimeError('diagnostic corpus changed')
            result=judge_one(cf,'gen',1000,'docker',5,cases_override=cases)
            errors=result_errors(result,prior['identity'])
            if result.get('total_testcases')!=len(cases):errors.append('coverage incomplete')
            if source.read_bytes()!=raw or (ROOT/'local/testcases'/str(s['qid'])/'cases.json').read_bytes()!=current:
                raise RuntimeError('original source/corpus changed')
            info.update(status='complete' if not errors else 'incomplete',variant_sha256=sha(cf.read_bytes()),
                        variant_result=result,validation_errors=errors)
        save(outdir/'evidence.json',info);items.append(info)
        print(t['id'],info['status'],info.get('variant_result',{}).get('ac_status'),flush=True)
        save(args.job/'format-variant-summary.json',{'items':items,'same_lc_source_confirmed':False})


if __name__=='__main__':main()
