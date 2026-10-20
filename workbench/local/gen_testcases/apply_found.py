# -*- coding: utf-8 -*-
r"""把 auto_fuzz 找到并收缩过的用例校验后补进语料。

流程与手工补用例完全一致，只是自动化了：
  1. 读 `local/results/auto_fuzz_cases.json`
  2. 按题去重
  3. **多语言差分投票校验**（`scale_expand.validate`）——保证期望值是对的
  4. 追加进 `cases.json`（带 `.bak_autofuzz` 备份）
  5. 可选：重判该题的 false_ac 槽位，确认槽位真的翻正

用法
----
    python -m local.gen_testcases.apply_found                     # 干跑，只看
    python -m local.gen_testcases.apply_found --apply             # 真正入库
    python -m local.gen_testcases.apply_found --apply --verify    # 入库并复判
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from local.common import KEY_TO_LABEL, TESTCASES_DIR  # noqa: E402
from local.gen_testcases.auto_fuzz import violates_constraints  # noqa: E402
from local.gen_testcases.constraints import (check as _c_check,
                                              parse as _c_parse)
from local.gen_testcases.scale_expand import validate  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
FOUND = REPO / "local" / "results" / "auto_fuzz_cases.json"
LOCAL_DB = REPO / "local" / "dashboard" / "packages" / "server" / "data" / "local.db"
ALL_MODELS = REPO / "local" / "results" / "all_models"


def verify_slots(qid: int) -> None:
    """重判该题的 false_ac 槽位，报告有多少翻正。"""
    from local.judge import judge_one
    if not LOCAL_DB.exists():
        return
    c = sqlite3.connect(f"file:{LOCAL_DB}?mode=ro", uri=True)
    try:
        slots = list(c.execute(
            "SELECT model,lang FROM slots WHERE qid=? AND klass='false_ac'", (qid,)))
    finally:
        c.close()
    if not slots:
        print(f"    q{qid}: 库里没有 false_ac 槽位可复判")
        return

    def run(s):
        model, lang = s
        f = ALL_MODELS / model / "codes" / f"{qid}_{KEY_TO_LABEL[lang]}_1.txt"
        if not f.exists():
            return None
        try:
            return judge_one(f, "gen", 1000, "docker", 20)["ac_status"]
        except Exception:  # noqa: BLE001
            return None

    with ThreadPoolExecutor(max_workers=2) as ex:
        res = [r for r in ex.map(run, slots) if r]
    fixed = [r for r in res if r != "Accepted"]
    print(f"    q{qid}: 复判 {len(res)} 个 -> **{len(fixed)} 个不再 Accepted** "
          f"{dict(Counter(fixed))}")


def verify_candidate(qid: int, candidate: list[dict], backend: str,
                     workers: int = 2, run_timeout_s: int = 5,
                     baseline_corpus: list[dict] | None = None,
                     slot_plan: list[tuple] | None = None) -> dict:
    """Compare a fixed submission set, using fresh baseline and LC truth."""
    from local.judge import judge_one
    from local.harness.identity import verification_identity, result_errors
    import copy
    import hashlib
    candidate = copy.deepcopy(candidate)
    baseline_corpus = copy.deepcopy(baseline_corpus)
    def corpus_hash(cases):
        return hashlib.sha256(json.dumps(cases, sort_keys=True, ensure_ascii=True,
                                         allow_nan=False).encode()).hexdigest()
    from local.dashboard.scripts.judge_all_models import ORIG_DB
    if not LOCAL_DB.exists():
        return {"skipped": "no local.db"}
    if baseline_corpus is None:
        return {"skipped": "a fresh baseline corpus is required"}
    if backend != "docker":
        return {"skipped": "publication requires Docker"}
    con = sqlite3.connect(LOCAL_DB.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        slots = list(con.execute(
            "SELECT model,lang,cand,task,leetcode FROM slots WHERE qid=? "
            "AND lc_origin='submissions' AND local_origin='all_models'", (qid,)))
        if slot_plan is not None:
            expected = list(con.execute(
                "SELECT model,lang,cand,task,leetcode FROM slots WHERE qid=? "
                "AND lc_origin='submissions' AND local_origin='all_models' "
                "AND identity_status='current' AND task='gen' AND leetcode<>''", (qid,)))
            if len(slot_plan) != len(set(slot_plan)) or set(slot_plan) != set(expected):
                return {"skipped": "frozen current slot plan differs from database"}
            slots = slot_plan
    finally:
        con.close()
    valid_lc = {"Accepted", "Wrong Answer", "Compile Error", "Runtime Error",
                "Time Limit Exceeded", "Memory Limit Exceeded", "Output Limit Exceeded"}
    eligible = [s for s in slots if s[4] in valid_lc]
    plan, missing = [], []
    for model, lang, cand, task, lc in eligible:
        path = ALL_MODELS / model / "codes" / f"{qid}_{KEY_TO_LABEL[lang]}_{cand}.txt"
        item = {"model": model, "lang": lang, "cand": cand, "task": task, "leetcode": lc}
        if path.is_file():
            plan.append((path, item))
        else:
            missing.append(item)

    def run(entry):
        path, item = entry
        context = dict(qid=qid, model=item["model"], lang=item["lang"],
                       attempt=item["cand"], task=item["task"], code_path=path,
                       config={"max_cases": 1000, "run_timeout_s": run_timeout_s})
        try:
            before = verification_identity(ORIG_DB, **context)
            corpus_hashes = (corpus_hash(baseline_corpus), corpus_hash(candidate))
            def judge(cases):
                out = judge_one(path, item["task"], 1000, backend, run_timeout_s,
                                cases_override=cases)
                if result_errors(out, before):
                    raise ValueError(", ".join(result_errors(out, before)))
                if out["total_testcases"] != len(cases):
                    raise ValueError("not all requested cases were executed")
                return out["ac_status"]
            base = judge(baseline_corpus)
            current = judge(candidate)
            if (before != verification_identity(ORIG_DB, **context)
                    or corpus_hashes != (corpus_hash(baseline_corpus), corpus_hash(candidate))):
                raise ValueError("judging inputs changed during verification")
        except Exception as e:
            return {**item, "outcome": "judge_error", "error": str(e)}
        was_ac, now_ac, lc_ac = base == "Accepted", current == "Accepted", item["leetcode"] == "Accepted"
        outcome = "same"
        if was_ac and not now_ac:
            outcome = "broken" if lc_ac else "fixed"
        elif not was_ac and now_ac:
            outcome = "recovered" if lc_ac else "regressed"
        return {**item, "outcome": outcome, "baseline": base, "candidate": current,
                "identity": before, "baseline_sha256": corpus_hashes[0],
                "candidate_sha256": corpus_hashes[1]}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(run, plan))
    counts = {key: sum(r["outcome"] == key for r in results)
              for key in ("fixed", "broken", "recovered", "regressed", "same", "judge_error")}
    counts.update(planned=len(eligible), executed=len(results)-counts["judge_error"],
                  missing=len(missing), missing_detail=missing, results=results,
                  excluded_no_lc=len(slots)-len(eligible), baseline="fresh_same_profile",
                  run_timeout_s=run_timeout_s)
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(
        description="把对拍找到的用例校验后补进语料。"
                    "候选语料先在内存里验证，通过才写盘。")
    ap.add_argument("--file", default=str(FOUND))
    ap.add_argument("--apply", action="store_true", help="不传则只干跑")
    ap.add_argument("--verify", action="store_true",
                    help="入库前在内存里双向验证（**--apply 现在强制要求它**；需要 docker）")
    ap.add_argument("--no-verify", action="store_true",
                    help="显式跳过防退化复判（默认不允许；会打印警告并可能被拒绝）")
    ap.add_argument("--force", action="store_true",
                    help="即使净收益为负也写入")
    ap.add_argument("--allow-unparsed", action="store_true",
                    help="即使题面有解析不出来的约束也发布（默认拒绝）")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--backend", default="docker")
    ap.add_argument("--run_timeout_s", type=int, default=5,
                    help="与 judge_all_models 保持一致，默认 5s（B-004：此前固定 20s，两边不同代）")
    ap.add_argument("--db-baseline", action="store_true",
                    help="基线改为读 local.db 的历史判定（无版本，条数可能与当前不同；仅供对照）")
    args = ap.parse_args()

    src = Path(args.file)
    if not src.exists():
        sys.exit(f"找不到 {src}（先跑 auto_fuzz --shrink）")
    data = json.loads(src.read_text(encoding="utf-8"))
    print(f"读入 {src.name}：{len(data)} 题\n")

    total_added = 0
    total_fixed = total_broken = 0
    # B2-001：这个计数器**必须初始化**。我的正则补丁找的是 `total_fixed = 0`，
    # 而实际代码是 `total_fixed = total_broken = 0`，于是没插进去，
    # 闸门一执行就 `UnboundLocalError`（dry-run 都会崩，退出码 1）。
    skipped_unparsed = 0
    refused_coverage = 0
    refused_verify = 0
    for qs, items in sorted(data.items(), key=lambda kv: -len(kv[1])):
        qid = int(qs)
        verify_skipped_note = False
        vr = None
        forced_reasons = []
        # 去重：不同模型可能收缩出同一个用例
        uniq, seen = [], set()
        for it in items:
            sig = repr(sorted(it["args"].items()))
            if sig not in seen:
                seen.add(sig)
                uniq.append({"args": it["args"],
                             "expected": it.get("expected")})
        p = TESTCASES_DIR / str(qid) / "cases.json"
        if not p.exists():
            print(f"q{qid}: 无 cases.json，跳过")
            continue
        old_bytes = p.read_bytes()
        orig = json.loads(old_bytes)
        # B2-008：与**现有语料**去重，而不只做批内去重。
        # 此前只比 `uniq` 内部，于是同一输入的用例可以反复入库 ——
        # 审查代理 B 实测现语料有 **29 条重复 args（16 题）**，其中
        # q2588 两条同 args 的用例 `votes` 还不一样（6 vs 8 语言），
        # 等于同一输入的用例身份不一致。
        have = {repr(sorted(c.get("args", {}).items())) for c in orig}
        before_n = len(uniq)
        uniq = [c for c in uniq
                if repr(sorted(c["args"].items())) not in have]
        if before_n != len(uniq):
            print(f"    与现有语料去重：{before_n} -> {len(uniq)} 条"
                  f"（已有 {before_n - len(uniq)} 条同输入的用例）")
        # 入库前再挡一道：违反题面约束的用例会让"假设了该约束"的正确解被判错。
        bad = [(c, why) for c in uniq
               for why in [violates_constraints(qid, c)] if why]
        if bad:
            for c, why in bad:
                print(f"    丢弃（违反题面约束：{why}）："
                      f"{json.dumps(c['args'], ensure_ascii=False)[:80]}")
            uniq = [c for c in uniq if violates_constraints(qid, c) is None]
        print(f"q{qid}: 候选 {len(uniq)} 条（原语料 {len(orig)} 条）")
        if not uniq:
            continue

        kept, stats = validate(qid, uniq, args.backend, verbose=False)
        print(f"    差分校验通过 {len(kept)}/{len(uniq)}  {stats}")
        if not kept:
            continue
        for c in kept:
            print(f"      {json.dumps(c, ensure_ascii=False)[:110]}")

        # 先验证、后发布：在内存里用候选语料重判该题全部槽位，**双向**统计
        #
        # D3-a（B-104，P1）：`--verify` 原来是**可选**的，省略它时直接写盘，
        # 防退化复判完全不执行。B 用"炸弹桩"实测：不带 --verify 时
        # `verify_candidate` 一次都没被调用，语料照写。
        # 现在：`--apply` **必须**带 `--verify`；确实要跳过必须显式 `--no-verify`
        # 并打印警告（否则"跳过验证"会变成事实上的默认）。
        if args.apply and not args.verify:
            # **A-113（P1）**：我第一版把 `--no-verify` 写成"打印警告后照常写盘" ——
            # A 指出这正是本批次要消灭的缺陷类型："保护看起来存在、实际无效"
            # （manifest 验收③写的是"正式发布**强制**复判"，没有例外条款）。
            # 现在：跳过复判必须**同时**显式 `--no-verify` **和** `--force`，
            # 并把"本次发布未复判"落进 meta.json（可查），而不是一句警告。
            if not getattr(args, "no_verify", False):
                print("    **--apply 强制要求 --verify**（防退化必须真的跑过）。"
                      "确实要跳过需要**同时**加 --no-verify 与 --force")
                refused_verify += 1
                continue
            if not args.force:
                print("    **--no-verify 必须与 --force 同时使用**"
                      "（单独使用不写盘）")
                refused_verify += 1
                continue
            print("    **警告：本次发布**未做防退化复判**（--no-verify --force）"
                  "—— 会写进 meta.json 以便事后发现**")
            verify_skipped_note = True
            forced_reasons.append("verification explicitly skipped")

        if args.verify:
            cand = orig + kept
            # B-004：**基线必须同代**。默认用当前磁盘语料在**同一进程、同一超时、
            # 同一后端**下重判作为基线 —— 而不是读 `local.db` 的历史值
            # （那一列没有语料/判题器版本，条数可能与当前不同；实测 52 个
            # (qid,total_testcases) 组不符，q2140 的 88 行全是 6 条语料时代的）。
            # 传 --db-baseline 可退回旧行为（仅供对照，不建议）。
            base = None
            if not getattr(args, "db_baseline", False):
                p_cur = TESTCASES_DIR / str(qid) / "cases.json"
                if p_cur.exists():
                    base = json.loads(p_cur.read_text(encoding="utf-8"))
            vr = verify_candidate(qid, cand, args.backend, args.workers,
                                  run_timeout_s=args.run_timeout_s,
                                  baseline_corpus=base)
            if base is None:
                print(f"    注意：基线取自 local.db（**无版本，条数可能与当前不同**）")
            if "skipped" in vr:
                print(f"    跳过双向验证：{vr['skipped']}")
                # B-003：验证**没跑成**不能当成零退化。此前 `[r for r in ... if r]`
                # 会把异常/缺代码/DB 缺失全部丢掉，于是 {fixed:0, broken:0} 通过门槛。
                if not args.force:
                    print("    **验证未执行，拒绝入库**（需 --force 强制）")
                    refused_verify += 1
                    continue
                forced_reasons.append(vr["skipped"])
            else:
                fixed = vr.get("fixed", 0)
                broken = vr.get("broken", 0)
                regressed = vr.get("regressed", 0)
                errs = vr.get("judge_error", vr.get("errors", 0))
                planned = vr.get("planned", 0)
                executed = vr.get("executed", 0)
                total_fixed += fixed
                total_broken += broken
                print(f"    双向验证：计划 {planned}  实际完成 {executed}  "
                      f"缺代码 {vr.get('missing', 0)}"
                      f"  异常 {errs}")
                print(f"              修好 {fixed}  弄坏 {broken}  "
                      f"（false_wa 转正 {vr.get('recovered',0)}  退步 {regressed}）")
                # Every planned, comparable submission must finish under the same profile.
                block: list[str] = []
                if executed != planned:
                    block.append(f"验证覆盖不足：{executed}/{planned}")
                if vr.get("missing", 0):
                    block.append(f"{vr['missing']} 个必需槽位缺代码")
                if planned == 0:
                    block.append("无验证对象（该题在 slots 里没有可解析代码的槽位）")
                if errs > 0:
                    block.append(f"有 {errs} 个槽位判题异常（没验证成）")
                if broken > 0:
                    block.append(f"弄坏 {broken} 个槽位")
                if regressed > 0:
                    block.append(f"新增 false_ac {regressed} 个")
                if block and args.force:
                    forced_reasons.extend(block)
                if block and not args.force:
                    print(f"    **不入库**：{'；'.join(block)}（需 --force 强制）")
                    refused_coverage += 1
                    continue

        # B-001 发布闸门：题面里有解析不出来的约束 = **未知**，不得自动发布。
        #
        # **D4（B-106，P2）**：这里原来读的是 `_c_parse(qid).get("_unparsed")`
        # —— **原始**列表，**没有**过滤 `VERIFIED[qid]["_verified_lines"]`。
        # 于是 q2616（唯一一行 `0 <= p <= (nums.length)/2` 已被人工核验、
        # `check` 也确实执行）被**永久误拦**。改用过滤后的 `unparsed(qid)`。
        # 同一处错误还在 `scale_expand.py`，本轮一并修。
        from local.gen_testcases.constraints import unparsed as _c_unparsed
        unp = _c_unparsed(qid)
        if unp and not getattr(args, "allow_unparsed", False):
            print(f"    **该题有 {len(unp)} 行约束未能解析，按未知处理，"
                  f"{'不发布' if args.apply else '将不会发布'}**")
            for line in unp[:3]:
                print(f"      {line[:90]}")
            print(f"      （确实要发布请加 --allow-unparsed，并在日志里说明依据）")
            skipped_unparsed += 1
            continue

        if unp:
            forced_reasons.append("unparsed constraints explicitly allowed")

        if not args.apply:
            total_added += len(kept)
            continue

        orig.extend(kept)
        # Persist the bypass and its evidence; terminal warnings are not an audit trail.
        from datetime import datetime
        import hashlib
        mp = p.parent / "meta.json"
        meta = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
        if not isinstance(meta, dict):
            raise ValueError(f"Invalid metadata: {mp}")
        meta["n_cases"] = len(orig)
        publication = {
            "recorded_at": datetime.now().isoformat(timespec="seconds"),
            "status": "unverified" if forced_reasons or verify_skipped_note else "verified",
            "reasons": forced_reasons, "verification": vr,
            "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
            "old_sha256": hashlib.sha256(old_bytes).hexdigest(),
            "new_sha256": hashlib.sha256(json.dumps(orig, ensure_ascii=False, indent=1).encode("utf-8")).hexdigest(),
            "run_timeout_s": args.run_timeout_s,
        }
        meta.setdefault("publications", []).append(publication)
        from local.gen_testcases.corpus_io import publish_cases
        publish_cases(p, orig, meta, old_bytes)
        total_added += len(kept)
        print(f"    已追加 -> {len(orig)} 条（已保留发布备份）")

    mode = "已入库" if args.apply else "干跑（加 --apply 才写入）"
    if args.verify:
        print(f"\n净收益：修好 {total_fixed}，弄坏 {total_broken}")
    print(f"{mode}：共 {total_added} 条用例")
    # B2-001：被闸门拦住的题必须在结尾汇总里出现，否则读者以为"全入库了"
    if skipped_unparsed:
        print(f"另有 **{skipped_unparsed} 题因含未解析约束被拒绝发布**"
              f"（题面里有解析不出来的约束 → 按未知处理，不自动发布）。"
              f"确认要发布请加 --allow-unparsed，并在日志里说明依据。")
    # D3：另外两类拒绝也要报出来，否则"0 条入库"看起来像"没有候选"
    if refused_verify:
        print(f"另有 **{refused_verify} 题因未带 --verify 被拒绝发布**"
              f"（防退化复判是强制的；确实要跳过请显式加 --no-verify）。")
    if refused_coverage:
        print(f"另有 **{refused_coverage} 题因验证覆盖不足被拒绝发布**"
              f"（无验证对象 / 判题异常 / 必需代码缺失 / 弄坏 / 退步）。")

    if args.apply and (refused_verify or refused_coverage or skipped_unparsed):
        raise SystemExit(3)


if __name__ == "__main__":
    main()
