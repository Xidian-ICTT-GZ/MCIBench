"""Prospective verification-aware selection study, with a separate final audit set."""
from __future__ import annotations
import argparse
from copy import deepcopy
import json
from pathlib import Path
import platform
import tempfile
import time

from local.common import KEY_TO_LABEL
from local.harness import runner
from local.harness.identity import image_digest, judge_source_closure
from local.judge import load_cases, judge_one
from local.lab.behavior import partition_cases, sha
from local.lab.probes import inputs, digest
from local.lab.selection import VERSION
from local.lab.study_inputs import QIDS, cases_for
from local.tools.code_mue_study import PILOT_QIDS, gates, check_dataset, request
from local.tools.gap_workflow import save
from local.tools.study_metrics import clustered_interval

ROOT=Path(__file__).resolve().parents[2]
POLICY=ROOT/'local/lab/selection.py'
TOPICS=tuple(q for q in QIDS if q not in PILOT_QIDS)


def freeze(folder):
    if (folder/'dataset.json').exists():raise ValueError('protocol already frozen; no overwrite')
    rows=[]
    for qid in TOPICS:
        corpus=load_cases(qid)
        probes,screening,selection=partition_cases(qid,corpus,8,return_metadata=True)
        # Exclude every corpus input, including the screening inputs used to select.
        audit=cases_for(qid,20261015,[inputs(c) for c in corpus])
        if {digest(inputs(c)) for c in audit}&{digest(inputs(c)) for c in corpus}:
            raise ValueError('audit input leaks into probes or selection screening')
        rows.append({'qid':qid,'split':'prospective','probes':probes,'probe_sha256':sha(probes),
                     'selection':selection,'screening':screening,'screening_sha256':sha(screening),
                     'validation':audit,'validation_sha256':sha(audit),'corpus_sha256':sha(corpus)})
    model=next(m for m in request('models')['data'] if m['id']=='99f2deec8d144833836ca4cd35394438')
    save(folder/'dataset.json',{'version':1,'frozen_at':time.time(),'host_python':platform.python_version(),
          'image':image_digest(),'judge_closure':dict(judge_source_closure()),
          'oracle_sha256':sha((ROOT/'local/lab/study_inputs.py').read_text(encoding='utf-8')),
          'selection_policy_sha256':sha(POLICY.read_text(encoding='utf-8')),'selection_policy_version':VERSION,
          'scope':'ten existing FT topics unused in first pilot; audit inputs disjoint from all local corpus inputs',
          'protocol':{'model':model,'languages':['python3','javascript'],'n':5,'k':8,'temperature':.7,
                      'input_roles':{'A':'input-only behavior probes','B':'selection screening with known answers','C':'final independent oracle audit, never used for selection'},
                      'baselines':['original_behavior_center','first_screened_candidate','uniform_random_candidate'],
                      'primary':'all_groups_correct_selection_fraction_and_coverage','bootstrap_question_clusters':1000},
          'rows':rows})
    print('frozen',len(rows),'topics',sum(len(r['validation']) for r in rows),'audit inputs',flush=True)


def check(folder):
    dataset=json.loads((folder/'dataset.json').read_bytes())
    check_dataset(dataset)
    if dataset['selection_policy_sha256']!=sha(POLICY.read_text(encoding='utf-8')):
        raise ValueError('selection policy changed after freeze; do not tune on this cohort')
    for r in dataset['rows']:
        if sha(r['screening'])!=r['screening_sha256'] or sha(load_cases(r['qid']))!=r['corpus_sha256']:
            raise ValueError('selection screening corpus changed after freeze')
    return dataset


