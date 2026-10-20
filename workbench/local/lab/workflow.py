"""All-catalog generation and explicit, frozen generated-source translation."""
from copy import deepcopy
import json
import math
from pathlib import Path
from functools import lru_cache

from local.common import LANGS, DESCRIPTIONS_DIR, load_snippet
from local.lab.behavior import sha
from local.lab.generation import prompt_for
from local.lab.storage import LabError
from local.lab import problem_io
from local.lab import source_guard
source_guard.register(__file__)

VERSION = 'generate-translate-local-v1'
INDEX = Path(__file__).with_name('data')/'problem_index.json'


@lru_cache(maxsize=2)
def _index(stamp):
    return {r['qid']:r for r in json.loads(INDEX.read_text(encoding='utf-8'))}


def problem(qid):
    if type(qid) is not int or qid <= 0:
        raise LabError('题号无效')
    item=_index(INDEX.stat().st_mtime_ns).get(qid)
    if item is None:
        raise LabError(f'q{qid} 不在当前题库中')
    return item


def contract_snapshot(qid,descriptor,*,description=None,provenance='frozen_at_generation'):
    row={'version':'source-io-contract-v1','qid':qid,
         'description_sha256':sha(description if description is not None else problem_io.description(qid)),
         'descriptor':deepcopy(descriptor),'provenance':provenance}
    row['sha256']=sha(row)
    return row


def checked_contract(row,qid):
    row=deepcopy(row);digest=row.pop('sha256',None)
    if digest!=sha(row) or row.get('version')!='source-io-contract-v1' or row.get('qid')!=qid or row.get('descriptor',{}).get('qid')!=qid:
        raise LabError('源代码的输入输出契约指纹无效')
    if row.get('description_sha256')!=sha(problem_io.description(qid)):
        raise LabError('源代码对应的题面已改变，请重新生成源代码后翻译')
    row['sha256']=digest
    return row


def source_contract(job,group,candidate):
    if group.get('input_contract'):return checked_contract(group['input_contract'],group['qid'])
    # Older portable jobs saved the exact public contract in their generation
    # prompt. Recover that contract rather than silently switching array/table
    # or node-identity formats after a parser update.
    prompts=[group.get('prompt','')]
    prompts += [g.get('prompt','') for g in job.get('result',{}).get('groups',[])
                if g.get('qid')==group['qid'] and g.get('source_sha256')==candidate.get('code_sha256')]
    marker='\nPublic serialized examples:\n'
    for prompt in prompts:
        if marker not in prompt or '\nProblem:\n' not in prompt:continue
        try:
            cases,_=json.JSONDecoder().raw_decode(prompt.split(marker,1)[1])
            text=prompt.split('\nProblem:\n',1)[1].split('\nSource language:',1)[0]
            if text!=problem_io.description(group['qid']):raise LabError('源代码对应的题面已改变，请重新生成后翻译')
            frozen=next((row for row in job.get('result',{}).get('inputs',[]) if row.get('qid')==group['qid']),{})
            descriptor={'qid':group['qid'],'kind':problem_io.kind(group['qid']),'official':cases,
                'comparison':deepcopy(frozen.get('comparison',{'mode':'ordered'})),
                'interface_note':'Use EXACTLY the public input/output shape below. This contract was recovered from the original frozen generation prompt; do not replace it with a newer serializer.',
                'warnings':['contract_recovered_from_frozen_prompt']}
            return contract_snapshot(group['qid'],descriptor,description=text,provenance='recovered_from_frozen_prompt')
        except (ValueError,TypeError,KeyError):continue
    return None


def source_snapshot(job, group, candidate):
    code=candidate.get('code')
    if (candidate.get('generation_state','succeeded')!='succeeded' or candidate.get('finish_reason')=='length'
            or not isinstance(code,str) or not code.strip() or sha(code)!=candidate.get('code_sha256')):
        raise LabError('源代码未完整生成或源码指纹不匹配')
    row={'job_id':job['id'],'job_title':job['title'],'candidate_id':candidate['id'],
         'candidate_index':candidate['index'],'qid':group['qid'],'language':group['language'],
         'model_id':group['model_id'],'model_name':group['model_name'],
         'code':code,'code_sha256':sha(code),'origin':'saved_candidate',
         'interface':group.get('interface','legacy_leetcode_method')}
    contract=source_contract(job,group,candidate)
    if contract:row['input_contract']=contract
    else:row['contract_binding']='legacy_unbound'
    row['snapshot_sha256']=sha(row)
    return row


