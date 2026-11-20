# -*- coding: utf-8 -*-
"""C2b：用移植的三表勾稽模块（legalwiki.domains.articulation）对全部公司-期间跑报表勾稽。

输出：eval/astock/c2b_articulation_stats.json / .md
  - 可判定组数、完全通过组数、各约束失败计数、失败样例
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

VER = Path(r"data/astock\fact_verification.db")
KB = Path(r"legalwiki-kb")
OUT = KB / "eval/astock"
import sys
sys.path.insert(0, str(KB))
from legalwiki.domains.articulation import check  # noqa: E402

PREFIX = re.compile(r"^(?:[一二三四五六七八九十]+、|加[:：]|减[:：]|其中[:：]|[（(]一[）)]|[（(]二[）)])\s*")
MAP = {
    "资产总计": "资产合计", "负债合计": "负债合计",
    "所有者权益合计": "所有者权益合计", "股东权益合计": "所有者权益合计",
    "负债和所有者权益(或股东权益)总计": "负债和所有者权益合计",
    "负债及股东权益总计": "负债和所有者权益合计",
    "经营活动产生的现金流量净额": "经营活动净额",
    "投资活动产生的现金流量净额": "投资活动净额",
    "筹资活动产生的现金流量净额": "筹资活动净额",
    "汇率变动对现金及现金等价物的影响": "汇率影响",
    "现金及现金等价物净增加额": "现金净增加额",
    "期初现金及现金等价物余额": "期初现金",
    "期末现金及现金等价物余额": "期末现金",
    "营业利润": "营业利润", "利润总额": "利润总额",
    "营业外收入": "营业外收入", "营业外支出": "营业外支出",
    "所得税费用": "所得税费用", "净利润": "净利润",
    "归属于母公司所有者的净利润": "归母净利润", "少数股东损益": "少数股东损益",
    "货币资金": "货币资金", "未分配利润": "未分配利润_资产负债表",
}


def norm(item: str) -> str | None:
    s = PREFIX.sub("", item.strip()).replace("：", ":").replace("（", "(").replace("）", ")").strip()
    return MAP.get(s)


def main() -> int:
    con = sqlite3.connect(f"file:{VER}?mode=ro", uri=True)
    rows = con.execute("select company, period, item, value_yuan from verification").fetchall()
    con.close()
    groups: dict[tuple[str, str], dict[str, float]] = {}
    for c, p, item, v in rows:
        k = norm(item)
        if k:
            groups.setdefault((c, p), {})[k] = float(v or 0)
    judgeable = passed = 0
    fails = Counter()
    fail_samples = []
    for (c, p), figs in groups.items():
        r = check(figs)
        if r["可判定数"] == 0:
            continue
        judgeable += 1
        if r["通过"]:
            passed += 1
        else:
            for d in r["失败"]:
                fails[d["约束"]] += 1
            if len(fail_samples) < 10:
                fail_samples.append({"company": c, "period": p,
                                     "失败": [(d["约束"], d.get("残差")) for d in r["失败"]]})
    rep = {"groups_with_figures": len(groups), "judgeable_groups": judgeable,
           "fully_passed": passed,
           "pass_rate": round(passed / judgeable, 4) if judgeable else None,
           "constraint_fail_counts": dict(fails),
           "fail_samples": fail_samples,
           "note": "勾稽模型移植自晋明 engine/statement_articulation.py；第⑦条按实测结论改为不等式"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "c2b_articulation_stats.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                                     encoding="utf-8")
    md = ["# C2b 三表勾稽（全公司-期间）", "",
          f"有数据的公司-期间组：{rep['groups_with_figures']}；可判定组：{judgeable}；"
          f"完全通过：**{passed}**（{rep['pass_rate']}）", "",
          "## 各约束失败计数", "", "| 约束 | 失败次数 |", "|---|---:|"]
    for k, v in fails.most_common():
        md.append(f"| {k} | {v} |")
    md += ["", "> 勾稽口径：A4 资产=负债+权益；A5 负债和权益合计；E1/E2 跨表（本数据集缺权益变动表→多为未提供）；",
           "> C1/C2 现金流勾稽；P1/P2/P3 利润表勾稽；I7 期末现金≤货币资金（不等式）。"]
    (OUT / "c2b_articulation_stats.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("groups_with_figures", "judgeable_groups",
                                          "fully_passed", "pass_rate", "constraint_fail_counts")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
