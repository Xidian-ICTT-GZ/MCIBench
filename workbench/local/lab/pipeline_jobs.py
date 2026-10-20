"""Generate first, translate generated sources, then independently execute locally."""
from copy import deepcopy
import json
import math
import time
from pathlib import Path

from local.common import LANGS
from local.harness import runner
from local.harness.identity import image_digest,judge_source_closure
from local.lab import workflow,problem_packages as packages,portable_judging as judging,problem_io
from local.lab.behavior import sha
from local.lab.diagnostics import redact
from local.lab.generation import generate,DIAGNOSTICS_VERSION,GenerationError
from local.lab.metrics import analyze,cross_language,normalize_value,stable_json
from local.lab.selection import recommend
from local.lab import interface_policy
from local.lab import native_adapters
from local.lab import probes as probe_selector
from local.lab import source_guard
source_guard.register(__file__)

BEHAVIOR_VERSION='code-mue-table-contract-v2'
SOURCE_CONTRACT_REVIEW_VERSION='known-sql-official-word-and-octet-revisions-v4'


class SourceContractReviewError(ValueError):
    code='source_contract_requires_review'
    retryable=False
    suggestion='已有源代码、译文和原始契约均保留；需记录新旧契约的迁移依据并重新验证，不能直接沿用已知有误的公开数据签发判定。'


def review_source_contract(qid,descriptor):
    """Do not reuse known-invalid historical SQL contracts as new answer evidence.

    Other historical formats remain frozen. This is admission only, without
    silently migrating a source interface or rewriting a historical snapshot.
    """
    if qid not in (180,1179,1484,1633,1661,1693,1934,3374,3451):return
    try:
        current,comparison,warnings=problem_io.official(qid)
        if warnings or not current or not descriptor.get('official'):
            raise ValueError('verified public examples unavailable')
        if qid in (1633,1661,1934) and descriptor.get('comparison',{}).get('numeric_profile')!=comparison['numeric_profile']:
            raise ValueError('historical numeric profile requires an explicit reviewed migration')
        if qid==1693 and descriptor.get('comparison',{}).get('date_profile')!=comparison['date_profile']:
            raise ValueError('historical DATE transport requires an explicit reviewed migration')
        if qid in (3374,3451):
            field='text_case_profile' if qid==3374 else 'input_rule_profile'
            if (descriptor.get('comparison',{}).get(field)!=comparison[field]
                    or descriptor.get('statement_revision')!=problem_io.statement_revision(qid)):
                raise ValueError('historical official-rule revision requires an explicit reviewed migration')
        for case in descriptor['official']:
            problem_io.check_database_input(qid,case['args'],current[0]['args'])
            expected=case['expected']
            if qid==180:
                columns=expected.get('columns') if type(expected) is dict else None
                if (type(columns) is not list or len(columns)!=1 or type(columns[0]) is not str or columns[0].casefold()!='consecutivenums'
                        or type(expected.get('rows')) is not list
                        or any(type(row) is not list or len(row)!=1 or row[0] is not None and type(row[0]) is not str
                               for row in expected['rows'])):
                    raise ValueError('q180 ConsecutiveNums must preserve the declared TEXT values')
            elif qid==1179:
                from local.lab.sql_answers import answer
                if not judging.compare(qid,expected,{'args':case['args'],'expected':answer(qid,case['args'])},comparison):
                    raise ValueError('q1179 requires all 13 declared pivot columns, not a public ellipsis')
            elif qid==1484:
                matching=next((row for row in current if row['args']==case['args']),None)
                if not matching or not judging.compare(qid,expected,matching,comparison):
                    raise ValueError('q1484 public product spelling correction requires an explicit reviewed migration')
    except (ValueError,TypeError,KeyError,AttributeError) as error:
        raise SourceContractReviewError(f'q{qid} 历史源契约与已核实的公开规则冲突，需核实后迁移；代码已保留：{error}') from error


def public_verdict(result):
    return {k:result[k] for k in ('state','ac_status','total_testcases','total_correct','runtime','memory',
                                  'version','cases_sha256','correctness_order')}


