"""Deterministic structural adapters, generated from the Python signature.

Tree, linked-list and design interfaces need a per-language bridge: build the nodes
from the JSON payload, invoke the native entry, serialise the result back. The
existing code only has such bridges for Python (repository-authored) and
JavaScript (reviewed), so every other language had to ask a model for one -- which
is why structural cells could not be gated without a profile.

This module emits the same bridge deterministically for a language, reusing the
Python snippet's signature (the prototype declares the contract once). It returns
None for any shape it does not know, so an unknown case falls back to the previous
behaviour instead of silently producing a wrong adapter.
"""
from __future__ import annotations

import ast

from local.common import load_snippet

VERSION = 'native-structural-v1'
SUPPORTED_SCALARS = {'int': 'int', 'float': 'double', 'bool': 'bool', 'str': 'string'}


def python_signature(qid):
    """(method name, [(param, annotation)], return annotation) from the snippet."""
    snippet = load_snippet(qid, 'python3')
    tree = ast.parse(snippet.rstrip() + '\n        pass\n')
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Solution')
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and not node.name.startswith('_'))
    params = [(p.arg, ast.unparse(p.annotation).replace(' ', '') if p.annotation else None)
              for p in method.args.args if p.arg != 'self']
    returns = ast.unparse(method.returns).replace(' ', '') if method.returns else None
    return method.name, params, returns


def _split_optional(type_name):
    if type_name and type_name.startswith('Optional[') and type_name.endswith(']'):
        return type_name[len('Optional['):-1], True
    return type_name, False


CPP_PREFIX = '''struct ListNode{int val;ListNode*next;ListNode(int v=0):val(v),next(nullptr){}};
struct TreeNode{int val;TreeNode*left;TreeNode*right;TreeNode(int v=0):val(v),left(nullptr),right(nullptr){}};
ListNode* mci_decode_list(const Mci& v){
    if(v.is_null())return nullptr;
    const Mci::Arr& a=v.array();ListNode*head=nullptr;ListNode*tail=nullptr;
    for(const Mci& item:a){ListNode*n=new ListNode((int)item.integer());if(!head)head=tail=n;else{tail->next=n;tail=n;}}
    return head;
}
Mci mci_encode_list(ListNode* head){
    Mci::Arr out;int guard=0;
    while(head){out.push_back(Mci((long long)head->val));head=head->next;if(++guard>100000)throw std::runtime_error("list cycle");}
    return Mci(out);
}
TreeNode* mci_decode_tree(const Mci& v){
    if(v.is_null())return nullptr;
    const Mci::Arr& a=v.array();if(a.empty())return nullptr;
    TreeNode* root=new TreeNode((int)a[0].integer());
    std::vector<TreeNode*> queue{root};size_t index=1;
    for(size_t qi=0;qi<queue.size()&&index<a.size();qi++){
        TreeNode* node=queue[qi];
        if(index<a.size()){const Mci& left=a[index++];if(!left.is_null()){node->left=new TreeNode((int)left.integer());queue.push_back(node->left);}}
        if(index<a.size()){const Mci& right=a[index++];if(!right.is_null()){node->right=new TreeNode((int)right.integer());queue.push_back(node->right);}}
    }
    return root;
}
Mci mci_encode_tree(TreeNode* root){
    Mci::Arr out;if(!root)return Mci(out);
    std::deque<TreeNode*> queue{root};
    while(!queue.empty()){
        TreeNode* node=queue.front();queue.pop_front();
        if(!node){out.push_back(Mci(nullptr));continue;}
        out.push_back(Mci((long long)node->val));
        queue.push_back(node->left);queue.push_back(node->right);
    }
    while(!out.empty()&&out.back().is_null())out.pop_back();
    return Mci(out);
}
'''


def _cpp_type(type_name):
    base, _optional = _split_optional(type_name)
    if base in ('ListNode', 'TreeNode'):
        return '%s*' % base
    if base in SUPPORTED_SCALARS:
        return SUPPORTED_SCALARS[base]
    if base.startswith('List[') and base.endswith(']'):
        inner, _ = _split_optional(base[5:-1])
        # Python List[str] is often vector<char> natively (compress(chars) is the
        # canonical case). The annotation alone cannot tell string from char, so this
        # shape is refused rather than guessed: a wrong adapter is worse than none.
        if inner in SUPPORTED_SCALARS and inner != 'str':
            return 'vector<%s>' % SUPPORTED_SCALARS[inner]
    return None


