"""Join a frozen discrepancy list to current SQL and explicit diagnostic causes."""
import argparse
import csv
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from local.tools.gap_workflow import DB,RESULTS,save,code_path,sha


def disposition(slot,payload):
    error=str(payload.get('_meta',{}).get('error',''))
    q,lang=slot['qid'],slot['lang']
    if slot['klass']=='false_wa':
        if lang=='python3' and 'IndentationError' in error:
            return 'format_source_binding','Check exact LC submitted code; formatting variants are not official fixes.'
        if q==2588 and lang=='c':return 'stack_policy','8/64 MiB controlled stack probe; review policy before changing production.'
        if q==47 and lang=='c':return 'submission_capacity','1000 result slots cannot hold 1260 legal permutations; verify LC source equivalence.'
        if q==1733:return 'submission_logic','Answer initialized to friendship count; valid counterexample needs more users taught.'
        if q==2070:return 'library_behavior','Equal-key binary search may return an interior match; inspect Rust runtime and original submission.'
        if q==2369:return 'return_type_policy','Numeric zero is rejected as boolean; check LC serialization semantics.'
        if q==2597 and lang=='python3':return 'budget_policy','Repeated budget probe; formal 5-second limit unchanged.'
        return 'reverse_unclassified','Inspect complete diagnostic input, output and code; no automatic source rewrite.'
    return {'Wrong Answer':('counterexample','Legal input generation, oracle, reference and nonregression gates.'),
            'Runtime Error':('crash_counterexample','Legal crash input; infrastructure failures are not model verdicts.'),
            'Time Limit Exceeded':('scale_counterexample','Worst-case input, repeated timeout and reference budget checks.'),
            'Compile Error':('compiler_or_source','Compare compiler/dependency and exact submitted source; do not add cases.')}.get(slot['leetcode'],('unclassified','Review evidence.'))


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--job',type=Path,required=True)
    ap.add_argument('--causes',type=Path,help='Optional diagnostic causes bound to current source and evidence hashes')
    args=ap.parse_args();causes={}
    if args.causes:
        for cause in json.loads(args.causes.read_bytes()):
            if cause['id'] in causes:raise ValueError('duplicate diagnostic cause')
            evidence=cause['evidence']
            if sha(Path(evidence['path']).read_bytes())!=evidence['sha256']:
                raise ValueError('diagnostic evidence changed')
            causes[cause['id']]=cause
    job=json.loads((args.job/'job.json').read_bytes());rows=[]
    with closing(sqlite3.connect(DB.resolve().as_uri()+'?mode=ro',uri=True)) as con:
        con.row_factory=sqlite3.Row
        for task in job['tasks']:
            old=task['slot']
            matches=list(con.execute("SELECT * FROM slots WHERE model=? AND qid=? AND lang=? AND task=? "
                    "AND cand=? AND lc_origin='submissions' AND local_origin='all_models'",
                    [old['model'],old['qid'],old['lang'],old['task'],old['cand']]))
            if len(matches)!=1:raise ValueError('slot not uniquely mapped to current SQL')
            slot=dict(matches[0]);rp=RESULTS/slot['model']/'results'/str(slot['qid'])/f"{slot['qid']}_{slot['lang']}_{slot['cand']}.json"
            payload=json.loads(rp.read_bytes());category,action=disposition(slot,payload)
            state='reevaluation_pending' if slot['identity_status']!='current' else 'resolved' if slot['klass'] not in ('false_ac','false_wa') else 'open'
            if state=='resolved':
                category='validated_resolution'
                action='Binary disagreement resolved; exact negative statuses may still differ.'
            elif state=='open' and task['id'] in causes:
                cause=causes[task['id']]
                if sha(code_path(slot).read_bytes())!=cause['code_sha256']:
                    raise ValueError('diagnostic source identity changed')
                category,action=cause['category'],cause['next_action']
            if state=='open' and old['klass']=='false_ac' and old.get('eval_split')!='dev':
                action='Read-only holdout or unknown split; do not target new inputs. '+action
            rows.append({'id':task['id'],'model':slot['model'],'qid':slot['qid'],'lang':slot['lang'],
                         'eval_split':old.get('eval_split','unknown'),'initial_branch':task['branch'],
                         'initial_class':old['klass'],'current_class':slot['klass'],'state':state,
                         'leetcode':slot['leetcode'],'local':slot['local'],'category':category,'next_action':action,
                         'same_lc_source_confirmed':False})
    save(args.job/'triage-board.json',rows)
    with (args.job/'triage-board.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else ['id']);writer.writeheader();writer.writerows(rows)
    from collections import Counter
    print('states',dict(Counter(r['state'] for r in rows)))
    print('open categories',dict(Counter(r['category'] for r in rows if r['state']=='open')))


if __name__=='__main__':main()
