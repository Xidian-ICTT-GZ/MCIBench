"""Explain a stored matrix cell with the same token and CE rules as metrics."""
from local.lab.metrics import token
from local.lab.storage import LabError


def compare(job, group_index, left_index, right_index):
    groups = job.get('result', {}).get('groups', [])
    if type(group_index) is not int or not 0 <= group_index < len(groups):
        raise LabError('候选组不存在', 404)
    group = groups[group_index]
    candidates = group['candidates']
    if any(type(i) is not int or not 0 <= i < len(candidates) for i in (left_index, right_index)):
        raise LabError('候选不存在', 404)
    metrics = group.get('metrics') or {}
    matrix = metrics.get('matrix')
    if not matrix:
        raise LabError('行为矩阵尚未计算', 409)
    left, right = candidates[left_index], candidates[right_index]
    probes = next((r['probes'] for r in job['result'].get('inputs', []) if r['qid'] == group['qid']), None)
    invalid = any(o['kind'] == 'compile_error' for c in (left, right) for o in c['outcomes'])
    rows = []
    for p, (a, b) in enumerate(zip(left['outcomes'], right['outcomes'])):
        matched = left_index == right_index or (not invalid and
                  token(a, candidate=left_index, probe=p) == token(b, candidate=right_index, probe=p))
        if left_index == right_index:
            reason = '对角线固定为 1，表示候选与自身；不能说明编译成功或答案正确'
        elif invalid:
            reason = '组内候选存在编译失败，按矩阵规则隔离；相同报错不算行为共识'
        elif a['kind'] == b['kind'] == 'value':
            reason = '按题目输出语义归一化后相同' if matched else '输出语义不同'
        elif matched:
            reason = '识别到相同异常类型；异常共识不代表正确'
        else:
            reason = '输出或失败类型不同；超时与未分类失败按候选隔离'
        rows.append({'probe_index': p+1, 'input': probes[p] if probes and p < len(probes) else None,
                     'left': a, 'right': b, 'matched': matched, 'reason': reason})
    agreement = matrix[left_index][right_index]
    if rows and abs(sum(r['matched'] for r in rows)/len(rows) - agreement) > 1e-8:
        raise LabError('历史矩阵与当前解释规则不一致，请保留原始记录核实', 409)
    return {'qid': group['qid'], 'left': left['index'], 'right': right['index'],
            'similarity': agreement, 'matches': sum(r['matched'] for r in rows), 'total': len(rows),
            'differing': sum(not r['matched'] for r in rows), 'inputs_available': probes is not None,
            'notice': '1 表示行为一致，0 表示没有计入一致；这不是通过/不通过标记。', 'rows': rows}
