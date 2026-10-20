"""Original solution interfaces, with deterministic or independently gated bridges."""
from copy import deepcopy
import ast
import json
from pathlib import Path
import re
import tempfile

from local.common import REPO_ROOT,KEY_TO_LABEL,load_snippet,load_reference
from local.harness import runner
from local.harness.typespec import parse_python_snippet,PlainSig
from local.harness.render import extract_plain_entry
from local.harness.output_drivers import render_output_driver
from local.harness.output_protocol import OutputCollector,OutputVerifier
from local.lab import portable_judging as portable,portable_drivers as drivers
from local.lab import problem_packages as packages,native_python,native_javascript,javascript_references
from local.lab.behavior import sha
from local.lab.generation import generate
from local.lab.testcase_workflow import save,lock
from local.lab import source_guard
source_guard.register(__file__)

VERSION='full-corpus-native-v1'
DATA_DIR=REPO_ROOT/'local/dashboard/packages/server/data/lab_native_adapters'
SENTINEL='MCIBENCH_NATIVE_ENTRY_USED'


def signature(qid):
    snippet=load_snippet(qid,'python3')
    snippet='\n'.join(line for line in snippet.splitlines() if not line.lstrip().startswith('#'))
    return parse_python_snippet(snippet)


def _cases(cases,sig):
    rows=deepcopy(cases)
    if not isinstance(sig,PlainSig):
        for row in rows:
            row.update(ops=row['args']['ops'],args=row['args']['args'])
    return rows


def _raw(qid,language,code,cases,comparison,*,collect=False,check_cancel=lambda:None):
    source_guard.check()
    sig=signature(qid);converted=_cases(cases,sig)
    entry=({'class_name':sig.class_name,'method_name':sig.method_name} if language=='python3'
           else extract_plain_entry(language,load_snippet(qid,language))) if isinstance(sig,PlainSig) else {}
    driver=render_output_driver(language,sig,entry,converted,code)
    checker=OutputCollector(qid,converted,signature=sig) if collect else OutputVerifier(qid,converted,signature=sig)
    if not collect and isinstance(sig,PlainSig):
        checker.validator=None
        checker.equal=lambda got,expected:portable.compare(qid,got,cases[checker.events[checker.position][0]],comparison)
    check_cancel()
    result=runner.run_submission(language,driver,limit=len(cases),backend='docker',run_timeout_s=5,output_verifier=checker)
    check_cancel()
    meta={'adapter':'deterministic_existing_harness','driver_sha256':sha(driver),'execution_supervisor':result.supervisor_protocol,
          'error':result.log[:2000],'asan_required':language in ('c','cpp'),'asan_status':'not_accepted'}
    if not collect and result.status=='Accepted' and language in ('c','cpp'):
        asan_checker=OutputVerifier(qid,converted,signature=sig)
        if isinstance(sig,PlainSig):
            asan_checker.validator=None
            asan_checker.equal=lambda got,expected:portable.compare(qid,got,cases[asan_checker.events[asan_checker.position][0]],comparison)
        confirmation=runner.run_submission(language,driver,limit=len(cases),backend='docker',run_timeout_s=5,asan=True,output_verifier=asan_checker)
        check_cancel();meta['asan_status']='passed' if confirmation.status=='Accepted' else confirmation.status
        if confirmation.status!='Accepted':
            if confirmation.status=='Runtime Error' and 'AddressSanitizer' in confirmation.stderr:result=confirmation
            else:raise ValueError('完整复判未完成 ASan 确认：'+confirmation.log[:300])
    return {'state':'SUCCESS','ac_status':result.status,'total_testcases':len(cases),'total_correct':result.total_correct or 0,
            'runtime':f'{result.runtime_ms:.0f} ms' if result.runtime_available else '',
            'memory':f'{result.memory_mb:.1f} MB' if result.memory_available else '',
            'version':VERSION,'cases_sha256':sha(cases),'correctness_order':'frozen_corpus_order',
            '_meta':meta,'outputs':checker.outputs if collect else []}