def launch(folder, *, restart=False):
    from local.tools.verify_dashboard import verify_served_build
    if verify_served_build('http://127.0.0.1:8090'):raise ValueError('current served build required')
    data=check(folder)
    gate=json.loads((folder/'reference-gates.json').read_bytes())
    if not gate.get('completed') or len(gate['rows'])!=8*len(data['rows']):raise ValueError('all eight-language oracle gates required')
    if gate['dataset_sha256']!=sha((folder/'dataset.json').read_text(encoding='utf-8')):raise ValueError('gate dataset identity differs')
    interrupted=[]
    if (folder/'jobs.json').exists():
        if not restart:raise ValueError('study already launched; do not resample')
        previous=json.loads((folder/'jobs.json').read_bytes())
        if (folder/'jobs-before-transport-fix.json').exists():raise ValueError('one transport restart already recorded')
        for ident in previous['jobs']:
            job=request('jobs/'+ident)
            if job['state'] not in ('interrupted','cancelled') or any(c.get('code') for g in job['result'].get('groups',[]) for c in g['candidates']):
                raise ValueError('transport restart requires terminal interrupted jobs with zero completed code samples')
            save(folder/f'interrupted-job-{ident}.json',job)
            interrupted.append({'id':ident,'state':job['state'],'completed_codes':0,'provider_cost':'unknown; no complete response recorded'})
        save(folder/'jobs-before-transport-fix.json',previous)
        save(folder/'transport-amendment.json',{'dataset_sha256':previous['dataset_sha256'],
             'reason':'response.read(n) could exceed the socket idle timeout under heartbeat traffic; bounded incremental body reads added',
             'generation_sha256':sha((ROOT/'local/lab/generation.py').read_text(encoding='utf-8')),
             'selection_policy_unchanged':True,'discarded_completed_samples':0,'interrupted_jobs':interrupted,
             'notice':'No complete model output was observed; missing responses and usage are not invented.'})
    model=data['protocol']['model']
    if next(m for m in request('models')['data'] if m['id']==model['id'])!=model:
        raise ValueError('model configuration changed after freeze')
    record={'dataset_sha256':sha((folder/'dataset.json').read_text(encoding='utf-8')),'jobs':[],'interrupted_jobs':interrupted}
    save(folder/'jobs.json',record)
    for start in (0,5):
        topics=[r['qid'] for r in data['rows'][start:start+5]]
        job=request('jobs',{'title':f'前瞻复核 · 验证后选码 · 批次 {start//5+1}',
                 'spec':{'qids':topics,'model_ids':[model['id']],'languages':data['protocol']['languages'],
                         'task':'gen','source_language':'python3','num_candidates':5,'probe_count':8,'temperature':.7,
                         'probe_strategy':'balanced','metamorphic_checks':True}})
        record['jobs'].append(job['id']);save(folder/'jobs.json',record)
        request('jobs/'+job['id']+'/run',{})
        print('submitted',job['id'],topics,flush=True)


def summarize(groups):
    count=len(groups)
    selections=[g for g in groups if g['advice_index'] is not None]
    return {'groups':count,'questions':len({g['qid'] for g in groups}),
            'candidates':sum(len(g['audit_correct']) for g in groups),
            'audit_passed_candidates':sum(sum(g['audit_correct']) for g in groups),
            'advice_coverage':len(selections)/count,'advice_selected_groups':len(selections),
            'advice_correct_all_groups':sum(g['advice_correct'] for g in groups)/count,
            'advice_correct_among_selected':sum(g['advice_correct'] for g in selections)/len(selections) if selections else None,
            'center_correct_all_groups':sum(g['center_correct'] for g in groups)/count,
            'first_screened_correct_all_groups':sum(g['first_screened_correct'] for g in groups)/count,
            'random_expected_correct':sum(sum(g['audit_correct'])/len(g['audit_correct']) for g in groups)/count,
            'paired_difference_from_center':sum(g['advice_correct']-g['center_correct'] for g in groups)/count,
            'paired_difference_ci95':clustered_interval(groups,lambda s:sum(g['advice_correct']-g['center_correct'] for g in s)/len(s)),
            'advice_failures_on_final_audit':[{'qid':g['qid'],'language':g['language'],'index':g['advice_index']+1} for g in selections if not g['advice_correct']],
            'abstained_groups':[{'qid':g['qid'],'language':g['language']} for g in groups if g['advice_index'] is None],
            'any_correct_available':sum(any(g['audit_correct']) for g in groups)}


