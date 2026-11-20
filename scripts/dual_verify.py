# -*- coding: utf-8 -*-
"""双源交叉验证：结构化事实库（新浪，权威） vs PDF 抽参（pypdf / pdfplumber）。

目的：
  1) 用 PDF 抽取作为独立第二意见，对结构化事实做"双验证"；
  2) 用案例真值（康正人工核对值）当裁判，量化两边的准确率；
  3) 不匹配即标注"待人工"，不静默合并。

输出：eval/astock/dual_verify.json + .md
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ASTOCK = Path(r"data/astock")
LC = Path(r"data\E迁移-20261111\康正财务智能体\data\listed_companies")
KB = Path(r"legalwiki-kb")
FACTS = ASTOCK / "astock_facts.db"
PDF2 = ASTOCK / "astock_rows2.db"
PDF5 = ASTOCK / "astock_rows5.db"
TOL = 0.01


def load_pdf(db: Path) -> dict[tuple, float]:
    out = {}
    if not db.exists():
        return out
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        for company, year, item, cur in con.execute("select company,year,item,cur_yuan from rows"):
            out[(str(company), int(year), item)] = float(cur)
    except sqlite3.OperationalError:
        pass
    con.close()
    return out


def load_case_truth() -> dict[tuple, float]:
    truth = {}
    for f in ("structured_cases_20261026.jsonl", "financial_assets_cases_20261026.jsonl",
              "expansion_cases_20261026.jsonl"):
        p = LC / f
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            c = json.loads(line)
            code, year = str(c.get("company_code")), int(c.get("report_year") or 0)
            for name, v in ((c.get("facts") or {}).get("items") or {}).items():
                if isinstance(v, dict) and isinstance(v.get("period_end_yuan"), (int, float)):
                    truth[(code, year, name)] = float(v["period_end_yuan"])
    return truth


def main() -> int:
    con = sqlite3.connect(f"file:{FACTS}?mode=ro", uri=True)
    facts = {}
    for company, item, period, value in con.execute(
            "select company,item,period,value_yuan from facts"):
        if period[:4].isdigit() and period.endswith("1231"):
            facts[(str(company), int(period[:4]), item)] = float(value)
    con.close()
    pdf2, pdf5 = load_pdf(PDF2), load_pdf(PDF5)
    truth = load_case_truth()

    def compare(second: dict[tuple, float]) -> dict:
        both, agree, mismatch = [], 0, []
        for key, v1 in facts.items():
            v2 = second.get(key)
            if v2 is None or v1 == 0:
                continue
            both.append(key)
            if abs(v1 - v2) / abs(v1) <= TOL:
                agree += 1
            else:
                mismatch.append({"key": list(key), "facts_yi": round(v1 / 1e8, 2),
                                 "pdf_yi": round(v2 / 1e8, 2),
                                 "ratio": round(v2 / v1, 4) if v1 else None})
        return {"overlap": len(both), "agree": agree,
                "agree_rate": round(agree / len(both), 4) if both else None,
                "mismatches": mismatch[:30], "mismatch_count": len(mismatch)}

    def accuracy(cand: dict[tuple, float], name: str) -> dict:
        checked = hit = 0
        for key, t in truth.items():
            v = cand.get(key)
            if v is None:
                continue
            checked += 1
            if abs(v - t) / (abs(t) or 1) <= TOL:
                hit += 1
        return {"source": name, "checked": checked, "hit": hit,
                "hit_rate": round(hit / checked, 4) if checked else None}

    report = {
        "experiment": "dual verification: structured facts vs PDF extraction",
        "facts_rows": len(facts), "case_truth_rows": len(truth),
        "pdf_pypdf_rows": len(pdf2), "pdf_pdfplumber_rows": len(pdf5),
        "vs_pypdf": compare(pdf2),
        "vs_pdfplumber": compare(pdf5),
        "accuracy_vs_truth": [accuracy(facts, "structured_sina"),
                              accuracy(pdf2, "pdf_pypdf"),
                              accuracy(pdf5, "pdf_pdfplumber")],
        "rule": "相对误差 ≤1% 视为一致；不一致 → 待人工（不静默合并）",
    }
    (KB / "eval" / "astock" / "dual_verify.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# 双源交叉验证：结构化事实库 vs PDF 抽参", "",
          f"事实库 {len(facts)} 条；PDF(pypdf) {len(pdf2)} 条；PDF(pdfplumber) {len(pdf5)} 条；"
          f"裁判（案例真值）{len(truth)} 条", "",
          "| 第二源 | 重叠 | 一致 | 一致率 |", "|---|---:|---:|---:|"]
    for k in ("vs_pypdf", "vs_pdfplumber"):
        d = report[k]
        md.append(f"| {k} | {d['overlap']} | {d['agree']} | {d['agree_rate']} |")
    md += ["", "## 对案例真值的准确率（裁判）", "",
           "| 源 | 可核条数 | 命中 | 准确率 |", "|---|---:|---:|---:|"]
    for a in report["accuracy_vs_truth"]:
        md.append(f"| {a['source']} | {a['checked']} | {a['hit']} | {a['hit_rate']} |")
    md += ["", "> 一致 ≠ 正确（可能两边同错）；不一致必须人工判定。", "",
           "> 双源验证的用途：结构化事实为第一源，PDF 抽参为独立第二意见；PDF 抽参可捕捉"
           "结构化源的重述/期间错位，结构化源可修正 PDF 抽取的表格/单位错误。"]
    (KB / "eval" / "astock" / "dual_verify.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("facts_rows", "vs_pypdf", "vs_pdfplumber",
                                             "accuracy_vs_truth")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