def _cpp_decode(type_name, expr):
    base, _optional = _split_optional(type_name)
    if base == 'ListNode':
        return 'mci_decode_list(%s)' % expr
    if base == 'TreeNode':
        return 'mci_decode_tree(%s)' % expr
    if base in ('int', 'float', 'bool', 'str'):
        accessor = {'int': 'integer()', 'float': 'number()', 'bool': 'boolean()', 'str': 'text()'}[base]
        return '(%s)%s.%s' % (SUPPORTED_SCALARS[base], expr, accessor)
    if base.startswith('List[') and base.endswith(']'):
        inner, _ = _split_optional(base[5:-1])
        if inner in SUPPORTED_SCALARS:
            accessor = {'int': 'integer()', 'float': 'number()', 'bool': 'boolean()', 'str': 'text()'}[inner]
            return ('[&]{vector<%s> v;for(const Mci& i:(%s).array())v.push_back((%s)i.%s);return v;}()'
                    % (SUPPORTED_SCALARS[inner], expr, SUPPORTED_SCALARS[inner], accessor))
    return None


def _cpp_encode(type_name, expr):
    base, _optional = _split_optional(type_name)
    if base == 'ListNode':
        return 'mci_encode_list(%s)' % expr
    if base == 'TreeNode':
        return 'mci_encode_tree(%s)' % expr
    if base in ('int', 'float', 'bool', 'str'):
        return 'Mci((%s)%s)' % ({'int': 'long long', 'float': 'double', 'bool': 'bool', 'str': 'string'}[base], expr)
    if base.startswith('List[') and base.endswith(']'):
        inner, _ = _split_optional(base[5:-1])
        if inner in SUPPORTED_SCALARS:
            return ('[&]{Mci::Arr v;for(const auto& i:(%s))v.push_back(Mci((%s)i));return Mci(v);}()'
                    % (expr, {'int': 'long long', 'float': 'double', 'bool': 'bool', 'str': 'string'}[inner]))
    return None


def cpp_bridge(qid, descriptor):
    """Return {'prefix','suffix'} for a shape this module understands, else None."""
    try:
        name, params, returns = python_signature(qid)
    except (OSError, ValueError, KeyError, StopIteration, SyntaxError):
        return None
    if not returns:
        return None
    expects = [case.get('args') for case in (descriptor.get('official') or [])]
    names = [param for param, _ in params]
    if any(not isinstance(args, dict) or set(args) != set(names) for args in expects):
        return None
    declarations = []
    for param, type_name in params:
        mapped = _cpp_type(type_name)
        decoded = _cpp_decode(type_name, 'data["%s"]' % param)
        if mapped is None or decoded is None:
            return None
        declarations.append((param, mapped, decoded))
    returned = _cpp_type(returns)
    encoded = _cpp_encode(returns, '_result')
    if returned is None or encoded is None:
        return None
    call = 'Solution().%s(%s)' % (name, ','.join('_arg%d' % index for index in range(len(declarations))))
    lines = ['Mci mci_adapter_solve(Mci data){']
    for index, (param, mapped, decoded) in enumerate(declarations):
        lines.append('    %s _arg%d=%s;' % (mapped, index, decoded))
    lines.append('    %s _result=%s;' % (returned, call))
    lines.append('    return %s;' % encoded)
    lines.append('}')
    return {'prefix': CPP_PREFIX, 'suffix': '\n'.join(lines) + '\n'}


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def prepare_reference_only(qid, language, descriptor, package, image, *, bridges=None):
    """Admit a structural problem through a deterministic bridge, without a model.

    Mutation coverage is deliberately absent: the environment has no profile, so no
    mutant can be generated. The gate that does run proves the bridge builds the
    nodes, invokes the declared native entry and serialises the result, because the
    reference must reproduce the expected outputs through it. The plan records that
    limitation instead of claiming a full gate.
    """
    from local.lab import portable_judging as judging

    builder = {'cpp': cpp_bridge, 'java': java_bridge, 'csharp': csharp_bridge,
               'javascript': javascript_bridge, 'golang': golang_bridge,
               'c': c_bridge, 'python3': _python_bridge_available}.get(language)
    if builder is None:
        return None
    bridge = builder(qid, descriptor)
    if not bridge:
        return None
    try:
        reference = (bridges or {}).get(language) or _load_reference(qid, language)
    except (OSError, ValueError, KeyError):
        return None
    combined = bridge['prefix'] + '\n' + reference + '\n' + bridge['suffix']
    verdict = judging.execute(qid, language, combined, package['cases'],
                              descriptor.get('comparison') or {'mode': 'ordered'},
                              native_bridge=True)
    meta = verdict.get('_meta') or {}
    passed = (verdict.get('ac_status') == 'Accepted'
              and verdict.get('total_correct') == verdict.get('total_testcases')
              and not meta.get('dropped_unrepresentable'))
    from local.lab.behavior import sha
    return {
        'kind': 'bridge',
        'qid': qid,
        'language': language,
        'prefix': bridge['prefix'],
        'suffix': bridge['suffix'],
        'adapter_sha256': sha(bridge['prefix'] + bridge['suffix']),
        'reference_code': reference,
        'reference_sha256': sha(reference),
        'reference_origin': 'repository_reference',
        'reference_gate': {'ac_status': verdict.get('ac_status'),
                           'correct': verdict.get('total_correct'),
                           'total': verdict.get('total_testcases'),
                           'dropped_unrepresentable': meta.get('dropped_unrepresentable'),
                           'error': (meta.get('error') or '')[:300]},
        'passed': passed,
        'admission': 'reference_only',
        'mutation_coverage': 'absent',
        'gates_run': ['reference_through_bridge'],
        'limitations': ['no_mutation_gate: adapter invocation is proven on the reference only',
                        'generated_by: native-structural-v1'],
        'binding': {'qid': qid, 'language': language,
                    'cases_sha256': sha(package['cases']),
                    'image': image},
    }


