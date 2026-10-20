"""Repository-authored serializers for standard Python node/mutation interfaces.

Only structure construction, native invocation and serialization live here.
There are no problem-solving algorithms or expected answers in these bridges.
"""
import ast
import re
from local.common import load_snippet
from local.lab import source_guard
source_guard.register(__file__)

PREFIX='''from typing import *
from collections import deque
class ListNode:
    def __init__(self,val=0,next=None): self.val,self.next=val,next
class TreeNode:
    def __init__(self,val=0,left=None,right=None): self.val,self.left,self.right=val,left,right
def _mci_native_decode(t,value):
    if t.startswith('Optional['): return None if value is None else _mci_native_decode(t[9:-1],value)
    if t.startswith('List['): return [_mci_native_decode(t[5:-1],v) for v in value]
    if t=='ListNode':
        head=tail=ListNode()
        for v in value: tail.next=ListNode(v);tail=tail.next
        return head.next
    if t in ('TreeNode','NextNode'):
        node_type=Node if t=='NextNode' else TreeNode
        if not value: return None
        if value[0] is None:
            if any(v is not None for v in value): raise ValueError('orphan tree values')
            return None
        root=node_type(value[0]);parents=[root];i=1
        for parent in parents:
            for side in ('left','right'):
                if i>=len(value): break
                v=value[i];i+=1
                if v is not None:
                    child=node_type(v);setattr(parent,side,child);parents.append(child)
        if any(v is not None for v in value[i:]): raise ValueError('orphan tree values')
        return root
    return value
def _mci_native_encode(t,value):
    if t.startswith('Optional['):
        inner=t[9:-1]
        return None if value is None and inner not in ('TreeNode','ListNode') else _mci_native_encode(inner,value)
    if t.startswith('List['): return [_mci_native_encode(t[5:-1],v) for v in value]
    if t=='ListNode':
        result=[];seen=set()
        while value is not None:
            if id(value) in seen: raise ValueError('cyclic result list')
            seen.add(id(value));result.append(value.val);value=value.next
        return result
    if t=='TreeNode':
        if value is None: return []
        queue=deque([value]);result=[];seen=set()
        while queue:
            node=queue.popleft()
            if node is None: result.append(None);continue
            if id(node) in seen: raise ValueError('non-tree result')
            seen.add(id(node));result.append(node.val);queue.extend((node.left,node.right))
        while result and result[-1] is None: result.pop()
        return result
    return value
'''


