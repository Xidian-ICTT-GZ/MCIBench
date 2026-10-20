# -*- coding: utf-8 -*-
"""把对拍缓存汇总成最终差异报告（Markdown + CSV）。

缓存是唯一权威产物：即使长时间任务中途被中断，报告也能随时从缓存重建，
不依赖某次运行是否跑到了结尾。

    python -m local.audit.report
    python -m local.audit.report --task trans
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from local.common import REPO_ROOT, TESTCASES_DIR

AUDIT_DIR = REPO_ROOT / "local" / "results" / "historical_audit"
CACHE = AUDIT_DIR / "judged_cache.jsonl"
ACCEPTED = "Accepted"

KLASS_DOC = {
    "agrees": "本地与 LeetCode 判定一致",
    "same_neg": "双方都判不通过（类型可能不同；多为环境/编译差异）",
    "false_ac": "本地 AC、LeetCode 非 AC —— 本地用例太弱（覆盖不足）",
    "false_wa": "本地非 AC、LeetCode AC —— 本地用例太严，或判题器有缺陷",
    "no_corpus": "该题不在本地评测集内，无法对拍（应排除）",
    # 与仪表盘口径一致：LeetCode 侧没有判定记录时不参与一致性统计。
    # 此前会被算成 false_ac（本地 AC + LC 空），等于把"不知道"当成"不过"。
    "no_lc": "LeetCode 侧没有判定记录 —— 无对照，不参与一致性统计",
}


def classify(leetcode: str, local: str, qid: int) -> str:
    if not (TESTCASES_DIR / str(qid) / "cases.json").exists():
        # judge_one reports "Wrong Answer" for a missing corpus; without this
        # guard those slots masquerade as local-vs-LeetCode conflicts.
        return "no_corpus"
    if local and not leetcode:
        # 没有对照就没有一致性可言，单独归类而不是算成 false_ac。
        return "no_lc"
    if leetcode == local:
        return "agrees"
    if local == ACCEPTED:
        return "false_ac"
    if leetcode == ACCEPTED:
        return "false_wa"
    return "same_neg"


def load(task: str | None) -> list[dict]:
    if not CACHE.exists():
        sys.exit(f"缓存不存在: {CACHE}（先跑 historical_audit）")
    # The cache is append-only and a slot can be re-appended when its wide
    # verdict is added, so dedupe by key with last-write-wins.
    latest: dict[str, dict] = {}
    for line in CACHE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("key"):
            latest[r["key"]] = r
    out = []
    for r in latest.values():
        if not r.get("local"):
            continue
        if task and not r["key"].startswith(f"{task}:"):
            continue
        r["klass"] = classify(r["leetcode"], r["local"], r["qid"])
        if r["klass"] == "no_corpus":
            continue          # not auditable: problem outside FT_test
        out.append(r)
    return out


def md_table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="", choices=["", "gen", "trans"])
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()
    task = args.task or None

    recs = load(task)
    if not recs:
        sys.exit("缓存里没有匹配的记录")
    label = task or "全部"

    klasses = Counter(r["klass"] for r in recs)
    n = len(recs)
    agree = klasses.get("agrees", 0) + klasses.get("same_neg", 0)

    L: list[str] = []
    L.append(f"# 本地判题 vs LeetCode 差异报告（{label}）\n")
    L.append(f"样本 {n} 条槽位；本地重判用生产语料（≤30 用例）。\n")
    L.append(f"**总体一致率 = {agree}/{n} = {agree/n*100:.1f}%**\n")

    L.append("## 一、方向分类\n")
    L.append(md_table(["分类", "含义", "槽位", "占比"],
                      [[k, KLASS_DOC.get(k, ""), v, f"{v/n*100:.1f}%"]
                       for k, v in klasses.most_common()]))

    # confusion matrix
    L.append("\n## 二、混淆矩阵（行 = LeetCode，列 = 本地）\n")
    lset = sorted({r["leetcode"] for r in recs})
    cset = sorted({r["local"] for r in recs})
    m = defaultdict(int)
    for r in recs:
        m[(r["leetcode"], r["local"])] += 1
    rows = [[lc] + [m.get((lc, c), 0) for c in cset] for lc in lset]
    L.append(md_table(["LeetCode \\ 本地"] + cset, rows))

    for kind, title in (("false_ac", "三、覆盖不足（本地 AC / LeetCode 非 AC）"),
                        ("false_wa", "四、太严或判题器缺陷（本地非 AC / LeetCode AC）")):
        sub = [r for r in recs if r["klass"] == kind]
        L.append(f"\n## {title}\n")
        if not sub:
            L.append("无。\n")
            continue
        per_q = Counter(r["qid"] for r in sub)
        rows = []
        for q, c in per_q.most_common(args.top):
            langs = Counter(r["lang"] for r in sub if r["qid"] == q)
            rows.append([f"q{q}", c,
                         " ".join(f"{l}:{v}" for l, v in langs.most_common())])
        L.append(md_table(["题号", "槽位", "按语言"], rows))
        by_lang = Counter(r["lang"] for r in sub)
        L.append("\n按语言: " +
                 "、".join(f"`{l}` {v}" for l, v in by_lang.most_common()) + "\n")
        if kind == "false_ac":
            # What kind of LeetCode failure are we failing to reproduce? A
            # crash/limit verdict (RE/TLE/MLE) means the input was too small to
            # make the model's code fail at all -- i.e. a SCALE gap, not a
            # missing scenario.
            src = Counter(r["leetcode"] for r in sub)
            L.append("\n按 LeetCode 判定来源分解：\n")
            L.append(md_table(["LeetCode 判定", "槽位", "占比", "含义"],
                              [[k, v, f"{v/len(sub)*100:.0f}%",
                                {"Runtime Error": "输入太小，没能让代码崩溃（规模缺口）",
                                 "Time Limit Exceeded": "输入太小，跑不进时限（规模缺口）",
                                 "Memory Limit Exceeded": "输入太小，占不满内存（规模缺口）",
                                 "Wrong Answer": "缺能区分行为的场景",
                                 "Compile Error": "本地渲染/编译差异"}.get(k, "")]
                               for k, v in src.most_common()]))
            scale_like = sum(v for k, v in src.items()
                             if k in ("Runtime Error", "Time Limit Exceeded",
                                      "Memory Limit Exceeded"))
            L.append(f"\n**其中 {scale_like}/{len(sub)} "
                     f"（{scale_like/len(sub)*100:.0f}%）属于规模类**"
                     f"——LeetCode 上崩溃/超时，本地却通过，因为用例规模不足以触发。\n")
            gk = Counter(r.get("gap_kind", "未用全量用例评估") for r in sub)
            L.append("\n缺口性质（是否可用已有的全量用例修好，"
                     "需 `--wide_on_gap` 才会评估）：\n")
            L.append(md_table(["性质", "槽位"],
                              [[k, v] for k, v in gk.most_common()]))
            L.append("\n`confirmed_gap` 必须**新增场景**（多为输入规模不足），"
                     "单纯放宽用例数无效。\n")

    # per-run
    L.append("\n## 五、按 run\n")
    per_run = defaultdict(Counter)
    for r in recs:
        per_run[r.get("run", "?")][r["klass"]] += 1
    rows = []
    for run, c in sorted(per_run.items(), key=lambda x: -sum(x[1].values())):
        tot = sum(c.values())
        rows.append([run[:46], tot, c.get("false_ac", 0), c.get("false_wa", 0),
                     f"{(c.get('agrees',0)+c.get('same_neg',0))/tot*100:.1f}%"])
    L.append(md_table(["run", "槽位", "false_ac", "false_wa", "一致率"], rows))

    # ---- actionable: what KIND of case is missing ----
    L.append("\n## 六、补用例建议（覆盖缺口 × 规模诊断）\n")
    gap_q = Counter(r["qid"] for r in recs if r["klass"] == "false_ac")
    scale_p = REPO_ROOT / "local" / "results" / "scale_gap.json"
    scale = {}
    if scale_p.exists():
        scale = {int(r["qid"]): r for r in json.loads(
            scale_p.read_text(encoding="utf-8"))}
    if not gap_q:
        L.append("无覆盖缺口。\n")
    else:
        if not scale:
            L.append("> 未找到 `local/results/scale_gap.json`，先跑 "
                     "`python -m local.audit.scale_gap --json "
                     "local/results/scale_gap.json` 可获得规模诊断。\n")
        rows = []
        for q, c in gap_q.most_common(args.top):
            s = scale.get(q, {})
            ratio = s.get("ratio_len")
            over = s.get("cases_over_value_range", 0)
            over_sc = s.get("cases_over_bound_scalar", 0)
            max_len = s.get("max_len", 0)
            # scalar-only problems have no list argument: show "-" rather than a
            # misleading "0/declared"
            scale_txt = (f"{max_len}/{s.get('declared_len') or '-'}"
                         if max_len else "（无列表参数）")
            if ratio and ratio >= 10:
                rec_txt = f"**规模不足 {ratio:.0f}×** → 补大规模用例"
            elif over_sc:
                rec_txt = f"标量越界 {over_sc} 例 → 先清理（会让约束内正确解法判错）"
            elif over:
                rec_txt = f"值域越界 {over} 例 → 先清理再用约束内规模"
            else:
                rec_txt = "需新增**区分性场景**（规模不是主因）"
            rows.append([f"q{q}", c, scale_txt, over_sc or over, rec_txt])
        L.append(md_table(["题号", "false_ac", "语料最大长度/题面约束",
                           "值域越界用例", "建议"], rows))
        n_scale = sum(1 for q in gap_q if (scale.get(q, {}).get("ratio_len") or 0) >= 10)
        L.append(f"\n其中 **{n_scale}/{len(gap_q)}** 道题的缺口可由「补大规模用例」直接命中；"
                 f"其余需要新增能区分行为的场景。\n")

    # ---- same_neg: both fail, but the failure TYPE drifts ----
    sn = [r for r in recs if r["klass"] == "same_neg"]
    L.append(f"\n## 七、双方都失败但类型不同（same_neg，{len(sn)} 条）\n")
    if sn:
        tr = Counter((r["leetcode"], r["local"]) for r in sn)
        L.append("pass@k 不受影响（双方都是失败），但**失败类型分布**会漂移，"
                 "而论文要报告失败类型。主要转移：\n")
        L.append(md_table(["LeetCode", "本地", "槽位", "占 same_neg"],
                          [[a, b, n, f"{n/len(sn)*100:.0f}%"]
                           for (a, b), n in tr.most_common(8)]))
        scale_like = sum(1 for r in sn
                         if r["leetcode"] in ("Runtime Error",
                                              "Time Limit Exceeded",
                                              "Memory Limit Exceeded"))
        L.append(f"\n其中 **{scale_like}/{len(sn)}（{scale_like/len(sn)*100:.0f}%）"
                 f"是规模类**：LeetCode 上崩溃/超时，本地在更小的输入上给出别的判定。\n")

        # failure-type distribution drift over all slots that failed on both sides
        neg = [r for r in recs if r["klass"] in ("same_neg", "agrees")
               and r["leetcode"] != ACCEPTED]
        if neg:
            leet = Counter(r["leetcode"] for r in neg)
            loc = Counter(r["local"] for r in neg)
            tot = sum(leet.values())
            keys = sorted(set(leet) | set(loc))
            L.append(f"\n**失败类型分布漂移**（{tot} 个双方都失败的槽位）：\n")
            L.append(md_table(["判定", "LeetCode", "本地", "差值"],
                              [[k, f"{leet.get(k,0)/tot*100:.1f}%",
                                f"{loc.get(k,0)/tot*100:.1f}%",
                                f"{(loc.get(k,0)-leet.get(k,0))/tot*100:+.1f}pp"]
                               for k in keys]))
            L.append("\n本地会**少报 Runtime Error、多报 Wrong Answer**——"
                     "因为用例规模不足以让代码崩溃，崩溃被观察成了答错。\n")

    L.append("\n## 八、说明\n")
    L.append("- `false_ac` 是补用例的主要目标；`false_wa` 指向语料期望值或判题器缺陷。\n")
    L.append("- 历史 `PENDING`/`REVOKED` 等非规范判定应先过滤，它们不在 "
             "`clean_results.py` 的 7 个规范值内。\n")
    L.append("- LeetCode 不告知失败用例，时限口径也不同，runtime/memory 不可直接比较。\n")
    L.append("- 补用例须走 `local.gen_testcases.differential` 全套校验后入库。\n")

    out_md = AUDIT_DIR / f"report_{label}.md"
    out_md.write_text("\n".join(L), encoding="utf-8")

    fields = ["run", "qid", "lang", "src", "tgt", "cand", "leetcode", "local", "klass"]
    out_csv = AUDIT_DIR / f"report_{label}.csv"
    with out_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in recs:
            w.writerow(r)

    print(f"样本 {n}  一致率 {agree/n*100:.1f}%")
    for k, v in klasses.most_common():
        print(f"  {k:12s} {v:6d}  {KLASS_DOC.get(k,'')}")
    print(f"\n-> {out_md}")
    print(f"-> {out_csv}")


if __name__ == "__main__":
    main()
