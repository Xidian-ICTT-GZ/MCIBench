"""On-demand independent test packages for every catalog problem family.

Reviewed finite oracles retain their existing publication gates. Other problems
use separately executed reference/oracle programs, anchored to public examples;
their evidence is explicitly weaker than a reviewed independent algorithm.
"""
from copy import deepcopy
import json
from pathlib import Path

from local.common import REPO_ROOT,load_reference,LANGS
from local.lab import problem_io as io, portable_drivers as drivers, portable_judging as judging
from local.lab import result_semantics
from local.lab import sql_answers
from local.lab import public_literals,javascript_protocol,javascript_async
from local.lab import javascript_answers,javascript_references,javascript_packages,native_javascript
from local.lab.behavior import sha
from local.lab.generation import generate
from local.lab.testcase_workflow import save,lock,expand
from local.lab import source_guard
source_guard.register(__file__)

VERSION='all-catalog-test-package-v1'
DATA_DIR=REPO_ROOT/'local/dashboard/packages/server/data/lab_problem_packages'


def _binding_source_identity():
    source_guard.check()
    return {'io_sha256':sha(Path(io.__file__).read_text(encoding='utf-8')),
            'literal_parser_sha256':sha(Path(public_literals.__file__).read_text(encoding='utf8')),
            'sql_answers_sha256':sha(Path(sql_answers.__file__).read_text(encoding='utf8')),
            'reviewed_sql_batch8':sql_answers.reviewed8.fingerprint(),
            'statement_revisions_sha256':sha(io.STATEMENT_REVISIONS.read_text(encoding='utf8')),
            'javascript_protocol_sha256':sha(Path(javascript_protocol.__file__).read_text(encoding='utf8')),
            'javascript_async_sha256':sha(Path(javascript_async.__file__).read_text(encoding='utf8')),
            'javascript_answers_sha256':sha(Path(javascript_answers.__file__).read_text(encoding='utf8')),
            'javascript_references_sha256':sha(Path(javascript_references.__file__).read_text(encoding='utf8')),
            'javascript_packages_sha256':sha(Path(javascript_packages.__file__).read_text(encoding='utf8')),
            'native_javascript_sha256':sha(Path(native_javascript.__file__).read_text(encoding='utf8')),
            'native_executor_sha256':sha(Path(__file__).with_name('native_adapters.py').read_text(encoding='utf8')),
            'javascript_clock_sha256':sha(Path(native_javascript.clock.__file__).read_text(encoding='utf8')),
            'driver_sha256':sha(Path(drivers.__file__).read_text(encoding='utf-8')),
            'checker_sha256':sha(Path(judging.__file__).read_text(encoding='utf-8')),
            'semantics_sha256':sha(Path(result_semantics.__file__).read_text(encoding='utf-8')),
            'builder_sha256':sha(Path(__file__).read_text(encoding='utf-8'))}


def _compose_binding(qid,image,descriptor,sources,mysql_identity=None):
    record={'qid':qid,'description_sha256':sha(io.description(qid)),'image':image,
            'descriptor_sha256':sha(descriptor) if descriptor is not None else None,**sources}
    if qid in (1211,1633,1661):
        from local.lab.mysql_runtime import identity
        record['mysql_environment']=(mysql_identity or identity)()
    return record


def binding(qid,image,descriptor=None):
    # Signing/execution always takes a fresh identity, never a catalog snapshot.
    return _compose_binding(qid,image,descriptor,_binding_source_identity())


class CatalogReadContext:
    """One display request shares source checks; verify again before returning.

    This is not used by publication or execution. It also keeps the first
    native-runtime lookup (including failure) local to this one request.
    """
    def __init__(self):
        self.sources=_binding_source_identity();self.mysql=None;self.mysql_error=None

    def native_identity(self):
        from local.lab.mysql_runtime import identity
        if self.mysql_error is not None:raise ValueError(self.mysql_error)
        if self.mysql is None:
            try:self.mysql=identity()
            except ValueError as error:
                self.mysql_error=str(error);raise
        return self.mysql

    def binding(self,qid,image,descriptor):
        return _compose_binding(qid,image,descriptor,self.sources,self.native_identity)

    def verify(self):
        if self.sources!=_binding_source_identity():raise ValueError('目录校验期间判题源码发生变化，请刷新或重启服务')