def identity_bridge(qid):
    # These fields describe test construction, not native method parameters.
    # In particular, compare object identity, never just a returned node value.
    common='''
def _mci_nodes(values):
    nodes=[ListNode(v) for v in values]
    for left,right in zip(nodes,nodes[1:]): left.next=right
    return nodes
'''
    if qid in (116,117):
        common+='''
class Node:
    def __init__(self,val=0,left=None,right=None,next=None): self.val,self.left,self.right,self.next=val,left,right,next
def _mci_next_signature(root):
    if root is None: return []
    level=[root];signature=[];seen=set()
    while level:
        node=level[0]
        for expected in level:
            if node is not expected or id(node) in seen: raise ValueError('invalid next-node identity or cycle')
            seen.add(id(node));signature.append(node.val);node=node.next
        if node is not None: raise ValueError('next pointer does not terminate at level boundary')
        signature.append('#');level=[child for parent in level for child in (parent.left,parent.right) if child is not None]
    return signature
'''
        suffix='''def mci_adapter_solve(data):
    root=_mci_native_decode('NextNode',data['root'])
    return _mci_next_signature(Solution().connect(root))
'''
    elif qid==142:
        suffix='''def mci_adapter_solve(data):
    nodes=_mci_nodes(data['head']);pos=data['pos']
    if pos!=-1:
        if not 0<=pos<len(nodes): raise ValueError('invalid cycle index')
        nodes[-1].next=nodes[pos]
    result=Solution().detectCycle(nodes[0] if nodes else None)
    if result is None: return {'node_index':None}
    for i,node in enumerate(nodes):
        if result is node: return {'node_index':i}
    raise ValueError('returned node does not belong to the input list')
'''
    elif qid==160:
        suffix='''def mci_adapter_solve(data):
    a=_mci_nodes(data['listA']);b=_mci_nodes(data['listB']);sa=data['skipA'];sb=data['skipB']
    if data['intersectVal']:
        if not 0<=sa<len(a) or not 0<=sb<len(b) or data['listA'][sa:]!=data['listB'][sb:]: raise ValueError('inconsistent shared tail')
        b=b[:sb]+a[sa:]
        if sb: b[sb-1].next=a[sa]
    result=Solution().getIntersectionNode(a[0] if a else None,b[0] if b else None)
    if result is None: return None
    ia=next((i for i,node in enumerate(a) if node is result),None)
    ib=next((i for i,node in enumerate(b) if node is result),None)
    if ia is None and ib is None: raise ValueError('returned node does not belong to either input list')
    return {'a_index':ia,'b_index':ib}
'''
    elif qid==843:
        common+='''
class Master:
    def __init__(self,secret,words,budget):
        self._secret=secret;self._words=set(words);self._budget=budget;self._calls=0;self._found=False
    def guess(self,word):
        self._calls+=1
        if self._calls>self._budget: raise RuntimeError('Master.guess call budget exceeded')
        if word not in self._words: return -1
        matches=sum(a==b for a,b in zip(word,self._secret))
        if matches==6: self._found=True
        return matches
'''
        suffix='''def mci_adapter_solve(data):
    master=Master(data['secret'],data['words'],data['allowedGuesses'])
    Solution().findSecretWord(list(data['words']),master)
    return {'guessed':master._found and master._calls<=master._budget}
'''
    else:return None
    return {'prefix':PREFIX+common,'suffix':suffix}


def bridge(qid,descriptor):
    special=identity_bridge(qid)
    if special:return special
    try:
        snippet=load_snippet(qid,'python3')
        tree=ast.parse(snippet.rstrip()+'\n        pass\n')
        cls=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='Solution')
        method=next(node for node in cls.body if isinstance(node,ast.FunctionDef))
        params=[p for p in method.args.args if p.arg!='self']
        names=[p.arg for p in params]
        if any(set(c['args'])!=set(names) for c in descriptor['official']):return None
        types=[ast.unparse(p.annotation).replace(' ','') for p in params]
        ret=ast.unparse(method.returns).replace(' ','') if method.returns else 'None'
        for text in types+[ret]:
            tokens=re.findall(r'\w+',text)
            if any(token not in ('List','Optional','int','str','bool','float','None','TreeNode','ListNode') for token in tokens):return None
        if ret=='None':return None  # Void output needs an explicit mutation contract.
        lines=['def mci_adapter_solve(data):']
        for i,(name,type_) in enumerate(zip(names,types)):
            lines.append(f'    _arg{i}=_mci_native_decode({type_!r},data[{name!r}])')
        lines.append(f'    _result={cls.name}().{method.name}('+','.join(f'_arg{i}' for i in range(len(params)))+')')
        expected=descriptor['official'][0]['expected']
        if type(expected) is dict and set(expected)=={'return','mutated'}:
            pairs=[]
            for name in expected['mutated']:
                i=names.index(name)
                pairs.append(repr(name)+f':_mci_native_encode({types[i]!r},_arg{i})[:_result]')
            lines.append("    return {'return':_result,'mutated':{"+','.join(pairs)+'}}')
        else:lines.append(f'    return _mci_native_encode({ret!r},_result)')
        return {'prefix':PREFIX,'suffix':'\n'.join(lines)+'\n'}
    except (OSError,ValueError,TypeError,SyntaxError,StopIteration):return None
