"""Expandable lab catalog, isolated from the fixed FT100 benchmark and its identities."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import platform

from local.common import (DESCRIPTIONS_DIR, KEY_TO_LABEL, LANGS, REPO_ROOT,
                          load_ft_test_qids, load_reference, load_snippet)
from local.harness.identity import judge_source_closure
from local.gen_testcases.extract_examples import extract_from_prompt
from local.judge import load_cases as benchmark_cases
from local.lab.behavior import sha

EXTENSION_FILE = Path(__file__).with_name('data') / 'catalog_extension.json'


def _extension(*, _judge_closure=None):
    try:
        data = json.loads(EXTENSION_FILE.read_text(encoding='utf-8'))
        identity = data['identity']
        closure=dict(judge_source_closure()) if _judge_closure is None else _judge_closure
        if (data.get('version') != 1 or identity['judge_closure'] != closure
                or identity['host_python'] != platform.python_version()
                or identity['policy'] != 'official-examples-scalar-dual-reference-v1'):
            return {}, '扩展语料的验证环境已变化，需要重新运行参考门禁'
        return {r['qid']: {**r, 'gate_image': identity['image']} for r in data['problems']}, ''
    except (OSError, ValueError, KeyError, TypeError):
        return {}, '尚无可用的扩展语料门禁记录'


def _fresh(row):
    try:
        qid, binding = row['qid'], row['bindings']
        source = DESCRIPTIONS_DIR / row['source']
        description = source.read_text(encoding='utf-8')
        official = {sha(c) for c in extract_from_prompt(description)}
        return (row['cases_sha256'] == sha(row['cases'])
                and source.parent.name == str(qid)
                and len({sha(c['args']) for c in row['cases']}) >= 3
                and all(sha(c) in official for c in row['cases'])
                and binding['description_sha256'] == sha(description)
                and all(binding['snippets_sha256'][lang] == sha(load_snippet(qid, lang)) for lang in LANGS)
                and {'python3', 'cpp'} <= set(row['languages'])
                and all(binding['references_sha256'][lang] == sha(load_reference(qid, lang)) for lang in row['languages'])
                and all(any(g['language'] == lang and g['state'] == 'SUCCESS' and g['status'] == 'Accepted'
                            and g['total'] == g['correct'] == len(row['cases']) and not g['dropped_unrepresentable']
                            for g in row['gates']) for lang in row['languages']))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def extension_row(qid):
    rows, reason = _extension()
    row = rows.get(qid)
    if row is None or not _fresh(row):
        raise ValueError(reason or f'q{qid} 扩展语料尚未就绪或证据已失效，请重新运行参考门禁')
    return row


def base_cases(qid):
    if qid in load_ft_test_qids():
        return benchmark_cases(qid)
    try:
        return deepcopy(extension_row(qid)['cases'])
    except ValueError:
        return None


def load_cases(qid):
    from local.lab.testcase_workflow import read_bundle
    row = read_bundle(qid)
    return deepcopy(row['cases']) if row else base_cases(qid)


def require_languages(qid, languages, *, image=None):
    from local.lab.testcase_workflow import read_bundle
    generated = read_bundle(qid)
    if generated and image is not None and generated['image'] != image:
        raise ValueError(f'q{qid} 补充测试的判题镜像已变化，需启用自动补充测试重做门禁')
    if generated:
        if set(languages) <= set(generated['languages']):
            return
        raise ValueError(f'q{qid} 补充测试尚未完成所选语言参考门禁，请启用自动补充测试重新验证')
    if qid in load_ft_test_qids():
        return
    row = extension_row(qid)
    missing = set(languages) - set(row['languages'])
    if missing:
        raise ValueError(f'q{qid} 尚未验证这些语言：' + '、'.join(KEY_TO_LABEL[l] for l in sorted(missing)))
    if image is not None and row['gate_image'] != image:
        raise ValueError(f'q{qid} 判题镜像已变化，需重新运行参考门禁')


def evidence(qid):
    from local.lab.testcase_workflow import read_bundle
    generated = read_bundle(qid)
    if generated:
        return {'scope': 'ft100' if qid in load_ft_test_qids() else 'extension',
                'evidence_level': 'independent_oracle_and_references', 'generated_count': len(generated['generated_cases']),
                'cases_sha256': generated['cases_sha256'], 'generated_sha256': generated['generated_sha256'],
                'binding': generated['binding'], 'gate_image': generated['image'], 'gates': generated['gates'],
                'independent_oracle': generated['independent_oracle'], 'llm_provided_expected': False,
                'leetcode_alignment': 'not_measured',
                'notice': '包含模型生成的非公开补充输入，预期答案由独立算法计算，并通过参考解门禁；未确认与 LeetCode 隐藏测试判定一致'}
    if qid in load_ft_test_qids():
        return {'scope': 'ft100', 'evidence_level': 'curated_local_corpus',
                'notice': '固定历史评测集；本地验证不等于 LeetCode 隐藏测试'}
    row = extension_row(qid)
    return {'scope': 'extension', 'evidence_level': 'official_examples_only', 'source': row['source'],
            'admission_builder_sha256': row.get('admission_builder_sha256'),
            'cases_sha256': row['cases_sha256'], 'bindings': row['bindings'], 'gate_image': row['gate_image'],
            'gates': row['gates'], 'notice': '扩展题仅验证已在题面和提示词中公开的官方示例，双语言参考解门禁已通过；验证输入与探测分离，仍不能推断隐藏测试正确率，低不确定性也可能来自输入覆盖不足'}


def lab_package_evidence(qid,*,_read_context=None):
    """Separate live lab evidence from the immutable historical/base catalog."""
    from local.lab import problem_packages
    try:
        path=problem_packages.DATA_DIR/f'{qid}.json'
        stored=json.loads(path.read_text(encoding='utf8'))
        row=problem_packages.read(qid,stored['binding']['image'],descriptor=stored['descriptor'],_catalog_context=_read_context)
        if not row:return None
        current=problem_packages.describe(qid)
        if row['descriptor']!=current:return None
        return {'evidence_level':row['evidence_level'],'case_count':len(row['cases']),'generated_count':row['generated_count'],
                'package_sha256':row['package_sha256'],'reference_languages':row['reference_languages'],
                'execution_protocol':row.get('execution_protocol'),'limitations':row['limitations']}
    except (OSError,ValueError,TypeError,KeyError):return None


def protocol_evidence(qid):
    row=lab_package_evidence(qid)
    return row if row and row['evidence_level']=='reviewed_protocol_oracles' else None


def catalog():
    from local.lab.testcase_workflow import read_bundle, DATA_DIR
    from local.lab.input_contracts import QIDS, require
    from local.lab import problem_io
    from local.lab import problem_packages
    from local.lab.problem_packages import DATA_DIR as PACKAGE_DIR
    ft = set(load_ft_test_qids())
    closure=dict(judge_source_closure())
    rows, warning = _extension(_judge_closure=closure)
    try:read_context=problem_packages.CatalogReadContext()
    except (OSError,ValueError) as error:
        read_context=None;warning=warning or str(error)
    index_path = Path(__file__).with_name('data') / 'problem_index.json'
    if not index_path.exists():
        from local.tools.inspect_lab_catalog import write_index
        metadata = write_index()
    else:
        metadata = json.loads(index_path.read_text(encoding='utf-8'))
    problems = []
    generated_qids = {int(p.stem) for p in DATA_DIR.glob('*.json') if p.stem.isdigit()}
    package_qids={int(p.stem) for p in PACKAGE_DIR.glob('*.json') if p.stem.isdigit()}
    for item in metadata:
        qid, title = item['qid'], item['title']
        row = rows.get(qid)
        if qid in ft:
            cases = benchmark_cases(qid) or []
            scope, level, languages = 'ft100', 'curated_local_corpus', list(LANGS) if cases else []
        elif row and _fresh(row):
            cases = row['cases']
            scope, level, languages = 'extension', 'official_examples_only', row['languages']
        else:
            cases, scope, level, languages = [], 'pending', 'not_ready', []
        generated=(read_bundle(qid,_base_cases=cases,_judge_closure=closure) if qid in generated_qids else None)
        if generated:
            cases, level, languages = generated['cases'], 'independent_oracle_and_references', generated['languages']
            scope = 'ft100' if qid in ft else 'extension'
        can_generate, generation_reason = False, '待补经过审查的输入约束与独立答案算法'
        if qid in QIDS:
            try:
                require(qid)
                can_generate, generation_reason = True, ''
            except (ValueError, OSError) as error:
                generation_reason = str(error)
        problems.append({'qid': qid, 'title': title, 'difficulty': item['difficulty'],
                         'tags': item['tags'], 'corpus_cases': len(cases),
                         'scope': scope, 'evidence_level': level, 'available_languages': languages,
                         'ready': bool(cases and languages), 'generated_cases': len(generated['generated_cases']) if generated else 0,
                         'test_generation_available': can_generate, 'test_generation_reason': generation_reason,
                         'leetcode_alignment': 'not_measured'})
        problems[-1].update(generation_available=True,generation_languages=problem_io.languages(qid),
                            problem_kind=problem_io.kind(qid),translation_requires_generated_source=True)
        package=(lab_package_evidence(qid,_read_context=read_context) if qid in package_qids and read_context is not None else None)
        if package:problems[-1]['lab_evidence']=package
        if qid in QIDS and cases:
            from local.lab.correctness_audit import evidence as correctness_evidence
            problems[-1]['correctness_evidence'] = correctness_evidence(qid,cases)
    if read_context is not None:read_context.verify()
    if closure!=dict(judge_source_closure()):raise ValueError('目录读取期间正式判题来源已变化，请重新核验')
    counts = {'total': len(problems), 'ready': sum(p['ready'] for p in problems),
              'historical': sum(p['scope'] == 'ft100' for p in problems),
              'extension': sum(p['scope'] == 'extension' for p in problems),
              'generated_ready': sum(p['generated_cases'] >= 12 for p in problems),
              'can_generate_tests': sum(p['test_generation_available'] for p in problems)}
    counts['can_generate']=len(problems)
    counts['protocol_ready']=sum(p.get('lab_evidence',{}).get('evidence_level')=='reviewed_protocol_oracles' for p in problems)
    counts['independent_package_ready']=sum(bool(p.get('lab_evidence')) and p['lab_evidence']['evidence_level']!='reviewed_protocol_oracles' for p in problems)
    return {'problems': problems, 'languages': [{'key': l, 'label': label} for l,label in problem_io.LANGUAGES.items()],
            'counts': counts, 'warning': warning}