def _load_reference(qid, language):
    from local.common import load_reference
    return load_reference(qid, language)


def _python_bridge_available(qid, descriptor):
    from local.lab import native_python
    return native_python.bridge(qid, descriptor)

JAVA_PREFIX = '''class ListNode{int val;ListNode next;ListNode(){}ListNode(int v){val=v;}ListNode(int v,ListNode n){val=v;next=n;}}
class TreeNode{int val;TreeNode left;TreeNode right;TreeNode(){}TreeNode(int v){val=v;}TreeNode(int v,TreeNode l,TreeNode r){val=v;left=l;right=r;}}
class MciCodec{
    static ListNode list(Object v){
        if(v==null)return null;List<Object> a=Mci.arr(v);ListNode head=null,tail=null;
        for(Object o:a){ListNode n=new ListNode((int)Mci.num(o));if(head==null){head=tail=n;}else{tail.next=n;tail=n;}}
        return head;
    }
    static Object list(ListNode head){
        List<Object> out=new ArrayList<Object>();int guard=0;
        while(head!=null){out.add(Long.valueOf(head.val));head=head.next;if(++guard>100000)throw new RuntimeException("list cycle");}
        return out;
    }
    static TreeNode tree(Object v){
        if(v==null)return null;List<Object> a=Mci.arr(v);if(a.isEmpty())return null;
        TreeNode root=new TreeNode((int)Mci.num(a.get(0)));
        List<TreeNode> queue=new ArrayList<TreeNode>();queue.add(root);int index=1;
        for(int qi=0;qi<queue.size()&&index<a.size();qi++){
            TreeNode node=queue.get(qi);
            if(index<a.size()){Object left=a.get(index++);if(left!=null&&!left.equals(null)){node.left=new TreeNode((int)Mci.num(left));queue.add(node.left);}}
            if(index<a.size()){Object right=a.get(index++);if(right!=null&&!right.equals(null)){node.right=new TreeNode((int)Mci.num(right));queue.add(node.right);}}
        }
        return root;
    }
    static Object tree(TreeNode root){
        List<Object> out=new ArrayList<Object>();if(root==null)return out;
        List<TreeNode> queue=new ArrayList<TreeNode>();queue.add(root);int qi=0;
        while(qi<queue.size()){
            TreeNode node=queue.get(qi++);
            if(node==null){out.add(null);continue;}
            out.add(Long.valueOf(node.val));queue.add(node.left);queue.add(node.right);
        }
        while(!out.isEmpty()&&out.get(out.size()-1)==null)out.remove(out.size()-1);
        return out;
    }
    static List<Integer> ints(Object v){
        List<Integer> out=new ArrayList<Integer>();
        for(Object o:Mci.arr(v))out.add(Integer.valueOf((int)Mci.num(o)));
        return out;
    }
    static Object encodeInts(List<Integer> values){
        List<Object> out=new ArrayList<Object>();
        for(Integer i:values)out.add(Long.valueOf(i.longValue()));
        return out;
    }
}
'''

JAVA_SCALARS = {'int': ('int', '(int)Mci.num(%s)', 'Long.valueOf(_result)'),
                'float': ('double', '(double)Mci.real(%s)', 'Double.valueOf(_result)'),
                'bool': ('boolean', '((Boolean)%s).booleanValue()', 'Boolean.valueOf(_result)'),
                'str': ('String', '((String)%s)', 'String.valueOf(_result)')}
JAVA_BOXED = {'int': 'Integer', 'float': 'Double', 'bool': 'Boolean', 'str': 'String'}


def _java_type(type_name):
    base, _optional = _split_optional(type_name)
    if base in ('ListNode', 'TreeNode'):
        return base
    if base in JAVA_SCALARS:
        return JAVA_SCALARS[base][0]
    if base.startswith('List[') and base.endswith(']'):
        inner, _ = _split_optional(base[5:-1])
        if inner in JAVA_BOXED and inner != 'str':
            return 'List<%s>' % JAVA_BOXED[inner]
    return None


