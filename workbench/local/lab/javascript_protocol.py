"""Reviewed declarative inputs for higher-order JavaScript tasks.

Function source is parsed into a small expression tree, never evaluated on the
host. This protocol covers the documented callback families, not arbitrary JS.
Native solutions still receive real functions and real shared object identities.
"""
import ast
import json
import re

from local.lab import source_guard
source_guard.register(__file__)

VERSION = 'javascript-callback-protocol-v1'
QIDS = frozenset((2618,2620,2626,2629,2630,2631,2634,2635,2666,2693,2704,2724))


def expression(text, params):
    """Translate only whitelisted expression syntax; no eval/exec/JS engine."""
    text=text.strip().rstrip(';').strip()
    while text.startswith('(') and text.endswith(')'):
        try:ast.parse(text[1:-1],mode='eval');text=text[1:-1].strip()
        except SyntaxError:break
    text=text.replace('===','==').replace('!==','!=')
    tree=ast.parse(text,mode='eval')
    def visit(n):
        if isinstance(n,ast.Constant) and type(n.value) in (int,float,bool,str,type(None)):return {'literal':n.value}
        if isinstance(n,ast.Name) and n.id in params:return {'arg':params.index(n.id)}
        if isinstance(n,ast.Name) and n.id in ('true','false','null'):return {'literal':{'true':True,'false':False,'null':None}[n.id]}
        if isinstance(n,ast.Attribute):
            if isinstance(n.value,ast.Name) and n.value.id=='this':return {'context':n.attr}
            return {'op':'get','args':[visit(n.value),{'literal':n.attr}]}
        if isinstance(n,ast.Subscript):return {'op':'get','args':[visit(n.value),visit(n.slice)]}
        if isinstance(n,ast.BinOp) and type(n.op) in (ast.Add,ast.Sub,ast.Mult,ast.Mod,ast.Pow):
            return {'op':{ast.Add:'add',ast.Sub:'subtract',ast.Mult:'multiply',ast.Mod:'modulo',ast.Pow:'power'}[type(n.op)],'args':[visit(n.left),visit(n.right)]}
        if isinstance(n,ast.UnaryOp) and isinstance(n.op,ast.USub):return {'op':'negate','args':[visit(n.operand)]}
        if isinstance(n,ast.Compare) and len(n.ops)==1 and type(n.ops[0]) in (ast.Gt,ast.Lt,ast.GtE,ast.LtE,ast.Eq,ast.NotEq):
            return {'op':{ast.Gt:'gt',ast.Lt:'lt',ast.GtE:'ge',ast.LtE:'le',ast.Eq:'strict_equal',ast.NotEq:'strict_not_equal'}[type(n.ops[0])],'args':[visit(n.left),visit(n.comparators[0])]}
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='String' and len(n.args)==1 and not n.keywords:
            return {'op':'string','args':[visit(n.args[0])]}
        raise ValueError('callback expression outside reviewed protocol')
    return visit(tree.body)


def callback(text):
    text=' '.join(text.strip().split()).rstrip(',;')
    # Object spread and this-bound templates are explicit reviewed operations.
    if re.fullmatch(r'function\s*\w*\s*\(a,\s*b\)\s*\{\s*return\s*\(\{\.\.\.a,\s*\.\.\.b\}\);?\s*\}',text):return {'kind':'merge_objects'}
    if re.fullmatch(r'function\s+tax\(price,\s*taxRate\)\s*\{\s*return `The cost of the \$\{this.item\} is \$\{price \* taxRate\}`;?\s*\}',text):return {'kind':'tax_message'}
    m=re.fullmatch(r'function\s*\w*\s*\(([^)]*)\)\s*\{\s*return\s+(.*?);?\s*\}',text)
    if not m:m=re.fullmatch(r'(\([^)]*\)|[A-Za-z_]\w*)\s*=>\s*(.*)',text)
    if not m:raise ValueError('callback syntax outside reviewed protocol')
    params=[p.strip() for p in m[1].strip('()').split(',') if p.strip()]
    if len(params)>4 or len(set(params))!=len(params) or any(not re.fullmatch(r'[A-Za-z_]\w*',p) for p in params):raise ValueError('callback parameters outside reviewed protocol')
    body=m[2].strip()
    if body.startswith('{') and body.endswith('}'):
        body=body[1:-1].strip()
        if not body.startswith('return '):raise ValueError('callback must return an expression')
        body=body[7:]
    return {'kind':'expression','expr':expression(body,params)}