def read(qid,image,*,directory=None,descriptor=None,_catalog_context=None):
    try:
        row=json.loads((Path(directory or DATA_DIR)/f'{qid}.json').read_text(encoding='utf-8'))
        digest=row.pop('package_sha256')
        expected_descriptor=descriptor if descriptor is not None else row.get('descriptor')
        expected=(_catalog_context.binding(qid,image,expected_descriptor) if _catalog_context is not None else binding(qid,image,expected_descriptor))
        if row['version']!=VERSION or row['binding']!=expected or digest!=sha(row):return None
        row['package_sha256']=digest
        if not row.get('cases') or not row.get('gates_passed'):return None
        return row
    except (OSError,ValueError,TypeError,KeyError):return None


def response_json(response):
    if response.get('finish_reason')!='stop':raise ValueError('模型响应被截断，未接收测试或规则')
    from local.harness.output_protocol import _object,_nonfinite
    return json.loads(response['code'],object_pairs_hook=_object,parse_constant=_nonfinite)


def describe(qid,profile=None,*,check_cancel=lambda:None,on_attempt=lambda record:None):
    cases,comparison,warnings=io.official(qid)
    descriptor_binding={'qid':qid,'description_sha256':sha(io.description(qid)),
                        'builder_sha256':sha(Path(__file__).read_text(encoding='utf8')),
                        'io_sha256':sha(Path(io.__file__).read_text(encoding='utf8'))}
    descriptor_binding['literal_parser_sha256']=sha(Path(public_literals.__file__).read_text(encoding='utf8'))
    descriptor_binding['sql_answers_sha256']=sha(Path(sql_answers.__file__).read_text(encoding='utf8'))
    descriptor_binding['reviewed_sql_batch8']=sql_answers.reviewed8.fingerprint()
    descriptor_binding['statement_revisions_sha256']=sha(io.STATEMENT_REVISIONS.read_text(encoding='utf8'))
    descriptor_binding['javascript_protocol_sha256']=sha(Path(javascript_protocol.__file__).read_text(encoding='utf8'))
    descriptor_binding['javascript_async_sha256']=sha(Path(javascript_async.__file__).read_text(encoding='utf8'))
    descriptor_path=DATA_DIR/'descriptors'/f'{qid}.json'
    if not cases:
        try:
            cached=json.loads(descriptor_path.read_text(encoding='utf8'))
            digest=cached.pop('sha256')
            if cached['binding']==descriptor_binding and digest==sha(cached):
                return cached['descriptor']
        except (OSError,ValueError,TypeError,KeyError):pass
    if not cases:
        if profile is None:raise ValueError('题面示例需要补充序列化契约')
        prompt=('Normalize the PUBLIC worked examples of the problem below to a JSON function interface. '
                'Return ONLY JSON {"cases":[{"args":{...},"expected":...,"input_excerpt":"EXACT substring",'
                '"output_excerpt":"EXACT substring","normalization_note":"..."}],"comparison":{"mode":"ordered"},'
                '"interface_note":"precise serialization conventions"}. '
                'Do not invent examples or expected values. Preserve quoted strings literally. Each excerpt must be an exact nonempty substring of the statement. '
                'For linked nodes use their stated values or indices and explain the convention. For functions/promises use a declarative JSON input, never executable JSON strings. '
                'For dataframe problems represent each input table as {"columns":[...],"types":["INTEGER"|"REAL"|"TEXT",...],"rows":[[...]...]}; '
                'output a table with columns and rows.\n'+io.description(qid))
        normalized=response_json(generate(profile,prompt,.2,purpose='contract',max_attempts=1,check_cancel=check_cancel,on_attempt=on_attempt))
        text=io.description(qid);cases=[]
        for item in normalized.get('cases',[]):
            if (type(item) is not dict or not item.get('input_excerpt') or not item.get('output_excerpt')
                    or item['input_excerpt'] not in text or item['output_excerpt'] not in text):
                raise ValueError('官方示例序列化缺少可定位题面依据')
            io.input_valid_shape(item['args'])
            try:
                expected,trailing=io.parse_json(item['output_excerpt'])
                if not trailing and not judging.equal(expected,item['expected']):raise ValueError('normalized answer changed an official JSON answer')
            except json.JSONDecodeError:pass
            cases.append({'args':item['args'],'expected':item['expected'],'origin':'model_normalized_official',
                          'input_excerpt':item['input_excerpt'],'output_excerpt':item['output_excerpt'],
                          'normalization_note':str(item.get('normalization_note',''))[:2000]})
        comparison=normalized.get('comparison',{'mode':'ordered'})
        note=str(normalized.get('interface_note',''))[:6000]
    else:note='Input data uses the args object and the exact output shape of the public JSON examples below. For design classes, process the ops/args trace and return the complete result array. For in-place methods, return the final required mutated result; counted prefixes use the {return,mutated} shape shown. TreeNode arrays use LeetCode level order: assign children only to NON-NULL queued parents. A null element is a MISSING child, never a zero-valued node; never link or visit null placeholders. ListNode arrays are the values from head to tail.'
    note+='\n'+io.serialization_note(qid)
    if not cases:raise ValueError('未取得可核对的公开输入与答案，已生成代码仍会保留')
    if comparison.get('mode') not in ('ordered','unordered','rows_unordered','all_unordered','table','shell_lines','word_frequency'):
        raise ValueError('unsupported result comparison contract')
    descriptor={'qid':qid,'kind':io.kind(qid),'official':cases,'comparison':comparison,'interface_note':note,'warnings':warnings}
    revision=io.statement_revision(qid)
    if revision:descriptor['statement_revision']=revision
    if cases[0].get('origin')=='model_normalized_official':
        record={'binding':descriptor_binding,'descriptor':descriptor}
        record['sha256']=sha(record);save(descriptor_path,record)
    return descriptor


