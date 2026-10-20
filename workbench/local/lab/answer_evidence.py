"""Per-problem answer evidence, shared by every language and independent of candidates.

The answer of a problem lives in its frozen cases: the expected outputs. That part
is language-neutral and must be established once. What differs per language is the
reference execution -- calling convention, types, serialisation -- and that is what
the per-language gate records.

This extends the existing answer_evidence block instead of introducing a rival
structure: the same evidence_level / reference_languages / limitations fields, plus
a language_gates map that says, per language, whether that language's reference
reproduced the shared expected outputs, and on which bytes.
"""
from __future__ import annotations

from local.lab.behavior import sha

VERSION = 'answer-evidence-v1'
ACCEPTED = 'Accepted'
# Risks that every finite, self-generated answer set carries. They are written
# into the record rather than left implicit.
BASE_LIMITATIONS = ('finite_tests_not_proof', 'oracle_agreement_can_share_errors')


def block(cases, *, evidence_level, source, limitations=(), reference_languages=()):
    """The shared half: one answer for all languages."""
    return {
        'version': VERSION,
        'evidence_level': evidence_level,
        'answer_source': source,
        'cases_sha256': sha(cases),
        'case_count': len(cases),
        'reference_languages': list(reference_languages),
        'limitations': list(dict.fromkeys(list(BASE_LIMITATIONS) + list(limitations))),
        'language_gates': {},
    }


def record_language(evidence, language, verdict, *, reference_sha256, interface,
                    snippet_sha256=None, cases_sha256=None):
    """Record one language's reference run against the shared answer."""
    meta = verdict.get('_meta') or {}
    row = {
        'interface': interface,
        'gate': verdict.get('ac_status'),
        'state': verdict.get('state'),
        'correct': verdict.get('total_correct'),
        'total': verdict.get('total_testcases'),
        'dropped_unrepresentable': meta.get('dropped_unrepresentable'),
        'reference_sha256': reference_sha256,
        'snippet_sha256': snippet_sha256,
        'cases_sha256': cases_sha256 or evidence['cases_sha256'],
        'error': (meta.get('error') or '')[:300],
    }
    evidence.setdefault('language_gates', {})[language] = row
    if row['gate'] == ACCEPTED and row['correct'] == row['total'] and not row['dropped_unrepresentable']:
        languages = set(evidence.get('reference_languages') or []) | {language}
        evidence['reference_languages'] = sorted(languages)
    return row


def normalize(evidence):
    """Accept the legacy block (reference_languages only) and the new one alike.

    Stored jobs predate per-language gates: they only list which languages
    reproduced the answer. That list is still real evidence, so it is mapped to
    gate rows marked legacy rather than being discarded.
    """
    if not isinstance(evidence, dict) or not evidence:
        return None
    if isinstance(evidence.get('language_gates'), dict):
        return evidence
    out = dict(evidence, language_gates={})
    for language in evidence.get('reference_languages') or []:
        out['language_gates'][language] = {'gate': ACCEPTED, 'state': 'SUCCESS',
                                           'correct': None, 'total': None,
                                           'dropped_unrepresentable': None, 'legacy': True}
    return out


def group_problems(group, language, cases=None, route=None):
    """Why this group's language may not rest on an independent answer.

    SQL and shell answers are established across dialects: the oracle languages
    need not include the dialect under test (mysql judged against sqlite+python
    agreement is normal). Requiring the judged language to appear there would
    reject correct evidence, so that check only applies to code routes, where the
    reference must implement the same callable contract in the same language.
    """
    evidence = normalize((group or {}).get('answer_evidence'))
    if evidence is None:
        return ['该题没有答案依据记录，不能签发新判定']
    if route in ('sql', 'shell'):
        return []
    return problems(evidence, language, cases)


def passes(evidence, language):
    row = (evidence.get('language_gates') or {}).get(language)
    return bool(row) and row.get('gate') == ACCEPTED and row.get('correct') == row.get('total') \
        and not row.get('dropped_unrepresentable')


def problems(evidence, language, cases=None):
    """Why a verdict in this language cannot rest on this answer, if it cannot."""
    reasons = []
    # Legacy blocks carry no cases digest; their corpus identity lives on the
    # group's correctness evidence instead, so that check is skipped here.
    if cases is not None and evidence.get('cases_sha256') and evidence['cases_sha256'] != sha(cases):
        reasons.append('答案依据与本次语料不是同一份（cases_sha256 不符）')
    row = (evidence.get('language_gates') or {}).get(language)
    if not row:
        reasons.append('该语言没有参考执行记录')
    elif row.get('gate') != ACCEPTED:
        reasons.append('该语言参考执行未通过：%s（%s/%s）'
                       % (row.get('gate'), row.get('correct'), row.get('total')))
    elif row.get('correct') != row.get('total'):
        reasons.append('该语言参考执行只通过 %s/%s' % (row.get('correct'), row.get('total')))
    elif row.get('dropped_unrepresentable'):
        reasons.append('该语言有 %s 条用例无法表示' % row.get('dropped_unrepresentable'))
    return reasons


def usable(evidence, language, cases=None):
    return not problems(evidence, language, cases)


def summary(evidence):
    gates = evidence.get('language_gates') or {}
    return {'version': VERSION,
            'cases_sha256': evidence.get('cases_sha256'),
            'case_count': evidence.get('case_count'),
            'answer_source': evidence.get('answer_source'),
            'evidence_level': evidence.get('evidence_level'),
            'passing_languages': sorted(lang for lang in gates if passes(evidence, lang)),
            'failing_languages': sorted(lang for lang in gates if not passes(evidence, lang)),
            'no_reference_languages': sorted(lang for lang in ('python3', 'c', 'cpp', 'java',
                                                               'javascript', 'csharp', 'golang', 'rust')
                                              if lang not in gates),
            'limitations': list(evidence.get('limitations') or [])}
