"""Measured language/scale controls; never tighten a budget from LC status alone."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import statistics
import time

from local.common import LANGS, KEY_TO_LABEL, load_reference
from local.gen_testcases.constraints import check
from local.harness import runner
from local.harness.identity import image_digest, judge_source_closure
from local.judge import judge_one
from local.tools import gap_workflow as workflow


SUPPORTED = (1014, 1673, 1957, 2009)


def control_case(qid, size):
    if type(size) is not int or size < 2:
        raise ValueError('size must be an integer >= 2')
    if qid == 1014:
        values = [(i * 131) % 1000 + 1 for i in range(size)]
        best, answer = values[0], -10**9
        for j in range(1, size):
            answer = max(answer, best + values[j] - j)
            best = max(best, values[j] + j)
        case = {'args': {'values': values}, 'expected': answer}
    elif qid == 1673:
        k = size // 2
        case = {'args': {'nums': list(range(size, 0, -1)), 'k': k}, 'expected': list(range(k, 0, -1))}
    elif qid == 1957:
        text = ('aaabbb' * ((size + 5) // 6))[:size]
        case = {'args': {'s': text}, 'expected': re.sub(r'(.)\1{2,}', r'\1\1', text)}
    elif qid == 2009:
        case = {'args': {'nums': [2 * i + 1 for i in range(size)]}, 'expected': size // 2}
    else:
        raise ValueError(f'q{qid} has no reviewed scale control')
    errors = check(qid, case)
    if errors:
        raise ValueError(f'q{qid} size {size} is not verified legal: {errors}')
    return case


def aggregate(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row['qid'], row['language'], row['role'], row['model'], row['size'])].append(row)
    output = []
    for key, values in sorted(grouped.items()):
        runtime = [v['runtime_ms'] for v in values if v['runtime_ms'] is not None]
        statuses = [v['status'] for v in values]
        output.append(dict(zip(('qid', 'language', 'role', 'model', 'size'), key),
                           repeats=len(values), statuses=statuses,
                           median_runtime_ms=statistics.median(runtime) if len(runtime) == len(values) else None,
                           median_wall_ms=statistics.median(v['wall_clock_ms'] for v in values),
                           stable_status=len(set(statuses)) == 1))
    return output


def selected_tasks(plan, qids):
    return [t for t in plan['tasks'] if t['branch'] == 'performance'
            and t['slot']['eval_split'] == 'dev' and t['slot']['qid'] in qids]


def comparison_profiles(summary):
    references = {(r['qid'], r['language'], r['size']): r for r in summary if r['role'] == 'reference'}
    profiles = []
    for row in summary:
        if row['role'] != 'candidate':
            continue
        reference = references.get((row['qid'], row['language'], row['size']))
        if not reference:
            continue
        baseline = reference['median_runtime_ms']
        measured = row['median_runtime_ms']
        ratio = measured / baseline if baseline is not None and baseline > 0 and measured is not None else None
        profiles.append({'qid': row['qid'], 'language': row['language'], 'model': row['model'],
                         'size': row['size'], 'runtime_ratio_to_reference': round(ratio, 3) if ratio is not None else None,
                         'candidate_statuses': row['statuses'], 'reference_statuses': reference['statuses'],
                         'interpretation': 'local_cost_ratio_not_lc_time_limit', 'same_lc_source_confirmed': False})
    return profiles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--qids', default='1014,1673,1957,2009')
    parser.add_argument('--sizes', default='100,1000,50000')
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--all-reference-languages', action='store_true')
    args = parser.parse_args()
    qids = {int(x) for x in args.qids.split(',')}
    sizes = sorted({int(x) for x in args.sizes.split(',')})
    if not qids.issubset(SUPPORTED) or not 2 <= args.repeats <= 5:
        raise ValueError('use reviewed controls and 2–5 repeats')
    cases = {(q, n): control_case(q, n) for q in qids for n in sizes}
    plan = workflow.plan()
    tasks = selected_tasks(plan, qids)
    if {t['slot']['qid'] for t in tasks} != qids:
        raise ValueError('requested questions must have current dev-only LC timeout discrepancies')
    for task in tasks:
        workflow.assert_current(task['slot'])
    args.job = args.job.resolve()
    args.job.mkdir(parents=True, exist_ok=True)
    runner.DOCKER_IMAGE = image_digest()
    evidence = {'schema': 1, 'diagnostic_only': True, 'formal_results_modified': False,
                'image': runner.DOCKER_IMAGE, 'judge_closure': dict(judge_source_closure()),
                'budget_s': 5, 'lc_time_limit_known': False, 'same_lc_source_confirmed': False,
                'qids': sorted(qids), 'sizes': sizes, 'repeats': args.repeats, 'rows': []}
    trials = []
    for qid in sorted(qids):
        targets = [t for t in tasks if t['slot']['qid'] == qid]
        languages = LANGS if args.all_reference_languages else sorted({t['slot']['lang'] for t in targets})
        for language in languages:
            path = args.job / 'sources' / 'reference' / f'{qid}_{KEY_TO_LABEL[language]}_1.txt'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(load_reference(qid, language), encoding='utf-8')
            trials.append((qid, language, 'reference', 'reference', path))
        for target in targets:
            slot = target['slot']
            original = workflow.code_path(slot)
            path = args.job / 'sources' / slot['model'] / original.name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(original.read_bytes())
            trials.append((qid, slot['lang'], 'candidate', slot['model'], path))
    evidence['source_hashes'] = {str(p.relative_to(args.job)): workflow.sha(p.read_bytes()) for *_, p in trials}
    evidence['corpus_hashes'] = {str(q): workflow.sha((workflow.CORPUS / str(q) / 'cases.json').read_bytes()) for q in qids}
    workflow.save(args.job / 'controls.json', [{'qid': q, 'size': n, 'case': case} for (q, n), case in sorted(cases.items())])
    evidence['controls_sha256'] = workflow.sha((args.job / 'controls.json').read_bytes())
    workflow.save(args.job / 'evidence.json', evidence)
    for qid, language, role, model, path in trials:
        for size in sizes:
            for repeat in range(1, args.repeats + 1):
                start = time.perf_counter()
                result = judge_one(path, 'gen', 1, 'docker', 5, cases_override=[cases[qid, size]])
                timing = result.get('_meta', {}).get('timing', {})
                row = {'qid': qid, 'language': language, 'role': role, 'model': model, 'size': size,
                       'repeat': repeat, 'status': result['ac_status'], 'state': result['state'],
                       'runtime_ms': timing.get('runtime_ms'), 'wall_clock_ms': round((time.perf_counter() - start) * 1000, 2),
                       'source_sha256': workflow.sha(path.read_bytes()), 'result': result}
                evidence['rows'].append(row)
                evidence['summary'] = aggregate(evidence['rows'])
                workflow.save(args.job / 'evidence.json', evidence)
                print(f'q{qid} {language} {role} n={size} repeat={repeat}: {row["status"]} runtime={row["runtime_ms"]}', flush=True)
                if result['state'] != 'SUCCESS' or (role == 'reference' and result['ac_status'] != 'Accepted'):
                    raise RuntimeError('reference or infrastructure gate failed; no calibration is published')
    for qid in qids:
        if workflow.sha((workflow.CORPUS / str(qid) / 'cases.json').read_bytes()) != evidence['corpus_hashes'][str(qid)]:
            raise RuntimeError('corpus changed during measurement')
    if dict(judge_source_closure()) != evidence['judge_closure']:
        raise RuntimeError('judge changed during measurement')
    for task in tasks:
        workflow.assert_current(task['slot'])
    evidence['completed'] = True
    evidence['comparison_profiles'] = comparison_profiles(evidence['summary'])
    evidence['budget_recommendation'] = None
    evidence['policy'] = 'Reference controls calibrate local overhead and growth, not LC limits. No arbitrary budget reduction; verify exact LC source and limits before changing time policy.'
    workflow.save(args.job / 'evidence.json', evidence)
    lines = ['# 语言与规模耗时校准', '', '诊断运行；未修改正式结果或语料。运行预算 5 秒；wall 包含编译、启动及确认开销，不能替代程序运行时间。', '',
             '| 题目 | 语言 | 对象 | 规模 | 重复 | 运行中位数 ms | 完整耗时中位数 ms | 状态 |', '|---|---|---|---:|---:|---:|---:|---|']
    for row in evidence['summary']:
        lines.append(f'| q{row["qid"]} | {row["language"]} | {row["model"]} | {row["size"]} | {row["repeats"]} | {row["median_runtime_ms"]} | {row["median_wall_ms"]} | {", ".join(row["statuses"])} |')
    lines += ['', '没有 LC 实际时间上限和同源提交证明，不能由历史 TLE 标签推导本地应缩短到多少秒。稳定的候选超时且参考解通过，才构成该输入上的性能缺口证据；入库仍须经过八语言参考和非回归门禁。']
    lines += ['', '## 同语言、同规模的参考耗时比', '', '| 题目 | 语言 | 规模 | 模型/参考运行耗时 |', '|---|---|---:|---:|']
    for row in evidence['comparison_profiles']:
        lines.append(f'| q{row["qid"]} | {row["language"]} | {row["size"]} | {row["runtime_ratio_to_reference"]} |')
    (args.job / 'report.md').write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    main()