def execute(qid,language,code,cases,comparison,plan,*,collect=False,check_cancel=lambda:None,full=False):
    source_guard.check()
    if plan['kind']=='deterministic':
        if full and not collect:
            from local.lab import correctness_audit,audited_judging
            evidence=correctness_audit.evidence(qid,cases,runner.DOCKER_IMAGE)
            if evidence.get('promoted') and language in correctness_audit.receipt(qid,cases)['binding']['languages']:
                with tempfile.TemporaryDirectory(prefix='native_full_') as folder:
                    path=Path(folder)/f'{qid}_{KEY_TO_LABEL[language]}_1.txt';path.write_text(code,encoding='utf8')
                    return audited_judging.run(path,cases,check_cancel=check_cancel)
        return _raw(qid,language,code,cases,comparison,collect=collect,check_cancel=check_cancel)
    combined=plan['prefix']+'\n'+code+'\n'+plan['suffix']
    out=portable.execute(qid,language,combined,cases,comparison,collect=collect,check_cancel=check_cancel,native_bridge=True)
    out['_meta'].update(adapter='gated_native_bridge',adapter_sha256=plan['adapter_sha256'],native_source_sha256=sha(code))
    out['version']=VERSION
    return out


def negative_source(code,language):
    """A crashing entry checks that a bridge invokes the supplied native code."""
    if language=='python3':
        tree=ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                node.body=[ast.Raise(exc=ast.Call(func=ast.Name(id='RuntimeError',ctx=ast.Load()),args=[ast.Constant(SENTINEL)],keywords=[]),cause=None)]
        return ast.unparse(ast.fix_missing_locations(tree))
    throws={'cpp':f'throw runtime_error("{SENTINEL}");','c':f'fprintf(stderr,"{SENTINEL}");abort();',
            'java':f'throw new RuntimeException("{SENTINEL}");','csharp':f'throw new System.Exception("{SENTINEL}");',
            'javascript':f'throw new Error("{SENTINEL}");','golang':f'panic("{SENTINEL}")','rust':f'panic!("{SENTINEL}");'}
    # Definitions in the reference source only; adapters/types are separate.
    matches=list(re.finditer(r'\b(?:function\s+\w*|\w+)\s*\([^;{}]*\)\s*(?:->[^{}]+)?\s*\{',code))
    if not matches:return None
    replacements=[]
    for match in matches:
        if any(start<=match.start()<end for start,end,body in replacements):continue
        if re.match(r'(?:if|for|while|switch|catch)\s*\(',match[0]):continue
        start=match.end();depth=1;i=start;quote=None;escape=False
        while i<len(code) and depth:
            ch=code[i]
            if quote:
                if escape:escape=False
                elif ch=='\\':escape=True
                elif ch==quote:quote=None
            elif ch in ('"',"'"):quote=ch
            elif ch=='{':depth+=1
            elif ch=='}':depth-=1
            i+=1
        if depth==0:replacements.append((start,i-1,throws[language]))
    if not replacements:return None
    for start,end,body in reversed(replacements):code=code[:start]+body+code[end:]
    return code


def sensitivity_gate(qid,language,code,cases,comparison,plan,*,check_cancel=lambda:None):
    """Only a complete, non-crashing wrong value proves output sensitivity.

    CE, RE and timeouts do not establish that a bridge uses the return value or
    mutated state. This gate is deliberately separate from the exception gate.
    """
    out=execute(qid,language,code,cases,comparison,plan,collect=True,check_cancel=check_cancel)
    mismatches=[]
    if out['ac_status']=='Collected' and len(out['outputs'])==len(cases):
        mismatches=[i for i,(value,case) in enumerate(zip(out['outputs'],cases))
                    if not portable.compare(qid,value,case,comparison)]
    return {'passed':bool(mismatches),'counterexample_indices':mismatches,
            'source_sha256':sha(code),'execution':out}


