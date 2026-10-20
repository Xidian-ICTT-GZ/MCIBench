"""Real sandbox regression of typed TEXT, scalar aliases and DELETE execution."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from local.harness import runner
from local.harness.identity import image_digest
from local.lab import problem_packages,portable_judging as judging
from local.lab.behavior import sha


def main():
    ap=argparse.ArgumentParser(__doc__);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    runner.DOCKER_IMAGE=image_digest();report={'image':runner.DOCKER_IMAGE,'checks':[]}
    def check(qid,label,code,expected_status,*,collect=False,cases=None):
        d=problem_packages.describe(qid);rows=cases or d['official']
        out=judging.execute(qid,'sqlite',code,rows,d['comparison'],collect=collect)
        passed=out['ac_status']==expected_status
        report['checks'].append({'qid':qid,'label':label,'source':code,'source_sha256':sha(code),'cases':rows,'verdict':out,'passed':passed})
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(qid,label,out['ac_status'],'PASS' if passed else 'FAIL',flush=True)
        if not passed:raise SystemExit(1)
    d=problem_packages.describe(177);cases=deepcopy(d['official'])
    for n,want in ((1,300),(3,100),(4,None)):
        row=deepcopy(cases[0]);row['args']['n']=n;row['expected']['rows']=[[want]];cases.append(row)
    check(177,'vary n without conflating a display heading with behavior',
          'SELECT (SELECT DISTINCT salary FROM Employee ORDER BY salary DESC LIMIT 1 OFFSET :n-1) AS "getNthHighestSalary(:n)"','Accepted',cases=cases)
    check(177,'maximum salary is not the nth salary','SELECT MAX(salary) AS answer FROM Employee','Wrong Answer')
    query='SELECT DISTINCT a.num AS ConsecutiveNums FROM Logs a JOIN Logs b ON b.id=a.id+1 AND b.num=a.num JOIN Logs c ON c.id=a.id+2 AND c.num=a.num'
    check(180,'VARCHAR public values remain text',query,'Accepted')
    d=problem_packages.describe(180);row=deepcopy(d['official'][0]);row['args']['tables']['Logs']['rows']=[[i,v] for i,v in enumerate(['001','001','001','1','1','1'],1)];row['expected']['rows']=[['001'],['1']]
    check(180,'leading zeros distinguish text values',query,'Accepted',cases=[row])
    check(180,'numeric cast cannot erase text identity',query.replace('a.num AS','CAST(a.num AS INTEGER) AS'),'Wrong Answer',cases=[row])
    deletion='DELETE FROM Person WHERE id NOT IN (SELECT MIN(id) FROM Person GROUP BY email)'
    d=problem_packages.describe(196);row=deepcopy(d['official'][0]);row['args']['tables']['Person']['rows']=[[8,'a'],[3,'b'],[1,'a']];row['expected']['rows']=[[3,'b'],[1,'a']]
    check(196,'DELETE returns final table without requiring result cursor',deletion,'Accepted',cases=[row])
    check(196,'oracle collection retains the mutation execution configuration',deletion,'Collected',collect=True,cases=[row])
    check(196,'SELECT cannot masquerade as a successful mutation','SELECT * FROM Person','Runtime Error')
    check(196,'DELETE RETURNING observes final table instead of returned deleted rows',deletion+' RETURNING *','Accepted',cases=[row])
    check(196,'UPDATE is not the required DELETE operation','UPDATE Person SET email=email RETURNING *','Runtime Error')
    check(176,'query text is preserved without textual template substitution',"SELECT 'if MUTATION:' AS sample",'Accepted',cases=[
        {'args':{'tables':{}},'expected':{'columns':['sample'],'rows':[['if MUTATION:']]}}])
    update="UPDATE Salary SET sex=CASE sex WHEN 'm' THEN 'f' ELSE 'm' END"
    check(627,'UPDATE observes final table state',update,'Accepted')
    check(627,'UPDATE RETURNING cannot substitute returned rows for final state',update+' RETURNING *','Accepted')
    check(627,'SELECT cannot masquerade as the required UPDATE',"SELECT id,name,CASE sex WHEN 'm' THEN 'f' ELSE 'm' END AS sex,salary FROM Salary",'Runtime Error')
    check(627,'wrong sex updates are detected',"UPDATE Salary SET sex='m'",'Wrong Answer')
    print('SQL contract failures: 0')


if __name__=='__main__':main()
