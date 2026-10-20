"""Independent Python answers for the finite declarative JavaScript protocols.

These algorithms neither call a candidate nor execute input source strings. The
published corpus also requires agreement with a separate native JS reference.
"""
from copy import deepcopy
from decimal import Decimal
import heapq
import math

from local.lab import javascript_protocol as sync,javascript_async as asynchronous,source_guard
source_guard.register(__file__)
UNDEFINED=object()


def string(v):
    if v is UNDEFINED:return 'undefined'
    if v is None:return 'null'
    if type(v) is bool:return 'true' if v else 'false'
    if type(v) is str:return v
    if type(v) is dict:return '[object Object]'
    if type(v) is list:return ','.join('' if x is None or x is UNDEFINED else string(x) for x in v)
    v=float(v)
    if math.isnan(v):return 'NaN'
    if math.isinf(v):return 'Infinity' if v>0 else '-Infinity'
    if v==0:return '0'
    raw=repr(v)
    if 1e-6<=abs(v)<1e21:return format(Decimal(raw),'f').rstrip('0').rstrip('.') if '.' in format(Decimal(raw),'f') else format(Decimal(raw),'f')
    mantissa,exponent=raw.split('e') if 'e' in raw else (raw,'0')
    return mantissa.rstrip('0').rstrip('.')+'e'+('+' if int(exponent)>=0 else '-')+str(abs(int(exponent)))


def number(v):
    if v is UNDEFINED:return math.nan
    if v is None:return 0.0
    if type(v) in (int,float,bool):return float(v)
    if type(v) in (dict,list):v=string(v)
    try:return float(v.strip()) if v.strip() else 0.0
    except ValueError:return math.nan


def truth(v):
    return not (v is None or v is UNDEFINED or v is False or type(v) is str and not v or type(v) in (int,float) and (v==0 or math.isnan(float(v))))


def equal(a,b):
    if type(a) in (dict,list) or type(b) in (dict,list):return a is b
    if type(a) in (int,float) and type(b) in (int,float):return float(a)==float(b)
    return type(a) is type(b) and a==b


def add(a,b):
    if type(a) in (dict,list):a=string(a)
    if type(b) in (dict,list):b=string(b)
    return string(a)+string(b) if type(a) is str or type(b) is str else number(a)+number(b)


def callback(fn,args,context=UNDEFINED):
    def eval_expr(e):
        if 'literal' in e:return e['literal']
        if 'arg' in e:return args[e['arg']] if e['arg']<len(args) else UNDEFINED
        if 'context' in e:return get(context,e['context'])
        op=e['op'];a=[eval_expr(x) for x in e['args']]
        if op=='get':return get(a[0],a[1])
        if op=='add':return add(*a)
        if op=='subtract':return number(a[0])-number(a[1])
        if op=='multiply':return number(a[0])*number(a[1])
        if op=='modulo':return math.fmod(number(a[0]),number(a[1])) if number(a[1]) else math.nan
        if op=='power':return math.pow(number(a[0]),number(a[1]))
        if op=='negate':return -number(a[0])
        if op=='string':return string(a[0])
        if op in ('strict_equal','strict_not_equal'):return equal(*a)==(op=='strict_equal')
        left,right=a
        if type(left) in (dict,list):left=string(left)
        if type(right) in (dict,list):right=string(right)
        if not (type(left) is str and type(right) is str):left,right=number(left),number(right)
        return {'gt':lambda:left>right,'ge':lambda:left>=right,'lt':lambda:left<right,'le':lambda:left<=right}[op]()
    def properties(v):
        if type(v) is dict:return v
        if type(v) in (str,list):return {str(i):x for i,x in enumerate(v)}
        return {}
    if fn['kind']=='merge_objects':return {**properties(args[0]),**properties(args[1])}
    if fn['kind']=='tax_message':return 'The cost of the '+string(get(context,'item'))+' is '+string(number(args[0])*number(args[1]))
    return eval_expr(fn['expr'])


def get(value,key):
    if value is None or value is UNDEFINED:raise ValueError('callback reads a property of null/undefined')
    key=string(key)
    if type(value) is dict:return value.get(key,UNDEFINED)
    if type(value) in (str,list):
        if key=='length':return len(value)
        if key.isdigit() and str(int(key))==key and int(key)<len(value):return value[int(key)]
    return UNDEFINED