def _java_decode(type_name, expr):
    base, _optional = _split_optional(type_name)
    if base == 'ListNode':
        return 'MciCodec.list(%s)' % expr
    if base == 'TreeNode':
        return 'MciCodec.tree(%s)' % expr
    if base in JAVA_SCALARS:
        return JAVA_SCALARS[base][1] % expr
    if base.startswith('List[') and base.endswith(']'):
        inner, _ = _split_optional(base[5:-1])
        if inner == 'int':
            return 'MciCodec.ints(%s)' % expr
    return None


def _java_encode(type_name, expr):
    base, _optional = _split_optional(type_name)
    if base == 'ListNode':
        return 'MciCodec.list(%s)' % expr
    if base == 'TreeNode':
        return 'MciCodec.tree(%s)' % expr
    if base in JAVA_SCALARS:
        return 'return %s;' % JAVA_SCALARS[base][2]
    if base.startswith('List[') and base.endswith(']'):
        inner, _ = _split_optional(base[5:-1])
        if inner == 'int':
            return 'MciCodec.encodeInts(%s)' % expr
    return None


def java_bridge(qid, descriptor):
    """Return {'prefix','suffix'} for java, mirroring the documented contract."""
    try:
        name, params, returns = python_signature(qid)
    except (OSError, ValueError, KeyError, StopIteration, SyntaxError):
        return None
    if not returns:
        return None
    names = [param for param, _ in params]
    for case in descriptor.get('official') or []:
        args = case.get('args')
        if not isinstance(args, dict) or set(args) != set(names):
            return None
    declarations = []
    for param, type_name in params:
        mapped = _java_type(type_name)
        decoded = _java_decode(type_name, 'data.get("%s")' % param)
        if mapped is None or decoded is None:
            return None
        declarations.append((param, mapped, decoded))
    returned = _java_type(returns)
    encoded = _java_encode(returns, '_result')
    if returned is None or encoded is None:
        return None
    call = 'new Solution().%s(%s)' % (name, ','.join('_arg%d' % i for i in range(len(declarations))))
    lines = ['class MciAdapter{', '    public Object solve(Map<String,Object> data){']
    for index, (param, mapped, decoded) in enumerate(declarations):
        lines.append('        %s _arg%d=%s;' % (mapped, index, decoded))
    lines.append('        %s _result=%s;' % (returned, call))
    lines.append('        return %s;' % encoded)
    lines.append('    }')
    lines.append('}')
    return {'prefix': JAVA_PREFIX, 'suffix': '\n'.join(lines) + '\n'}

JS_PREFIX = '''function ListNode(val,next){this.val=(val===undefined?0:val);this.next=(next===undefined?null:next);}
function TreeNode(val,left,right){this.val=(val===undefined?0:val);this.left=(left===undefined?null:left);this.right=(right===undefined?null:right);}
function mci_decode_list(a){if(a===null||a===undefined)return null;var head=null,tail=null;for(var i=0;i<a.length;i++){var n=new ListNode(a[i]);if(!head){head=tail=n;}else{tail.next=n;tail=n;}}return head;}
function mci_encode_list(head){var out=[],guard=0;while(head){out.push(head.val);head=head.next;if(++guard>100000)throw new Error('list cycle');}return out;}
function mci_decode_tree(a){if(a===null||a===undefined||a.length===0)return null;var root=new TreeNode(a[0]);var queue=[root],index=1;for(var qi=0;qi<queue.length&&index<a.length;qi++){var node=queue[qi];if(index<a.length){var lv=a[index++];if(lv!==null){node.left=new TreeNode(lv);queue.push(node.left);}}if(index<a.length){var rv=a[index++];if(rv!==null){node.right=new TreeNode(rv);queue.push(node.right);}}}return root;}
function mci_encode_tree(root){var out=[];if(!root)return out;var queue=[root],qi=0;while(qi<queue.length){var node=queue[qi++];if(!node){out.push(null);continue;}out.push(node.val);queue.push(node.left);queue.push(node.right);}while(out.length&&out[out.length-1]===null)out.pop();return out;}
'''


def _js_decode(type_name, expr):
    base, _optional = _split_optional(type_name)
    if base == 'ListNode':
        return 'mci_decode_list(%s)' % expr
    if base == 'TreeNode':
        return 'mci_decode_tree(%s)' % expr
    # Scalars and arrays of scalars travel unchanged in JavaScript.
    if base in ('int', 'float', 'bool', 'str'):
        return expr
    if base.startswith('List[') and base.endswith(']'):
        inner, _ = _split_optional(base[5:-1])
        if inner in ('int', 'float', 'bool', 'str'):
            return expr
    return None


