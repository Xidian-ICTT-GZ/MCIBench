"""Offline, self-contained HTML report. No external resources; every user string escaped."""
from __future__ import annotations

from datetime import datetime, timezone
import html
import json

VERSION = 'lab-report-v3'

TEXT = {
    'en': {
        'title': 'MCIBench evaluation report', 'job': 'Job', 'state': 'State', 'type': 'Type',
        'parent': 'Parent job', 'children': 'Derived jobs', 'created': 'Created', 'operator': 'Operator',
        'model': 'Model', 'language': 'Language', 'qid': 'Problem', 'verdict': 'Verdict',
        'candidates': 'Candidates', 'code': 'Saved source', 'metrics': 'Behaviour metrics',
        'uncertainty': 'Spectral uncertainty U', 'matrix': 'Behaviour matrix', 'corpus': 'Corpus',
        'evidence': 'Evidence', 'limitations': 'Limitations', 'incomplete': 'Incomplete items',
        'first': 'First failing case', 'expected': 'Expected', 'actual': 'Actual',
        'not_captured': 'not captured', 'args': 'Input', 'calls': 'Model calls', 'mode': 'Corpus mode',
        'none': 'none', 'reused': 'Reused from parent', 'rerun': 'Re-executed',
        'note': 'Low U means the candidates agreed on the probe inputs. It does not prove correctness.',
        'offline': 'Generated offline; no external resources or scripts are loaded.',
        'legacy': 'Historical record: shown as interpreted at the time, not re-executed now.',
        'live_now': 'Execution record produced by this job.',
        'execution': 'Execution configuration', 'corpus_sha': 'Corpus sha256', 'cases': 'Cases',
        'source_program': 'Source program', 'source_language': 'Source language',
        'preservation': 'Translation preservation', 'per_input': 'Per-input comparison',
        'source_output': 'Source output', 'target_output': 'Target output',
        'advisories': 'Corpus notices', 'derived': 'Derived job',
        'answer': 'Answer evidence', 'answer_source': 'Answer source',
        'answer_level': 'Evidence level', 'answer_sha': 'Answer sha256',
        'answer_langs': 'Languages with an independent reference run',
        'answer_missing': 'Languages without one', 'answer_limits': 'Answer limitations',
    },
    'zh': {
        'title': 'MCIBench 评测报告', 'job': '任务', 'state': '状态', 'type': '类型',
        'parent': '父任务', 'children': '派生任务', 'created': '创建时间', 'operator': '操作人',
        'model': '模型', 'language': '语言', 'qid': '题目', 'verdict': '判定',
        'candidates': '候选', 'code': '保存的源码', 'metrics': '行为指标',
        'uncertainty': '谱熵 U', 'matrix': '行为矩阵', 'corpus': '语料',
        'evidence': '证据', 'limitations': '限制', 'incomplete': '未完成项',
        'first': '首个失败用例', 'expected': '期望值', 'actual': '实际值',
        'not_captured': '未采集', 'args': '输入', 'calls': '模型调用', 'mode': '语料模式',
        'none': '无', 'reused': '复用父任务', 'rerun': '重新执行',
        'note': '低 U 只表示候选在探测输入上行为一致，不能证明代码正确。',
        'offline': '离线生成；不加载任何外部资源或脚本。',
        'legacy': '历史记录：按当时解释展示，未在当前配置下重新执行。',
        'live_now': '本任务产生的执行记录。',
        'execution': '执行配置', 'corpus_sha': '语料 sha256', 'cases': '语料条数',
        'source_program': '源程序', 'source_language': '源语言',
        'preservation': '转译保持率', 'per_input': '逐输入对比',
        'source_output': '源程序输出', 'target_output': '目标程序输出',
        'advisories': '语料提示', 'derived': '派生任务',
        'answer': '答案依据', 'answer_source': '答案来源',
        'answer_level': '证据级别', 'answer_sha': '答案 sha256',
        'answer_langs': '已通过独立参考执行的语言',
        'answer_missing': '尚无参考执行的语言', 'answer_limits': '答案限制',
    },
}


