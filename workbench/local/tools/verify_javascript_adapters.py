"""Real sandbox acceptance of native callbacks, identities and virtual timers.

Manual solutions below are adapter fixtures, not model performance samples and
not part of the functional mutation-rate benchmark.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from local.harness import runner
from local.harness.identity import image_digest
from local.lab import native_adapters as adapters,native_javascript as native,problem_packages as packages
from local.lab.behavior import sha

from local.lab.javascript_references import SOURCES as FIXTURES


def main():
    ap=argparse.ArgumentParser(__doc__);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    runner.DOCKER_IMAGE=image_digest();report={'image':runner.DOCKER_IMAGE,'fixture_scope':'adapter gates only; not model accuracy or mutation-rate samples',
        'sources':{name:sha(Path(module.__file__).read_text(encoding='utf8')) for name,module in [('native',native),('callbacks',native.protocol),('async',native.asynchronous),('clock',native.clock)]},'checks':[]}
    def check(qid,label,code,*,cases=None,expected=None,entry=False):
        d=packages.describe(qid);plan={'kind':'bridge',**native.bridge(qid,d)}
        plan['adapter_sha256']=sha({'prefix':plan['prefix'],'suffix':plan['suffix']})
        rows=cases if cases is not None else d['official']
        result=adapters.execute(qid,'javascript',code,rows,d['comparison'],plan,collect=entry)
        passed=native.observed_entry(result,adapters.SENTINEL) if entry else result['ac_status']==expected
        report['checks'].append({'qid':qid,'label':label,'source':code,'source_sha256':sha(code),'passed':passed,'cases':rows,'verdict':result})
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(qid,label,result['ac_status'],'PASS' if passed else 'FAIL',flush=True)
        if not passed:raise SystemExit(1)
    for qid,code in sorted(FIXTURES.items()):
        check(qid,'reviewed native fixture / all public examples',code,expected='Accepted')
        check(qid,'native entry exception is observed',native.negative_source(qid,adapters.SENTINEL),entry=True)
        # A fully completed wrong return proves output sensitivity. RE/CE/TLE
        # must not count; run the same collection gate as the production flow.
        d=packages.describe(qid);plan={'kind':'bridge',**native.bridge(qid,d),'adapter_sha256':'gate-only'}
        gate=adapters.sensitivity_gate(qid,'javascript',native.sensitivity_source(qid),d['official'],d['comparison'],plan)
        report['checks'].append({'qid':qid,'label':'completed wrong-output gate','passed':gate['passed'],'gate':gate})
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(qid,'completed wrong-output gate','PASS' if gate['passed'] else 'FAIL',flush=True)
        if not gate['passed']:raise SystemExit(1)
    # Wrong implementations which previously could appear plausible.
    check(2630,'JSON value equality must not merge distinct identities',
        'var memoize=fn=>{const c=new Map();return (...a)=>{const k=JSON.stringify(a);if(!c.has(k))c.set(k,fn(...a));return c.get(k);};};',expected='Wrong Answer')
    check(2666,'returning cached first value instead of undefined is rejected',
        'var once=fn=>{let used=false,value;return (...a)=>{if(!used){used=true;value=fn(...a);}return value;};};',expected='Wrong Answer')
    check(2721,'sequential promise execution violates elapsed time',
        'var promiseAll=async fs=>{const values=[];for(const f of fs)values.push(await f());return values;};',expected='Wrong Answer')
    check(2650,'uncaught cancellation cannot replace caught partial result',
        'var cancellable=g=>{let reject;const p=new Promise((a,b)=>{reject=b;(async()=>{try{let s=g.next();while(!s.done)s=g.next(await s.value);a(s.value);}catch(e){b(e);}})();});return [()=>reject("Cancelled"),p];};',expected='Wrong Answer')
    # Microtask drain must handle arbitrary finite depth, not N await loops.
    chain='var timeLimit=(fn,t)=>(...a)=>Promise.race([(async()=>{for(let i=0;i<200;i++)await Promise.resolve();return fn(...a);})(),new Promise((_,r)=>setTimeout(()=>r("Time Limit Exceeded"),t))]);'
    check(2637,'200 native microtasks do not advance virtual time',chain,expected='Accepted')
    check(2704,'same-object references compare by actual identity',FIXTURES[2704],cases=[
        {'args':{'objects':{'a':{}},'value':{'$ref':'a'},'other':{'$ref':'a'},'method':'toBe'},'expected':{'value':True}},
        {'args':{'objects':{},'value':{},'other':{},'method':'toBe'},'expected':{'error':'Not Equal'}}],expected='Accepted')
    timer_cache='''var TimeLimitedCache=function(){this.values=new Map();};
TimeLimitedCache.prototype.set=function(k,v,d){const old=this.values.get(k);if(old)clearTimeout(old.timer);this.values.set(k,{v,timer:setTimeout(()=>this.values.delete(k),d)});return !!old;};
TimeLimitedCache.prototype.get=function(k){return this.values.get(k)?.v??-1;};TimeLimitedCache.prototype.count=function(){return this.values.size;};'''
    boundary=[{'args':{'actions':['TimeLimitedCache','set','get','set','get','get'],
       'values':[[],[1,4,0],[1],[1,8,10],[1],[1]],'timeDelays':[0,0,0,1,10,11]},'expected':[None,False,-1,False,8,-1]}]
    check(2622,'timer cache expires at exact deadline including zero duration',timer_cache,cases=boundary,expected='Accepted')
    check(2622,'timestamp cache agrees with timer cache at exact deadline',FIXTURES[2622],cases=boundary,expected='Accepted')
    check(2627,'same-time input event precedes the timer it cancels',FIXTURES[2627],cases=[
        {'args':{'t':50,'calls':[{'t':50,'inputs':[1]},{'t':100,'inputs':[2]}]},'expected':[{'t':150,'inputs':[2]}]}],expected='Accepted')
    fn={'kind':'expression','expr':{'arg':0}}
    check(2715,'equal-time timeout was scheduled before cancellation',FIXTURES[2715],cases=[
        {'args':{'fn':fn,'args':[5],'t':30,'cancelTimeMs':30},'expected':[{'time':30,'returned':5}]}],expected='Accepted')
    check(2725,'cancellation precedes rescheduled equal-time interval',FIXTURES[2725],cases=[
        {'args':{'fn':fn,'args':[5],'t':30,'cancelTimeMs':60},'expected':[{'time':0,'returned':5},{'time':30,'returned':5}]}],expected='Accepted')
    check(2721,'earliest rejection wins even if later in input order',FIXTURES[2721],cases=[
        {'args':{'functions':[{'delay':90,'outcome':'reject','value':'late'},{'delay':20,'outcome':'reject','value':'first'}]},'expected':{'t':20,'rejected':'first'}}],expected='Accepted')
    check(2650,'caught cancellation resolves next yield and stops generator',FIXTURES[2650],cases=[
        {'args':{'cancelledAt':20,'program':[{'op':'try','error':'e','body':[{'op':'yield','promise':{'delay':100,'outcome':'resolve'}}],
           'catch':[{'op':'yield','promise':{'delay':None,'outcome':'resolve','value':2}},{'op':'return','value':{'literal':99}}]}]},'expected':{'resolved':2}}],expected='Accepted')
    date_cache=FIXTURES[2622].replace('Date.now()','new Date().getTime()')
    check(2622,'new Date shares the virtual clock',date_cache,expected='Accepted')
    print('JavaScript adapter failures: 0; checks:',len(report['checks']))


if __name__=='__main__':main()