def _js_encode(type_name, expr):
    base, _optional = _split_optional(type_name)
    if base == 'ListNode':
        return 'mci_encode_list(%s)' % expr
    if base == 'TreeNode':
        return 'mci_encode_tree(%s)' % expr
    if base in ('int', 'float', 'bool', 'str'):
        return expr
    if base.startswith('List[') and base.endswith(']'):
        inner, _ = _split_optional(base[5:-1])
        if inner in ('int', 'float', 'bool', 'str'):
            return expr
    return None


def javascript_bridge(qid, descriptor):
    """JavaScript references are usually a var function, not a Solution class."""
    try:
        name, params, returns = python_signature(qid)
    except (OSError, ValueError, KeyError, StopIteration, SyntaxError):
        return None
    if not returns:
        return None
    names = [param for param, _ in params]
    for case in descriptor.get('official') or []:
        args = case.get('args')
        if not isinstance(args, dict) or set(args) != set(names):
            return None
    declarations = []
    for param, type_name in params:
        decoded = _js_decode(type_name, "data['%s']" % param)
        if decoded is None:
            return None
        declarations.append((param, decoded))
    encoded = _js_encode(returns, '_result')
    if encoded is None:
        return None
    call_args = ','.join('_arg%d' % i for i in range(len(declarations)))
    lines = ['function mci_adapter_solve(data){']
    for index, (param, decoded) in enumerate(declarations):
        lines.append('    var _arg%d=%s;' % (index, decoded))
    # Support both shapes: a Solution class or a var function.
    lines.append("    var _holder=(typeof Solution!=='undefined'&&Solution)?new Solution():null;")
    lines.append('    var _result=_holder?_holder.%s(%s):%s(%s);' % (name, call_args, name, call_args))
    lines.append('    return %s;' % encoded)
    lines.append('}')
    return {'prefix': JS_PREFIX, 'suffix': '\n'.join(lines) + '\n'}


CS_PREFIX = '''public class ListNode{public int val;public ListNode next;public ListNode(int v=0,ListNode n=null){val=v;next=n;}}
public class TreeNode{public int val;public TreeNode left;public TreeNode right;public TreeNode(int v=0,TreeNode l=null,TreeNode r=null){val=v;left=l;right=r;}}
class MciCodec{
    public static ListNode DecodeList(System.Text.Json.JsonElement e){
        if(e.ValueKind==System.Text.Json.JsonValueKind.Null)return null;
        ListNode head=null,tail=null;
        foreach(var item in e.EnumerateArray()){var n=new ListNode((int)item.GetInt64());if(head==null){head=tail=n;}else{tail.next=n;tail=n;}}
        return head;
    }
    public static object EncodeList(ListNode head){
        var outList=new System.Collections.Generic.List<object>();int guard=0;
        while(head!=null){outList.Add((long)head.val);head=head.next;if(++guard>100000)throw new System.Exception("list cycle");}
        return outList;
    }
    public static TreeNode DecodeTree(System.Text.Json.JsonElement e){
        if(e.ValueKind==System.Text.Json.JsonValueKind.Null)return null;
        var arr=new System.Collections.Generic.List<System.Text.Json.JsonElement>();
        foreach(var item in e.EnumerateArray())arr.Add(item);
        if(arr.Count==0)return null;
        var root=new TreeNode((int)arr[0].GetInt64());
        var queue=new System.Collections.Generic.List<TreeNode>();queue.Add(root);int index=1;
        for(int qi=0;qi<queue.Count&&index<arr.Count;qi++){
            var node=queue[qi];
            if(index<arr.Count){var left=arr[index++];if(left.ValueKind!=System.Text.Json.JsonValueKind.Null){node.left=new TreeNode((int)left.GetInt64());queue.Add(node.left);}}
            if(index<arr.Count){var right=arr[index++];if(right.ValueKind!=System.Text.Json.JsonValueKind.Null){node.right=new TreeNode((int)right.GetInt64());queue.Add(node.right);}}
        }
        return root;
    }
    public static object EncodeTree(TreeNode root){
        var outList=new System.Collections.Generic.List<object>();if(root==null)return outList;
        var queue=new System.Collections.Generic.List<TreeNode>();queue.Add(root);int qi=0;
        while(qi<queue.Count){
            var node=queue[qi++];
            if(node==null){outList.Add(null);continue;}
            outList.Add((long)node.val);queue.Add(node.left);queue.Add(node.right);
        }
        while(outList.Count>0&&outList[outList.Count-1]==null)outList.RemoveAt(outList.Count-1);
        return outList;
    }
    public static System.Collections.Generic.List<int> Ints(System.Text.Json.JsonElement e){
        var outList=new System.Collections.Generic.List<int>();
        foreach(var item in e.EnumerateArray())outList.Add((int)item.GetInt64());
        return outList;
    }
    public static object EncodeInts(System.Collections.Generic.List<int> values){
        var outList=new System.Collections.Generic.List<object>();
        foreach(var v in values)outList.Add((long)v);
        return outList;
    }
}
'''