def esc(value):
    return html.escape('' if value is None else str(value), quote=True)


def pretty(value):
    try:
        return esc(json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False))
    except (TypeError, ValueError):
        return esc(repr(value))


def _outcome(outcome):
    if not isinstance(outcome, dict):
        return '-'
    kind = outcome.get('kind')
    if kind == 'value':
        try:
            return 'value ' + json.dumps(outcome.get('value'), ensure_ascii=False, allow_nan=False)[:160]
        except (TypeError, ValueError):
            return 'value <unserializable>'
    if kind == 'exception':
        return 'exception %s' % (outcome.get('exception_type') or '')
    return '%s %s' % (kind, outcome.get('status') or '')


def _row(label, value):
    return '<tr><th>%s</th><td>%s</td></tr>' % (esc(label), value)


def _table(rows):
    return '<table>%s</table>' % ''.join(rows)


def _code(text):
    return '<pre class="code">%s</pre>' % esc(text)


def _verdict(verdict):
    if not isinstance(verdict, dict) or not verdict:
        return esc('-')
    status = verdict.get('ac_status') or verdict.get('state') or '-'
    return '%s <span class="muted">(%s/%s, %s)</span>' % (
        esc(status), esc(verdict.get('total_correct')), esc(verdict.get('total_testcases')),
        esc(verdict.get('version', '')))


def _matrix(matrix):
    if not isinstance(matrix, list) or not matrix:
        return ''
    head = ''.join('<th>%d</th>' % (i + 1) for i in range(len(matrix)))
    body = ''.join('<tr><th>%d</th>%s</tr>' % (
        r + 1, ''.join('<td>%.2f</td>' % float(c) if isinstance(c, (int, float)) else '<td>-</td>' for c in row))
        for r, row in enumerate(matrix))
    return '<table class="matrix"><tr><th></th>%s</tr>%s</table>' % (head, body)


def _counterexample(lang, record):
    """Show the observed value, or say plainly that it was not captured."""
    if not isinstance(record, dict) or not record.get('case'):
        return ''
    label = TEXT[lang]
    actual = record.get('actual')
    source = record.get('actual_source') or ''
    if actual is None:
        shown = '%s <span class="muted">(%s)</span>' % (
            esc(label['not_captured']), esc(source or 'unknown'))
    else:
        shown = pretty(actual)
    parts = ['<h4>%s</h4>%s' % (esc(label['first']), _table([
        _row('case', esc(record.get('case'))),
        _row(label['args'], pretty(record.get('args'))),
        _row(label['expected'], pretty(record.get('expected'))),
        _row(label['actual'], shown)])),
        '<p class="muted">%s</p>' % esc('actual_source=%s' % (source or 'unknown'))]
    if record.get('actual_error'):
        parts.append('<p class="muted">%s</p>' % esc(record['actual_error']))
    return ''.join(parts)


def _translation(lang, group, candidate):
    label = TEXT[lang]
    sources = group.get('source_outcomes') or []
    targets = candidate.get('outcomes') or []
    rate = candidate.get('translation_preservation')
    head = [_table([_row(label['preservation'], esc('%.4f' % rate if isinstance(rate, float) else '-')),
                    _row(label['source_language'], esc(group.get('source_language'))),
                    _row('source sha256', esc(str(group.get('source_sha256'))[:16]))])]
    if group.get('source_code'):
        head.append('<h4>%s</h4>%s' % (esc(label['source_program']), _code(group['source_code'])))
    if sources and len(sources) == len(targets):
        rows = '<tr><th>#</th><th>%s</th><th>%s</th><th>match</th></tr>' % (
            esc(label['source_output']), esc(label['target_output']))
        body = ''.join('<tr><td>%d</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
            index + 1, esc(_outcome(a)), esc(_outcome(b)),
            'yes' if a.get('kind') == b.get('kind') == 'value' and a.get('semantic_key') == b.get('semantic_key') else 'no')
            for index, (a, b) in enumerate(zip(sources, targets)))
        head.append('<h4>%s</h4><table>%s%s</table>' % (esc(label['per_input']), rows, body))
    return ''.join(head)


