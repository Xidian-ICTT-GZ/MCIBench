# -*- coding: utf-8 -*-
r"""从**结果数据**自动生成状态表 —— D6 要求的"数字不许手写"。

## 为什么需要它

用户第 6 条指出：`HANDOVER.md` 里手写的数字**已经漂移**。实测差异：

| 项 | 文档写的 | 实际 |
|---|---|---|
| 语料条数 | 2665 | **2622** |
| 二元一致率 | 97.90% | **97.89%** |
| `false_ac` 中 TLE | 41 | **40** |
| `false_ac` 中 WA | 47 | **48** |

手写数字**必然**漂移 —— 因为数据和代码都在变，而文档不会自动跟。
所以状态表改为**生成**：本脚本算完 → 写进 `STATUS.md` 的标记区。
`HANDOVER.md` 只引用 `STATUS.md`，不再自己写数字。

## 用法

    python -m local.tools.gen_status_table           # 打印
    python -m local.tools.gen_status_table --write   # 写入 STATUS.md 的标记区
    python -m local.tools.gen_status_table --check   # 与 STATUS.md 比对，不一致则非零退出

`--check` 供验收脚本（D5）调用：**状态表过期就失败**。
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from local.common import TESTCASES_DIR, load_ft_test_qids  # noqa: E402

DB = REPO / "local" / "dashboard" / "packages" / "server" / "data" / "local.db"
# D6：状态表**直接写进交接文档**的标记区（不再是单独的 STATUS.md），
# 这样"交接里的数字"与"生成它的脚本"只有一个来源。
STATUS = REPO / "local" / "docs" / "当前状态.md"
BEGIN = "<!-- BEGIN GENERATED -->"
BEGIN_DATA = "<!-- BEGIN DATA -->"   # 只有这一段参与 --check
END_DATA = "<!-- END DATA -->"
END = "<!-- END GENERATED -->"

# ft_test 当前口径
SCOPE = "lc_origin='submissions' AND local_origin='all_models' AND identity_status='current' AND qid IN (SELECT qid FROM problems WHERE in_ft_test=1)"
WHERE = SCOPE + " AND klass IN ('agrees','same_neg','false_ac','false_wa')"


def _git(*a: str) -> str:
    try:
        r = subprocess.run(["git", *a], cwd=str(REPO / "local"),
                           capture_output=True, text=True, timeout=30)
        return (r.stdout or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _image() -> str:
    try:
        r = subprocess.run(["docker", "image", "inspect", "local-judge:1",
                            "--format", "{{.Id}}"],
                           capture_output=True, text=True, timeout=30)
        return (r.stdout or "").strip()[:19]
    except Exception:  # noqa: BLE001
        return "（拿不到）"


def corpus_stats() -> dict:
    tot = 0
    n_prob = 0
    for q in load_ft_test_qids():
        p = TESTCASES_DIR / str(q) / "cases.json"
        if p.exists():
            tot += len(json.loads(p.read_text(encoding="utf-8")))
            n_prob += 1
    return {"problems": n_prob, "cases": tot}


def metrics() -> dict:
    if not DB.exists():
        return {}
    c = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    try:
        if "identity_status" not in {r[1] for r in c.execute("PRAGMA table_info(slots)")}:
            return {"migration_required": True}
        coverage = dict(c.execute("SELECT identity_status, COUNT(*) FROM slots WHERE lc_origin='submissions' AND qid IN (SELECT qid FROM problems WHERE in_ft_test=1) GROUP BY identity_status"))
        row = c.execute(f"""SELECT
            COUNT(*),
            SUM(leetcode='Accepted' AND local='Accepted'),
            SUM(leetcode='Accepted' AND local<>'Accepted'),
            SUM(leetcode<>'Accepted' AND local='Accepted'),
            SUM(leetcode<>'Accepted' AND local<>'Accepted')
            FROM slots WHERE {WHERE}""").fetchone()
        N, TP, FN, FP, TN = (x or 0 for x in row)
        klass = dict(c.execute(
            f"SELECT klass, COUNT(*) FROM slots WHERE {WHERE} GROUP BY klass"))
        nolc = c.execute(
            f"SELECT COUNT(*) FROM slots WHERE {SCOPE} AND klass='no_lc'").fetchone()[0]
        fa = dict(c.execute(
            f"SELECT leetcode, COUNT(*) FROM slots WHERE {WHERE} "
            f"AND klass='false_ac' GROUP BY leetcode"))
        fw = dict(c.execute(
            f"SELECT local, COUNT(*) FROM slots WHERE {WHERE} "
            f"AND klass='false_wa' GROUP BY local"))
        return {"coverage": coverage, "N": N, "TP": TP, "FN": FN, "FP": FP, "TN": TN,
                "klass": klass, "no_lc": nolc, "false_ac_by_lc": fa,
                "false_wa_by_local": fw}
    finally:
        c.close()


def fingerprint() -> str:
    """**报告**用：拿不到就标注原因，**不**硬失败。

    与 `validate.fingerprint()` 的策略不同是刻意的：
      - `validate` 要**绑定**版本 ⇒ 拿不到镜像必须失败（否则指纹抖动）
      - 状态表只是**描述现状** ⇒ 应如实写"镜像不可用"并继续，
        让读者看到"现在无法证明版本绑定"，而不是整个报告打不开
    """
    try:
        from local.gen_testcases.validate import fingerprint as fp
        return fp()
    except SystemExit as e:
        return f"不可用（{str(e).strip().splitlines()[-3].strip()[:46]}）"
    except Exception as e:  # noqa: BLE001
        return f"不可用（{type(e).__name__}）"


def golden_stats() -> dict:
    p = REPO / "local" / "results" / "golden_check.json"
    if not p.exists():
        return {"lines": 0, "accepted": 0, "fingerprints": []}
    n = acc = 0
    fps = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        n += 1
        fps.add(d.get("fingerprint"))
        if d.get("status_full") == "Accepted":
            acc += 1
    return {"lines": n, "accepted": acc, "fingerprints": sorted(x for x in fps if x)}


def render() -> str:
    cs = corpus_stats()
    m = metrics()
    g = golden_stats()
    fp = fingerprint()
    L: list[str] = []
    A = L.append
    A("### 快照区（仅供参考，**不**参与 --check —— HEAD 每提交一次就变）")
    A("")
    A("| 项 | 值 | 来源 |")
    A("|---|---|---|")
    A(f"| 仓库 HEAD | `{_git('rev-parse', '--short', 'HEAD') or '?'}` | git |")
    A(f"| 工作区 | {'干净' if not _git('status', '--porcelain') else '**有未提交改动**'} | git |")
    A(f"| 镜像 | `{_image()}` | docker |")
    A(f"| 当前参考解指纹 | `{fp}` | `validate.fingerprint()` |")
    A("")
    A("### 数据区（**必须**与当前数据一致，否则 --check 失败）")
    A("")
    A(BEGIN_DATA)
    A("| 项 | 值 | 来源 |")
    A("|---|---|---|")
    A(f"| 语料 | **{cs['cases']} 条** / {cs['problems']} 题 | 遍历 `testcases/*/cases.json` |")
    A(f"| `golden_check.json` | {g['lines']} 条，`status_full=Accepted` **{g['accepted']}** | 逐行解析 |")
    A(f"| 记录里的指纹 | {g['fingerprints'] or '（无）'} | 同上 |")
    # C-106 要求的其余行：结果文件数 / _judge_version 集合 / 快照与变更清单计数
    res = REPO / "local" / "results" / "all_models"
    files = sorted(res.glob("*/results/*/*.json")) if res.exists() else []
    vers: dict[str, int] = {}
    idents = 0
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(d, dict):
            # judge_meta.json 是**列表**（C-008 改成追加），不是槽位结果
            continue
        v = d.get("_judge_version") or "<无>"
        vers[v] = vers.get(v, 0) + 1
        if d.get("_identity") is not None:
            idents += 1
    A(f"| 结果文件数 | {len(files)} | `results/all_models/*/results/*/*.json` |")
    A(f"| 其中带 `_identity` | {idents} | 同上 |")
    A(f"| `_judge_version` 分布 | {vers} | 同上 |")
    snaps = REPO / "local" / "results" / "slot_snapshots"
    chgs = REPO / "local" / "results" / "corpus_changes"
    A(f"| 槽位快照 | {len(list(snaps.glob('*.csv'))) if snaps.exists() else 0} 份 "
      f"| `results/slot_snapshots/` |")
    A(f"| 语料变更清单 | {len(list(chgs.glob('*.json'))) if chgs.exists() else 0} 份 "
      f"| `results/corpus_changes/` |")
    if m.get("migration_required"):
        A("| 当前统计 | 尚未导入身份字段，不可据旧指标验收 | importer |")
    elif m:
        A(f"| 计划槽位身份覆盖 | {m['coverage']} | SQL；包含缺失与无法验证 |")
        N = m["N"]
        A(f"| 可比槽位 N | **{N}** | `{WHERE}` |")
        A(f"| 2×2 | TP={m['TP']} FN={m['FN']} FP={m['FP']} TN={m['TN']} | SQL |")
        def rate(n, d, precision=2):
            return f"{n/d*100:.{precision}f}% ({n}/{d})" if d else "不适用（分母为零）"
        A(f"| 精确一致率 | {rate(m['klass'].get('agrees',0), N)} | SQL |")
        A(f"| 二元一致率 | {rate(m['TP']+m['TN'], N)} | SQL |")
        A(f"| 漏检率 | {rate(m['FP'], m['FP']+m['TN'], 3)} | SQL |")
        A(f"| 误拒率 | {rate(m['FN'], m['TP']+m['FN'], 3)} | SQL |")
        A(f"| klass 分布 | {m['klass']} | SQL |")
        A(f"| `no_lc` | {m['no_lc']} | SQL |")
        A(f"| `false_ac` 按 LC 判定 | {m['false_ac_by_lc']} | SQL |")
        A(f"| `false_wa` 按本地判定 | {m['false_wa_by_local']} | SQL |")
    A(END_DATA)
    return "\n".join(L)


def lint_handwritten() -> list[str]:
    """扫描交接文档里**生成区之外**的手写数字（C-106 的根因）。

    放行两类（否则会误报，实测第一版就把"验证记录里的测量值"和
    "历史说明"全报了）：
      ① 行内含**可复现命令**（反引号里是 `python -m …` / SQL / 路径）
         —— 那是"验证记录"，数字本身是证据，不是状态声明
      ② `<!-- lint-allow -->` … `<!-- lint-end -->` 之间的内容
         —— 用于历史说明与引用他人的发现数字
    """
    if not STATUS.exists():
        return []
    txt = STATUS.read_text(encoding="utf-8")
    # 只检查**生成区之外**的内容
    if BEGIN in txt and END in txt:
        outside = txt.split(BEGIN)[0] + txt.split(END, 1)[1]
    else:
        outside = txt
    # 去掉显式允许区
    outside = re.sub(r"<!--\s*lint-allow\s*-->.*?<!--\s*lint-end\s*-->",
                     "", outside, flags=re.S)
    bad = []
    pats = [
        (r"\d{3,}\s*条", "条数"),
        (r"\d+\.\d+\s*%", "百分比"),
        (r"TLE\s*\d+", "TLE 计数"),
        (r"WA\s*\d+", "WA 计数"),
        (r"N\s*=\s*\d{3,}", "分母 N"),
    ]
    for i, line in enumerate(outside.splitlines(), 1):
        s = line.strip()
        # ① 表头 / 分隔线
        if s.startswith("|---") or s.startswith("| 项 "):
            continue
        # ② 带可复现命令的行（反引号里有命令/路径/SQL）
        if re.search(r"`[^`]*(python|local/|SELECT|select|docker|git)[^`]*`", line):
            continue
        for pat, what in pats:
            if re.search(pat, line):
                bad.append(f"L{i} 手写{what}: {s[:80]}")
                break
    return bad


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--lint", action="store_true",
                    help="扫描交接文档里生成区之外的**手写数字**")
    a = ap.parse_args()

    if a.lint:
        bad = lint_handwritten()
        if bad:
            print(f"**交接文档里有 {len(bad)} 处手写数字（应改为引用生成区）：**")
            for b in bad[:20]:
                print(f"  {b}")
            sys.exit(1)
        print("交接文档的生成区之外没有手写数字 ✓")
        return
    body = render()

    if a.check:
        if not STATUS.exists():
            sys.exit(f"{STATUS} 不存在")
        t = STATUS.read_text(encoding="utf-8")
        if BEGIN not in t or END not in t:
            sys.exit(f"{STATUS} 缺少生成标记")
        if BEGIN_DATA not in t or END_DATA not in t:
            sys.exit("状态表缺少数据区标记")
        cur = t.split(BEGIN_DATA, 1)[1].split(END_DATA, 1)[0].strip()
        # 与**新渲染 body 的数据区**比，不是整段 body
        # （我第一版拿整段去比，于是永远不等 —— --check 恒假）
        if BEGIN_DATA not in body or END_DATA not in body:
            sys.exit("新渲染缺少数据区标记")
        want = body.split(BEGIN_DATA, 1)[1].split(END_DATA, 1)[0].strip()
        if cur != want:
            print("**状态表已过期**（数据变了但 STATUS.md 没重新生成）")
            print("请跑：python -m local.tools.gen_status_table --write")
            sys.exit(1)
        print("状态表与当前数据一致 ✓")
        return

    if a.write:
        STATUS.parent.mkdir(parents=True, exist_ok=True)
        old = STATUS.read_text(encoding="utf-8") if STATUS.exists() else ""
        head = old.split(BEGIN, 1)[0] if BEGIN in old else (
            "# 当前评测状态（自动生成）\n\n"
            "> 使用 `python -m local.tools.gen_status_table --write` 更新，`--check` 核对数据。\n"
            "> 文件条数和历史 Accepted 不代表当前身份验收通过；最终验收使用 `python -m local.tools.verify_release`。\n\n")
        tail = ("\n\n" + old.split(END, 1)[1].lstrip("\n")) if END in old else "\n"
        STATUS.write_text(f"{head}{BEGIN}\n{body}\n{END}{tail}", encoding="utf-8")
        print(f"已写入 {STATUS}")
    else:
        print(body)


if __name__ == "__main__":
    main()
