"""One place that decides which execution entry a frozen job may reuse.

The original run picks its entry from the task interface:

  * leetcode_method -> a native adapter (deterministic replay, or a bridge that
    wraps the submitted source with a frozen adapter);
  * anything else   -> the portable JSON driver.

A rejudge or resume must replay through the *same* entry. Defaulting to the
portable driver when the original was native can resolve a helper function and
turn "wrong target function, correct helper" into a false Accepted.
"""
from __future__ import annotations

import json
from pathlib import Path

from local.common import load_reference
from local.harness.identity import image_digest
from local.lab import interface_policy
from local.lab import problem_packages as packages
from local.lab.behavior import sha

NATIVE_INTERFACE = 'leetcode_method'

PORTABLE = 'portable_json'
# The live pipeline (jobs.py) judges the full corpus with audited_judging. A replay
# must use the same program, otherwise 'rejudge reproduces the verdict' is false.
AUDITED = 'audited_judging'
COMBINED = 'combined_validation_probes'
DETERMINISTIC = 'native_deterministic'
BRIDGE = 'native_bridge'


class Blocked(Exception):
    """The frozen entry point cannot be replayed without guessing."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _reference_candidates(qid, language):
    """Deterministic sources for a bridge reference, in trust order."""
    yield 'repository', lambda: load_reference(qid, language)
    if language == 'javascript':
        def reviewed():
            from local.lab import javascript_references
            return javascript_references.SOURCES.get(qid)
        yield 'reviewed_javascript', reviewed


def restore_reference(plan, qid, language):
    """Recover a bridge reference without a model, if a verifiable copy exists."""
    wanted = plan.get('reference_sha256')
    if not isinstance(wanted, str):
        return None
    for _origin, loader in _reference_candidates(qid, language):
        try:
            candidate = loader()
        except (OSError, ValueError, KeyError):
            continue
        if isinstance(candidate, str) and sha(candidate) == wanted:
            return candidate
    return None


def _binding_problems(plan, group, cases):
    """A passed plan is only evidence for the corpus and image it was gated on."""
    binding = plan.get('binding')
    if not isinstance(binding, dict) or not binding:
        return ['计划缺少 binding，无法证明参考门禁覆盖了本任务']
    problems = []
    if binding.get('qid') != group.get('qid'):
        problems.append('计划绑定的题号 %r 与任务 %r 不一致' % (binding.get('qid'), group.get('qid')))
    if binding.get('language') != group.get('language'):
        problems.append('计划绑定的语言 %r 与任务 %r 不一致'
                        % (binding.get('language'), group.get('language')))
    if cases is not None and binding.get('cases_sha256') != sha(cases):
        problems.append('计划的参考门禁是在另一份语料上通过的（binding.cases_sha256 不符）')
    image = binding.get('image')
    if image and image != image_digest():
        problems.append('计划的参考门禁是在另一个判题镜像上通过的')
    return problems


def resolve(group, cases=None):
    """Return (plan, path). Raises Blocked when the entry cannot be replayed."""
    recorded = (group.get('executor') or {}).get('entry')
    if recorded == 'audited_judging':
        # Replay through the program that actually produced the parent verdict.
        return None, AUDITED
    if recorded == 'combined_validation_probes':
        # Replay it the way it was produced: observe, re-judge validation, merge.
        return None, COMBINED
    if recorded and recorded != 'audited_judging':
        raise Blocked('unknown_executor', '任务记录了未知的判题入口 %r' % (recorded,))
    try:
        # Missing interfaces are re-derived from the package; unknown ones block.
        interface, origin = interface_policy.resolve(
            group, derive=lambda: packages.code_interface(group.get('qid'), group.get('language')))
    except interface_policy.UnknownInterface as error:
        raise Blocked('unknown_interface', str(error)) from None
    group = dict(group, interface=interface, interface_origin=origin)
    plan = group.get('native_adapter')
    if interface != NATIVE_INTERFACE:
        return None, PORTABLE
    if not isinstance(plan, dict) or not plan:
        raise Blocked('missing_native_plan',
                      '原生接口任务缺少冻结执行计划；不能用 portable 驱动代替，'
                      '因为它可能解析到辅助函数并把错误的目标函数判成 AC')
    if plan.get('passed') is not True:
        raise Blocked('native_plan_not_passed', '冻结的原生计划未通过门禁，不能复用')
    problems = _binding_problems(plan, group, cases)
    if problems:
        raise Blocked('native_gate_binding_mismatch', '；'.join(problems))
    kind = plan.get('kind')
    if kind == 'deterministic':
        if not isinstance(plan.get('binding'), dict):
            raise Blocked('native_plan_unknown', '确定性原生计划缺少 binding，无法证明可重放')
        # Deterministic replay renders a driver from the signature and calls the
        # entry directly; it never needs the reference program.
        return plan, DETERMINISTIC
    if kind == 'bridge':
        qid, language = group.get('qid'), group.get('language')
        if all(isinstance(plan.get(key), str) for key in ('prefix', 'suffix')):
            restored = restore_reference(plan, qid, language)
            if restored is not None:
                plan = dict(plan, reference_code=restored, reference_restored=True)
                return plan, BRIDGE
        raise Blocked('bridge_dependency_missing',
                      '桥接计划的参考程序未持久化，且无法用可验证的仓库/审查参考确定性重建；'
                      '恢复不降级到 portable 入口')
    raise Blocked('native_plan_unknown', '未知的原生计划类型 %r' % (kind,))


def dependency_problems(group, entry, qid):
    """Corpus, contract and package must still describe one coherent set."""
    problems = []
    entry = entry or {}
    contract = group.get('input_contract')
    snapshot_contract = entry.get('input_contract')
    if contract is not None and snapshot_contract is not None and sha(contract) != sha(snapshot_contract):
        problems.append('冻结语料与任务记录的输入契约不一致')
    package_sha = entry.get('package_sha256')
    if package_sha:
        path = packages.DATA_DIR / ('%s.json' % qid)
        if not path.exists():
            problems.append('题包 %s 已不存在，无法证明冻结语料仍有效' % qid)
        else:
            try:
                row = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                row = {}
            if row.get('package_sha256') != package_sha:
                problems.append('题包 %s 在冻结之后被修改过' % qid)
    return problems