def partitions(cases,count,*,qid=0,strategy='balanced'):
    # Answer-blind deterministic input ordering, with a reserved validation set.
    unique={sha(c['args']):c for c in cases}
    rows=[deepcopy(unique[k]) for k in sorted(unique)]
    from local.lab import probes as probe_selection
    if len(rows)<=2:
        tags=[probe_selection.features({'args':row['args']},{}) for row in rows]
        all_tags=set().union(*tags)
        metadata={'version':'validated-corpus-probes-v1','strategy':strategy,'requested_probe_count':count,
            'actual_probe_count':len(rows),'unique_legal_input_count':len(rows),'validation_count':0,
            'features_available':len(all_tags),'features_covered':len(all_tags),
            'warnings':['语料不足三个不同输入，未分离验证集；完整复判仍执行全部语料'],
            'answers_used_for_selection':False,'selected':[{'input_sha256':sha(row['args']),'features':sorted(features),'new_features':[]} for row,features in zip(rows,tags)]}
        return rows,[],metadata
    selected,validation,metadata=probe_selection.select(qid,rows,count,strategy=strategy,prevalidated=True)
    metadata['input_admission']='package_constraint_gate'
    by_input={sha(row['args']):row for row in rows}
    return [by_input[sha(row['args'])] for row in selected],validation,metadata


def semantic(qid,case,value,comparison):
    mode=comparison.get('mode','ordered')
    validity=judging.result_semantics.valid(qid,value,case['args'])
    if validity is True:return stable_json({'valid_spec_result':True})
    mode=judging.result_semantics.mode(qid,mode)
    if qid==1 and judging.compare(qid,value,case,comparison):return stable_json({'valid_two_sum':True})
    if mode=='table':
        v=deepcopy(value)
        if type(v) is dict:
            columns=v.get('columns')
            if type(columns) is list and all(type(c) is str for c in columns):
                v['columns']=['__scalar_return__'] if qid==177 and comparison.get('scalar_function_return') is True and len(columns)==1 else [c.casefold() for c in columns]
            if type(v.get('rows')) is list:
                # Match SQL/JSON grading: integral floats and integers are equal,
                # while numeric TEXT, booleans, NULL and dtype metadata differ.
                for row in v['rows']:
                    if type(row) is list:
                        for i,cell in enumerate(row):
                            if type(cell) is float and math.isfinite(cell) and cell.is_integer():row[i]=int(cell)
                if comparison.get('unordered_rows'):v['rows'].sort(key=stable_json)
        return stable_json(v)
    if mode=='word_frequency' and type(value) is str:
        return stable_json(sorted(value.splitlines()))
    return stable_json(normalize_value(value,mode=mode if mode in ('ordered','rows_unordered','all_unordered') else 'ordered'))


def execute(qid,language,code,cases,comparison,plan=None,**kwargs):
    if plan:return native_adapters.execute(qid,language,code,cases,comparison,plan,**kwargs)
    kwargs.pop('full',None)
    return judging.execute(qid,language,code,cases,comparison,**kwargs)


def observe(qid,language,code,cases,comparison,check_cancel,plan=None):
    if not cases:return []
    result=execute(qid,language,code,cases,comparison,plan,collect=True,check_cancel=check_cancel)
    outcomes=[]
    for i,case in enumerate(cases):
        if i<len(result['outputs']):
            value=result['outputs'][i]
            outcomes.append({'kind':'value','value':value,'semantic_key':semantic(qid,case,value,comparison),
                             'status':'Collected','runtime_ms':None,'memory_mb':None})
        else:
            status=result['ac_status']
            outcomes.append({'kind':'compile_error' if status=='Compile Error' else 'timeout' if status=='Time Limit Exceeded' else 'failure',
                             'status':status,'runtime_ms':None,'memory_mb':None})
    return outcomes


