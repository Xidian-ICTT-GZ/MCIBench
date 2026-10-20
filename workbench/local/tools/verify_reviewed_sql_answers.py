"""Real sandbox cross-checks for reviewed pivot/decimal controllers and DATE IO."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from local.harness import runner
from local.harness.identity import image_digest
from local.lab import problem_io as io,sql_answers as sql,portable_judging as judging


def main():
    ap=argparse.ArgumentParser(__doc__);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    runner.DOCKER_IMAGE=image_digest();report={'controller_version':sql.VERSION,'checks':[],'notice':'Finite controller/adaptor QA, not model samples or a functional detection-rate denominator.'}
    def save():
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    pivot,comparison,_=io.official(1179)
    examples=deepcopy(pivot)
    for rows in ([],[[3,0,'Jan'],[3,-7,'Dec'],[8,None,'May']],[[1,1,'Apr'],[2,2,'Sep'],[1,0,'Feb']]):
        data=deepcopy(pivot[0]['args']);data['tables']['Department']['rows']=rows
        examples.append({'args':data,'expected':sql.answer(1179,data),'origin':'controller_qa_fixture'})
    numeric,number_comparison,_=io.official(1211)
    numbers=deepcopy(numeric)
    old=json.loads((ROOT/'local/docs/reviews/20261017-sql-batch5/1211-fix/before/package.json').read_text(encoding='utf8'))
    changes=[]
    for i,c in enumerate(old['cases'][1:],1):
        expected=sql.answer(1211,c['args'])
        if expected!=c['expected']:changes.append({'case_index':i,'previous':c['expected'],'current':expected})
        numbers.append({**deepcopy(c),'expected':expected})
    data=deepcopy(numeric[0]['args'])
    for rows in ([['A','r',201,1]],[['A','r',1,1]]+[['A','r'+str(i),500,5] for i in range(31)]):
        item=deepcopy(data);item['tables']['Queries']['rows']=rows
        numbers.append({'args':item,'expected':sql.answer(1211,item),'origin':'controller_qa_fixture'})
    for seed in range(1,31):
        item=deepcopy(data);item['tables']['Queries']['rows']=[['Q'+str(i%3),'r'+str(i),1+(seed*(i+7))%500,1+(seed+i*3)%5] for i in range(1+seed%35)]
        numbers.append({'args':item,'expected':sql.answer(1211,item),'origin':'controller_qa_fixture'})
    for qid,cases,comp,languages in ((1179,examples,comparison,('python3','sqlite','mysql')),(1211,numbers,number_comparison,('python3','mysql'))):
        for language in languages:
            verdict=judging.execute(qid,language,sql.reference(qid,language),cases,comp)
            report['checks'].append({'qid':qid,'language':language,'case_count':len(cases),'passed':verdict['ac_status']=='Accepted','verdict':verdict});save()
            print(qid,language,len(cases),verdict['ac_status'],flush=True)
            if verdict['ac_status']!='Accepted':raise SystemExit(1)
    public,comp,_=io.official(607)
    query="SELECT s.name FROM SalesPerson s WHERE NOT EXISTS (SELECT 1 FROM Orders o JOIN Company c ON o.com_id=c.com_id WHERE c.name='RED' AND o.sales_id=s.sales_id)"
    verdict=judging.execute(607,'mysql',query,public,comp)
    report['checks'].append({'qid':607,'language':'mysql','case_count':len(public),'passed':verdict['ac_status']=='Accepted','verdict':verdict})
    report['changed_old_numeric_answers']=changes;save()
    if verdict['ac_status']!='Accepted':raise SystemExit(1)
    print('SQL controller/date QA failures: 0; corrected old numeric answers:',len(changes))


if __name__=='__main__':main()