def python_sensitivity_source(code):
    """Gate-only deterministic corruption, including observable void mutation."""
    tree=ast.parse(code)
    class Returns(ast.NodeTransformer):
        def visit_Return(self,node):
            if node.value is not None:node.value=ast.Call(func=ast.Name(id='_mci_gate_value',ctx=ast.Load()),args=[node.value],keywords=[])
            return node
    for cls in tree.body:
        if not isinstance(cls,ast.ClassDef):continue
        for method in cls.body:
            if not isinstance(method,ast.FunctionDef) or method.name.startswith('_'):continue
            method=Returns().visit(method)
            parameters=[p.arg for p in method.args.posonlyargs+method.args.args if p.arg not in ('self','cls')]
            final=[ast.Expr(ast.Call(func=ast.Name(id='_mci_gate_inplace',ctx=ast.Load()),args=[ast.Name(id=name,ctx=ast.Load())],keywords=[])) for name in parameters]
            if final:method.body=[ast.Try(body=method.body,handlers=[],orelse=[],finalbody=final)]
    helper=ast.parse('''
def _mci_gate_inplace(value):
    if isinstance(value,list) and value:
        value[0]=_mci_gate_value(value[0])
    elif hasattr(value,'val'):
        value.val=_mci_gate_value(value.val)
def _mci_gate_value(value):
    if type(value) is bool: return not value
    if type(value) in (int,float): return value+1
    if type(value) is str: return value+'__gate__'
    _mci_gate_inplace(value)
    return value
''')
    tree.body.extend(helper.body)
    return ast.unparse(ast.fix_missing_locations(tree))


def declared_solution_returns(qid):
    if qid is None:return {}
    try:
        stub=ast.parse(load_snippet(qid,'python3').rstrip()+'\n        pass\n')
        for cls in stub.body:
            if isinstance(cls,ast.ClassDef) and cls.name=='Solution':
                return {m.name:ast.unparse(m.returns) for m in cls.body if isinstance(m,ast.FunctionDef) and m.returns is not None}
    except (ValueError,SyntaxError,OSError):pass
    return {}


def python_void_source(code,*,qid=None):
    """A no-op native void method must not fabricate API/mutation success."""
    tree=ast.parse(code);changed=False;declared=declared_solution_returns(qid)
    for cls in tree.body:
        if not isinstance(cls,ast.ClassDef):continue
        for method in cls.body:
            result_type=(ast.unparse(method.returns) if method.returns is not None else declared.get(method.name,'') if cls.name=='Solution' else '') if isinstance(method,ast.FunctionDef) else ''
            if isinstance(method,ast.FunctionDef) and not method.name.startswith('_') and result_type=='None':
                method.body=[ast.Return(value=ast.Constant(None))];changed=True
    return ast.unparse(ast.fix_missing_locations(tree)) if changed else None


def python_null_node_source(code,*,qid=None):
    """Return identity must be observable even when node values do not matter.

    This is only an adapter gate fixture, not a functional mutation-rate sample.
    A value mutation is equivalent for cycle/intersection identity questions.
    """
    tree=ast.parse(code);changed=False;declared=declared_solution_returns(qid)
    class Returns(ast.NodeTransformer):
        def visit_Return(self,node):return ast.copy_location(ast.Return(value=ast.Constant(None)),node)
    for cls in tree.body:
        if not isinstance(cls,ast.ClassDef) or cls.name!='Solution':continue
        for method in cls.body:
            result_type=(ast.unparse(method.returns) if method.returns is not None else declared.get(method.name,'')) if isinstance(method,ast.FunctionDef) else ''
            if (isinstance(method,ast.FunctionDef) and not method.name.startswith('_')
                    and any(name in result_type for name in ('ListNode','TreeNode','Node'))):
                Returns().visit(method);changed=True
    return ast.unparse(ast.fix_missing_locations(tree)) if changed else None