CS_ACCESSOR = {'int': ('int', '(int)%s.GetInt64()'), 'float': ('double', '%s.GetDouble()'),
               'bool': ('bool', '%s.GetBoolean()'), 'str': ('string', '%s.GetString()')}


def _cs_type(type_name):
    base, _optional = _split_optional(type_name)
    if base in ('ListNode', 'TreeNode'):
        return base
    if base in CS_ACCESSOR:
        return CS_ACCESSOR[base][0]
    if base.startswith('List[') and base.endswith(']'):
        inner, _ = _split_optional(base[5:-1])
        if inner == 'int':
            return 'System.Collections.Generic.List<int>'
    return None


def _cs_decode(type_name, expr):
    base, _optional = _split_optional(type_name)
    if base == 'ListNode':
        return 'MciCodec.DecodeList(%s)' % expr
    if base == 'TreeNode':
        return 'MciCodec.DecodeTree(%s)' % expr
    if base in CS_ACCESSOR:
        return CS_ACCESSOR[base][1] % expr
    if base.startswith('List[') and base.endswith(']'):
        inner, _ = _split_optional(base[5:-1])
        if inner == 'int':
            return 'MciCodec.Ints(%s)' % expr
    return None


def _cs_encode(type_name, expr):
    base, _optional = _split_optional(type_name)
    if base == 'ListNode':
        return 'MciCodec.EncodeList(%s)' % expr
    if base == 'TreeNode':
        return 'MciCodec.EncodeTree(%s)' % expr
    if base in CS_ACCESSOR:
        return '(long)(%s)' % expr
    if base.startswith('List[') and base.endswith(']'):
        inner, _ = _split_optional(base[5:-1])
        if inner == 'int':
            return 'MciCodec.EncodeInts(%s)' % expr
    return None


def csharp_bridge(qid, descriptor):
    """C# uses a non-public MciAdapter because the reference is a public Solution."""
    try:
        name, params, returns = python_signature(qid)
    except (OSError, ValueError, KeyError, StopIteration, SyntaxError):
        return None
    if not returns:
        return None
    names = [param for param, _ in params]
    for case in descriptor.get('official') or []:
        args = case.get('args')
        if not isinstance(args, dict) or set(args) != set(names):
            return None
    declarations = []
    for param, type_name in params:
        mapped = _cs_type(type_name)
        decoded = _cs_decode(type_name, 'data.GetProperty("%s")' % param)
        if mapped is None or decoded is None:
            return None
        declarations.append((param, mapped, decoded))
    returned = _cs_type(returns)
    encoded = _cs_encode(returns, '_result')
    if returned is None or encoded is None:
        return None
    pascal = name[0].upper() + name[1:]
    call = 'new Solution().%s(%s)' % (pascal, ','.join('_arg%d' % i for i in range(len(declarations))))
    lines = ['class MciAdapter{', '    public object Solve(System.Text.Json.JsonElement data){']
    for index, (param, mapped, decoded) in enumerate(declarations):
        lines.append('        %s _arg%d=%s;' % (mapped, index, decoded))
    lines.append('        %s _result=%s;' % (returned, call))
    lines.append('        return %s;' % encoded)
    lines.append('    }')
    lines.append('}')
    return {'prefix': CS_PREFIX, 'suffix': '\n'.join(lines) + '\n'}

