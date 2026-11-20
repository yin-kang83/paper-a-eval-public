# -*- coding: utf-8 -*-
"""双验证强制门 CLI：构建事实验证表 + 报告 + 人工抽样清单。

用法：
  python scripts/dual_verify_gate.py                 # 全量验证
  python scripts/dual_verify_gate.py --sample 20     # 额外输出 20 条人工复核清单
输出：
  data/astock\fact_verification.db   (每事实状态)
  eval/astock/dual_gate.json / .md
  eval/astock/dual_gate_sample.csv（抽样清单）
"""
from __future__ import annotations

import argparse
import re
import csv
import json
import random
import sqlite3
import sys
from pathlib import Path

KB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KB))

from legalwiki.verify.dual import (STATUS_CONFIRMED, STATUS_DISPUTED, STATUS_SINGLE,
                                   Verification, load_case_truth, load_pdf_rows,
                                   load_structured, verify_facts)  # noqa: E402

# 定义敏感科目：跨源口径可能不同（归母/合并、财务费用含不含利息收入等）→ 不判真实冲突
DEFINITION_SENSITIVE = {"其他综合收益", "财务费用", "少数股东权益", "营业总收入", "净利润"}


def refine(vers: list[Verification]) -> tuple[list[Verification], dict]:
    """后处理：零值缺失、定义差异与真实冲突分离。"""
    refined, buckets = [], {"definition_diff": [], "invalid_zero": [], "disputed": []}
    for v in vers:
        item = v.fact.item
        if v.fact.value_yuan == 0:
            v.status = "invalid_zero"
            v.note = "第一源为 0，疑似缺失/未列报，不作答案"
            buckets["invalid_zero"].append(v)
        elif v.status == STATUS_DISPUTED and item in DEFINITION_SENSITIVE:
            v.status = "definition_diff"
            v.note = "口径/定义差异（非数据冲突），需人工核定义"
            buckets["definition_diff"].append(v)
        elif v.status == STATUS_DISPUTED:
            buckets["disputed"].append(v)
        refined.append(v)
    return refined, buckets

ASTOCK = Path(r"data/astock")
LC = Path(r"data\E迁移-20261111\康正财务智能体\data\listed_companies")
FACTS_DB = ASTOCK / "astock_facts.db"
VER_DB = ASTOCK / "fact_verification.db"
OUT = KB / "eval" / "astock"


def canon(name: str) -> str:
    s = str(name or "")
    s = re.sub(r"[（(][^）)]*[）)]", "", s)
    return re.sub(r"\s+", "", s)


