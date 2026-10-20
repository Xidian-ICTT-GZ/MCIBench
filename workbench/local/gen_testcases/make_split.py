# -*- coding: utf-8 -*-
r"""生成开发集 / 留出集划分清单。

为什么需要
----------
所有语料改进都是用**同一批题目的错误**驱动的：在 q2270 上发现分歧就补 q2270 的用例，
再拿 q2270 报"修好了"。这只能证明**修复覆盖**，不能说明对新题目也可靠。

所以把 100 题分成两份：
  dev       语料被改动过的题（改进就是用它们的错误驱动的）
  holdout   语料从未改动的题 —— **只有它上面的指标才是无偏的**

判据：git 历史里改过 `testcases/<qid>/cases.json`，或目录里留有回滚备份。

**限定**：判题器层面的改动（C/C++ 预编译头、类型系统位数、多解校验器、编译标志）
是全局的，无法按题留出。所以这个划分衡量的是**语料驱动**的改善，
不是"整个判题器对新题目的泛化能力"。

用法
----
    python -m local.gen_testcases.make_split           # 重新生成
    python -m local.gen_testcases.make_split --show    # 只看当前划分
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from local.common import TESTCASES_DIR, load_ft_test_qids  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
LOCAL = REPO / "local"
MANIFEST = TESTCASES_DIR / "_split.json"


def touched_qids() -> set[int]:
    """语料被改动过的题号（git 历史 ∪ 留有备份）。"""
    out: set[int] = set()
    try:
        r = subprocess.run(
            ["git", "log", "--format=", "--name-only", "--diff-filter=M",
             "--", "testcases/*/cases.json"],
            cwd=str(LOCAL), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120)
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if line.startswith("testcases/") and line.endswith("/cases.json"):
                mid = line.split("/")[1]
                if mid.isdigit():
                    out.add(int(mid))
    except Exception as e:  # noqa: BLE001
        print(f"  git 查询失败（{type(e).__name__}），只用备份文件判断")
    # 备份文件也是"动过"的证据
    for p in TESTCASES_DIR.glob("*/cases.json.bak_*"):
        if p.parent.name.isdigit():
            out.add(int(p.parent.name))
    return out


def build() -> dict:
    qids = load_ft_test_qids()
    t = touched_qids()
    dev = sorted(q for q in qids if q in t)
    hold = sorted(q for q in qids if q not in t)
    return {
        "date": str(date.today()),
        "criterion": "git 历史改过 testcases/<qid>/cases.json，或留有回滚备份",
        "caveat": "判题器层面的改动是全局的，无法按题留出；"
                  "本划分只衡量语料驱动的改善",
        "n_total": len(qids),
        "dev": dev,
        "holdout": hold,
    }


def load() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return build()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true", help="只显示当前划分")
    args = ap.parse_args()

    if args.show and MANIFEST.exists():
        m = load()
    else:
        m = build()
        MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        print(f"已写入 {MANIFEST}")

    print(f"\n  划分依据: {m['criterion']}")
    print(f"  限定:     {m['caveat']}")
    print(f"\n  总计   {m['n_total']} 题")
    print(f"  dev    {len(m['dev'])} 题（语料被动过 —— 改进就是用它驱动的）")
    print(f"  holdout {len(m['holdout'])} 题（**语料从未改动，指标无偏**）")
    print(f"\n  holdout 题号: {','.join(str(q) for q in m['holdout'])}")


if __name__ == "__main__":
    main()