def code_interface(qid,language):
    if language in ('mysql','sqlite','bash'):return language
    try:
        from local.common import load_snippet
        load_snippet(qid,language)
        # SQL/Pandas interfaces have distinct runtime contracts; algorithm
        # snippets are retained exactly when the repository has one.
        return 'leetcode_method'
    except (OSError,ValueError,KeyError):return drivers.VERSION


def prompt_for(qid,language,descriptor,*,source=None,interface=None,main_only=False):
    interface=interface or drivers.VERSION
    statement=io.main_statement(qid) if main_only else io.description(qid)
    lead=('Implement the programming problem below.' if source is None else
          'Translate the supplied generated source program to the target language. Preserve its algorithm and behavior; do not silently repair it or replace it with a reference solution.')
    lead+='\nUse the MAIN task input/output contract and all its guarantees. Follow-up questions do not expand the legal input domain or change the required answer. This does not authorize repairing a source program during translation.'
    text=(lead+'\nTarget language: '+io.LANGUAGES[language]+'.\n'+drivers.CONTRACTS[language]+
          '\nThis platform uses a standalone JSON function interface, including for linked lists, trees and design classes. '
          'Use the serialization convention below rather than an implicit LeetCode runner. Preserve required algorithmic complexity.\n'+descriptor['interface_note']+
          '\nPublic serialized examples:\n'+json.dumps(descriptor['official'],ensure_ascii=False)+
          '\nProblem:\n'+statement)
    if interface=='leetcode_method':
        from local.common import load_snippet
        text=(lead+'\nTarget language: '+io.LANGUAGES[language]+'. Return only complete solution code matching the original target interface below. '
              'Do not add a main function or JSON solve wrapper. The platform supplies the standard task types and execution adapter. '
              'Preserve required algorithmic complexity.\nTarget interface:\n'+load_snippet(qid,language)+'\nProblem:\n'+statement)
    if source:
        text+='\nSource language: '+io.LANGUAGES.get(source['language'],source['language'])+'\nSource interface: '+source.get('interface','legacy_leetcode_method')+'\nSource code:\n'+source['code']
    if language in ('mysql','sqlite'):
        text+='\nTarget SQL dialect contract (overrides any legacy or source-language SQL syntax note, while preserving its input/output shape and algorithm): '+drivers.CONTRACTS[language]
    return text


def _reference(qid,language):
    try:return load_reference(qid,language)
    except (OSError,ValueError,KeyError):return None


