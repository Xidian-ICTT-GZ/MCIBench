"""Declarative promise/generator inputs, parsed without executing source text."""
import re

from local.lab import javascript_protocol as callbacks,source_guard
source_guard.register(__file__)
VERSION='javascript-async-protocol-v1'
QIDS=frozenset((2622,2627,2637,2650,2715,2721,2723,2725))


def promise(text,decode):
    text=' '.join(text.split()).strip().rstrip(';')
    head=re.fullmatch(r'new Promise\((?:\((?:resolve|res),\s*reject\)|resolve|res)\s*=>\s*(.*?)\)',text)
    if not head:raise ValueError('promise syntax outside reviewed protocol')
    body=head[1];delay=None
    timer=re.fullmatch(r'setTimeout\(\(\)\s*=>\s*(.*),\s*(\d+)\)',body)
    if timer:body=timer[1];delay=int(timer[2])
    else:
        timer=re.fullmatch(r'setTimeout\((?:res|resolve),\s*(\d+)\)',body)
        if timer:return {'delay':int(timer[1]),'outcome':'resolve'}
    end=re.fullmatch(r'(resolve|res|reject)\((.*)\)',body)
    if not end:raise ValueError('promise settlement outside reviewed protocol')
    value,offset=decode(end[2])
    if end[2][offset:].strip():raise ValueError('promise value outside JSON protocol')
    return {'delay':delay,'outcome':'reject' if end[1]=='reject' else 'resolve','value':value}


def _split_list(text):
    """Split commas only outside balanced JS delimiters and quoted strings."""
    result=[];start=0;stack=[];quote=None;escaped=False
    for i,ch in enumerate(text):
        if quote:
            if escaped:escaped=False
            elif ch=='\\':escaped=True
            elif ch==quote:quote=None
        elif ch in ('"',"'",'`'):quote=ch
        elif ch in '([{':stack.append(ch)
        elif ch in ')]}':
            if not stack or stack.pop()!={')':'(',']':'[','}':'{'}[ch]:raise ValueError('unbalanced function input')
        elif ch==',' and not stack:result.append(text[start:i].strip());start=i+1
    if quote or stack:raise ValueError('unbalanced function input')
    result.append(text[start:].strip())
    return [x for x in result if x]


def generator(text,decode):
    m=re.fullmatch(r'function\*\s*\(\)\s*\{(.*)\}',text.strip(),re.S)
    if not m:raise ValueError('generator syntax outside reviewed protocol')
    def expr(text):
        text=text.strip()
        template=re.fullmatch(r'`Error: \$\{(\w+)\}`',text)
        if template:return {'op':'add','args':[{'literal':'Error: '},{'local':template[1]}]}
        try:
            value,end=decode(text)
            if not text[end:].strip():return {'literal':value}
        except ValueError:pass
        if re.fullmatch(r'[A-Za-z_]\w*',text):return {'local':text}
        addition=re.fullmatch(r'(\w+)\s*\+\s*(\w+)',text)
        if addition:return {'op':'add','args':[expr(addition[1]),expr(addition[2])]}
        raise ValueError('generator expression outside reviewed protocol')
    def block(raw):
        statements=[];remaining=raw.strip()
        while remaining:
            remaining=remaining.strip().lstrip(';').strip()
            if not remaining:break
            if remaining.startswith('try'):
                start=re.match(r'try\s*\{',remaining)
                if not start:raise ValueError('invalid generator try')
                depth=1;end=start.end()
                while end<len(remaining) and depth:
                    if remaining[end]=='{':depth+=1
                    elif remaining[end]=='}':depth-=1
                    end+=1
                body=remaining[start.end():end-1];rest=remaining[end:]
                catch=re.match(r'\s*catch\s*\(\s*(\w+)\s*\)\s*\{',rest)
                if not catch:raise ValueError('generator catch missing')
                depth=1;stop=catch.end()
                while stop<len(rest) and depth:
                    if rest[stop]=='{':depth+=1
                    elif rest[stop]=='}':depth-=1
                    stop+=1
                if depth:raise ValueError('generator catch unbalanced')
                statements.append({'op':'try','body':block(body),'error':catch[1],'catch':block(rest[catch.end():stop-1])})
                remaining=rest[stop:];continue
            if ';' not in remaining:raise ValueError('generator statement terminator required')
            stmt,remaining=remaining.split(';',1);stmt=' '.join(stmt.split())
            if stmt.startswith(('return ','throw ')):
                op,body=stmt.split(' ',1);statements.append({'op':op,'value':expr(body)});continue
            assignment=re.fullmatch(r'(?:let|const)\s+(\w+)\s*=\s*(.*)',stmt)
            addition=re.fullmatch(r'(\w+)\s*\+=\s*(.*)',stmt)
            target=None;mode=None;body=stmt
            if assignment:target,body=assignment.groups();mode='set'
            elif addition:target,body=addition.groups();mode='add'
            if body.startswith('yield '):
                step={'op':'yield','promise':promise(body[6:],decode)}
                if target:step.update(target=target,mode=mode)
                statements.append(step)
            elif assignment:statements.append({'op':'set','target':target,'value':expr(body)})
            else:raise ValueError('generator statement outside reviewed protocol')
        return statements
    return block(m[1])