def references(data):
    pool=deepcopy(data['objects'])
    def restore(v):
        if type(v) is dict:
            if set(v)=={'$ref'}:return pool[v['$ref']]
            return {k:restore(x) for k,x in v.items()}
        return [restore(x) for x in v] if type(v) is list else v
    return restore


def _answer(qid,data):
    if qid==2620:return [data['n']+i for i in range(len(data['calls']))]
    if qid==2618:
        obj=data['object'];target=data['class']
        if target in ('null','undefined') or 'undefined' in obj or obj.get('primitive',UNDEFINED) is None:return False
        if 'primitive' in obj:
            first={bool:'Boolean',int:'Number',float:'Number',str:'String'}[type(obj['primitive'])]
            return target in (first,'Object')
        if 'class' in obj:return target in ('Function','Object')
        cls=obj['instance']
        while cls:
            if cls==target:return True
            cls=data['classes'][cls] or 'Object' if cls in data['classes'] else 'Object' if cls!='Object' else None
        return False
    if qid==2629:
        out=data['x']
        for f in reversed(data['functions']):
            out=callback(f,[out])
            if type(out) not in (int,float) or not math.isfinite(out) or int(out)!=out:raise ValueError('composition callback must return an integer')
        return out
    if qid==2626:
        out=data['init']
        for n in data['nums']:
            out=callback(data['fn'],[out,n])
            if type(out) not in (int,float) or not math.isfinite(out):raise ValueError('reducer must return a finite number')
        return out
    if qid in (2634,2635):
        out=[]
        for i,n in enumerate(data['arr']):
            value=callback(data['fn'],[n,i])
            if qid==2634:
                if truth(value):out.append(n)
            else:
                if type(value) not in (int,float) or not math.isfinite(value) or int(value)!=value:raise ValueError('mapping callback must return an integer')
                out.append(value)
        return out
    if qid==2631:
        groups={}
        for item in data['array']:
            key=callback(data['fn'],[item])
            if type(key) is not str:raise ValueError('group selector must return a string')
            groups.setdefault(key,[]).append(item)
        return groups
    if qid==2724:
        keys=[callback(data['fn'],[item]) for item in data['arr']]
        if any(type(k) not in (int,float) or not math.isfinite(k) for k in keys) or len(set(keys))!=len(keys):raise ValueError('sort keys must be distinct finite numbers')
        return [value for _,value in sorted(zip(keys,data['arr']),key=lambda pair:pair[0])]
    if qid==2693:return callback(data['fn'],data['args'][1:],data['args'][0])
    if qid==2666:
        result=callback(data['fn'],data['calls'][0]);return [{'calls':1,'value':{'$undefined':True} if result is UNDEFINED else result}]
    if qid==2704:
        restore=references(data);same=equal(restore(data['value']),restore(data['other']))
        success=same if data['method']=='toBe' else not same
        return {'value':True} if success else {'error':'Not Equal' if data['method']=='toBe' else 'Equal'}
    if qid==2630:
        restore=references(data);invocations=[restore(row) for row in data['inputs']];cache={};out=[];calls=0
        def key(v):return ('object',id(v)) if type(v) in (dict,list) else ('number',float(v)) if type(v) in (int,float) else (type(v).__name__,v)
        for args in invocations:
            identity=tuple(key(v) for v in args)
            if identity not in cache:
                calls+=1;value=callback(data['fn'],args);cache[identity]=value
            else:value=cache[identity]
            out.append({'val':value,'calls':calls})
        return out
    if qid==2622:
        state={};out=[None]*len(data['actions'])
        for t,i in sorted((t,i) for i,t in enumerate(data['timeDelays']) if i):
            action=data['actions'][i];args=data['values'][i]
            state={k:v for k,v in state.items() if v[1]>t}
            if action=='set':
                k,v,d=args;out[i]=k in state;state[k]=(v,t+d)
            elif action=='get':out[i]=state.get(args[0],(-1,))[0]
            else:out[i]=len(state)
        return out
    if qid==2627:
        queue=[(c['t'],i,'input',c['inputs']) for i,c in enumerate(data['calls'])];heapq.heapify(queue)
        serial=len(queue);pending=None;out=[]
        while queue:
            t,i,kind,args=heapq.heappop(queue)
            if kind=='input':serial+=1;pending=serial;heapq.heappush(queue,(t+data['t'],serial,'invoke',args))
            elif i==pending:out.append({'t':t,'inputs':args})
        return out
    if qid in (2715,2725):
        value=callback(data['fn'],data['args'])
        if qid==2715:return [{'time':data['t'],'returned':value}] if data['t']<=data['cancelTimeMs'] else []
        times=list(range(0,data['cancelTimeMs'],data['t']))
        if data['cancelTimeMs']==data['t']:times.append(data['t'])
        return [{'time':t,'returned':value} for t in times]
    if qid==2637:
        delay=data['fn']['delay']
        if delay is not None and delay==data['t']:raise ValueError('equal-deadline timeLimit behavior awaits verified interpretation')
        if delay is not None and delay>data['t']:return {'rejected':'Time Limit Exceeded','time':data['t']}
        return {'resolved' if data['fn']['outcome']=='resolve' else 'rejected':callback({'kind':'expression','expr':data['fn']['expr']},data['inputs']),'time':delay or 0}
    if qid==2721:
        failed=[(p['delay'] or 0,i,p.get('value',UNDEFINED)) for i,p in enumerate(data['functions']) if p['outcome']=='reject']
        if failed:
            t,_,value=min(failed,key=lambda row:row[:2]);return {'t':t,'rejected':value}
        return {'t':max(p['delay'] or 0 for p in data['functions']),'resolved':[p.get('value',UNDEFINED) for p in data['functions']]}
    if qid==2723:return number(data['promise1']['value'])+number(data['promise2']['value'])
    if qid==2650:return generator_answer(data)
    raise ValueError('no reviewed protocol answer')