def _oracle(qid,language,descriptor,profile,path,check_cancel,on_attempt):
    reviewed_sql=sql_answers.reference(qid,language)
    if reviewed_sql:
        verdict=judging.execute(qid,language,reviewed_sql,descriptor['official'],descriptor['comparison'],check_cancel=check_cancel)
        record={'language':language,'code':reviewed_sql,'code_sha256':sha(reviewed_sql),
                'origin':'reviewed_sql_reference','controller_version':sql_answers.VERSION,'official_gate':verdict}
        save(path,record)
        if verdict['ac_status']!='Accepted':raise ValueError('经审查 SQL 参考程序未通过公开示例，禁止自动修补或发布')
        return record
    reference=_reference(qid,language)
    prompt=prompt_for(qid,language,descriptor,main_only=True)
    prompt+='\nYou are building an independent answer oracle. You have NOT been given any candidate under evaluation. Prefer a direct, independently checkable algorithm within the stated constraints.'
    if reference:
        prompt+='\nRepository reference implementation: adapt its interface to the JSON function without altering its problem semantics. Fix no errors based on candidate outputs.\n'+reference
    for attempt in range(3):
        response=generate(profile,prompt,.3,max_attempts=1,check_cancel=check_cancel,on_attempt=on_attempt)
        record={'language':language,'response':response,'reference_sha256':sha(reference) if reference else None}
        save(path.with_name(path.stem+f'.try{attempt+1}.json'),record);save(path,record)
        if response.get('finish_reason')!='stop' or not response.get('code','').strip():
            prompt+='\nPrevious response was incomplete. Return a concise complete independent implementation.';continue
        verdict=judging.execute(qid,language,response['code'],descriptor['official'],descriptor['comparison'],check_cancel=check_cancel)
        save(path.with_name(path.stem+f'.try{attempt+1}.gate.json'),verdict);save(path.with_suffix('.gate.json'),verdict)
        if verdict['ac_status']=='Accepted':break
        observed=judging.execute(qid,language,response['code'],descriptor['official'],descriptor['comparison'],collect=True,check_cancel=check_cancel)
        save(path.with_name(path.stem+f'.try{attempt+1}.observed.json'),observed)
        prompt+='\nRepair ONLY this independent oracle using the public examples. LeetCode level-order trees consume children of NON-NULL queued parents; they are not heap-indexed arrays.\nPrevious code:\n'+response['code']+'\nExecution diagnostic:\n'+verdict['_meta']['error'][:1500]+'\nObserved public outputs:\n'+json.dumps(observed['outputs'],ensure_ascii=False)
    else:raise ValueError(f'{language} 独立答案程序未通过公开示例门禁，三次尝试已保留')
    return {'language':language,'code':response['code'],'code_sha256':sha(response['code']),
            'origin':'adapted_repository_reference' if reference else 'independently_generated_oracle',
            'reference_sha256':sha(reference) if reference else None,'official_gate':verdict}


def _expand(v):
    if type(v) is dict:
        if set(v)=={'$ref'}:return deepcopy(v)
        if any(str(k).startswith('$') for k in v):return expand(v)
        return {k:_expand(child) for k,child in v.items()}
    if type(v) is list:return [_expand(child) for child in v]
    return v