def prepare(qid,language,descriptor,package,profile,image,*,check_cancel=lambda:None,on_event=lambda e:None):
    source_guard.check()
    bind={'qid':qid,'language':language,'image':image,'snippet_sha256':sha(load_snippet(qid,language)),
          'python_snippet_sha256':sha(load_snippet(qid,'python3')) if (REPO_ROOT/f'MCIBench-test/metadata/templates/snippets/{qid}/Python3.json').exists() else None,
          'cases_sha256':sha(package['cases']),'module_sha256':sha(Path(__file__).read_text(encoding='utf8')),
          'driver_sha256':sha(Path(drivers.__file__).read_text(encoding='utf8'))}
    bind['checker_sha256']=sha(Path(portable.__file__).read_text(encoding='utf8'))
    bind['native_python_sha256']=sha(Path(native_python.__file__).read_text(encoding='utf8'))
    bind['native_javascript_sha256']=sha(Path(native_javascript.__file__).read_text(encoding='utf8'))
    bind['javascript_protocol_sha256']=sha(Path(native_javascript.protocol.__file__).read_text(encoding='utf8'))
    bind['javascript_async_sha256']=sha(Path(native_javascript.asynchronous.__file__).read_text(encoding='utf8'))
    bind['javascript_clock_sha256']=sha(Path(native_javascript.clock.__file__).read_text(encoding='utf8'))
    bind['javascript_references_sha256']=sha(Path(javascript_references.__file__).read_text(encoding='utf8'))
    bind['comparison_sha256']=sha(package['comparison'])
    bind['descriptor_sha256']=sha(descriptor)
    bind['semantics_sha256']=sha(Path(portable.result_semantics.__file__).read_text(encoding='utf8'))
    path=DATA_DIR/str(qid)/f'{language}.json'
    if path.exists():
        old=json.loads(path.read_text(encoding='utf8'));digest=old.pop('receipt_sha256',None)
        if old.get('binding')==bind and old.get('passed') and digest==sha(old):old['receipt_sha256']=digest;return old
    with lock(qid,DATA_DIR):
        plan={'kind':'deterministic','binding':bind,'qid':qid,'language':language,'passed':False}
        try:
            sig=signature(qid)
            if isinstance(sig,PlainSig) and sig.ret is None:raise ValueError('mutation bridge required')
            if any(type(c['expected']) is dict and set(c['expected'])=={'return','mutated'} for c in descriptor['official']):raise ValueError('counted mutation bridge required')
            if isinstance(sig,PlainSig) and any(set(c['args'])!={p.name for p in sig.params} for c in descriptor['official']):raise ValueError('hidden API context requires a bridge')
            _cases(descriptor['official'],sig)
            entry=({'class_name':sig.class_name,'method_name':sig.method_name} if language=='python3'
                   else extract_plain_entry(language,load_snippet(qid,language))) if isinstance(sig,PlainSig) else {}
            render_output_driver(language,sig,entry,_cases(descriptor['official'],sig),'')
        except (ValueError,TypeError,KeyError,OSError,AssertionError):plan['kind']='bridge'
        def save_attempt(record):
            plan.setdefault('attempts',[]).append(record)
            save(path.with_suffix('.pending.json'),plan)
        trusted_javascript=native_javascript.bridge(qid,descriptor) if language=='javascript' else None
        if trusted_javascript:
            plan['kind']='bridge';baseline=javascript_references.SOURCES[qid];origin='reviewed_native_protocol_reference'
        else:
            try:baseline=load_reference(qid,language);origin='repository_reference'
            except (OSError,ValueError):baseline=None;origin='separately_generated_native_reference'
        if baseline is None:
            on_event({'qid':qid,'stage':'native_reference_generation','language':language})
            response=generate(profile,packages.prompt_for(qid,language,descriptor,interface='leetcode_method')+
                '\nBuild an independent reference implementation, not a translation of any candidate.',.3,max_attempts=1,check_cancel=check_cancel,on_attempt=save_attempt)
            if response.get('finish_reason')!='stop':raise ValueError('原生接口参考程序未完整生成')
            baseline=response['code']
        plan.update(reference_code=baseline,reference_sha256=sha(baseline),reference_origin=origin)
        if plan['kind']=='deterministic':
            gate=_raw(qid,language,baseline,package['cases'],package['comparison'],check_cancel=check_cancel)
            plan['reference_gate']=gate;save(path.with_suffix('.pending.json'),plan)
            if gate['ac_status']!='Accepted':
                # A different program may be generated, but repository source is never edited.
                on_event({'qid':qid,'stage':'native_reference_generation','language':language})
                response=generate(profile,packages.prompt_for(qid,language,descriptor,interface='leetcode_method')+
                    '\nProduce a fresh independent reference solution. The repository reference failed a gate; do not use any candidate under evaluation.',.3,max_attempts=1,check_cancel=check_cancel,on_attempt=save_attempt)
                if response.get('finish_reason')!='stop':raise ValueError('原生接口参考程序响应截断')
                baseline=response['code'];gate=_raw(qid,language,baseline,package['cases'],package['comparison'],check_cancel=check_cancel)
                plan.update(reference_code=baseline,reference_sha256=sha(baseline),reference_origin='separately_generated_native_reference',reference_gate=gate)
                save(path.with_suffix('.pending.json'),plan)
                if gate['ac_status']!='Accepted':raise ValueError('原生接口参考门禁未通过，代码已保留')
        else:
            # Generate a gate-only wrong implementation independently of the
            # bridge. Its output must execute fully and disagree with an answer.
            mutant_prompt=('Return ONLY complete native solution code with the EXACT interface below. '
                'This is a gate-only incorrect implementation to test an invocation adapter. '
                'Make one deterministic functional change to the reference so that at least one supplied input returns a wrong value '
                'or has wrong mutated state. It MUST compile, terminate, preserve valid result types and NOT throw, crash, hang, print, '
                'embed expected answers or inspect platform helpers. Keep support types outside the solution unchanged.\nInterface:\n'+
                load_snippet(qid,language)+'\nReference:\n'+baseline+'\nGate inputs and expected serialization:\n'+
                json.dumps(descriptor['official'],ensure_ascii=False))
            mutants=[python_sensitivity_source(baseline)] if language=='python3' else []
            if language=='javascript' and native_javascript.bridge(qid,descriptor):
                mutants=[native_javascript.sensitivity_source(qid)]
            if language=='python3':
                void_mutant=python_void_source(baseline,qid=qid)
                if void_mutant:mutants.append(void_mutant)
                null_mutant=python_null_node_source(baseline,qid=qid)
                if null_mutant:mutants.append(null_mutant)
            for mutant_index in range(0 if mutants else 2):
                response=generate(profile,mutant_prompt,.4,purpose='gate_mutation',max_attempts=1,check_cancel=check_cancel,on_attempt=save_attempt)
                if response.get('finish_reason')!='stop' or not response.get('code','').strip():
                    raise ValueError('接口输出敏感性门禁程序未完整生成')
                mutants.append(response['code'])
                mutant_prompt+='\nUse a different functional change from this previous attempt:\n'+response['code']
            plan['sensitivity_sources']=[{'code':code,'sha256':sha(code)} for code in mutants]
            prompt=('Create ONLY a JSON object {"prefix":"...","suffix":"..."} containing an input/output bridge, NOT a solution algorithm. '
                    'The complete driver is platform JSON helpers + prefix + UNMODIFIED native solution source + suffix + platform main. '
                    'prefix defines missing LeetCode types/APIs; suffix implements the bridge entry and MUST invoke the native entry/class. '
                    'IMPORTANT: the bridge entry has a DIFFERENT name to avoid replacing the solution: use mci_adapter_solve instead of solve for Python/JavaScript/C/C++/Go/Rust; '
                    'for Java use class MciAdapter { public Object solve(Map<String,Object> data) {...} }; for C# use class MciAdapter with public object Solve(JsonElement data). '
                    'Never implement the problem algorithm in the adapter, never embed expected answers, and never catch solution exceptions to fabricate results. '
                    'Hidden APIs such as isBadVersion/guess/knows must receive their test context from JSON data and must not be exposed as extra native parameters. '
                    'Return actual serialized output or required mutated arguments. Keep all target solution interfaces unchanged. '
                    'Available JSON helper API:\n'+drivers.CONTRACTS[language]+'\nNative interface:\n'+load_snippet(qid,language)+
                    '\nSerialization:\n'+(descriptor.get('interface_note') or '')+'\nPublic cases:\n'+json.dumps(descriptor['official'],ensure_ascii=False)+
                    '\nNative reference for invocation gate:\n'+baseline+'\nProblem:\n'+packages.io.description(qid))
            for attempt in range(3):
                on_event({'qid':qid,'stage':'native_adapter_gate','language':language})
                try:
                    adapter=trusted_javascript or (native_python.bridge(qid,descriptor) if attempt==0 and language=='python3' else None)
                    if adapter is None:adapter=packages.response_json(generate(profile,prompt,.2,purpose='adapter',max_attempts=1,check_cancel=check_cancel,on_attempt=save_attempt))
                    if type(adapter) is not dict or set(adapter)!={'prefix','suffix'} or any(type(v) is not str for v in adapter.values()):raise ValueError('原生接口适配响应无效')
                except (ValueError,TypeError,KeyError) as error:
                    save_attempt({'stage':'invalid_adapter_response','attempt':attempt+1,'reason':str(error)})
                    prompt+='\nPrevious response was invalid. Return EXACTLY {"prefix":"code", "suffix":"code"}, with no solution/code field or other keys. Use proper JSON newline escapes.'
                    continue
                plan.update(adapter);plan['adapter_sha256']=sha(adapter)
                gate=execute(qid,language,baseline,package['cases'],package['comparison'],plan,check_cancel=check_cancel)
                plan['reference_gate']=gate;save(path.with_suffix('.pending.json'),plan)
                if gate['ac_status']=='Accepted':
                    negative=(native_javascript.negative_source(qid,SENTINEL) if language=='javascript' and native_javascript.bridge(qid,descriptor) else negative_source(baseline,language))
                    if negative:
                        bad=execute(qid,language,negative,descriptor['official'],descriptor['comparison'],plan,collect=True,check_cancel=check_cancel)
                        plan['entry_injection_gate']=bad;save(path.with_suffix('.pending.json'),plan)
                        if native_javascript.observed_entry(bad,SENTINEL):
                            sensitivity=[]
                            for mutant in mutants:
                                gate_row=sensitivity_gate(qid,language,mutant,package['cases'],package['comparison'],plan,check_cancel=check_cancel)
                                sensitivity.append(gate_row)
                                if gate_row['passed']:break
                            plan['output_sensitivity_gates']=sensitivity;save(path.with_suffix('.pending.json'),plan)
                            if any(row['passed'] for row in sensitivity):break
                            prompt+='\nOutput-sensitivity check failed: invoke the native return value/mutated arguments and serialize THAT actual result. Do not compute the problem result in the bridge.'
                    prompt+='\nThe adapter failed its native-entry invocation check. It must call the supplied solution and let solution exceptions propagate.'
                else:prompt+='\nPrevious bridge failed. Repair only invocation/serialization, not the native solution.\n'+json.dumps(adapter)+'\nDiagnostic:\n'+gate['_meta']['error'][:1500]
            else:raise ValueError('原生接口适配门禁未通过，代码已保留')
        plan['passed']=True;plan['receipt_sha256']=sha(plan);save(path,plan)
        return plan