def official_input(qid, text, decode):
    """Return a reviewed input, or fail rather than guessing from the answer."""
    def value(s):
        out,end=decode(s.strip())
        if s.strip()[end:].strip():raise ValueError('trailing input syntax')
        return out
    if qid==2620:
        m=re.fullmatch(r'n\s*=\s*(-?\d+)\s*(\[.*\])',text,re.S)
        if not m:raise ValueError('counter calls missing')
        return {'n':int(m[1]),'calls':value(m[2])}
    if qid==2629:
        m=re.fullmatch(r'functions\s*=\s*\[(.*?)\]\s*,\s*x\s*=\s*(-?\d+)',text,re.S)
        if not m:raise ValueError('composition input missing')
        return {'functions':[callback(s) for s in m[1].split(',') if s.strip()],'x':int(m[2])}
    if qid in (2626,2634,2635,2631,2724):
        m=re.match(r'(nums|arr|array)\s*=\s*',text)
        if not m:raise ValueError('array input missing')
        arr,end=decode(text[m.end():].strip());rest=text[m.end():].strip()[end:].strip().lstrip(',').strip()
        if not rest.startswith('fn'):raise ValueError('callback input missing')
        fn=re.sub(r'^fn\s*=\s*','',rest)
        result={m[1]:arr}
        if qid==2626:
            n=re.search(r'\s+init\s*=\s*(-?\d+)\s*$',fn)
            if not n:raise ValueError('reduce initial value missing')
            result['init']=int(n[1]);fn=fn[:n.start()].rstrip(', \n')
        result['fn']=callback(fn)
        return result
    if qid in (2666,2693):
        m=re.search(r'\b(calls|args)\s*=\s*',text)
        if not m:raise ValueError('invocation input missing')
        fn=re.sub(r'^fn\s*=\s*','',text[:m.start()].strip()).rstrip(', \n')
        return {'fn':callback(fn),m[1]:value(text[m.end():])}
    if qid==2630:
        m=re.search(r'\bfn\s*=\s*',text)
        if not m:raise ValueError('memoized callback missing')
        inputs=re.sub(r'^getInputs\s*=\s*\(\)\s*=>\s*','',text[:m.start()].strip()).strip()
        objects={}
        if inputs.startswith('{'):
            n=re.fullmatch(r'\{\s*const\s+o\s*=\s*\{\};\s*return\s+(.*?);?\s*\}',inputs,re.S)
            if not n:raise ValueError('object alias syntax outside reviewed protocol')
            objects={'o':{}};inputs=re.sub(r'\bo\b','{"$ref":"o"}',n[1].rstrip(';').strip())
        return {'objects':objects,'inputs':value(inputs),'fn':callback(text[m.end():])}
    if qid==2704:
        m=re.fullmatch(r'func\s*=\s*\(\)\s*=>\s*expect\((.*?)\)\.(toBe|notToBe)\((.*?)\)',text,re.S)
        if not m:raise ValueError('expect invocation outside reviewed protocol')
        return {'objects':{},'value':value(m[1]),'method':m[2],'other':value(m[3])}
    if qid==2618:
        m=re.search(r'checkIfInstanceOf\((new\s+\w+\(\)|\w+),\s*(\w+)\)',text)
        if not m:raise ValueError('instance input outside reviewed protocol')
        first=m[1];classes={name:parent for name,parent in re.findall(r'class\s+(\w+)\s+extends\s+(\w+)',text)}
        classes.update({name:None for name in re.findall(r'class\s+(\w+)\s*\{',text)})
        obj=({'instance':first[4:-2].strip()} if first.startswith('new ') else {'class':first} if first in ('Date','Number','String','Object','Array','Function','Boolean') or first in classes else {'primitive':value(first)})
        return {'classes':classes,'object':obj,'class':m[2]}
    raise ValueError('unknown callback task')


def valid_fn(fn):
    if type(fn) is not dict:return False
    if fn=={'kind':'merge_objects'} or fn=={'kind':'tax_message'}:return True
    if set(fn)!={'kind','expr'} or fn['kind']!='expression':return False
    def expr(e,depth=0):
        if depth>20 or type(e) is not dict:return False
        if set(e)=={'literal'}:return type(e['literal']) in (str,int,float,bool,type(None))
        if set(e)=={'arg'}:return type(e['arg']) is int and 0<=e['arg']<4
        if set(e)=={'context'}:return type(e['context']) is str
        arity={'add':2,'subtract':2,'multiply':2,'modulo':2,'power':2,'get':2,'gt':2,'lt':2,'ge':2,'le':2,'strict_equal':2,'strict_not_equal':2,'negate':1,'string':1}
        return (set(e)=={'op','args'} and type(e['op']) is str and e['op'] in arity and type(e['args']) is list
                and len(e['args'])==arity[e['op']] and all(expr(a,depth+1) for a in e['args']))
    return expr(fn['expr'])


def valid(qid,data):
    try:return _valid(qid,data)
    except (TypeError,ValueError,KeyError,RecursionError,OverflowError):return False