def parse_inputs(response,descriptor,seen):
    data=response_json(response)
    if type(data) is not dict or set(data)!={'cases'} or type(data['cases']) is not list or len(data['cases'])>100:raise ValueError('仅接受最多100条测试输入的 cases JSON')
    accepted=[];rejected=[];template=descriptor['official'][0]['args']
    for i,item in enumerate(data['cases']):
        try:
            if type(item) is not dict or not set(item)<={'args','category'} or 'args' not in item:raise ValueError('模型不得提供测试答案')
            args=_expand(item['args']);io.input_valid_shape(args)
            if io.controller_valid(descriptor.get('qid'),args) is False:raise ValueError('reviewed input construction constraints rejected input')
            if set(args)!=set(template):raise ValueError('参数名与公开接口不一致')
            if descriptor['kind']=='database':
                io.check_database_input(descriptor['qid'],args,template)
                for name,t in args['tables'].items():
                    schema=template['tables'][name]
                    t['types']=schema['types']
            if descriptor['kind']=='dataframe':
                for name,schema in template.items():
                    if type(schema) is dict and {'columns','rows','types'}<=set(schema):
                        table=args[name]
                        if type(table) is not dict or not {'columns','rows'}<=set(table) or not set(table)<={'columns','rows','types'} or table['columns']!=schema['columns'] or type(table['rows']) is not list:
                            raise ValueError('input dataframe schema changed')
                        if 'types' in table and table['types']!=schema['types']:raise ValueError('input dataframe dtype changed')
                        for row in table['rows']:
                            if type(row) is not list or len(row)!=len(schema['columns']):raise ValueError('input dataframe row width changed')
                            for value,type_ in zip(row,schema['types']):
                                if value is None:continue
                                if not (type(value) is int if type_=='INTEGER' else type(value) in (int,float) if type_=='REAL' else type(value) is str):
                                    raise ValueError('input dataframe cell type changed')
                        table['types']=deepcopy(schema['types'])
                    elif type(args[name]) is not type(schema):raise ValueError('input dataframe parameter shape changed')
            if descriptor['kind']=='shell':
                if set(args['files'])!=set(template['files']) or any(type(v) is not str for v in args['files'].values()):raise ValueError('shell file schema changed')
            if sha(args) in seen:raise ValueError('重复或公开输入')
            seen.add(sha(args));accepted.append({'args':args,'origin':'model_input_independent_execution'})
        except (ValueError,TypeError,KeyError,IndexError) as error:rejected.append({'index':i,'reason':str(error)[:300]})
    return accepted,rejected


