# -*- coding: utf-8 -*-
"""冲突归因 v2：单位/符号/缺失/口径对/精度/科目映射可疑/公司-年度系统偏差/真实差异。

v1 发现：冲突集中在 601669-2021（26%）、600377-2021（17%）→ 不是逐科目映射错误，
而是公司-年度级系统偏差（疑似重述/合并范围），需第三源裁决。
"""
from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

KB = Path(r"legalwiki-kb")
VER_DB = Path(r"data/astock\fact_verification.db")
OUT = KB / "eval" / "astock"
SCALES = (1e-4, 1e-3, 1e-2, 1e2, 1e3, 1e4)
DEF_PAIRS = {"营业收入", "营业总收入", "净利润", "归属于母公司股东的净利润",
             "财务费用", "其他综合收益", "少数股东权益"}


def classify(v1: float, v2: float, item: str) -> str:
    if v2 == 0:
        return "zero_second"
    if v1 == 0:
        return "zero_first"
    ratio = v2 / v1
    if any(abs(ratio - s) / s < 0.01 for s in SCALES):
        return "unit_scale"
    if abs(abs(v2) - abs(v1)) / max(abs(v1), 1e-9) <= 0.012 and v1 * v2 < 0:
        return "sign_diff"
    if item in DEF_PAIRS:
        return "definition_pair"
    rel = abs(v1 - v2) / max(abs(v1), 1e-9)
    if rel <= 0.05:
        return "round_diff"
    return "genuine"


def main() -> int:
    con = sqlite3.connect(f"file:{VER_DB}?mode=ro", uri=True)
    rows = con.execute(
        "select company,period,item,value_yuan,second_source,second_value,rel_diff "
        "from verification where status='disputed'").fetchall()
    total_by_grp, dis_by_grp = {}, {}
    for company, period, status in con.execute("select company,period,status from verification"):
        key = (str(company), str(period))
        total_by_grp[key] = total_by_grp.get(key, 0) + 1
        if status == "disputed":
            dis_by_grp[key] = dis_by_grp.get(key, 0) + 1
    item_total = Counter()
    for company, period, item, status in con.execute(
            "select company,period,item,status from verification"):
        if status != "invalid_zero":
            item_total[item] += 1
    con.close()

    records = []
    for company, period, item, v1, src, v2, rel in rows:
        cls = classify(v1, v2 or 0, item)
        note = ""
        key = (str(company), str(period))
        rate = dis_by_grp.get(key, 0) / max(total_by_grp.get(key, 1), 1)
        if (cls in ("genuine", "round_diff")
                and dis_by_grp.get(key, 0) >= 3 and rate >= 0.05):
            cls, note = "systematic_group", "公司-年度系统偏差（疑似重述/合并范围），需第三源裁决"
        elif (cls in ("genuine", "round_diff")
              and item_total.get(item, 0) >= 5
              and (dis_by_grp.get(key, 0)) and False):
            pass
        # 科目级：该科目冲突占比高 → 映射可疑
        if cls in ("genuine", "round_diff"):
            item_dis = sum(1 for r in rows if r[2] == item)
            it_rate = item_dis / max(item_total.get(item, 1), 1)
            if item_dis >= 5 and it_rate >= 0.10:
                cls, note = "item_mapping_suspect", "科目级差异率高，疑似映射/口径问题，优先审映射"
        records.append({"company": company, "period": period, "item": item,
                        "first_yi": round(v1 / 1e8, 2), "second_source": src,
                        "second_yi": round((v2 or 0) / 1e8, 2),
                        "rel_diff": round(rel or 0, 4), "class": cls, "note": note})

    by_class = Counter(r["class"] for r in records)
    by_item = Counter(r["item"] for r in records)
    sys_groups = [(k, n) for k, n in sorted(dis_by_grp.items(), key=lambda x: -x[1])
                  if n >= 3 and n / max(total_by_grp.get(k, 1), 1) >= 0.05]
    report = {"total": len(records), "by_class": dict(by_class),
              "by_item": dict(by_item.most_common()),
              "systematic_groups": [{"company": k[0], "period": k[1],
                                     "disputes": n,
                                     "total": total_by_grp.get(k, 0),
                                     "rate": round(n / max(total_by_grp.get(k, 1), 1), 4)}
                                    for k, n in sys_groups[:20]],
              "rule": "单位/符号/缺失/口径对/精度/科目映射可疑/公司-年度系统偏差/真实差异"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "dispute_classification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    with (OUT / "dispute_review.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["company", "period", "item", "first_yi", "second_source", "second_yi",
                    "rel_diff", "auto_class", "human_verdict", "note"])
        for r in records:
            w.writerow([r["company"], r["period"], r["item"], r["first_yi"], r["second_source"],
                        r["second_yi"], r["rel_diff"], r["class"], "", r["note"]])

    md = ["# 双源冲突归因（129 条）", "",
          f"总冲突 {len(records)} 条", "",
          "| 自动分类 | 条数 | 含义 |", "|---|---:|---|",
          f"| genuine | {by_class.get('genuine', 0)} | 无规则可解释，需人工/第三源 |",
          f"| round_diff | {by_class.get('round_diff', 0)} | 相对差 ≤5%，精度/四舍五入 |",
          f"| definition_pair | {by_class.get('definition_pair', 0)} | 已知口径差异对 |",
          f"| systematic_group | {by_class.get('systematic_group', 0)} | 公司-年度系统偏差 |",
          f"| item_mapping_suspect | {by_class.get('item_mapping_suspect', 0)} | 科目映射可疑 |",
          f"| unit_scale | {by_class.get('unit_scale', 0)} | 单位/倍率错误 |",
          f"| sign_diff | {by_class.get('sign_diff', 0)} | 符号相反 |",
          "", "## 系统偏差组（需第三源裁决）", ""]
    for g in report["systematic_groups"][:10]:
        md.append(f"- {g['company']} {g['period']}：{g['disputes']}/{g['total']} 冲突（{g['rate']*100:.1f}%）")
    md += ["", "## 按科目（前 20）", "", "| 科目 | 冲突数 |", "|---|---:|"]
    for k, n in by_item.most_common(20):
        md.append(f"| {k} | {n} |")
    for cls in ("genuine", "systematic_group", "item_mapping_suspect", "round_diff", "definition_pair"):
        grp = [r for r in records if r["class"] == cls]
        if not grp:
            continue
        md += ["", f"## {cls}（前 12）", "",
               "| 公司 | 期间 | 科目 | 第一源(亿) | 第二源(亿) | 相对差 | 备注 |",
               "|---|---|---|---:|---:|---:|---|"]
        for r in grp[:12]:
            md.append(f"| {r['company']} | {r['period']} | {r['item']} | {r['first_yi']} | "
                      f"{r['second_yi']} | {r['rel_diff']} | {r['note']} |")
    md += ["", "> 人工复核清单：`eval/astock/dispute_review.csv`（填写 human_verdict）"]
    (OUT / "dispute_classification.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"total": len(records), "by_class": dict(by_class),
                      "systematic_groups": len(report["systematic_groups"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