def evaluate(folder):
    data=check(folder)
    tasks=json.loads((folder/'jobs.json').read_bytes())
    identity=sha((folder/'dataset.json').read_text(encoding='utf-8'))
    if tasks['dataset_sha256']!=identity:raise ValueError('job dataset changed')
    dest=folder/'audit-labels.json'
    labels=json.loads(dest.read_bytes()) if dest.exists() else {'dataset_sha256':identity,'rows':[]}
    if labels['dataset_sha256']!=identity:raise ValueError('audit checkpoint mismatch')
    runner.DOCKER_IMAGE=data['image']
    groups=[]
    for ident in tasks['jobs']:
        job=request('jobs/'+ident)
        if job['state']!='completed':raise ValueError(f"job {ident} is {job['state']}; no fabricated results")
        if job['result']['manifest'].get('selection_policy_sha256')!=data['selection_policy_sha256']:
            raise ValueError('actual selection policy differs from frozen protocol')
        save(folder/f'job-{ident}.json',job)
        for group in job['result']['groups']:
            row=next(r for r in data['rows'] if r['qid']==group['qid'])
            actual=next(r for r in job['result']['inputs'] if r['qid']==group['qid'])
            if actual['probe_sha256']!=row['probe_sha256'] or actual['validation_sha256']!=row['screening_sha256']:
                raise ValueError('actual probe/screening inputs differ from frozen protocol')
            advice=group.get('selection_advice',{})
            if advice.get('provenance')!='frozen_at_run':raise ValueError('prospective advice was not frozen during run')
            correct=[]
            for c in group['candidates']:
                old=next((r for r in labels['rows'] if r['id']==c['id']),None)
                if old and old['code_sha256']!=c['code_sha256']:raise ValueError('audited candidate changed')
                if not old:
                    with tempfile.TemporaryDirectory(prefix='mci_advice_audit_') as tmp:
                        path=Path(tmp)/f"{group['qid']}_{KEY_TO_LABEL[group['language']]}_1.txt"
                        path.write_text(c['code'],encoding='utf-8')
                        verdict=judge_one(path,'gen',len(row['validation']),'docker',run_timeout_s=5,cases_override=deepcopy(row['validation']))
                    if verdict['state']!='SUCCESS':raise RuntimeError('final audit environment failed')
                    old={'id':c['id'],'qid':group['qid'],'language':group['language'],'code_sha256':c['code_sha256'],
                         'audit_passed':verdict['ac_status']=='Accepted','verdict':verdict}
                    labels['rows'].append(old);save(dest,labels)
                    print('audit',group['qid'],group['language'],c['index'],verdict['ac_status'],flush=True)
                correct.append(old['audit_passed'])
            indices={c['id']:i for i,c in enumerate(group['candidates'])}
            chosen=indices.get(advice.get('candidate_id'))
            center=indices.get(group['metrics'].get('selected_candidate'))
            rejected={r['candidate_id'] for r in advice.get('rejected',[])}
            first=next((i for i,c in enumerate(group['candidates']) if c['id'] not in rejected),None) if advice['state']=='recommended' else None
            groups.append({'qid':group['qid'],'language':group['language'],'audit_correct':correct,
                    'advice_index':chosen,'center_index':center,'first_screened_index':first,
                    'advice_correct':int(chosen is not None and correct[chosen]),
                    'center_correct':int(center is not None and correct[center]),
                    'first_screened_correct':int(first is not None and correct[first]),
                    'screening_passed':[c.get('validation_passed') for c in group['candidates']],
                    'uncertainty':group['metrics']['uncertainty']})
    summary=summarize(groups)
    save(folder/'report.json',{'dataset_sha256':identity,'summary':summary,'groups':groups,
           'limitations':['one model, ten existing topics and two languages; small prospective cohort',
                          'C is disjoint from both A and B; passing finite C does not imply LeetCode or all-input correctness',
                          '100% observations or equal policies do not prove superiority or generalization']})
    fmt=lambda value:'N/A' if value is None else f'{value:.1%}'
    lines=['# 验证后选码：前瞻复核','',
           '先冻结选码策略，再在首轮未使用的十道既有题目上生成代码。A 为探测输入，B 为选码筛选输入，C 为独立 oracle 复核输入；C 与全部原语料不重叠，不参与选码。', '',
           '| 指标 | 结果 |','|---|---:|',f"| 候选通过 C | {summary['audit_passed_candidates']}/{summary['candidates']} |",
           f"| 建议覆盖率 | {fmt(summary['advice_coverage'])} |",
           f"| 建议正确选择 / 全部组 | {fmt(summary['advice_correct_all_groups'])} |",
           f"| 建议通过 C / 有建议组 | {fmt(summary['advice_correct_among_selected'])} |",
           f"| 原行为中心通过 C / 全部组 | {fmt(summary['center_correct_all_groups'])} |",
           f"| 验证筛选后按原顺序通过 C / 全部组 | {fmt(summary['first_screened_correct_all_groups'])} |",
           f"| 随机选择通过 C 的期望 | {fmt(summary['random_expected_correct'])} |",'',
           f"对行为中心的配对差值：{summary['paired_difference_from_center']:.3f}，题目聚类 bootstrap 95% 区间 {summary['paired_difference_ci95']['low']}～{summary['paired_difference_ci95']['high']}。",'',
           '拒绝建议也计入全部组的分母，另报覆盖率，避免只展示通过者制造高通过率。B 已用于选择，不能拿 B 的通过率证明选择有效。完整逐候选 C 标签和失败/拒绝列表见 report.json。', '',
           '仅一个模型、十道既有题目、两种语言，且有限 C 输入不证明 LC 一致或全输入正确。若方法得分相同或样本全通过，应报告未观察到差异，不宣称改进已获得泛化证明。']
    (folder/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('report',folder/'report.md',summary,flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['freeze','gates','launch','restart-after-transport-fix','evaluate']);p.add_argument('--folder',type=Path,required=True)
    args=p.parse_args();args.folder.mkdir(parents=True,exist_ok=True)
    {'freeze':freeze,'gates':gates,'launch':launch,'restart-after-transport-fix':lambda folder:launch(folder,restart=True),'evaluate':evaluate}[args.action](args.folder)


if __name__=='__main__':main()