def official_input(qid,text,block,decode,assignments):
    if qid in (2622,2627):return assignments(text)
    def literal(raw):
        value,end=decode(raw.strip())
        if raw.strip()[end:].strip():raise ValueError('trailing asynchronous input')
        return value
    if qid in (2715,2725):
        parts=_split_list(text)
        if len(parts)!=3:raise ValueError('timer input fields missing')
        fn=re.sub(r'^fn\s*=\s*','',parts[0]);args=literal(re.sub(r'^args\s*=\s*','',parts[1]));t=literal(re.sub(r'^t\s*=\s*','',parts[2]))
        # The cancellation time is absent from Input. Read the same worked
        # example's explicit code, never derive it from the expected result.
        times=re.findall(r'\bconst\s+cancelTimeMs\s*=\s*(\d+)\s*;',block)
        if len(times)!=1:raise ValueError('cancel time lacks unambiguous same-example evidence')
        return {'fn':callbacks.callback(fn),'args':args,'t':t,'cancelTimeMs':int(times[0])}
    if qid==2637:
        m=re.fullmatch(r'fn\s*=\s*async\s*\((.*?)\)\s*=>\s*\{(.*?)\}\s*inputs\s*=\s*(\[.*?\])\s*t\s*=\s*(\d+)',text,re.S)
        if not m:raise ValueError('time-limit input outside reviewed protocol')
        body=' '.join(m[2].split());delay=None
        awaiter=re.match(r'await new Promise\(res => setTimeout\(res,\s*(\d+)\)\);\s*',body)
        if awaiter:delay=int(awaiter[1]);body=body[awaiter.end():]
        result=re.fullmatch(r'(return|throw)\s+(.*?);?',body)
        if not result:raise ValueError('async function body outside reviewed protocol')
        return {'fn':{'kind':'async','delay':delay,'outcome':'resolve' if result[1]=='return' else 'reject',
                      'expr':callbacks.expression(result[2],[p.strip() for p in m[1].split(',') if p.strip()])},'inputs':literal(m[3]),'t':int(m[4])}
    if qid==2721:
        m=re.fullmatch(r'functions\s*=\s*\[(.*)\]',text,re.S)
        if not m:raise ValueError('promise function list missing')
        return {'functions':[promise(re.sub(r'^\(\)\s*=>\s*','',fn),decode) for fn in _split_list(m[1])]}
    if qid==2723:
        parts=_split_list(text)
        if len(parts)!=2:raise ValueError('two promises required')
        return {f'promise{i+1}':promise(re.sub(r'^promise[12]\s*=\s*','',p),decode) for i,p in enumerate(parts)}
    if qid==2650:
        m=re.fullmatch(r'generatorFunction\s*=\s*(.*?)\s*cancelledAt\s*=\s*(null|\d+)',text,re.S)
        if not m:raise ValueError('generator input missing')
        return {'program':generator(m[1],decode),'cancelledAt':literal(m[2])}
    raise ValueError('unknown asynchronous task')


def valid(qid,data):
    try:return _valid(qid,data)
    except (TypeError,ValueError,KeyError,RecursionError,OverflowError):return False


