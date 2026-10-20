"""Model-proposed inputs checked by independent Python/native-JS algorithms."""
from copy import deepcopy
import json
from pathlib import Path

from local.lab import javascript_answers as answers,javascript_references as references,native_javascript as native,source_guard
from local.lab.behavior import sha
from local.lab.generation import generate
from local.lab.testcase_workflow import lock,save
source_guard.register(__file__)


def build(qid,descriptor,profile,target,image,*,auto,directory,check_cancel,on_event):
    # Import after the shared package API is initialized, avoiding an import
    # cycle. No candidate source is ever supplied to an answer program.
    from local.lab import problem_packages as packages,native_adapters,portable_judging
    directory=Path(directory)
    def emit(stage,**data):check_cancel();on_event({'qid':qid,'stage':stage,**data})
    current=packages.binding(qid,image,descriptor)
    reference=references.SOURCES[qid]
    adapter=native.bridge(qid,descriptor)
    if adapter is None:raise ValueError('公开示例不符合已审查 JavaScript 协议，保留原契约待核实')
    plan={'kind':'bridge',**adapter,'adapter_sha256':sha(adapter)}
    with lock(qid,directory):
        cached=packages.read(qid,image,directory=directory,descriptor=descriptor)
        if cached and cached.get('evidence_level')=='reviewed_protocol_oracles' and (not auto or cached['generated_count']>=target):emit('reused_verified_corpus');return cached
        official=deepcopy(descriptor['official'])
        for case in official:
            answer=answers.answer(qid,case['args'])
            if not portable_judging.compare(qid,answer,case,descriptor['comparison']):raise ValueError('已审查 Python 答案与官方示例不一致，未发布')
        path=directory/'protocol_pending'/f'{qid}.json'
        draft={'binding':current,'qid':qid,'state':'building','accepted':[],'rejected':[],'attempts':[],'input_batches':[]}
        if path.exists():
            old=json.loads(path.read_text(encoding='utf8'))
            if old.get('binding')==current:draft=old
        def persist(record=None):
            if record is not None:draft['attempts'].append(record)
            save(path,draft)
        persist()
        if 'public_gate' not in draft:
            emit('independent_oracle_gate',language='javascript')
            gate=native_adapters.execute(qid,'javascript',reference,official,descriptor['comparison'],plan,check_cancel=check_cancel)
            draft['public_gate']=gate;persist()
        if draft['public_gate']['ac_status']!='Accepted':raise ValueError('已审查 JavaScript 参考解未通过公开示例，未发布')
        inputs=deepcopy(draft['accepted']);seen={sha(c['args']) for c in official+inputs}
        if auto:
            for round_index in range(3):
                missing=target-len(inputs)
                if missing<=0:break
                emit('requesting_test_inputs',round=round_index+1,generated_count=len(inputs),target=target)
                prompt=(f'Propose {min(missing,100)} different legal inputs. Return ONLY {{"cases":[{{"args":{{...}},"category":"boundary|adversarial|random"}}]}}. '
                    'Do not provide answers, code, executable strings, or unsupported callback kinds. Match EXACT field names and declarative AST syntax of the examples. '
                    'Keep all arrays under 30 items and the response within the token budget. Do not turn ordinary JSON object arguments into strings. '
                    'For memoize, distinct literal objects are distinct references, while {$ref:"id"} reuses an object from the objects pool. '
                    'All functions must be well-defined on actual arguments. For composition and map use integer-returning functions; groupBy must return a string and sort keys must be distinct numbers. '
                    'Use varied scalar constants and inputs to make distinct cases; do not invent other protocol shapes. '
                    'For timeLimit, do not propose equal delay and t: the equality boundary is explicitly pending verification. '
                    'No undefined/nonfinite final JSON values. '
                    '\nSerialization:\n'+descriptor['interface_note']+'\nAlready used input objects (do not repeat):\n'+
                    json.dumps([c['args'] for c in official+inputs],ensure_ascii=False)[:20000]+
                    '\nProblem:\n'+packages.io.description(qid))
                response=generate(profile,prompt,.7,purpose='test_inputs',max_attempts=1,check_cancel=check_cancel,on_attempt=persist)
                try:proposed,rejected=packages.parse_inputs(response,descriptor,seen)
                except (ValueError,TypeError,KeyError,OverflowError) as error:
                    draft['rejected'].append({'round':round_index+1,'reason':str(error),'response':response});persist();continue
                draft['rejected']+=rejected;legal=[]
                for proposal in proposed:
                    try:proposal['expected']=answers.answer(qid,proposal['args']);legal.append(proposal)
                    except (ValueError,TypeError,KeyError,IndexError,OverflowError,ZeroDivisionError) as error:
                        draft['rejected'].append({'reason':str(error),'args':proposal['args']})
                legal=legal[:missing]
                if legal:
                    emit('reference_gate',language='javascript')
                    observed=native_adapters.execute(qid,'javascript',reference,legal,descriptor['comparison'],plan,collect=True,check_cancel=check_cancel)
                    draft['input_batches'].append({'cases':legal,'execution':observed});persist()
                    if observed['ac_status']!='Collected' or len(observed['outputs'])!=len(legal):raise ValueError('JavaScript 独立答案未完整执行，保留证据未发布')
                    for row,observed_value in zip(legal,observed['outputs']):
                        if portable_judging.compare(qid,observed_value,row,descriptor['comparison']):
                            row['origin']='model_input_python_and_javascript_oracles';inputs.append(row)
                        else:draft['rejected'].append({'reason':'reviewed Python/JavaScript answer disagreement','args':row['args'],'python_answer':row['expected'],'javascript_answer':observed_value})
                    draft['accepted']=inputs;persist()
            if len(inputs)<target:raise ValueError(f'仅有 {len(inputs)}/{target} 条通过 Python/JavaScript 独立答案门禁的补充输入，保留断点未发布')
        cases=official+inputs
        emit('reference_gate',language='javascript')
        gate=native_adapters.execute(qid,'javascript',reference,cases,descriptor['comparison'],plan,check_cancel=check_cancel)
        if gate['ac_status']!='Accepted':persist();raise ValueError('完整语料 JavaScript 参考门禁失败，未发布')
        if current!=packages.binding(qid,image,descriptor):raise ValueError('发布前配置发生变化，未发布')
        row={'version':packages.VERSION,'qid':qid,'binding':current,'descriptor':descriptor,'cases':cases,'cases_sha256':sha(cases),
             'comparison':descriptor['comparison'],'generated_count':len(inputs),'gates_passed':True,
             'reference_languages':['python3','javascript'],'evidence_level':'reviewed_protocol_oracles',
             'constraint_evidence':'reviewed_declarative_protocol','oracles':[
                {'language':'python3','origin':'reviewed_protocol_answer','module_sha256':sha(Path(answers.__file__).read_text(encoding='utf8'))},
                {'language':'javascript','origin':'reviewed_native_reference','code':reference,'code_sha256':sha(reference),'official_gate':draft['public_gate']}],
             'gates':[{'language':'javascript','verdict':gate}],'leetcode_alignment':'not_measured',
             'execution_protocol':{'version':native.asynchronous.VERSION if qid in native.asynchronous.QIDS else native.protocol.VERSION,
                'callback_scope':'reviewed_declarative_family','clock':'deterministic_timer_order_v1' if qid in native.asynchronous.QIDS else None},
             'limitations':['finite_tests_not_proof','oracles_can_share_controller_errors','arbitrary_callback_families_not_verified','not_audited15_mutation_evidence','undefined_final_values_outside_verified_scope']}
        if qid in native.asynchronous.QIDS:row['limitations'].append('virtual_timing_not_leetcode_wall_clock_equivalence')
        if qid==2637:row['limitations'].append('equal_deadline_pending_verified_interpretation')
        row['package_sha256']=sha(row);save(directory/f'{qid}.json',row)
        draft['state']='published';persist();emit('published_generated_tests',generated_count=len(inputs));return row
