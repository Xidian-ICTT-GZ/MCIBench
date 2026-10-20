"""Frozen exploratory Code-MUE pilot; independent oracles, no corpus publication."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import platform
import tempfile
import time
import urllib.request

from local.common import LANGS, KEY_TO_LABEL, load_reference
from local.harness import runner
from local.harness.identity import image_digest, judge_source_closure
from local.judge import load_cases, judge_one
from local.lab.behavior import partition_cases, sha
from local.lab.study_inputs import cases_for
from local.tools.gap_workflow import save
from local.tools.study_metrics import scores, report as research_report

# Chosen before candidate generation and validation labels; covers different interfaces.
PILOT_QIDS = (781, 1103, 1277, 1287, 1323, 1969, 2073, 2094, 2138, 2225)


def freeze(folder):
    destination = folder / 'dataset.json'
    if destination.exists():
        raise ValueError('already frozen; use the existing dataset')
    rows = []
    for index, qid in enumerate(PILOT_QIDS):
        probes, _, selection = partition_cases(qid, load_cases(qid), 8, return_metadata=True)
        validation = cases_for(qid, 20261014, probes)
        rows.append({'qid': qid, 'split': 'dev' if index % 2 == 0 else 'test',
                     'probes': probes, 'probe_sha256': sha(probes), 'selection': selection,
                     'validation': validation, 'validation_sha256': sha(validation)})
    save(destination, {'version': 1, 'frozen_at': time.time(), 'host_python': platform.python_version(),
         'image': image_digest(), 'judge_closure': dict(judge_source_closure()),
         'oracle_sha256': sha(Path(__file__).resolve().parents[1].joinpath('lab/study_inputs.py').read_text(encoding='utf-8')),
         'protocol': {'languages': ['python3', 'javascript'], 'n': 5, 'k': 8, 'temperature': .7,
                      'model_id': '99f2deec8d144833836ca4cd35394438', 'selection': 'spectral_center',
                      'labels': 'all_independent_oracle_validation_inputs_passed',
                      'low_u_cutoff': .1, 'bootstrap_question_clusters': 1000},
         'scope': 'existing topics; seeded or exhaustive small-domain oracle inputs, disjoint from probes; not a new blind benchmark',
         'rows': rows})
    print('frozen', destination, len(rows), 'questions', flush=True)


def check_dataset(dataset):
    if dataset['oracle_sha256'] != sha(Path(__file__).resolve().parents[1].joinpath('lab/study_inputs.py').read_text(encoding='utf-8')):
        raise ValueError('oracle source changed after freeze')
    if dataset['image'] != image_digest() or dataset['judge_closure'] != dict(judge_source_closure()):
        raise ValueError('judge environment changed after freeze')
    for row in dataset['rows']:
        if row['probe_sha256'] != sha(row['probes']) or row['validation_sha256'] != sha(row['validation']):
            raise ValueError('frozen inputs changed')


def gates(folder):
    dataset = json.loads((folder/'dataset.json').read_bytes())
    check_dataset(dataset)
    runner.DOCKER_IMAGE = dataset['image']
    dest = folder/'reference-gates.json'
    evidence = json.loads(dest.read_bytes()) if dest.exists() else {'dataset_sha256': sha((folder/'dataset.json').read_text(encoding='utf-8')), 'rows': []}
    if evidence['dataset_sha256'] != sha((folder/'dataset.json').read_text(encoding='utf-8')):
        raise ValueError('reference gate dataset mismatch')
    for row in dataset['rows']:
        for language in LANGS:
            code = load_reference(row['qid'], language)
            old = next((r for r in evidence['rows'] if r['qid'] == row['qid'] and r['language'] == language), None)
            if old:
                if old['code_sha256'] != sha(code) or old['status'] != 'Accepted':
                    raise ValueError('previous reference gate failed or source changed')
                continue
            with tempfile.TemporaryDirectory(prefix='mci_study_') as tmp:
                path = Path(tmp)/f"{row['qid']}_{KEY_TO_LABEL[language]}_1.txt"
                path.write_text(code, encoding='utf-8')
                started = time.perf_counter()
                verdict = judge_one(path, 'gen', len(row['validation']), 'docker',
                                    run_timeout_s=5, cases_override=deepcopy(row['validation']))
            item = {'qid': row['qid'], 'language': language, 'code_sha256': sha(code),
                    'status': verdict['ac_status'], 'state': verdict['state'],
                    'correct': verdict['total_correct'], 'total': verdict['total_testcases'],
                    'wall_ms': round((time.perf_counter()-started)*1000, 3), 'verdict': verdict}
            evidence['rows'].append(item)
            save(dest, evidence)
            print(row['qid'], language, item['status'], item['correct'], '/', item['total'], flush=True)
            if item['state'] != 'SUCCESS' or item['status'] != 'Accepted':
                raise RuntimeError('independent oracle/reference disagreement; investigate before generation')
    evidence['completed'] = True
    save(dest, evidence)


def request(path, body=None):
    req = urllib.request.Request('http://127.0.0.1:8090/api/v1/lab/'+path,
              data=json.dumps(body).encode() if body is not None else None,
              headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def launch(folder):
    from local.tools.verify_dashboard import verify_served_build
    if verify_served_build('http://127.0.0.1:8090'):
        raise ValueError('current dashboard build required')
    dataset = json.loads((folder/'dataset.json').read_bytes())
    check_dataset(dataset)
    gates = json.loads((folder/'reference-gates.json').read_bytes())
    if not gates.get('completed') or len(gates['rows']) != 8*len(dataset['rows']):
        raise ValueError('all eight-language oracle gates required')
    if (folder/'jobs.json').exists():
        raise ValueError('pilot already launched; do not resample')
    protocol = dataset['protocol']
    profile = next(p for p in request('models')['data'] if p['id'] == protocol['model_id'])
    record = {'dataset_sha256':sha((folder/'dataset.json').read_text(encoding='utf-8')), 'model':profile, 'jobs':[]}
    save(folder/'jobs.json',record)
    for split in ('dev','test'):
        qids = [r['qid'] for r in dataset['rows'] if r['split'] == split]
        spec = {'qids':qids, 'model_ids':[protocol['model_id']], 'languages':protocol['languages'],
                'task':'gen','source_language':'python3','num_candidates':protocol['n'],
                'probe_count':protocol['k'],'temperature':protocol['temperature'],
                'probe_strategy':'balanced','metamorphic_checks':True}
        job = request('jobs', {'title':f'研究试验 · Code-MUE 冻结先导 · {split}', 'spec':spec})
        record['jobs'].append({'id':job['id'],'split':split})
        save(folder/'jobs.json',record)
        request('jobs/'+job['id']+'/run', {})
        print(split,job['id'],'submitted',flush=True)


def evaluate(folder):
    dataset = json.loads((folder/'dataset.json').read_bytes())
    check_dataset(dataset)
    jobs = json.loads((folder/'jobs.json').read_bytes())
    if jobs['dataset_sha256'] != sha((folder/'dataset.json').read_text(encoding='utf-8')):
        raise ValueError('pilot dataset identity changed')
    runner.DOCKER_IMAGE = dataset['image']
    dest = folder/'candidate-labels.json'
    labels = json.loads(dest.read_bytes()) if dest.exists() else {'dataset_sha256':jobs['dataset_sha256'],'rows':[]}
    if labels['dataset_sha256'] != jobs['dataset_sha256']:
        raise ValueError('independent validation checkpoint belongs to a different dataset')
    groups, snapshots = [], []
    for task in jobs['jobs']:
        job = request('jobs/'+task['id'])
        if job['state'] != 'completed':
            raise ValueError(f"job {job['id']} is {job['state']}; no fabricated study result")
        snapshots.append(job)
        save(folder/f"job-{job['id']}.json",job)
        for group in job['result']['groups']:
            data = next(r for r in dataset['rows'] if r['qid']==group['qid'])
            if group['probe_sha256'] != data['probe_sha256'] or len(group['candidates']) != dataset['protocol']['n']:
                raise ValueError('actual sampling or probe identity differs from frozen protocol')
            correct = []
            for candidate in group['candidates']:
                item = next((r for r in labels['rows'] if r['id'] == candidate['id']),None)
                if item and item['code_sha256'] != candidate['code_sha256']:
                    raise ValueError('candidate source changed')
                if item and (item['qid'] != group['qid'] or item['language'] != group['language']):
                    raise ValueError('candidate validation interface changed')
                if not item:
                    with tempfile.TemporaryDirectory(prefix='mci_study_label_') as tmp:
                        path = Path(tmp)/f"{group['qid']}_{KEY_TO_LABEL[group['language']]}_1.txt"
                        path.write_text(candidate['code'],encoding='utf-8')
                        start = time.perf_counter()
                        verdict = judge_one(path,'gen',len(data['validation']),'docker',run_timeout_s=5,cases_override=deepcopy(data['validation']))
                    if verdict['state'] != 'SUCCESS':
                        raise RuntimeError('independent validation environment failed')
                    item = {'id':candidate['id'],'qid':group['qid'],'language':group['language'],
                            'code_sha256':candidate['code_sha256'],'passed':verdict['ac_status']=='Accepted',
                            'verdict':verdict,'wall_ms':(time.perf_counter()-start)*1000}
                    labels['rows'].append(item);save(dest,labels)
                    print('label',group['qid'],group['language'],candidate['index'],verdict['ac_status'],flush=True)
                correct.append(item['passed'])
            selected = next((i for i,c in enumerate(group['candidates']) if c.get('selected')),None)
            row_sums = [sum(row) for row in group['metrics']['matrix']]
            eligible = [i for i,c in enumerate(group['candidates']) if any(o['kind']=='value' for o in c['outcomes'])
                        and not any(o['kind']=='compile_error' for o in c['outcomes'])]
            maximum = max((row_sums[i] for i in eligible),default=0)
            best = min((i for i in eligible if maximum-row_sums[i] <= 1e-10),default=None)
            groups.append({'qid':group['qid'],'language':group['language'],'split':data['split'],
                 'candidate_count':len(correct),'scores':scores(group),'selected_index':selected,
                 'selected_error':int(selected is None or not correct[selected]),'any_correct':any(correct),
                 'random_accuracy':sum(correct)/len(correct),'mean_center_correct':int(best is not None and correct[best]),'correct':correct})
    result = {'dataset_sha256':jobs['dataset_sha256'],'groups':groups,'summary':research_report(groups),
              'cost':{'generation_attempts':sum(len(c.get('generation',{}).get('attempts',[])) for j in snapshots for g in j['result']['groups'] for c in g['candidates']),
                      'usage': [c.get('usage',{}) for j in snapshots for g in j['result']['groups'] for c in g['candidates']],
                      'jobs_timing':[j['result'].get('timing') for j in snapshots],
                      'independent_label_wall_ms':sum(r['wall_ms'] for r in labels['rows'])},
              'limitations':['仅一个模型、十道既有题目、两种语言、N=5，是探索性先导试验。',
                             '独立标签仅覆盖所选小规模输入，不证明全输入正确或 LeetCode 一致。',
                             '题目既有，非探测语料可能有输入重合，不能称为新盲测基准。',
                             'test 仅五道题；所有失败组若仅来自一道题，AUROC 聚类置信区间不具备估计条件，不把有效抽样的退化区间当作确定性。',
                             '只有一类正确性标签时，AUROC/AP 明确为 N/A，不补造有效性。']}
    save(folder/'report.json',result)
    lines = ['# Code-MUE 冻结先导试验','', '真实模型：DeepSeek Flash 关闭思考；10 道既有题目、Python/JavaScript、每组 N=5、K=8、温度 0.7。输入、独立 oracle 与 dev/test 划分均在生成前冻结。八语言共 80 次参考门禁通过。', '',
             '正确性标签来自与探测输入不重叠的独立 oracle 验证，表示通过所选输入，不能称作全输入正确或 LC 通过。','',
             '| 范围 | 题目 | 组 | 中心候选通过率 | 随机选择期望通过率 | 低 U 共同错误 |',
             '|---|---:|---:|---:|---:|---:|']
    for split in ('all','dev','test'):
        s=result['summary'][split]
        lines.append(f"| {split} | {s['questions']} | {s['groups']} | {s['center_accuracy']:.3f} | {s['random_selection_expected_accuracy']:.3f} | {s['low_u_common_wrong']} |")
    lines += ['', '| test 风险分数 | AUROC | AP | AURC |','|---|---:|---:|---:|']
    for name,m in result['summary']['test']['risk_metrics'].items():
        fmt=lambda v:'N/A（标签仅一类）' if v is None else f'{v:.4f}'
        lines.append(f"| {name} | {fmt(m['auroc'])} | {fmt(m['auprc_ap'])} | {m['aurc']:.4f} |")
    lines += ['', 'AUROC/AP 的目标是识别行为中心候选在独立输入上失败的组；AURC 是按风险由低到高保留组时的风险曲线均值，越低越好。同分组按期望顺序处理，避免标签或遍历顺序影响结果。随机候选基线使用每组真实正确候选比例的期望，不重采样模型。完整覆盖风险曲线、题目聚类 bootstrap、语言结果与成本见 report.json。', '', '## 实际发现', '']
    for row in groups:
        if row['selected_error']:
            lines.append(f"- q{row['qid']} / {row['language']}：{sum(row['correct'])}/{row['candidate_count']} 个候选通过独立验证，U={row['scores']['spectral_u']:.4f}，行为中心候选未通过。行为中心选择不保证找到正确候选。")
    lines += ['', '本轮中心候选通过率与随机基线直接比较，不宣称中心选择优于随机。若失败仅来自一个组，观察到 AUROC=1 也不足以证明泛化有效；应扩充模型、难度和独立失败题目后复验。低 U 共同错误的人工实跑反例另存 controlled-common-wrong.json，不计入自然模型统计。', '', '## 局限', '']
    lines += ['- '+x for x in result['limitations']]
    (folder/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('study report',folder/'report.md',flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['freeze', 'gates', 'launch', 'evaluate'])
    parser.add_argument('--folder', type=Path, required=True)
    args = parser.parse_args()
    args.folder.mkdir(parents=True, exist_ok=True)
    {'freeze':freeze,'gates':gates,'launch':launch,'evaluate':evaluate}[args.action](args.folder)


if __name__ == '__main__':
    main()
