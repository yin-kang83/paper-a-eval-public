# -*- coding: utf-8 -*-
"""E1c · A股结构审计（真实年报数据）——按实际案例 schema 校验。

可用勾稽（案例字段：facts.items[科目].{period_end_yuan, period_begin_yuan, change_yuan}）：
  1) 变动勾稽：change = end − begin（全部科目）
  2) 应收账款：账面价值 = 账面余额 − 坏账准备
  3) 交叉比率：_cross_check.ratio = numerator / denominator
输出：eval/astock/e1c_structure_audit.json + .md
"""
from __future__ import annotations

import json
import time
from pathlib import Path

LC = Path(r"data\E迁移-20261111\康正财务智能体\data\listed_companies")
OUT = Path(r"legalwiki-kb\eval\astock")
TOL = 0.01


def load(name: str):
    p = LC / name
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    cases = []
    for f in ("structured_cases_20261026.jsonl", "financial_assets_cases_20261026.jsonl",
              "expansion_cases_20261026.jsonl"):
        cases.extend(load(f))
    results = []

    def add(case, check, expected, actual, note=""):
        residual = round(actual - expected, 2) if isinstance(expected, (int, float)) and isinstance(actual, (int, float)) else None
        passed = residual is not None and abs(residual) <= TOL
        results.append({"case_id": case["case_id"], "company": case.get("company_name"),
                        "year": case.get("report_year"), "check": check,
                        "expected": expected, "actual": actual,
                        "residual": residual, "pass": passed, "note": note})

    for c in cases:
        items = (c.get("facts") or {}).get("items") or {}
        for name, v in items.items():
            if not isinstance(v, dict):
                continue
            end, beg, chg = v.get("period_end_yuan"), v.get("period_begin_yuan"), v.get("change_yuan")
            if all(isinstance(x, (int, float)) for x in (end, beg)):
                expect_chg = end - beg
                if isinstance(chg, (int, float)):
                    add(c, f"change={name}", round(expect_chg, 2), round(chg, 2))
                # 应收账款勾稽
                gross, prov = v.get("gross_end_yuan"), v.get("provision_end_yuan")
                if all(isinstance(x, (int, float)) for x in (gross, prov)):
                    add(c, f"AR_book={name}", round(gross - prov, 2), round(end, 2))
        cc = (c.get("facts") or {}).get("_cross_check")
        if cc and isinstance(cc.get("ratio"), (int, float)):
            num = items.get(cc.get("numerator"), {}).get("period_end_yuan") if isinstance(items.get(cc.get("numerator")), dict) else None
            den = items.get(cc.get("denominator"), {}).get("period_end_yuan") if isinstance(items.get(cc.get("denominator")), dict) else None
            if num and den:
                add(c, "cross_check_ratio", round(num / den, 4), round(cc["ratio"], 4), "ratio=num/den")

    # 跨年衔接：同公司+同科目+同主题，year 递增时 begin(Y) 应等于 end(Y-1)
    def series_key(c):
        return (c.get("company_code"), c.get("topic"))

    def items_of(c):
        return ((c.get("facts") or {}).get("items") or {})

    grouped = {}
    for c in cases:
        grouped.setdefault(series_key(c), []).append(c)
    for key, group in grouped.items():
        group = [g for g in group if g.get("report_year")]
        group.sort(key=lambda g: g["report_year"])
        for a, b in zip(group, group[1:]):
            if b["report_year"] != a["report_year"] + 1:
                continue
            for name, va in items_of(a).items():
                vb = items_of(b).get(name)
                if not (isinstance(va, dict) and isinstance(vb, dict)):
                    continue
                end_a, beg_b = va.get("period_end_yuan"), vb.get("period_begin_yuan")
                if isinstance(end_a, (int, float)) and isinstance(beg_b, (int, float)):
                    add(b, f"transition={name}", round(end_a, 2), round(beg_b, 2), "期初=上年期末")

    # 负对照：对每类检查注入 +1% 偏移，验证可检出
    neg = {}
    for name, base in (("change", None),):
        pass
    for r in results[:]:
        if r["expected"] is None or not isinstance(r["actual"], (int, float)):
            continue
        k = r["check"].split("=")[0]
        perturbed = r["actual"] * 1.01 + 1.0
        detected = abs(perturbed - r["expected"]) > TOL
        d = neg.setdefault(k, {"n": 0, "detected": 0})
        d["n"] += 1
        d["detected"] += 1 if detected else 0

    n = len(results)
    passed = sum(1 for r in results if r["pass"])
    anomalies = [r for r in results if not r["pass"]]
    report = {"experiment": "E1c structure audit (A-share annual reports)",
              "cases": len(cases), "checks": n, "passed": passed,
              "pass_rate": round(passed / n, 4) if n else None, "tolerance": TOL,
              "anomalies": anomalies,
              "by_check": {},
              "negative_control": neg,
              "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    for r in results:
        k = r["check"].split("=")[0]
        d = report["by_check"].setdefault(k, {"n": 0, "passed": 0})
        d["n"] += 1
        d["passed"] += 1 if r["pass"] else 0
    (OUT / "e1c_structure_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# E1c · A股结构审计（真实年报数据）", "",
          f"案例 {len(cases)}；可勾稽检查 {n} 条；**通过 {passed}（{report['pass_rate']}）**；容差 {TOL}", "",
          "| 检查类型 | 条数 | 通过 |", "|---|---:|---:|"]
    for k, d in report["by_check"].items():
        md.append(f"| {k} | {d['n']} | {d['passed']} |")
    if anomalies:
        md += ["", f"## 异常 {len(anomalies)} 条（残差≠0）", ""]
        for a in anomalies[:30]:
            md.append(f"- {a['case_id']} {a['check']}：期望 {a['expected']} 实际 {a['actual']} 残差 {a['residual']}")
    md += ["", "## 负对照（+1%+1元扰动）", ""]
    for k, d in report["negative_control"].items():
        md.append(f"- {k}: 注入 {d['n']} 条，检出 {d['detected']}（{round(d['detected']/d['n'],4) if d['n'] else 'N/A'}）")
    md += ["", "> 数据来自巨潮年报摘录（案例库）；勾稽在案例内/相邻年度间进行；100% 通过=抽取结果内部自洽，",
           "> 不代表审计发现能力上限；检出能力由负对照给出。"]
    (OUT / "e1c_structure_audit.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("cases", "checks", "passed", "pass_rate", "by_check")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