def check_snapshot(row,qid,language):
    row=deepcopy(row)
    digest=row.pop('snapshot_sha256',None)
    if (digest!=sha(row) or row.get('qid')!=qid or row.get('language')!=language
            or not row.get('code') or sha(row['code'])!=row.get('code_sha256')):
        raise LabError('翻译源代码快照无效或不匹配题目与源语言')
    if row.get('input_contract'):checked_contract(row['input_contract'],qid)
    row['snapshot_sha256']=digest
    return row


def upgrade_snapshot(store,row,qid,language):
    """Enrich only an already trusted frozen source; never expose deleted jobs.

    Clones of older tasks may hold a source snapshot made before contracts were
    introduced. The source job can be soft-deleted, but its original generation
    prompt remains sufficient to recover the matching code's contract.
    """
    row=check_snapshot(row,qid,language)
    if row.get('input_contract'):return row
    with store.connect() as con:
        original=con.execute('SELECT * FROM jobs WHERE id=?',(row['job_id'],)).fetchone()
    if original is None:return row
    job=store.job_row(original)
    groups=list(job.get('result',{}).get('groups',[]))
    groups += [{**stage,'candidates':[stage['candidate']]} for stage in job.get('result',{}).get('source_generations',[]) if stage.get('candidate')]
    for group in groups:
        if group.get('qid')!=qid or group.get('language')!=language:continue
        for candidate in group.get('candidates',[]):
            if candidate.get('id')!=row['candidate_id'] or candidate.get('code_sha256')!=row['code_sha256'] or sha(candidate.get('code',''))!=row['code_sha256']:continue
            contract=source_contract(job,group,candidate)
            if contract:
                previous=row.pop('snapshot_sha256');row.pop('contract_binding',None)
                row.update(input_contract=contract,legacy_snapshot_sha256=previous)
                row['snapshot_sha256']=sha(row)
                return row
    return row


def resolve_source(store,choice,qid,language):
    if type(choice) is not dict or set(choice)!={'job_id','candidate_id'}:
        raise LabError('请选择已生成的源代码候选')
    if any(not isinstance(v,str) or not 1<=len(v)<=100 for v in choice.values()):
        raise LabError('源任务或候选编号无效')
    job=store.job(choice['job_id'])
    for group in job.get('result',{}).get('groups',[]):
        if group['qid']!=qid or group['language']!=language:
            continue
        for candidate in group.get('candidates',[]):
            if candidate['id']==choice['candidate_id']:
                return source_snapshot(job,group,candidate)
    # Source-generation stages of chained translations are also reusable.
    for stage in job.get('result',{}).get('source_generations',[]):
        if stage['qid']==qid and stage['language']==language and stage.get('candidate',{}).get('id')==choice['candidate_id']:
            return source_snapshot(job,stage,stage['candidate'])
    raise LabError('未找到与题目和源语言匹配的已生成候选')


def sources(store,qid,language=None):
    problem(qid)
    if language is not None and language not in problem_io.LANGUAGES:
        raise LabError('源语言无效')
    with store.connect() as con:
        rows=con.execute("""SELECT * FROM jobs WHERE deleted=0 AND
            EXISTS (SELECT 1 FROM json_each(jobs.spec,'$.qids') WHERE value=?)
            ORDER BY created_at DESC LIMIT 100""",(qid,)).fetchall()
    output=[]
    for raw in rows:
        job=store.job_row(raw)
        groups=list(job.get('result',{}).get('groups',[]))
        groups += [{**s,'candidates':[s['candidate']]} for s in job.get('result',{}).get('source_generations',[]) if s.get('candidate')]
        for group in groups:
            if group['qid']!=qid or language and group['language']!=language:
                continue
            for candidate in group.get('candidates',[]):
                try:
                    snapshot=source_snapshot(job,group,candidate)
                    item={k:v for k,v in snapshot.items() if k not in ('code','input_contract')}
                    if snapshot.get('input_contract'):item['contract_sha256']=snapshot['input_contract']['sha256']
                    output.append(item)
                except LabError:
                    continue
    return output