ALL_LANGUAGES = ('python3', 'c', 'cpp', 'java', 'javascript', 'csharp', 'golang', 'rust')


def _answer_block(lang, group):
    """Show what the verdict rests on: the shared answer and its per-language gates."""
    evidence = group.get('answer_evidence')
    if not isinstance(evidence, dict) or not evidence:
        return ''
    label = TEXT[lang]
    passing = set(evidence.get('reference_languages') or [])
    gates = evidence.get('language_gates') or {}
    for language, row in gates.items():
        if isinstance(row, dict) and row.get('gate') == 'Accepted' \
                and row.get('correct') == row.get('total') and not row.get('dropped_unrepresentable'):
            passing.add(language)
    missing = [language for language in ALL_LANGUAGES if language not in passing]
    rows = [_row(label['answer_level'], esc(evidence.get('evidence_level'))),
            _row(label['answer_source'], esc(evidence.get('answer_source') or '-')),
            _row(label['answer_sha'], esc(str(evidence.get('cases_sha256') or '-')[:16])),
            _row(label['answer_langs'], esc(', '.join(sorted(passing)) or label['none'])),
            _row(label['answer_missing'], esc(', '.join(missing) or label['none']))]
    parts = ['<h4>%s</h4>%s' % (esc(label['answer']), _table(rows))]
    if gates:
        gate_rows = ''.join(
            '<tr><td>%s</td><td>%s</td><td>%s/%s</td><td>%s</td></tr>' % (
                esc(language), esc((row or {}).get('gate')), esc((row or {}).get('correct')),
                esc((row or {}).get('total')), esc((row or {}).get('dropped_unrepresentable')))
            for language, row in sorted(gates.items()))
        parts.append('<table><tr><th>%s</th><th>gate</th><th>correct</th><th>dropped</th></tr>%s</table>'
                     % (esc(label['language']), gate_rows))
    limitations = evidence.get('limitations') or []
    if limitations:
        parts.append('<p class="muted">%s: %s</p>' % (
            esc(label['answer_limits']), esc('; '.join(str(x) for x in limitations))))
    return ''.join(parts)


def _candidate(lang, index, candidate, group=None):
    label = TEXT[lang]
    code = candidate.get('code')
    verdict = candidate.get('corpus_verdict') or candidate.get('verdict')
    parts = ['<section class="cand"><h3>%s %s</h3>' % (esc(label['candidates']), esc(index)),
             _table([_row(label['verdict'], _verdict(verdict)),
                     _row('AC', esc(candidate.get('corpus_passed', candidate.get('validation_passed')))),
                     _row('sha256', esc(str(candidate.get('code_sha256'))[:16]))])]
    # The combined verdict counts validation passes only, so its total is not the
    # number of passing cases; without this note the number reads as "1 of 4 passed".
    if (verdict or {}).get('correctness_order') == 'validation_then_probes':
        parts.append('<p class="note">%s</p>' % esc(
            '计分口径：只计验证用例的通过数；验证未全部通过时，探测用例不计分。'
            '所以这个数字不等于“通过的用例数”。'
            if lang == 'zh' else
            'Scoring: validation passes only. Probe cases are not counted unless every '
            'validation case passes, so this number is not the count of passing cases.'))
    parts.append('<h4>%s</h4>%s' % (esc(label['code']), _code(code) if isinstance(code, str) else esc('-')))
    if isinstance(candidate.get('corpus_counterexample'), dict):
        parts.append(_counterexample(lang, candidate['corpus_counterexample']))
    if group is not None and (group.get('source_outcomes') or group.get('source_code')):
        parts.append(_translation(lang, group, candidate))
    if candidate.get('full_execution_evidence'):
        parts.append('<h4>%s</h4><pre class="json">%s</pre>' % (
            esc(label['evidence']), pretty(candidate['full_execution_evidence'])))
    parts.append('</section>')
    return ''.join(parts)