def build(qid,descriptor,profile,target,image,*,auto=True,directory=None,check_cancel=lambda:None,on_event=lambda e:None):
    from local.lab import input_contracts as reviewed
    from local.lab import testcase_workflow as flow
    from local.lab.catalog import load_cases
    directory=Path(directory or DATA_DIR)
    if qid in javascript_protocol.QIDS|javascript_async.QIDS and native_javascript.bridge(qid,descriptor):
        return javascript_packages.build(qid,descriptor,profile,target,image,auto=auto,directory=directory,
            check_cancel=check_cancel,on_event=on_event)
    def emit(stage,**data):check_cancel();on_event({'qid':qid,'stage':stage,**data})
    if qid in reviewed.QIDS:
        existing=flow.read_bundle(qid,image=image)
        reference_languages=existing['languages'] if existing else ['python3','cpp']
        if auto:bundle=flow.build(qid,profile,target,reference_languages,image,check_cancel=check_cancel,on_event=on_event)
        else:bundle=existing
        cases=deepcopy(bundle['cases'] if bundle else load_cases(qid))
        if not cases:raise ValueError('独立答案语料缺失')
        return {'version':VERSION,'qid':qid,'descriptor':descriptor,'cases':cases,'cases_sha256':sha(cases),
                'gates_passed':True,'evidence_level':'reviewed_independent_oracle','reference_languages':reference_languages,
                'generated_count':len(bundle['generated_cases']) if bundle else 0,'comparison':descriptor['comparison'],
                'oracle_scope':{'max_length':2000 if qid==3 else 1000 if qid==1014 else None,
                                'outside_oracle_scope':sum(len(c['args']['values'])>1000 for c in cases) if qid==1014 else 0}}
    with lock(qid,directory):
        cached=read(qid,image,directory=directory,descriptor=descriptor)
        if cached and (not auto or cached['generated_count']>=target):emit('reused_verified_corpus');return cached
        current_binding=binding(qid,image,descriptor)
        checkpoint=directory/'pending'/f'{qid}.json'
        draft={'version':VERSION,'qid':qid,'binding':current_binding,'descriptor':descriptor,'oracles':[],
               'accepted':[],'attempts':[],'rejected':[],'state':'building','profile':{k:profile[k] for k in ('id','name','model_name','api_url') if k in profile}}
        if checkpoint.exists():
            old=json.loads(checkpoint.read_text(encoding='utf-8'))
            if old.get('binding')==current_binding:draft=old
        def persist(record=None):
            if record is not None:draft['attempts'].append(record)
            save(checkpoint,draft)
        persist()
        if descriptor['kind']!='shell':
            for language in ('python3','mysql') if qid in (1211,1633,1661) else ('python3','sqlite') if descriptor['kind']=='database' else ('python3','cpp'):
                if not any(o['language']==language for o in draft['oracles']):
                    emit('independent_oracle_gate',language=language)
                    oracle=_oracle(qid,language,descriptor,profile,directory/'attempts'/f'{qid}-{language}-oracle.json',check_cancel,persist)
                    draft['oracles'].append(oracle);persist()
        if descriptor['kind'] not in ('shell',) and 'validator' not in draft:
            emit('input_contract_gate')
            prompt=('Implement a Python JSON function def solve(data: dict) returning strictly True iff ONE SINGLE input object satisfies EVERY constraint of the problem below. '
                    'Use the MAIN task guarantees. Follow-up questions do NOT authorize inputs excluded by the main statement. '
                    'IMPORTANT: data is ONE dict such as {"height":[0,1,0]}; it is NOT a list of examples. Do not loop over an outer list of test cases. '
                    'Return False for non-dicts or wrong/missing/extra parameter names. Derived mathematical variables such as n=len(height) are not additional input fields. '
                    'No solution or expected-output calculation. Do not execute strings from data. Treat bool as distinct from int. '
                    'Enforce semantic guarantees, relational constraints, table uniqueness and foreign keys where stated. '
                    'The platform will additionally enforce JSON shape and size. No main.\nInput serialization:\n'+descriptor['interface_note']+
                    '\nSeparate public input objects, one per line (each is passed in a separate call):\n'+'\n'.join(json.dumps(c['args'],ensure_ascii=False) for c in descriptor['official'])+'\nProblem:\n'+io.main_statement(qid))
            for validation_attempt in range(3):
                response=generate(profile,prompt,.2,purpose='validator',max_attempts=1,check_cancel=check_cancel,on_attempt=persist)
                if response.get('finish_reason')!='stop':raise ValueError('输入约束程序响应截断')
                gate_inputs=[{'args':c['args'],'expected':True} for c in descriptor['official']]+[{'args':[],'expected':False},{'args':None,'expected':False}]
                gate=judging.execute(0,'python3',response['code'],gate_inputs,check_cancel=check_cancel)
                draft.setdefault('validator_attempts',[]).append({'code':response['code'],'code_sha256':sha(response['code']),'gate':gate});persist()
                if gate['ac_status']=='Accepted':
                    draft['validator']=draft['validator_attempts'][-1];persist();break
                observed=judging.execute(0,'python3',response['code'],gate_inputs,collect=True,check_cancel=check_cancel)
                draft['validator_attempts'][-1]['observed']=observed;persist()
                prompt+='\nPrevious constraint validator failed a gate. Fix only this validator. Each PUBLIC INPUT OBJECT must return True; [] and null must return False. Do not compute or return the programming-task answer.\nPrevious validator:\n'+response['code']+'\nGate diagnostic:\n'+gate['_meta']['error'][:800]+'\nActual values returned:\n'+json.dumps(observed['outputs'],ensure_ascii=False)
            if 'validator' not in draft:raise ValueError('输入约束程序未通过公开输入门禁')
        inputs=deepcopy(draft['accepted'])
        extras=deepcopy(draft.get('reviewed_extras',[]))
        seen={sha(c['args']) for c in descriptor['official']+inputs}
        for extra in extras:
            io.input_valid_shape(extra['args'])
            has_controller,controlled=io.controller_answer(qid,extra['args'])
            if (not str(extra.get('origin','')).startswith('reviewed_') or not has_controller
                    or sha(extra['args']) in seen
                    or not judging.compare(qid,controlled,extra,descriptor['comparison'])):
                raise ValueError('reviewed extra input lacks independent answer evidence or is duplicated; not published')
            if descriptor['kind']=='database':io.check_database_input(qid,extra['args'],descriptor['official'][0]['args'])
            seen.add(sha(extra['args']))
        if auto:
            for round_index in range(3):
                missing=target-len(inputs)
                if missing<=0:break
                emit('requesting_test_inputs',round=round_index+1,generated_count=len(inputs),target=target)
                prompt=(f'Propose {min(missing,100)} DIFFERENT legal inputs for the following problem. '
                        'Follow the MAIN task guarantees; do not mix in a follow-up variant or tied/empty cases forbidden by those guarantees. '
                        'Return ONLY {"cases":[{"args":{...},"category":"boundary|adversarial|random|scale"}]}. '
                        'Never give expected answers or executable recipes. Prefer compact small diverse inputs. Each input should normally use fewer than 30 elements; at most two scale inputs. '
                        'Keep every array/string under 2000 items, all input combined under 100000 items. The entire response must fit the output token budget. '
                        'Every JSON object must have unique keys. Design-class traces go inside a SINGLE outer args object containing ops and args. '
                        'Respect ALL numerical and semantic constraints. Include edge cases, repetition, empty/minimal structures when legal and different branches. '
                        'For SQL preserve table names, column names/types, primary keys and stated relationships. For shell preserve the input filenames. '
                        'Do NOT repeat any input below.\nSerialization: '+descriptor['interface_note']+
                        '\nExisting inputs: '+json.dumps([c['args'] for c in descriptor['official']+inputs+extras],ensure_ascii=False)[:16000]+
                        '\nProblem:\n'+io.main_statement(qid))
                reasons=[str(x.get('reason',''))[:500] for x in draft['rejected'][-6:]]
                if reasons:prompt+='\nPrevious rejected proposals: '+json.dumps(reasons,ensure_ascii=False)+'\nCorrect these violations. Do not repeat rejected or existing inputs; main-task guarantees are mandatory.'
                response=generate(profile,prompt,.7,purpose='test_inputs',max_attempts=1,check_cancel=check_cancel,on_attempt=persist)
                try:proposed,rejected=parse_inputs(response,descriptor,seen)
                except (ValueError,TypeError,KeyError,OverflowError) as error:
                    draft['rejected'].append({'reason':str(error),'round':round_index+1,'response':response});persist()
                    emit('rejected_model_response',round=round_index+1,reason=str(error))
                    continue
                draft['rejected']+=rejected
                proposed=proposed[:missing]
                answers_by_input={}
                if proposed and descriptor['kind']!='shell':
                    validator=judging.execute(0,'python3',draft['validator']['code'],proposed,collect=True,check_cancel=check_cancel)
                    draft.setdefault('input_batches',[]).append({'input_sha256':sha(proposed),'validator':validator});persist()
                    if validator['ac_status']!='Collected' or len(validator['outputs'])!=len(proposed):
                        raise ValueError('输入约束程序未完整执行补充输入，未发布')
                    legal=[]
                    for proposal,value in zip(proposed,validator['outputs']):
                        if value is True:legal.append(proposal)
                        else:draft['rejected'].append({'reason':'model-proposed constraint validator rejected input','input_sha256':sha(proposal['args'])})
                    proposed=legal
                    oracle_outputs=[]
                    if proposed:
                        for oracle in draft['oracles']:
                            out=judging.execute(qid,oracle['language'],oracle['code'],proposed,descriptor['comparison'],collect=True,check_cancel=check_cancel)
                            draft['input_batches'][-1].setdefault('oracles',[]).append({'language':oracle['language'],'execution':out});persist()
                            if out['ac_status']!='Collected' or len(out['outputs'])!=len(proposed):
                                raise ValueError('独立答案程序未完整执行补充输入，未发布')
                            oracle_outputs.append(out['outputs'])
                        for index,proposal in enumerate(proposed):
                            answers_by_input[sha(proposal['args'])]=[values[index] for values in oracle_outputs]
                for proposal in proposed:
                    check_cancel();args=proposal['args']
                    if descriptor['kind']=='shell':
                        try:answer=io.shell_answer(qid,args)
                        except (ValueError,KeyError):draft['rejected'].append({'reason':'shell input constraints'});continue
                    else:
                        answers=answers_by_input[sha(args)]
                        # Compare with the actual result contract, not loose text equality.
                        if not judging.compare(qid,answers[1],{'args':args,'expected':answers[0]},descriptor['comparison']):
                            draft['rejected'].append({'reason':'independent answer disagreement','args':args,'answers':answers});persist();continue
                        answer=answers[0]
                        has_controller,controlled=io.controller_answer(qid,args)
                        if has_controller and not judging.compare(qid,answer,{'args':args,'expected':controlled},descriptor['comparison']):
                            draft['rejected'].append({'reason':'reviewed controller disagrees with answer programs','args':args,'answers':answers,'controller_answer':controlled});persist();continue
                    proposal['expected']=answer;inputs.append(proposal);draft['accepted']=inputs;persist()
                if len(inputs)>=target:break
            if len(inputs)<target:raise ValueError(f'仅有 {len(inputs)}/{target} 条通过独立执行门禁的补充输入，保留生成代码与断点，未发布')
        cases=deepcopy(descriptor['official'])+inputs+extras
        # Recheck all accepted inputs as one corpus and require complete output.
        gates=[]
        for oracle in draft['oracles']:
            emit('reference_gate',language=oracle['language'])
            gate=judging.execute(qid,oracle['language'],oracle['code'],cases,descriptor['comparison'],check_cancel=check_cancel)
            gates.append({'language':oracle['language'],'verdict':gate})
            if gate['ac_status']!='Accepted':persist();raise ValueError('完整语料独立答案门禁失败，保留旧语料')
        if binding(qid,image,descriptor)!=current_binding:raise ValueError('构建期间题面或判题配置变化，未发布')
        row={'version':VERSION,'qid':qid,'binding':current_binding,'descriptor':descriptor,'cases':cases,
             'cases_sha256':sha(cases),'comparison':descriptor['comparison'],'oracles':draft['oracles'],
             'gates':gates,'gates_passed':True,'generated_count':len(inputs),
             'reference_languages':[o['language'] for o in draft['oracles']],
             'evidence_level':'reviewed_shell_oracle' if descriptor['kind']=='shell' else 'reviewed_sql_controller_and_executed_oracles' if qid in sql_answers.QIDS else 'reviewed_controller_and_executed_oracles' if qid in (142,160,843) else 'executed_oracle_agreement',
             'constraint_evidence':'reviewed_shell_rules' if descriptor['kind']=='shell' else 'reviewed_sql_input_scope' if qid in sql_answers.QIDS else 'reviewed_controller_and_model_validator' if qid in (142,160,843) else 'model_proposed_validator',
             'validator':draft.get('validator'),'leetcode_alignment':'not_measured',
             'limitations':['finite_tests_not_proof','oracle_agreement_can_share_errors','model_proposed_constraints_not_manual_review'] if descriptor['kind']!='shell' else ['finite_tests_not_proof']}
        if extras:row['reviewed_added_case_count']=len(extras)
        if qid in sql_answers.QIDS:
            row['oracle_scope']={'max_rows':sql_answers.MAX_ROWS[qid],'version':sql_answers.VERSION,'description':sql_answers.note(qid)}
            if qid==1211:row['limitations'].append('unreviewed_collation_families_excluded_from_generated_corpus')
            if qid in sql_answers.reviewed8.QIDS:
                row['oracle_scope'].update(sql_answers.reviewed8.scope(qid))
                row['limitations'].remove('model_proposed_constraints_not_manual_review')
        if descriptor.get('statement_revision'):row['statement_revision']=deepcopy(descriptor['statement_revision'])
        if draft.get('reviewed_migration'):
            row['reviewed_migration']=deepcopy(draft['reviewed_migration'])
            retained=set(row['reviewed_migration'].get('retained_model_input_sha256',[]))
            row['reviewed_migration']['new_model_input_sha256_after_resume']=[sha(c['args']) for c in inputs if sha(c['args']) not in retained]
            row['reviewed_migration']['needs_model_input_resume']=len(inputs)<target
            row['reviewed_migration']['completed_model_input_count']=len(inputs)
        if qid in javascript_protocol.QIDS|javascript_async.QIDS:
            row['execution_protocol']={'version':javascript_async.VERSION if qid in javascript_async.QIDS else javascript_protocol.VERSION,
                'callback_scope':'reviewed_declarative_family','clock':'deterministic_timer_order_v1' if qid in javascript_async.QIDS else None}
            row['limitations'].append('arbitrary_callback_families_not_verified')
            if qid in javascript_async.QIDS:row['limitations'].append('virtual_timing_not_leetcode_wall_clock_equivalence')
        row['package_sha256']=sha(row);save(directory/f'{qid}.json',row)
        draft['state']='published';persist();emit('published_generated_tests',generated_count=len(inputs))
        return row