def validate(payload,store,*,trusted_snapshots=False):
    spec={'workflow_version':VERSION}
    for field,maximum,typ in (('qids',10,int),('model_ids',5,str),('languages',10,str)):
        values=payload.get(field)
        if (type(values) is not list or not 1<=len(values)<=maximum
                or any(type(v) is not typ for v in values) or len(set(values))!=len(values)):
            raise LabError(f'{field} 请选择 1–{maximum} 个不同的有效项')
        spec[field]=deepcopy(values)
    spec.update(task=payload.get('task','gen'),source_language=payload.get('source_language','python3'),
                num_candidates=payload.get('num_candidates',5),probe_count=payload.get('probe_count',8),
                temperature=payload.get('temperature',.7),probe_strategy=payload.get('probe_strategy','balanced'),
                metamorphic_checks=payload.get('metamorphic_checks',True),
                auto_testcases=payload.get('auto_testcases',True),testcase_count=payload.get('testcase_count',30))
    if spec['task'] not in ('gen','trans') or spec['source_language'] not in problem_io.LANGUAGES or any(l not in problem_io.LANGUAGES for l in spec['languages']):
        raise LabError('任务类型或语言无效')
    if spec['task']=='trans' and spec['source_language'] in spec['languages']:
        raise LabError('转译的目标语言不能包含源语言')
    for key,lo,hi in (('num_candidates',1,25),('probe_count',2,20),('testcase_count',12,100)):
        if type(spec[key]) is not int or not lo<=spec[key]<=hi:
            raise LabError(f'{key} 必须在 {lo}–{hi} 之间')
    if type(spec['temperature']) not in (int,float) or not math.isfinite(spec['temperature']) or not 0<spec['temperature']<=2:
        raise LabError('随机采样温度必须大于 0 且不超过 2')
    if spec['probe_strategy'] not in ('balanced','hash') or any(type(spec[k]) is not bool for k in ('metamorphic_checks','auto_testcases')):
        raise LabError('探测策略或测试开关无效')
    if len(spec['qids'])*len(spec['model_ids'])*len(spec['languages'])*spec['num_candidates']>200:
        raise LabError('单任务目标代码上限为 200，请减少选择或拆分任务')
    for ident in spec['model_ids']:
        if not store.profile(ident)['enabled']:
            raise LabError('所选模型已禁用')
    for qid in spec['qids']:
        problem(qid)
        for language in spec['languages']+([spec['source_language']] if spec['task']=='trans' else []):
            if language not in problem_io.languages(qid):raise LabError(f'q{qid} 与所选执行语言不匹配')
            try:problem_io.description(qid)
            except (OSError,ValueError,KeyError) as error:raise LabError(f'q{qid} 题面缺失：{error}') from None
    if spec['task']=='trans':
        mode=payload.get('source_mode','generate')
        if mode not in ('generate','candidate'):
            raise LabError('翻译来源必须为先生成或已生成候选')
        spec['source_mode']=mode
        if mode=='candidate':
            selections=payload.get('source_candidates',{})
            frozen=payload.get('source_snapshots',{}) if trusted_snapshots else {}
            spec['source_candidates'],spec['source_snapshots']={},{}
            for qid in spec['qids']:
                key=str(qid)
                snapshot=(upgrade_snapshot(store,frozen[key],qid,spec['source_language']) if key in frozen
                          else resolve_source(store,selections.get(key),qid,spec['source_language']))
                spec['source_snapshots'][key]=snapshot
                spec['source_candidates'][key]={k:snapshot[k] for k in ('job_id','candidate_id')}
    return spec


def validate_update(payload,store,ident):
    """Only reuse server-owned snapshots when an existing selection is unchanged."""
    incoming=deepcopy(payload);incoming.pop('source_snapshots',None)
    old=store.job(ident)['spec'];frozen={}
    if (old.get('workflow_version')==VERSION and old.get('source_language')==incoming.get('source_language')
            and incoming.get('task')=='trans' and incoming.get('source_mode')=='candidate'):
        for qid in incoming.get('qids',[]):
            key=str(qid)
            if (old.get('source_candidates',{}).get(key)==incoming.get('source_candidates',{}).get(key)
                    and key in old.get('source_snapshots',{})):
                frozen[key]=old['source_snapshots'][key]
    incoming['source_snapshots']=frozen
    return validate(incoming,store,trusted_snapshots=True)
