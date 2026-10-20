"""Verification-aware advice, kept separate from the label-free Code-MUE kernel."""
from __future__ import annotations

import hashlib
import math

VERSION = 'verified-behavior-advice-v3-full-execution'
REASONS = {
    'source_unbound': '代码或源码指纹不完整',
    'generation_incomplete': '生成未成功完成',
    'truncated': '生成达到输出上限，代码可能截断',
    'validation_incomplete': '本地验证记录不完整',
    'validation_failed': '未通过全部本地验证输入',
    'probe_failure': '探测输入存在失败或行为记录不完整',
    'probe_answer_failure': '探测输入的实际输出未通过标准答案核验',
    'relation_failure': '变形关系被违反或执行失败',
    'full_execution_failed': '独立完整复判未通过',
}


def exclusions(candidate, probe_count, validation_count):
    reasons = []
    code = candidate.get('code')
    if not isinstance(code, str) or not code or hashlib.sha256(code.encode('utf-8')).hexdigest() != candidate.get('code_sha256'):
        reasons.append('source_unbound')
    if candidate.get('generation_state', 'succeeded') != 'succeeded':
        reasons.append('generation_incomplete')
    if candidate.get('finish_reason') == 'length':
        reasons.append('truncated')
    verdict = candidate.get('verdict') or {}
    total, correct = verdict.get('total_testcases'), verdict.get('total_correct')
    if verdict.get('state') != 'SUCCESS' or type(total) is not int or total <= 0 or total != validation_count or type(correct) is not int or not 0 <= correct <= total:
        reasons.append('validation_incomplete')
    elif candidate.get('validation_passed') is not True or verdict.get('ac_status') != 'Accepted' or correct != total:
        reasons.append('validation_failed')
    outcomes = candidate.get('outcomes') or []
    if len(outcomes) != probe_count or any(o.get('kind') != 'value' for o in outcomes):
        reasons.append('probe_failure')
    if candidate.get('probe_verdict') and candidate['probe_verdict'].get('ac_status') != 'Accepted':
        reasons.append('probe_answer_failure')
    # Full re-execution may detect issues invisible to the label-free probes.
    full = candidate.get('corpus_verdict') or {}
    if full.get('version') in ('full-corpus-executed-v2','full-corpus-json-v1','full-corpus-native-v1') and (full.get('state') != 'SUCCESS'
            or full.get('ac_status') != 'Accepted' or full.get('total_correct') != full.get('total_testcases')):
        reasons.append('full_execution_failed')
    if any(r.get('state') in ('violated', 'execution_failure') for r in candidate.get('metamorphic', [])):
        reasons.append('relation_failure')
    return reasons


def recommend(group, *, expected_count=None):
    """Filter by validation; rank survivors by frozen centrality, ties by source order.

    These validation results are selection evidence, never an independent accuracy
    measurement of the selected policy. No correctness label enters analyze().
    """
    candidates = group.get('candidates') or []
    metrics = group.get('metrics') or {}
    k = metrics.get('probe_count', group.get('probe_count', 0))
    output = {'version': VERSION, 'state': 'incomplete', 'candidate_id': None, 'candidate_index': None,
              'eligible_count': 0, 'rejected': [], 'behavior_center_id': metrics.get('selected_candidate'),
              'same_as_behavior_center': None, 'validation_count': group.get('validation_count', 0),
              'uses_validation_labels': True, 'changes_behavior_metrics': False,
              'notice': '建议使用了本地验证结果；这些输入不能再作为选码效果的独立复核，不保证 LeetCode 通过。'}
    if not metrics.get('matrix') or type(k) is not int or k <= 0 or not candidates or (expected_count is not None and len(candidates) != expected_count):
        output['reason'] = ('至少需要两个候选才能比较行为中心；单份代码的判题结果仍可查看。' if len(candidates)==1 and candidates[0].get('generation_state')=='succeeded'
                            else '候选组的生成或行为评测尚不完整，暂不建议选码。')
        return output
    eligible = []
    for position, candidate in enumerate(candidates):
        reasons = exclusions(candidate, k, group.get('validation_count', 0))
        if reasons:
            output['rejected'].append({'candidate_id': candidate.get('id'), 'candidate_index': candidate.get('index', position+1),
                                       'reason_codes': reasons, 'reasons': [REASONS[r] for r in reasons]})
        else:
            centrality = candidate.get('centrality')
            score = round(float(centrality), 8) if type(centrality) in (int, float) and 0 <= centrality <= 1 and math.isfinite(centrality) else 0.
            eligible.append((score, -position, candidate))
    output['eligible_count'] = len(eligible)
    if not eligible:
        output.update(state='abstained', reason='没有候选同时满足验证通过、探测成功和生成完整等条件，保留全部结果，不回退推荐失败代码。')
        return output
    candidate = max(eligible, key=lambda item: item[:2])[2]
    output.update(state='recommended', candidate_id=candidate['id'], candidate_index=candidate['index'],
                  validation_count=candidate['verdict']['total_testcases'],
                  same_as_behavior_center=candidate['id'] == output['behavior_center_id'],
                  reason='先排除验证未通过或存在执行/生成风险的候选，再按原行为中心性选择；同分取原候选顺序。')
    return output


def decorate_job(job):
    """Read-only legacy view; stored source/metrics/labels are never rewritten."""
    for group in job.get('result', {}).get('groups', []):
        if not group.get('selection_advice'):
            advice = recommend(group, expected_count=job['spec'].get('num_candidates'))
            advice['provenance'] = 'derived_from_saved_evidence'
            group['selection_advice'] = advice
    return job