def run(engine,ident,event):
    from local.lab.jobs import Cancelled
    started=time.perf_counter()
    result={'groups':[],'cross_language':[],'source_generations':[],'inputs':[],
            'workflow_version':workflow.VERSION,'behavior_semantics_version':BEHAVIOR_VERSION,'leetcode_verdict':None,
            'notice':'本地判定基于冻结测试和独立答案执行；不保证 LeetCode 隐藏测试通过。',
            'failures':[],'timing':{'max_sandbox_concurrency':1,'phases_ms':{'prepare_ms':0.,'generation_ms':0.,'probe_ms':0.,'metamorphic_ms':0.,'validation_ms':0.,'full_corpus_ms':0.}},
            'testcase_workflow':{'state':'running','target_per_question':0,'events':[],'questions':[]}}
    phase='prepare';context={};profiles={};progress=[0,0];candidate_total=1
    def check_cancel():
        if event.is_set():raise Cancelled()
    def write(stage=None,state=None):
        check_cancel()
        fields={'result':result,'progress':min(99,int(sum(progress)/(2*candidate_total)*100))}
        if stage is not None:fields['stage']=stage
        if state is not None:fields['state']=state
        engine.store.write_job(ident,**fields)
    def failure(error,where,ctx):
        message=redact(str(error),[p.get('api_key','') for p in profiles.values()])[:1000]
        row={'phase':where,'context':deepcopy(ctx),'code':getattr(error,'code','execution_incomplete'),
             'message':message,'suggestion':getattr(error,'suggestion','已有代码和断点保留；核对失败阶段后可复制任务重试。'),
             'retryable':getattr(error,'retryable',False),'attempt_count':len(getattr(error,'attempts',[]))}
        result['failures'].append(row);result.setdefault('failure',row)
        return row
    def sample(profile,prompt,candidate,stage):
        nonlocal phase
        phase='generation';check_cancel();write(stage,'generating')
        candidate['generation']={'version':DIAGNOSTICS_VERSION,'attempts':[]}
        def attempt(record):candidate['generation']['attempts'].append(record);write(stage)
        def report(record):candidate['generation']['in_flight']=record;write(stage)
        t0=time.perf_counter()
        try:
            response=generate(profile,prompt,spec['temperature'],on_attempt=attempt,on_progress=report,check_cancel=check_cancel)
            candidate.update(response,code_sha256=sha(response['code']),prompt_sha256=sha(prompt),generation_state='succeeded')
            if response.get('finish_reason')!='stop':
                candidate['generation_state']='incomplete'
                raise ValueError('模型输出未完整结束，保留代码但不能用于后续翻译或完整判定')
        except Cancelled:
            candidate['generation_state']='cancelled';raise
        except Exception as error:
            candidate.setdefault('generation_state','failed')
            if candidate['generation_state']=='generating':candidate['generation_state']='failed'
            candidate['generation_failure']=failure(error,'generation',context)
            if isinstance(error,GenerationError):candidate['generation']['attempts']=error.attempts
        finally:
            candidate['generation'].pop('in_flight',None)
            elapsed=(time.perf_counter()-t0)*1000
            candidate['timing']={'generation_ms':elapsed,'probe_ms':0.,'metamorphic_ms':0.,'validation_ms':0.,'full_corpus_ms':0.}
            result['timing']['phases_ms']['generation_ms']+=elapsed
            write(stage)
        return candidate.get('generation_state')=='succeeded'
    def new_candidate(qid,model,language,index):
        return {'id':f'{qid}-{model}-{language}-{index}','index':index if type(index) is int else 1,
                'code':'','raw':'','code_sha256':'','outcomes':[],'verdict':None,'generation_state':'generating'}
    try:
        source_guard.check()
        job=engine.store.job(ident);spec=job['spec']
        profiles={i:engine.store.profile(i,private=True) for i in spec['model_ids']}
        candidate_total=len(spec['qids'])*len(profiles)*len(spec['languages'])*spec['num_candidates']
        result['manifest']={'workflow_version':workflow.VERSION,'spec':spec,
                            'behavior_semantics_version':BEHAVIOR_VERSION,
                            'source_contract_review_version':SOURCE_CONTRACT_REVIEW_VERSION,
                            'models':[{k:v for k,v in p.items() if k!='api_key'} for p in profiles.values()],
                            'judge_closure':dict(judge_source_closure()),'correctness_version':judging.VERSION,
                            'pipeline_sha256':sha(Path(__file__).read_text(encoding='utf-8')),
                            'package_builder_sha256':sha(Path(packages.__file__).read_text(encoding='utf-8')),
                            'driver_sha256':sha(Path(packages.drivers.__file__).read_text(encoding='utf-8')),
                            'checker_sha256':sha(Path(judging.__file__).read_text(encoding='utf-8'))}
        result['manifest']['semantics_sha256']=sha(Path(judging.result_semantics.__file__).read_text(encoding='utf-8'))
        result['manifest']['probe_selector_sha256']=sha(Path(probe_selector.__file__).read_text(encoding='utf8'))
        result['manifest']['workflow_sha256']=sha(Path(workflow.__file__).read_text(encoding='utf8'))
        result['testcase_workflow']['target_per_question']=spec['testcase_count'] if spec['auto_testcases'] else 0
        for qid in spec['qids']:
            check_cancel();context={'qid':qid};phase='input_contract'
            first_profile=profiles[spec['model_ids'][0]]
            descriptor_error=None
            try:
                frozen_contract=spec.get('source_snapshots',{}).get(str(qid),{}).get('input_contract') if spec['task']=='trans' and spec['source_mode']=='candidate' else None
                descriptor=(workflow.checked_contract(frozen_contract,qid)['descriptor'] if frozen_contract else
                    packages.describe(qid,first_profile,check_cancel=check_cancel,on_attempt=lambda record:write(f'q{qid} 序列化契约响应')))
            except Cancelled:raise
            except Exception as error:
                descriptor_error=error
                # A failed judging contract must not erase the useful generated
                # code. No verdict can be issued with this provisional schema.
                descriptor={'qid':qid,'kind':problem_io.kind(qid),'official':[],
                    'comparison':{'mode':'ordered'},'warnings':['unverified_serialization'],
                    'interface_note':'Public serialization could not be verified. For a missing native template, infer a JSON input object and output from the statement and document the inferred fields. The code will remain ungraded until the contract is verified.'}
            input_contract=workflow.contract_snapshot(qid,descriptor) if descriptor_error is None else None
            # Finish generation/translation even if test preparation later fails.
            question_groups=[]
            for model_id,profile in profiles.items():
                source=None
                if spec['task']=='trans':
                    if spec['source_mode']=='candidate':source=deepcopy(spec['source_snapshots'][str(qid)])
                    else:
                        source_candidate=new_candidate(qid,model_id,spec['source_language'],'source')
                        source_interface=packages.code_interface(qid,spec['source_language'])
                        stage={'qid':qid,'language':spec['source_language'],'model_id':model_id,
                               'model_name':profile['name'],'interface':source_interface,'input_contract':input_contract,'candidate':source_candidate}
                        result['source_generations'].append(stage)
                        context={'qid':qid,'model_name':profile['name'],'language':spec['source_language'],'candidate_index':1}
                        good=sample(profile,packages.prompt_for(qid,spec['source_language'],descriptor,interface=source_interface),source_candidate,f'q{qid}：先生成翻译源代码')
                        if good:source=workflow.source_snapshot(job,stage,source_candidate)
                        else:
                            progress[0]+=len(spec['languages'])*spec['num_candidates'];write(f'q{qid} 源代码生成未完成，未调用翻译')
                            continue
                for language in spec['languages']:
                    group={'qid':qid,'model_id':model_id,'model_name':profile['name'],'language':language,
                           'behavior_semantics_version':BEHAVIOR_VERSION,
                           'interface':packages.code_interface(qid,language),'input_contract':input_contract,'candidates':[],'metrics':None,
                           'validation_count':0,'corpus_count':0,'probe_count':0,
                           'correctness_evidence':{'state':'not_audited','profile_version':judging.VERSION,'case_count':0,'cases_sha256':''},
                           'corpus_evidence':{'scope':'all_catalog','evidence_level':'preparing','notice':'正在准备独立本地判题证据。'}}
                    if source:
                        group.update(source_language=source['language'],source_code=source['code'],source_sha256=source['code_sha256'],source_snapshot=source)
                    result['groups'].append(group);question_groups.append(group)
                    prompt=packages.prompt_for(qid,language,descriptor,source=source,interface=group['interface']);group['prompt']=prompt
                    for index in range(1,spec['num_candidates']+1):
                        context={'qid':qid,'model_name':profile['name'],'language':language,'candidate_index':index}
                        c=new_candidate(qid,model_id,language,index);group['candidates'].append(c)
                        sample(profile,prompt,c,f'q{qid} / {profile["name"]} / {problem_io.LANGUAGES[language]}：生成候选 {index}/{spec["num_candidates"]}')
                        progress[0]+=1
            if not question_groups:continue
            try:
                phase='testcase_generation';context={'qid':qid}
                write(f'q{qid}：构建独立判题语料','evaluating')
                if descriptor_error is not None:raise ValueError('公开示例契约未核实，已有生成代码保留：'+str(descriptor_error))
                workflow.checked_contract(input_contract,qid)
                if frozen_contract:
                    phase='source_contract_review'
                    review_source_contract(qid,descriptor)
                phase='testcase_generation'
                image=engine.image or image_digest();engine.image=image;runner.DOCKER_IMAGE=image
                result['manifest']['image']=image
                def testcase_event(update):
                    result['testcase_workflow']['events'].append(update)
                    write(f'q{qid} 自动补充测试：{update["stage"]}')
                package=packages.build(qid,descriptor,first_profile,spec['testcase_count'],image,
                                       auto=spec['auto_testcases'],check_cancel=check_cancel,on_event=testcase_event)
                cases=package['cases'];comparison=package['comparison']
                probes,validation,probe_metadata=partitions(cases,spec['probe_count'],qid=qid,strategy=spec['probe_strategy'])
                snapshot={'qid':qid,'full_corpus':deepcopy(cases),'probes':[{'args':c['args']} for c in probes],
                          'probe_sha256':sha([c['args'] for c in probes]),'validation':deepcopy(validation),
                          'validation_count':len(validation),'validation_sha256':sha(validation),
                          'package_sha256':package.get('package_sha256'),'comparison':comparison,'input_contract':input_contract,
                          'selection':probe_metadata,
                          'answer_evidence':{k:package.get(k) for k in ('evidence_level','constraint_evidence','reference_languages','oracle_scope','limitations','execution_protocol','statement_revision')}}
                result['inputs'].append(snapshot)
                result['testcase_workflow']['questions'].append({'qid':qid,'state':'verified','generated_count':package['generated_count'],
                      'evidence_level':package['evidence_level'],'leetcode_alignment':'not_measured'})
            except Cancelled:raise
            except Exception as error:
                failure(error,phase,context)
                for g in question_groups:g['judging_state']='incomplete';g['judging_error']=result['failures'][-1]['message'];g['metrics']=analyze(g['candidates'])
                write(f'q{qid}：代码已保留，本地判题未完成');continue
            for group in question_groups:
                language=group['language']
                native_plan=None
                if language=='mysql' or group.get('source_language')=='mysql':
                    try:
                        from local.lab import mysql_packages
                        phase='mysql_reference_gate';write(f'q{qid}：原生 MySQL 参考门禁')
                        mysql_gate=mysql_packages.prepare(qid,descriptor,package,first_profile,check_cancel=check_cancel,on_event=testcase_event)
                        result['manifest']['mysql_environment']=mysql_gate['binding']['runtime']
                        if language=='mysql':group['sql_evidence']=mysql_packages.summary(mysql_gate)
                        if group.get('source_language')=='mysql':group['source_sql_evidence']=mysql_packages.summary(mysql_gate)
                    except Cancelled:raise
                    except Exception as error:
                        group['judging_state']='incomplete';group['judging_error']=failure(error,phase,{'qid':qid,'language':'mysql'})['message'];group['metrics']=analyze(group['candidates']);write();continue
                try:
                    # One place decides the entry. A missing interface is re-derived
                    # from the package and recorded; an unknown one blocks instead of
                    # silently falling through to the portable driver.
                    iface,iface_origin=interface_policy.resolve(group,derive=lambda:packages.code_interface(qid,language))
                except interface_policy.UnknownInterface as error:
                    phase='interface'
                    group['judging_state']='incomplete';group['judging_error']=failure(error,phase,{'qid':qid,'language':language})['message'];group['metrics']=analyze(group['candidates']);write();continue
                group['interface']=iface
                group['interface_origin']=iface_origin
                if interface_policy.route(iface)==interface_policy.NATIVE_ROUTE:
                    try:
                        phase='native_adapter';write(f'q{qid} / {problem_io.LANGUAGES[language]}：原生接口门禁')
                        native_plan=native_adapters.prepare(qid,language,descriptor,package,first_profile,image,check_cancel=check_cancel,on_event=testcase_event)
                        group['native_adapter']={k:v for k,v in native_plan.items() if k not in ('reference_code','attempts')}
                    except Cancelled:raise
                    except Exception as error:
                        group['judging_state']='incomplete';group['judging_error']=failure(error,phase,{'qid':qid,'language':language})['message'];group['metrics']=analyze(group['candidates']);write();continue
                group.update(corpus_count=len(cases),validation_count=len(validation),probe_count=len(probes),probe_selection=probe_metadata,
                             corpus_evidence={'scope':'all_catalog','evidence_level':package['evidence_level'],
                                'notice':'本地执行使用独立答案与冻结语料；未审查题目的约束程序和答案交叉检查仍可能存在共同错误。'},
                             answer_evidence=snapshot['answer_evidence'])
                group['correctness_evidence'].update(case_count=len(cases),cases_sha256=sha(cases))
                source_outcomes=None
                if group.get('source_snapshot'):
                    source=group['source_snapshot']
                    if source['interface'] in (packages.drivers.VERSION,'mysql','sqlite','bash'):
                        try:source_outcomes=observe(qid,source['language'],source['code'],probes,comparison,check_cancel)
                        except Cancelled:raise
                        except Exception as error:group['source_probe_failure']=str(error)[:300]
                    else:
                        # Old generated sources retain their original LeetCode call interface.
                        try:
                            source_plan=native_adapters.prepare(qid,source['language'],descriptor,package,first_profile,image,check_cancel=check_cancel,on_event=testcase_event)
                            source_outcomes=observe(qid,source['language'],source['code'],probes,comparison,check_cancel,source_plan)
                        except Cancelled:raise
                        except Exception as error:group['source_probe_failure']=str(error)[:300]
                    group['source_outcomes']=source_outcomes
                for c in group['candidates']:
                    if c['generation_state']!='succeeded':continue
                    context={'qid':qid,'model_name':group['model_name'],'language':language,'candidate_index':c['index']}
                    try:
                        phase='probe';write(f'q{qid} / {problem_io.LANGUAGES[language]}：行为探测','evaluating');t0=time.perf_counter()
                        c['outcomes']=observe(qid,language,c['code'],probes,comparison,check_cancel,native_plan)
                        c['timing']['probe_ms']=(time.perf_counter()-t0)*1000
                        phase='validation';t0=time.perf_counter()
                        if validation:
                            v=execute(qid,language,c['code'],validation,comparison,native_plan,check_cancel=check_cancel)
                            c['verdict']=public_verdict(v);c['validation_passed']=v['state']=='SUCCESS' and v['ac_status']=='Accepted'
                        c['timing']['validation_ms']=(time.perf_counter()-t0)*1000
                        c['probe_verdict']=public_verdict(execute(qid,language,c['code'],probes,comparison,native_plan,check_cancel=check_cancel))
                        c['metamorphic']=[]
                        if spec['metamorphic_checks'] and qid in __import__('local.lab.input_contracts',fromlist=['QIDS']).QIDS:
                            from local.lab.metamorphic import proposals,evaluate
                            for relation in proposals(qid,[{'args':x['args']} for x in probes]):
                                phase='metamorphic';transformed=observe(qid,language,c['code'],[{'args':relation['input']['args'],'expected':None}],comparison,check_cancel,native_plan)[0]
                                c['metamorphic'].append(evaluate(relation,c['outcomes'][relation['base_probe_index']],transformed))
                        phase='full_corpus';t0=time.perf_counter();write(f'q{qid} / {problem_io.LANGUAGES[language]}：完整语料独立复判')
                        full=execute(qid,language,c['code'],deepcopy(cases),comparison,native_plan,check_cancel=check_cancel,full=True)
                        group['correctness_evidence']['profile_version']=full['version']
                        if full['version']=='full-corpus-executed-v2':
                            from local.lab.correctness_audit import evidence as audited_evidence
                            group['correctness_evidence']=audited_evidence(qid,cases,image)
                        c['corpus_verdict']=public_verdict(full);c['full_execution_evidence']=full['_meta']
                        c['corpus_passed']=full['state']=='SUCCESS' and full['ac_status']=='Accepted';c['judging_state']='completed'
                        c['timing']['full_corpus_ms']=(time.perf_counter()-t0)*1000
                        if source_outcomes and len(source_outcomes)==len(c['outcomes']):
                            # Compare normalized observable values across the two interfaces.
                            c['translation_preservation']=sum(a['kind']==b['kind']=='value' and semantic(qid,probe,a['value'],comparison)==semantic(qid,probe,b['value'],comparison)
                                for probe,a,b in zip(probes,source_outcomes,c['outcomes']))/len(probes)
                        for key in ('probe_ms','validation_ms','full_corpus_ms'):result['timing']['phases_ms'][key]+=c['timing'][key]
                        progress[1]+=1;write()
                    except Cancelled:raise
                    except Exception as error:c['judging_state']='incomplete';c['judging_failure']=failure(error,phase,context);write()
                group['metrics']=analyze(group['candidates'])
                complete=[c for c in group['candidates'] if c.get('judging_state')=='completed']
                group['judging_state']='completed' if len(complete)==spec['num_candidates'] else 'incomplete'
                group['local_pass_rate']=sum(c.get('corpus_passed',False) for c in complete)/len(complete) if len(complete)==spec['num_candidates'] else None
                group['validation_pass_rate']=sum(c.get('validation_passed',False) for c in complete)/len(complete) if validation and len(complete)==spec['num_candidates'] else None
                group['selection_advice']=recommend(group,expected_count=spec['num_candidates']);group['selection_advice']['provenance']='frozen_at_run'
                write()
        result['cross_language']=cross_language(result['groups'])
        result['testcase_workflow']['state']=('failed' if any(f['phase'] in ('testcase_generation','input_contract','source_contract_review') for f in result['failures'])
                                             else 'completed' if len(result['testcase_workflow']['questions'])==len(spec['qids']) else 'incomplete')
        result['timing']['wall_ms']=(time.perf_counter()-started)*1000
        check_cancel()
        engine.store.write_job(ident,state='failed' if result['failures'] else 'completed',stage='部分流程未完成，已保留生成代码与证据' if result['failures'] else '评测完成',
                               error=result['failures'][0]['message'] if result['failures'] else '',result=result,progress=min(100,int(sum(progress)/(2*candidate_total)*100)))
    except Cancelled:
        result['testcase_workflow']['state']='cancelled'
        engine.store.write_job(ident,state='cancelled',stage='已取消，保留已完成结果',result=result)
    except Exception as error:
        failure(error,phase,context)
        engine.store.write_job(ident,state='failed',stage='任务失败，已保留生成代码与证据',error=result['failures'][-1]['message'],result=result)
    finally:
        with engine.lock:engine.events.pop(ident,None)