def _valid(qid,data):
    """Protocol/known statement bounds only; None leaves unknown tasks alone."""
    if qid not in QIDS:return None
    if type(data) is not dict:return False
    integer=lambda x,lo,hi:type(x) is int and lo<=x<=hi
    if qid==2620:return set(data)=={'n','calls'} and integer(data['n'],-1000,1000) and type(data['calls']) is list and len(data['calls'])<=1000 and all(c=='call' for c in data['calls'])
    if qid==2629:return set(data)=={'functions','x'} and integer(data['x'],-1000,1000) and type(data['functions']) is list and len(data['functions'])<=1000 and all(valid_fn(f) for f in data['functions'])
    if qid in (2626,2634,2635,2631,2724):
        name='nums' if qid==2626 else 'array' if qid==2631 else 'arr'
        if set(data)!={name,'fn'}|({'init'} if qid==2626 else set()) or type(data[name]) is not list or not valid_fn(data['fn']):return False
        arr=data[name]
        if qid==2626:return len(arr)<=1000 and all(integer(x,0,1000) for x in arr) and integer(data['init'],0,1000)
        if qid in (2634,2635):return len(arr)<=1000 and all(integer(x,-10**9,10**9) for x in arr)
        return len(arr)<=100000 if qid==2631 else 1<=len(arr)<=500000
    if qid in (2630,2704):
        fields={'objects','inputs','fn'} if qid==2630 else {'objects','value','other','method'}
        if set(data)!=fields or type(data['objects']) is not dict:return False
        if any(type(v) not in (dict,list) for v in data['objects'].values()):return False
        def refs(v):
            if type(v) is dict:
                if '$ref' in v:return set(v)=={'$ref'} and type(v['$ref']) is str and v['$ref'] in data['objects']
                return all(refs(x) for x in v.values())
            return all(refs(x) for x in v) if type(v) is list else True
        # Pool entries are JSON literals; references occur in invocation values.
        if any('$ref' in v for v in data['objects'].values() if type(v) is dict):return False
        if qid==2704:return data['method'] in ('toBe','notToBe') and refs(data['value']) and refs(data['other'])
        return type(data['inputs']) is list and 1<=len(data['inputs'])<=100000 and all(type(r) is list and refs(r) for r in data['inputs']) and sum(map(len,data['inputs']))<=100000 and valid_fn(data['fn'])
    if qid in (2666,2693):
        name='calls' if qid==2666 else 'args'
        if set(data)!={'fn',name} or not valid_fn(data['fn']) or type(data[name]) is not list:return False
        if qid==2693:return 1<=len(data['args'])<=100 and type(data['args'][0]) in (dict,list) and len(json.dumps(data['args'][0],separators=(',',':')))<=100000
        return 1<=len(data['calls'])<=10 and all(type(r) is list and 1<=len(r)<=100 for r in data['calls']) and len(json.dumps(data['calls'],ensure_ascii=False,separators=(',',':')).encode('utf-16-le'))//2<=1000
    if set(data)!={'classes','object','class'} or type(data['classes']) is not dict:return False
    builtins={'Date','Number','String','Boolean','Object','Array','Function','undefined','null'}
    classes=data['classes']
    if len(classes)>50 or any(not re.fullmatch('[A-Za-z_]\\w*',k) or k in builtins or (v is not None and v not in classes and v not in builtins-{'undefined','null'}) for k,v in classes.items()):return False
    for k in classes:
        seen=set()
        while k in classes:
            if k in seen:return False
            seen.add(k);k=classes[k]
    obj=data['object']
    return (data['class'] in builtins|set(classes) and type(obj) is dict and len(obj)==1 and
            (set(obj)=={'primitive'} and type(obj['primitive']) in (int,float,bool,str,type(None)) or
             set(obj)=={'undefined'} and obj['undefined'] is True or
             set(obj) in ({'instance'},{'class'}) and next(iter(obj.values())) in (builtins-{'null','undefined'})|set(classes)))


def note(qid):
    if qid not in QIDS:return ''
    return ('Reviewed JavaScript callback protocol '+VERSION+'. Native interfaces are unchanged. '
        'Callbacks are declarative objects {kind:"expression",expr:EXPR}, {kind:"merge_objects"}, or {kind:"tax_message"}. '
        'EXPR is {literal:JSON_SCALAR}, {arg:INDEX_0_TO_3}, {context:PROPERTY}, or {op:OP,args:[EXPR,...]}. '
        'Binary OP: add/subtract/multiply/modulo/power/get/gt/lt/ge/le/strict_equal/strict_not_equal; unary OP: negate/string. '
        'No executable callback strings. Only this finite callback family is verified, not arbitrary JavaScript functions. '
        'For memoize/expect, objects maps IDs to JSON object/array values; {$ref:"ID"} in invocation arguments preserves identity across calls. '
        'Literal object occurrences have distinct identity even when their JSON contents are equal. '
        'For once, serialize every non-undefined return or actual callback invocation as {calls:TOTAL_CALLBACK_CALLS,value:RETURN}; '
        'an invoked callback returning undefined uses value:{$undefined:true}. Subsequent undefined returns without invoking fn add no record. '
        'For callPolyfill, args[0] is this; remaining args are actual positional parameters. '
        'For expect, call the actual toBe/notToBe method and serialize {value:RESULT} or {error:MESSAGE}; never perform the comparison in the adapter. '
        'For instanceof, classes maps names to parent names/null; object is {instance:CLASS}, {class:CLASS}, {primitive:SCALAR}, or {undefined:true}; class is a class name, null or undefined string.')
