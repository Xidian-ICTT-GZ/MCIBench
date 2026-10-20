"""Parse public JSON-like literals without executing statement code."""
import ast
import io
import json
import tokenize
from local.lab import source_guard
source_guard.register(__file__)


def _fallback(text):
    text=text.strip().replace('\u00a0',' ')
    if not text or text[0] not in "[{'\"":raise ValueError('a public literal is required')
    # Locate a single balanced literal, respecting both quote styles. No
    # attribute, call, arithmetic or function expressions are admitted.
    stack=[];quote=None;escape=False;end=None
    for i,char in enumerate(text):
        if quote:
            if escape:escape=False
            elif char=='\\':escape=True
            elif char==quote:
                quote=None
                if not stack:end=i+1;break
        elif char in "'\"":quote=char
        elif char in '[{':stack.append(char)
        elif char in ']}':
            if not stack or stack.pop()!=('[' if char==']' else '{'):raise ValueError('unbalanced public literal')
            if not stack:end=i+1;break
    if end is None:raise ValueError('incomplete public literal')
    tokens=list(tokenize.generate_tokens(io.StringIO(text[:end]).readline));rewritten=[]
    significant=[t for t in tokens if t.type not in (tokenize.NL,tokenize.NEWLINE,tokenize.INDENT,tokenize.DEDENT,tokenize.ENDMARKER)]
    for i,t in enumerate(significant):
        value=t.string
        if t.type==tokenize.NAME:
            if i+1<len(significant) and significant[i+1].string==':':value=repr(value)
            elif value in ('null','true','false'):value={'null':'None','true':'True','false':'False'}[value]
            elif value not in ('None','True','False'):raise ValueError('executable names are not public literals')
        rewritten.append(value)
    value=ast.literal_eval(' '.join(rewritten))
    def validate(v):
        if type(v) is dict:
            if any(type(k) is not str for k in v):raise ValueError('string object keys required')
            for child in v.values():validate(child)
        elif type(v) is list:
            for child in v:validate(child)
        elif type(v) not in (str,int,float,bool,type(None)):raise ValueError('JSON-compatible literals only')
    validate(value)
    # literal_eval accepts duplicate dict keys; detect them on the AST as well.
    tree=ast.parse(' '.join(rewritten),mode='eval')
    for node in ast.walk(tree):
        if isinstance(node,ast.Dict):
            keys=[ast.literal_eval(k) for k in node.keys]
            if len(keys)!=len(set(keys)):raise ValueError('duplicate public object key')
    return value,end


def decode(text):
    text=text.strip().replace('\u00a0',' ')
    def object_(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('duplicate public object key')
            result[key]=value
        return result
    try:return json.JSONDecoder(object_pairs_hook=object_).raw_decode(text)
    except json.JSONDecodeError:pass
    try:return _fallback(text)
    except (ValueError,SyntaxError,TypeError,tokenize.TokenError,IndentationError) as error:
        raise json.JSONDecodeError(str(error),text,0) from error
