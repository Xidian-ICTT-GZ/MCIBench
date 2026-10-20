"""Real native MySQL contract QA, including the unchanged q601 candidate."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from local.lab import portable_judging as judging,problem_packages as packages,mysql_runtime
from local.lab.behavior import sha


def main():
    ap=argparse.ArgumentParser(__doc__);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    report={'runtime':mysql_runtime.identity(),'checks':[],'notice':'Runtime contract QA and finite frozen candidate evidence, not general correctness or LC equivalence.'}
    def save():
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    def run(label,qid,code,cases,comparison,wanted):
        out=judging.execute(qid,'mysql',code,cases,comparison)
        row={'label':label,'qid':qid,'source_sha256':sha(code),'cases_sha256':sha(cases),'wanted':wanted,'verdict':out,'passed':out['ac_status']==wanted}
        report['checks'].append(row);save();print(label,out['ac_status'],'PASS' if row['passed'] else 'FAIL',flush=True)
        if not row['passed']:raise SystemExit(1)
        return out
    d=packages.describe(180)
    consecutive=' FROM Logs l JOIN Logs m ON m.id=l.id+1 JOIN Logs n ON n.id=l.id+2 WHERE l.num=m.num AND m.num=n.num'
    run('text_preserved',180,'SELECT DISTINCT l.num AS ConsecutiveNums'+consecutive,d['official'],d['comparison'],'Accepted')
    run('numeric_text_coercion_rejected',180,'SELECT DISTINCT CAST(l.num AS SIGNED) AS ConsecutiveNums'+consecutive,d['official'],d['comparison'],'Wrong Answer')
    run('syntax_failure',180,'SELECT FROM Logs',d['official'],d['comparison'],'Runtime Error')
    run('bounded_query_timeout',180,'SELECT SLEEP(30) AS ConsecutiveNums',d['official'],d['comparison'],'Time Limit Exceeded')
    cases=deepcopy(d['official']);cases[0]['args']['tables']['Logs']['rows'][0][1]=1
    try:judging.execute(180,'mysql','SELECT 1',cases,d['comparison'])
    except ValueError:
        report['checks'].append({'label':'invalid_input_ungraded','passed':True});save()
    else:raise AssertionError('invalid typed input reached judging')
    d=packages.describe(196)
    run('native_delete_join',196,'DELETE p FROM Person p JOIN Person other ON p.email=other.email AND p.id>other.id',d['official'],d['comparison'],'Accepted')
    run('select_cannot_impersonate_delete',196,'SELECT * FROM Person',d['official'],d['comparison'],'Runtime Error')
    d=packages.describe(627)
    run('native_update_enum',627,"UPDATE Salary SET sex=CASE WHEN sex='m' THEN 'f' ELSE 'm' END",d['official'],d['comparison'],'Accepted')
    d=packages.describe(177)
    function='''CREATE FUNCTION getNthHighestSalary(N INT) RETURNS INT
BEGIN
 SET N=N-1;
 RETURN (SELECT DISTINCT salary FROM Employee ORDER BY salary DESC LIMIT N,1);
END'''
    run('native_scalar_function',177,function,d['official'],d['comparison'],'Accepted')
    old=json.loads((ROOT/'local/docs/reviews/20261017-sql-batch3/1.json').read_text(encoding='utf8'))
    g=next(g for g in old['result']['groups'] if g['qid']==601)
    snapshot=next(s for s in old['result']['inputs'] if s['qid']==601)
    candidate=g['candidates'][0]
    if sha(candidate['code'])!=candidate['code_sha256']:raise ValueError('q601 source changed')
    out=run('q601_unchanged_original',601,candidate['code'],snapshot['full_corpus'],snapshot['comparison'],'Accepted')
    report['q601']={'source_unchanged':True,'original_status':candidate['corpus_verdict']['ac_status'],
                   'native_mysql_status':out['ac_status'],'original_job_id':old['id'],'public_and_supplementary_cases':len(snapshot['full_corpus'])}
    save()
    print('Native MySQL checks:',len(report['checks']),'failures: 0',flush=True)


if __name__=='__main__':main()