def load_em_rows(db: Path) -> dict[tuple, float]:
    out = {}
    if not db.exists():
        return out
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    for company, period, item, value in con.execute(
            "select company,period,item,value_yuan from facts"):
        out[(str(company), period, canon(item))] = float(value)
    con.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=20)
    ap.add_argument("--tol", type=float, default=0.01)
    args = ap.parse_args()

    facts = load_structured(FACTS_DB)
    secondaries = {
        "pdf_pypdf": load_pdf_rows(ASTOCK / "astock_rows2.db"),
        "pdf_pdfplumber": load_pdf_rows(ASTOCK / "astock_rows5.db"),
        "eastmoney": load_em_rows(ASTOCK / "eastmoney_facts.db"),
        "case_truth": load_case_truth([LC / "structured_cases_20261026.jsonl",
                                       LC / "financial_assets_cases_20261026.jsonl",
                                       LC / "expansion_cases_20261026.jsonl"]),
    }
    print("facts:", len(facts), "secondaries:",
          {k: len(v) for k, v in secondaries.items()})
    vers = verify_facts(facts, secondaries, args.tol)
    vers, buckets = refine(vers)

    if VER_DB.exists():
        VER_DB.unlink()
    con = sqlite3.connect(VER_DB)
    con.execute("CREATE TABLE verification (company TEXT, period TEXT, item TEXT,"
                " value_yuan REAL, status TEXT, second_source TEXT, second_value REAL,"
                " rel_diff REAL, note TEXT, PRIMARY KEY(company,period,item))")
    for v in vers:
        con.execute("INSERT OR REPLACE INTO verification VALUES (?,?,?,?,?,?,?,?,?)",
                    (v.fact.company, v.fact.period, v.fact.item, v.fact.value_yuan,
                     v.status, v.second_source, v.second_value, v.rel_diff, v.note))
    con.commit()
    con.close()

    all_statuses = (STATUS_CONFIRMED, STATUS_DISPUTED, STATUS_SINGLE,
                    "definition_diff", "invalid_zero")
    by_status = {st: sum(1 for v in vers if v.status == st) for st in all_statuses}
    disputes = [{"company": v.fact.company, "period": v.fact.period, "item": v.fact.item,
                 "structured_yi": round(v.fact.value_yuan / 1e8, 2),
                 "second_source": v.second_source,
                 "second_yi": round(v.second_value / 1e8, 2) if v.second_value else None,
                 "rel_diff": round(v.rel_diff, 4) if v.rel_diff else None}
                for v in vers if v.status == STATUS_DISPUTED]
    total = len(vers)
    answerable = total - by_status["invalid_zero"]
    report = {"facts": total, "tolerance": args.tol, "by_status": by_status,
              "answerable": answerable,
              "confirmed_rate": round(by_status[STATUS_CONFIRMED] / answerable, 4) if answerable else None,
              "disputes": disputes[:100], "dispute_count": len(disputes),
              "definition_diff_count": by_status["definition_diff"],
              "invalid_zero_count": by_status["invalid_zero"],
              "gate_rule": "confirmed 可答；disputed 拒答/人工；definition_diff 需核定义；"
                           "invalid_zero 不作答案；single_source 可答但标'单源'"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "dual_gate.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    # 人工抽样：single_source 与 disputed 优先
    rng = random.Random(20261113)
    pool = [v for v in vers if v.status != STATUS_CONFIRMED]
    sample = rng.sample(pool, min(args.sample, len(pool))) if pool else []
    with (OUT / "dual_gate_sample.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["company", "period", "item", "value_yi", "status", "second_source", "note"])
        for v in sample:
            w.writerow([v.fact.company, v.fact.period, v.fact.item,
                        round(v.fact.value_yuan / 1e8, 2), v.status, v.second_source, v.note])

    md = ["# 双验证强制门（结构化源 vs 独立第二源）", "",
          f"可答事实 {answerable}（剔除零值缺失 {by_status['invalid_zero']}）", "",
          f"事实 {total} 条；容差 {args.tol}", "",
          "| 状态 | 条数 | 占比 |", "|---|---:|---:|"]
    for st, n in by_status.items():
        md.append(f"| {st} | {n} | {round(n/total*100, 1) if total else 0}% |")
    md += ["", f"**确认率 {report['confirmed_rate']}**；冲突 {len(disputes)} 条（隔离待人工）", "",
           "## 冲突事实（前 30）", "", "| 公司 | 期间 | 科目 | 结构源(亿) | 第二源 | 第二值(亿) |",
           "|---|---|---|---:|---|---:|"]
    for d in disputes[:30]:
        md.append(f"| {d['company']} | {d['period']} | {d['item']} | {d['structured_yi']} | "
                  f"{d['second_source']} | {d['second_yi']} |")
    md += ["", "## 门规则", "", "- `confirmed`：可答", "- `disputed`：**拒答/隔离**，人工复核",
           "- `single_source`：可答但标注“单源”，不得用于结论", "",
           f"人工抽样清单：`eval/astock/dual_gate_sample.csv`（{len(sample)} 条）"]
    (OUT / "dual_gate.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"by_status": by_status, "confirmed_rate": report["confirmed_rate"],
                      "disputes": len(disputes), "sample": len(sample)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