def _derived(lang, result, spec):
    """Header block shared by rejudge and resume, which have no generate payload."""
    label = TEXT[lang]
    kind = result.get('kind')
    rows = []
    if kind == 'rejudge':
        corpus = result.get('corpus') or {}
        executor = result.get('executor') or {}
        rows = [_row(label['parent'], esc(result.get('parent_job_id'))),
                _row(label['mode'], esc(corpus.get('mode'))),
                _row(label['cases'], esc(corpus.get('cases'))),
                _row(label['corpus_sha'], esc(str(corpus.get('sha256'))[:16])),
                _row(label['calls'], esc(result.get('model_calls'))),
                _row('execution path', esc(executor.get('path'))),
                _row(label['verdict'], _verdict(result.get('verdict')))]
    else:
        rows = [_row(label['parent'], esc(result.get('resumed_from'))),
                _row(label['reused'], esc(spec.get('resume_reused_candidates'))),
                _row(label['rerun'], esc('%s %s' % (len(result.get('groups') or []), 'groups'))),
                _row(label['calls'], esc(result.get('model_calls'))),
                _row(label['corpus'], esc((spec.get('model_budget') or {}).get('policy') or 'frozen snapshot'))]
    body = [_table(rows)]
    if kind == 'rejudge' and spec.get('code') is not None:
        body.append('<h4>%s</h4>%s' % (esc(label['code']), _code(spec.get('code'))))
    if kind == 'rejudge':
        frozen = spec.get('frozen') or {}
        body.append('<h4>%s</h4><pre class="json">%s</pre>' % (
            esc(label['execution']), pretty({'frozen': frozen, 'executor': result.get('executor')})))
        evidence = frozen.get('answer_evidence')
        if isinstance(evidence, dict):
            body.append(_answer_block(lang, {'answer_evidence': evidence}))
    if isinstance(result.get('first_failure'), dict):
        body.append(_counterexample(lang, dict(result['first_failure'],
                                               actual_source=result['first_failure'].get('actual_source', 'not_collected'))))
    if result.get('note'):
        body.append('<p class="muted">%s</p>' % esc(result['note']))
    return '<section><h2>%s</h2>%s</section>' % (esc(label['derived']), ''.join(body))


def _advisories(lang, advisories):
    if not advisories:
        return ''
    items = []
    for item in advisories:
        if isinstance(item, dict):
            text = ' · '.join('%s=%s' % (key, item[key]) for key in
                              ('qid', 'status', 'reason_code', 'cases_sha256', 'report')
                              if item.get(key) not in (None, ''))
            items.append('<li>%s</li>' % esc(text or json.dumps(item, ensure_ascii=False)[:200]))
        else:
            items.append('<li>%s</li>' % esc(item))
    return '<h2>%s</h2><ul>%s</ul>' % (esc(TEXT[lang]['advisories']), ''.join(items))