GO_PREFIX = '''type ListNode struct{ Val int; Next *ListNode }
type TreeNode struct{ Val int; Left *TreeNode; Right *TreeNode }
func mciDecodeList(v interface{}) *ListNode {
	if v == nil { return nil }
	arr := MciArr(v)
	var head, tail *ListNode
	for _, item := range arr {
		n := &ListNode{Val: int(MciInt(item))}
		if head == nil { head, tail = n, n } else { tail.Next = n; tail = n }
	}
	return head
}
func mciEncodeList(head *ListNode) interface{} {
	out := []interface{}{}
	guard := 0
	for head != nil {
		out = append(out, int64(head.Val))
		head = head.Next
		guard++
		if guard > 100000 { panic("list cycle") }
	}
	return out
}
func mciDecodeTree(v interface{}) *TreeNode {
	if v == nil { return nil }
	arr := MciArr(v)
	if len(arr) == 0 { return nil }
	root := &TreeNode{Val: int(MciInt(arr[0]))}
	queue := []*TreeNode{root}
	index := 1
	for qi := 0; qi < len(queue) && index < len(arr); qi++ {
		node := queue[qi]
		if index < len(arr) {
			if arr[index] != nil { node.Left = &TreeNode{Val: int(MciInt(arr[index]))}; queue = append(queue, node.Left) }
			index++
		}
		if index < len(arr) {
			if arr[index] != nil { node.Right = &TreeNode{Val: int(MciInt(arr[index]))}; queue = append(queue, node.Right) }
			index++
		}
	}
	return root
}
func mciEncodeTree(root *TreeNode) interface{} {
	out := []interface{}{}
	if root == nil { return out }
	queue := []*TreeNode{root}
	for qi := 0; qi < len(queue); qi++ {
		node := queue[qi]
		if node == nil { out = append(out, nil); continue }
		out = append(out, int64(node.Val))
		queue = append(queue, node.Left, node.Right)
	}
	for len(out) > 0 && out[len(out)-1] == nil { out = out[:len(out)-1] }
	return out
}
func mciInts(v interface{}) []int {
	out := []int{}
	for _, item := range MciArr(v) { out = append(out, int(MciInt(item))) }
	return out
}
func mciEncodeInts(values []int) interface{} {
	out := []interface{}{}
	for _, value := range values { out = append(out, int64(value)) }
	return out
}
'''

GO_SCALARS = {'int': 'int', 'float': 'float64', 'bool': 'bool', 'str': 'string'}


def _go_type(type_name):
    base, _optional = _split_optional(type_name)
    if base in ('ListNode', 'TreeNode'):
        return '*%s' % base
    if base in GO_SCALARS:
        return GO_SCALARS[base]
    if base.startswith('List[') and base.endswith(']'):
        inner, _ = _split_optional(base[5:-1])
        if inner == 'int':
            return '[]int'
    return None


def _go_decode(type_name, expr):
    base, _optional = _split_optional(type_name)
    if base == 'ListNode':
        return 'mciDecodeList(%s)' % expr
    if base == 'TreeNode':
        return 'mciDecodeTree(%s)' % expr
    if base == 'int':
        return 'int(MciInt(%s))' % expr
    if base == 'float':
        return '(%s).(float64)' % expr
    if base == 'bool':
        return '(%s).(bool)' % expr
    if base == 'str':
        return '(%s).(string)' % expr
    if base.startswith('List[') and base.endswith(']'):
        inner, _ = _split_optional(base[5:-1])
        if inner == 'int':
            return 'mciInts(%s)' % expr
    return None


def _go_encode(type_name, expr):
    base, _optional = _split_optional(type_name)
    if base == 'ListNode':
        return 'mciEncodeList(%s)' % expr
    if base == 'TreeNode':
        return 'mciEncodeTree(%s)' % expr
    if base == 'int':
        return 'int64(%s)' % expr
    if base in ('float', 'bool', 'str'):
        return expr
    if base.startswith('List[') and base.endswith(']'):
        inner, _ = _split_optional(base[5:-1])
        if inner == 'int':
            return 'mciEncodeInts(%s)' % expr
    return None


def golang_bridge(qid, descriptor):
    """Go references are package-level funcs, so the adapter calls them directly."""
    try:
        name, params, returns = python_signature(qid)
    except (OSError, ValueError, KeyError, StopIteration, SyntaxError):
        return None
    if not returns:
        return None
    names = [param for param, _ in params]
    for case in descriptor.get('official') or []:
        args = case.get('args')
        if not isinstance(args, dict) or set(args) != set(names):
            return None
    declarations = []
    for param, type_name in params:
        mapped = _go_type(type_name)
        decoded = _go_decode(type_name, 'data["%s"]' % param)
        if mapped is None or decoded is None:
            return None
        declarations.append((param, mapped, decoded))
    returned = _go_type(returns)
    encoded = _go_encode(returns, '_result')
    if returned is None or encoded is None:
        return None
    call = '%s(%s)' % (name, ', '.join('_arg%d' % i for i in range(len(declarations))))
    lines = ['func mci_adapter_solve(data map[string]interface{}) interface{} {']
    for index, (param, mapped, decoded) in enumerate(declarations):
        lines.append('\t_arg%d := %s' % (index, decoded))
    lines.append('\tvar _result %s = %s' % (returned, call))
    lines.append('\treturn %s' % encoded)
    lines.append('}')
    return {'prefix': GO_PREFIX, 'suffix': '\n'.join(lines) + '\n'}

