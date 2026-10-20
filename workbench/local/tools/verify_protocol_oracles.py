"""Cross-check reviewed Python algorithms against real native JS execution.

Deterministic adversarial QA inputs here are not the model-generated published
corpus, and are not included in any model quality/functional mutation rate.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import random
import sys

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from local.harness import runner
from local.harness.identity import image_digest
from local.lab import javascript_answers as answers,javascript_protocol as protocol,javascript_references as references
from local.lab import native_javascript as native,native_adapters,problem_packages
from local.lab.behavior import sha


def inputs(qid):
    rng=random.Random(20261016+qid)
    for i in range(12):
        n=rng.randint(-20,20);k=rng.randint(1,9)
        fn=protocol.callback('x => x + 1')
        if qid==2618:
            obj=[{'primitive':None},{'undefined':True},{'primitive':False},{'primitive':0},{'primitive':''},{'class':'Date'},{'instance':'Dog'}][i%7]
            yield {'classes':{'Animal':None,'Dog':'Animal'},'object':obj,'class':['Object','Number','Boolean','Function','Animal','null','undefined'][i%7]}
        elif qid==2620:yield {'n':n,'calls':['call']*(i%5)}
        elif qid==2626:yield {'nums':[rng.randint(0,10) for _ in range(i%5)],'init':i,'fn':protocol.callback(['(a,b) => a + b','(a,b) => a - b','(a,b) => a + b*b'][i%3])}
        elif qid==2629:yield {'x':n,'functions':[protocol.callback('x => x * 2'),fn]*(i%4)}
        elif qid==2630:
            yield {'objects':{'a':{'n':n}},'inputs':[[{'$ref':'a'},{}],[{'$ref':'a'},{}],[{'$ref':'a'},{'$ref':'a'}],[{'$ref':'a'},{'$ref':'a'}]],'fn':{'kind':'merge_objects'}}
        elif qid==2631:yield {'array':[{'id':x} for x in ['__proto__','constructor','toString','x',str(n),'__proto__']],'fn':protocol.callback('x => x.id')}
        elif qid==2634:yield {'arr':[n,0,-1,1,k],'fn':protocol.callback(['x => x + 1','(x,i) => i === 0','x => String(x)','x => x % 3'][i%4])}
        elif qid==2635:yield {'arr':[n,0,-1,1,k],'fn':protocol.callback(['(x,i) => x + i','x => x % 3','x => x * x'][i%3])}
        elif qid==2666:yield {'calls':[[n],[k]],'fn':fn}
        elif qid==2693:yield {'args':[{'item':'item'+str(i)},.1,.2+i],'fn':{'kind':'tax_message'}}
        elif qid==2704:yield {'objects':{'a':{}},'value':[{'$ref':'a'},{},0,False,None][i%5],'other':[{'$ref':'a'},{},False,0,None][i%5],'method':'toBe' if i%2 else 'notToBe'}
        elif qid==2724:yield {'arr':[{'x':n+j*100} for j in (3,1,2,0)],'fn':protocol.callback('x => x.x')}
        elif qid==2622:yield {'actions':['TimeLimitedCache','set','set','get','get','count'],'values':[[],[i,i,20],[i,99,40],[i],[i],[]],'timeDelays':[0,0,10,20,50,60]}
        elif qid==2627:yield {'t':i*10,'calls':[{'t':50,'inputs':[n]},{'t':50+i*10,'inputs':[k]},{'t':100,'inputs':[i]}]}
        elif qid==2637:yield {'t':50,'inputs':[n],'fn':{'kind':'async','delay':[None,0,20,80][i%4],'outcome':'resolve' if i%2 else 'reject','expr':fn['expr']}}
        elif qid in (2715,2725):yield {'fn':fn,'args':[n],'t':30,'cancelTimeMs':[10,30,60,75][i%4]}
        elif qid==2721:yield {'functions':[{'delay':t,'outcome':'reject' if i%3==j else 'resolve','value':v} for j,(t,v) in enumerate([(60,n),(20,k),(20,i)])]}
        elif qid==2723:yield {'promise1':{'delay':20,'outcome':'resolve','value':n},'promise2':{'delay':0,'outcome':'resolve','value':k}}
        elif qid==2650:
            yield {'cancelledAt':[None,0,10,50][i%4],'program':[{'op':'try','error':'e','body':[
                {'op':'yield','promise':{'delay':20,'outcome':'reject' if i%2 else 'resolve','value':n}},
                {'op':'return','value':{'literal':k}}],
                'catch':[{'op':'yield','promise':{'delay':10,'outcome':'resolve','value':i},'target':'x','mode':'set'},
                         {'op':'return','value':{'local':'x'}}]}]}


def main():
    ap=argparse.ArgumentParser(__doc__);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    runner.DOCKER_IMAGE=image_digest();report={'image':runner.DOCKER_IMAGE,'checks':[]}
    for qid in sorted(references.SOURCES):
        descriptor=problem_packages.describe(qid);cases=deepcopy(descriptor['official'])
        for data in inputs(qid):cases.append({'args':data,'expected':answers.answer(qid,data),'origin':'deterministic_qa_not_published'})
        adapter=native.bridge(qid,descriptor);plan={'kind':'bridge',**adapter,'adapter_sha256':sha(adapter)}
        verdict=native_adapters.execute(qid,'javascript',references.SOURCES[qid],cases,descriptor['comparison'],plan)
        passed=verdict['ac_status']=='Accepted';report['checks'].append({'qid':qid,'passed':passed,'cases':cases,'verdict':verdict})
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(qid,len(cases),verdict['ac_status'],'PASS' if passed else 'FAIL',flush=True)
        if not passed:raise SystemExit(1)
    print('independent oracle disagreements: 0; cases:',sum(len(x['cases']) for x in report['checks']))


if __name__=='__main__':main()