def render(job, *, lang='en', children=(), advisories=()):
    """Render one job as a standalone document. Unknown fields degrade gracefully."""
    lang = 'zh' if lang == 'zh' else 'en'
    label = TEXT[lang]
    spec = job.get('spec') or {}
    result = job.get('result') or {}
    kind = spec.get('kind') or spec.get('workflow_version') or 'generate/translate'
    derived = result.get('kind') in ('rejudge', 'resume')
    parts = ['<!DOCTYPE html><html lang="%s"><head><meta charset="utf-8">' % lang,
             '<meta name="viewport" content="width=device-width,initial-scale=1">',
             '<title>%s · %s</title>' % (esc(label['title']), esc(job.get('title'))),
             '<style>body{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:24px;max-width:1080px;color:#222}',
             'h1{font-size:20px}h2{font-size:16px;margin-top:28px}b{font-weight:600}',
             'table{border-collapse:collapse;margin:8px 0}th,td{border:1px solid #ddd;padding:4px 8px;text-align:left;vertical-align:top}',
             'th{background:#f6f6f6;font-weight:600}pre{background:#f7f7f7;border:1px solid #e5e5e5;padding:8px;overflow:auto;white-space:pre-wrap}',
             '.muted{color:#666;font-size:12px}.matrix td{text-align:center}.cand{border-top:1px solid #eee;padding-top:12px;margin-top:12px}',
             '</style></head><body>',
             '<h1>%s</h1>' % esc(label['title']),
             '<p class="muted">%s</p>' % esc(label['offline']),
             _table([
                 _row(label['job'], esc(job.get('id'))),
                 _row(label['state'], esc(job.get('state'))),
                 _row(label['type'], esc(kind)),
                 _row(label['created'], esc(job.get('created_at'))),
                 _row(label['operator'], esc((job.get('operator') or spec.get('operator') or 'legacy/unknown'))),
                 _row(label['parent'], esc(spec.get('parent_job_id') or spec.get('resume_parent_job_id')
                                           or result.get('parent_job_id') or result.get('resumed_from') or '-')),
                 _row(label['children'], esc(', '.join(children) if children else label['none'])),
                 _row(label['model'], esc(spec.get('model_ids') or result.get('model') or '-')),
                 _row(label['qid'], esc(spec.get('qids') or spec.get('qid') or (result.get('candidate') or {}).get('qid') or '-')),
                 _row(label['language'], esc(spec.get('languages') or spec.get('language') or (result.get('candidate') or {}).get('language') or '-')),
             ])]

    if job.get('state') in ('failed', 'interrupted', 'cancelled') and job.get('error'):
        parts.append('<h2>%s</h2><p class="warn">%s</p>' % (esc(label['incomplete']), esc(job['error'])))
    if derived:
        parts.append(_derived(lang, result, spec))
    groups = result.get('groups') or []
    for gi, group in enumerate(groups):
        metrics = group.get('metrics') or {}
        parts.append('<section><h2>%s %d · q%s / %s</h2>' % (
            esc(label['candidates']), gi + 1, esc(group.get('qid')), esc(group.get('language'))))
        if metrics:
            parts.append(_table([
                _row(label['uncertainty'], esc(metrics.get('uncertainty'))),
                _row('method', esc(metrics.get('method'))),
                _row('sample / probe', esc('%s / %s' % (metrics.get('sample_count'), metrics.get('probe_count')))),
            ]))
            parts.append('<p class="muted">%s</p>' % esc(label['note']))
            if metrics.get('matrix'):
                parts.append('<h4>%s</h4>%s' % (esc(label['matrix']), _matrix(metrics['matrix'])))
        parts.append(_answer_block(lang, group))
        for ci, candidate in enumerate(group.get('candidates') or []):
            parts.append(_candidate(lang, ci + 1, candidate, group))
        parts.append('</section>')
    if not groups and not derived:
        parts.append('<h2>%s</h2><pre class="json">%s</pre>' % (esc(label['evidence']), pretty(result)))

    parts.append(_advisories(lang, advisories))
    limitations = result.get('limitations') or []
    if limitations:
        parts.append('<h2>%s</h2><ul>%s</ul>' % (
            esc(label['limitations']), ''.join('<li>%s</li>' % esc(x) for x in limitations)))

    # Only a job that actually produced this evidence may claim a live record.
    parts.append('<p class="muted">%s</p>' % esc(label['legacy'] if not result else label['live_now']))
    parts.append('<p class="muted">report %s · %s</p>' % (
        esc(VERSION), esc(datetime.now(timezone.utc).isoformat(timespec='seconds'))))
    parts.append('</body></html>')
    return ''.join(parts)