class ScriptError(Exception):
    def __init__(self,value):self.value=value


def generator_answer(data):
    locals={}
    def expr(e):
        if 'literal' in e:return e['literal']
        if 'local' in e:return locals.get(e['local'],UNDEFINED)
        return add(expr(e['args'][0]),expr(e['args'][1]))
    def run(steps):
        for s in steps:
            if s['op']=='return':return True,expr(s['value'])
            if s['op']=='throw':raise ScriptError(expr(s['value']))
            if s['op']=='set':locals[s['target']]=expr(s['value'])
            elif s['op']=='yield':
                value=yield s['promise']
                if 'target' in s:locals[s['target']]=add(locals.get(s['target'],UNDEFINED),value) if s['mode']=='add' else value
            elif s['op']=='try':
                try:completed,value=yield from run(s['body'])
                except ScriptError as e:locals[s['error']]=e.value;completed,value=yield from run(s['catch'])
                if completed:return True,value
        return False,UNDEFINED
    gen=run(data['program']);now=0;sequence=0;cancelled=False;queued=[]
    def resume(method,value=None,cancel=False):
        nonlocal sequence
        try:
            p=next(gen) if method=='start' else gen.throw(ScriptError(value)) if method=='throw' else gen.send(value)
        except StopIteration as e:return {'resolved':e.value[1]}
        except ScriptError as e:return {'rejected':e.value}
        if cancel:return {('resolved' if p['outcome']=='resolve' else 'rejected'):p.get('value',UNDEFINED)}
        if p['delay'] is None:return resume('throw' if p['outcome']=='reject' else 'next',p.get('value',UNDEFINED))
        sequence+=1;heapq.heappush(queued,(now+p['delay'],sequence,p));return None
    result=resume('start')
    if result is not None:return result
    sequence+=1
    if data['cancelledAt'] is not None:heapq.heappush(queued,(data['cancelledAt'],sequence,None))
    while queued:
        now,_,p=heapq.heappop(queued)
        result=resume('throw','Cancelled',True) if p is None else resume('throw' if p['outcome']=='reject' else 'next',p.get('value',UNDEFINED))
        if result is not None:return result
    raise ValueError('generator did not complete')


def answer(qid,data):
    validator=asynchronous.valid if qid in asynchronous.QIDS else sync.valid
    if validator(qid,data) is not True:raise ValueError('input violates reviewed protocol construction rules')
    out=_answer(qid,deepcopy(data))
    def check(v):
        if v is UNDEFINED:raise ValueError('output is undefined outside supported JSON result scope')
        if type(v) is float and not math.isfinite(v):raise ValueError('nonfinite result outside supported JSON scope')
        if type(v) is dict:return {k:check(x) for k,x in v.items()}
        if type(v) is list:return [check(x) for x in v]
        if type(v) in (int,float):
            n=float(v)
            if not math.isfinite(n):raise ValueError('nonfinite result outside supported JSON scope')
            return int(n) if n.is_integer() and abs(n)<1e21 else n
        return v
    return check(out)