C_PREFIX = '''struct ListNode{int val;struct ListNode*next;};
struct TreeNode{int val;struct TreeNode*left;struct TreeNode*right;};
static struct ListNode* mci_decode_list(Mci* v){
    /* A JSON null arrives with length 0; mci_truth only accepts booleans. */
    size_t n=mci_len(v);
    if(n==0)return NULL;
    struct ListNode*head=NULL;struct ListNode*tail=NULL;
    for(long long i=0;i<n;i++){struct ListNode*node=malloc(sizeof(struct ListNode));node->val=(int)mci_int(mci_at(v,i));node->next=NULL;if(!head){head=tail=node;}else{tail->next=node;tail=node;}}
    return head;
}
static Mci* mci_encode_list(struct ListNode* head){
    Mci* out=mci_array();long long guard=0;
    while(head){mci_push(out,mci_integer(head->val));head=head->next;if(++guard>100000){fprintf(stderr,"list cycle");abort();}}
    return out;
}
static struct TreeNode* mci_decode_tree(Mci* v){
    size_t n=mci_len(v);if(n==0)return NULL;
    struct TreeNode** queue=malloc(sizeof(struct TreeNode*)*(size_t)n);
    struct TreeNode* root=malloc(sizeof(struct TreeNode));root->val=(int)mci_int(mci_at(v,0));root->left=NULL;root->right=NULL;
    long long qn=1,index=1;queue[0]=root;
    for(long long qi=0;qi<qn&&index<n;qi++){
        struct TreeNode* node=queue[qi];
        /* The platform struct exposes type: 0 is JSON null. mci_truth only accepts
           booleans, so it cannot be used to test tree placeholders. */
        if(index<n){Mci* item=mci_at(v,index++);if(item->type!=0){struct TreeNode* child=malloc(sizeof(struct TreeNode));child->val=(int)mci_int(item);child->left=NULL;child->right=NULL;node->left=child;queue[qn++]=child;}}
        if(index<n){Mci* item=mci_at(v,index++);if(item->type!=0){struct TreeNode* child=malloc(sizeof(struct TreeNode));child->val=(int)mci_int(item);child->left=NULL;child->right=NULL;node->right=child;queue[qn++]=child;}}
    }
    free(queue);
    return root;
}
static Mci* mci_encode_ints(int* values, int size){
    Mci* out=mci_array();
    for(int i=0;i<size;i++)mci_push(out,mci_integer(values[i]));
    return out;
}
'''


def _c_param(type_name):
    base, _optional = _split_optional(type_name)
    if base == 'ListNode':
        return 'struct ListNode*', 'mci_decode_list(%s)'
    if base == 'TreeNode':
        return 'struct TreeNode*', 'mci_decode_tree(%s)'
    # Scalars and arrays are not serialised here yet: refuse rather than guess.
    return None, None


def _c_return(type_name, expr):
    """Return (kind, declaration, encode expression)."""
    base, _optional = _split_optional(type_name)
    if base == 'ListNode':
        return 'node', 'struct ListNode*', 'mci_encode_list(%s)' % expr
    if base == 'TreeNode':
        return None, None, None
    if base == 'int':
        return 'scalar', 'int', 'mci_integer(%s)' % expr
    if base.startswith('List[') and base.endswith(']'):
        inner, _ = _split_optional(base[5:-1])
        if inner == 'int':
            # LeetCode C convention: return the array and report the size by pointer.
            return 'int_list', 'int*', 'mci_encode_ints(%s, _retSize)' % expr
    return None, None, None


def c_bridge(qid, descriptor):
    """C references use out-parameters for arrays and never define the node structs."""
    try:
        name, params, returns = python_signature(qid)
    except (OSError, ValueError, KeyError, StopIteration, SyntaxError):
        return None
    if not returns:
        return None
    names = [param for param, _ in params]
    for case in descriptor.get('official') or []:
        args = case.get('args')
        if not isinstance(args, dict) or set(args) != set(names):
            return None
    declarations = []
    for param, type_name in params:
        mapped, decode = _c_param(type_name)
        if mapped is None:
            return None
        declarations.append((mapped, decode % ('mci_get(data,"%s")' % param)))
    kind, returned, encoded = _c_return(returns, '_result')
    if kind is None:
        return None
    call_args = ', '.join('_arg%d' % i for i in range(len(declarations)))
    lines = ['Mci* mci_adapter_solve(Mci* data){']
    for index, (mapped, decode) in enumerate(declarations):
        lines.append('    %s _arg%d=%s;' % (mapped, index, decode))
    if kind == 'int_list':
        lines.append('    int _retSize=0;')
        lines.append('    %s _result=%s(%s, &_retSize);' % (returned, name, call_args))
    else:
        lines.append('    %s _result=%s(%s);' % (returned, name, call_args))
    lines.append('    return %s;' % encoded)
    lines.append('}')
    prefix = C_PREFIX if 'TreeNode' in returns or any('TreeNode' in (t or '') for _, t in params) else C_PREFIX
    return {'prefix': prefix, 'suffix': '\n'.join(lines) + '\n'}