def _valid(qid,data):
    if qid not in QIDS:return None
    if type(data) is not dict:return False
    integer=lambda x,lo,hi:type(x) is int and lo<=x<=hi
    def delay(v):return v is None or integer(v,0,1000000)
    def promised(p):return type(p) is dict and {'delay','outcome'}<=set(p)<= {'delay','outcome','value'} and delay(p['delay']) and p['outcome'] in ('resolve','reject')
    if qid in (2715,2725):return (set(data)=={'fn','args','t','cancelTimeMs'} and callbacks.valid_fn(data['fn']) and type(data['args']) is list and 1<=len(data['args'])<=10 and integer(data['t'],20,1000) and integer(data['cancelTimeMs'],10,1000) and (qid==2715 or 30<=data['t']<=100 and data['cancelTimeMs']<=500))
    if qid==2637:
        p=data.get('fn');return (set(data)=={'fn','inputs','t'} and type(data['inputs']) is list and len(data['inputs'])<=10 and integer(data['t'],0,1000) and type(p) is dict and set(p)=={'kind','delay','outcome','expr'} and p['kind']=='async' and delay(p['delay']) and p['outcome'] in ('resolve','reject') and callbacks.valid_fn({'kind':'expression','expr':p['expr']}))
    if qid==2721:return set(data)=={'functions'} and type(data['functions']) is list and 1<=len(data['functions'])<=10 and all(promised(p) for p in data['functions'])
    if qid==2723:return set(data)=={'promise1','promise2'} and all(promised(p) and p['outcome']=='resolve' and type(p.get('value')) in (int,float) for p in data.values())
    if qid==2627:return (set(data)=={'t','calls'} and integer(data['t'],0,1000) and type(data['calls']) is list and 1<=len(data['calls'])<=10 and all(type(c) is dict and set(c)=={'t','inputs'} and integer(c['t'],0,1000) and type(c['inputs']) is list and len(c['inputs'])<=10 for c in data['calls']))
    if qid==2622:
        if set(data)!={'actions','values','timeDelays'} or any(type(data[k]) is not list for k in data) or not 1<=len(data['actions'])<=100 or len(data['actions'])!=len(data['values']) or len(data['actions'])!=len(data['timeDelays']):return False
        if data['actions'][0]!='TimeLimitedCache' or data['values'][0]!=[] or data['timeDelays'][0]!=0:return False
        for i,(a,v,t) in enumerate(zip(data['actions'],data['values'],data['timeDelays'])):
            if type(v) is not list or not integer(t,0,1450) or (i and a=='TimeLimitedCache'):return False
            if a=='set' and (len(v)!=3 or not all(integer(n,0,10**9) for n in v[:2]) or not integer(v[2],0,1000)):return False
            if a=='get' and (len(v)!=1 or not integer(v[0],0,10**9)):return False
            if a=='count' and v:return False
            if a not in ('TimeLimitedCache','set','get','count'):return False
        return True
    if set(data)!={'program','cancelledAt'} or not (data['cancelledAt'] is None or integer(data['cancelledAt'],0,1000)):return False
    count=[0]
    def expr(e):
        if type(e) is not dict:return False
        if set(e)=={'literal'}:return True
        if set(e)=={'local'}:return type(e['local']) is str and bool(re.fullmatch('[A-Za-z_]\\w*',e['local']))
        return set(e)=={'op','args'} and e['op']=='add' and type(e['args']) is list and len(e['args'])==2 and all(expr(x) for x in e['args'])
    def program(steps,depth=0):
        if depth>10 or type(steps) is not list:return False
        for s in steps:
            count[0]+=1
            if count[0]>100 or type(s) is not dict:return False
            op=s.get('op')
            if op in ('return','throw'):
                if set(s)!={'op','value'} or not expr(s['value']):return False
            elif op=='set':
                if set(s)!={'op','target','value'} or not expr(s['value']) or not expr({'local':s['target']}):return False
            elif op=='yield':
                if not {'op','promise'}<=set(s)<={'op','promise','target','mode'} or not promised(s['promise']):return False
                if ('target' in s)!=('mode' in s) or 'target' in s and (s['mode'] not in ('set','add') or not expr({'local':s['target']})):return False
            elif op=='try':
                if set(s)!={'op','body','error','catch'} or not expr({'local':s['error']}) or not program(s['body'],depth+1) or not program(s['catch'],depth+1):return False
            else:return False
        return True
    return program(data['program'])


def note(qid):
    if qid not in QIDS:return ''
    return ('Reviewed async protocol '+VERSION+'. Promises are {delay:MS_OR_NULL,outcome:"resolve"|"reject",value:JSON}; '
        'omitted value means undefined; null delay means immediate settlement, numeric delay means a timer. '
        'timeLimit fn is {kind:"async",delay:MS_OR_NULL,outcome:"resolve"|"reject",expr:CALLBACK_EXPRESSION}; see callback expression protocol. '
        'Generator program is a finite list of {op:"set",target:NAME,value:EXPR}, {op:"yield",promise:PROMISE,target:OPTIONAL_NAME,mode:"set"|"add"}, '
        '{op:"return"|"throw",value:EXPR}, {op:"try",body:PROGRAM,error:NAME,catch:PROGRAM}. '
        'Generator EXPR: {literal:JSON}, {local:NAME}, or {op:"add",args:[EXPR,EXPR]}. '
        'Callbacks use the reviewed declarative expression family; never execute input source strings. '
        'Use an ideal deterministic millisecond clock: Date.now/new Date/performance.now and timeout/interval/clear APIs share it. '
        'Drain native Promise microtasks after each timer; equal-time events use scheduling order. Input events are scheduled before timers they create. '
        'timeDelays for TimeLimitedCache are ABSOLUTE times, not cumulative delays; expiration at a deadline precedes an operation at that same deadline. Timer normalization is a local execution contract, not a claim of LeetCode timing equivalence. '
        'For cancellable timers, cancelTimeMs comes from the same official explanation, not from expected outputs. '
        'For generated inputs, include explicit cancelTimeMs. timeLimit with numeric fn.delay exactly equal to t remains pending verified interpretation and is not published automatically. '
        'Generator controllers only construct a real generator and pass it to the candidate; they do not drive it to completion themselves.')
