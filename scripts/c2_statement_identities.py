# -*- coding: utf-8 -*-
"""C2：报表级勾稽验证（现金流量表三勾稽 + 利润表勾稽），用于升级单源事实的可信层级。

背景：原 c1 只用资产负债表恒等式（资产=负债+权益），导致现金流量/损益科目无法验证。
本脚本补充各报表自己的勾稽：
  现金流 C1：经营 + 投资 + 筹资 + 汇率影响 = 现金及现金等价物净增加额
  现金流 C2：期初余额 + 净增加额 = 期末余额
  利润表 P1：营业利润 + 营业外收入 − 营业外支出 = 利润总额
  利润表 P2：利润总额 − 所得税费用 = 净利润
  利润表 P3：净利润 = 归母净利润 + 少数股东损益

输出：
  Verification 库 verification_tiers 表更新（single_source → internally_consistent 若其报表勾稽通过）
  eval/astock/c2_statement_checks.json / .md
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
TOL_REL = 0.01
TOL_ABS = 1e6  # 100 万元（元单位）

PREFIX = re.compile(r"^(?:[一二三四五六七八九十]+、|加[:：]|减[:：]|其中[:：]|[（(]一[）)]|[（(]二[）)])\s*")
ALIAS = {
    "经营活动产生的现金流量净额": "CFO",
    "投资活动产生的现金流量净额": "CFI",
    "筹资活动产生的现金流量净额": "CFF",
    "汇率变动对现金及现金等价物的影响": "FX",
    "现金及现金等价物净增加额": "NET",
    "期初现金及现金等价物余额": "BEGIN",
    "期末现金及现金等价物余额": "END",
    "营业利润": "OP",
    "利润总额": "TP",
    "营业外收入": "NOI",
    "营业外支出": "NOE",
    "所得税费用": "TAX",
    "归属于母公司所有者的净利润": "NP_PARENT",
    "少数股东损益": "NP_MINORITY",
    "净利润": "NP",
    "资产总计": "ASSETS",
    "负债合计": "LIAB",
    "流动负债合计": "CL",
    "非流动负债合计": "NCL",
    "流动资产合计": "CA",
    "非流动资产合计": "NCA",
    "所有者权益合计": "EQUITY",
    "股东权益合计": "EQUITY",
}

CASH_FLOW_KEYS = {"CFO", "CFI", "CFF", "FX", "NET", "BEGIN", "END"}
CASH_KW = ("现金流量", "现金及现金等价物", "经营活动", "投资活动", "筹资活动", "汇率变动")
INCOME_KW = ("营业", "利润", "收入", "成本", "费用", "收益", "损益", "所得税", "净利润", "每股")


def statement_of(item: str) -> str:
    if any(k in item for k in CASH_KW):
        return "cash"
    if any(k in item for k in INCOME_KW):
        return "income"
    return "balance"
INCOME_KEYS = {"OP", "TP", "NOI", "NOE", "TAX", "NP", "NP_PARENT", "NP_MINORITY"}
BALANCE_KEYS = {"ASSETS", "LIAB", "CL", "NCL", "CA", "NCA", "EQUITY"}


def norm_item(item: str) -> str | None:
    s = PREFIX.sub("", item.strip())
    s = s.replace("：", ":").replace("（", "(").replace("）", ")").strip()
    for k, v in ALIAS.items():
        if s == k:
            return v
    return None


def close(a: float, b: float) -> bool:
    return abs(a - b) <= max(TOL_ABS, abs(a) * TOL_REL, abs(b) * TOL_REL)


def main() -> int:
    con = sqlite3.connect(str(VER))
    rows = con.execute("select company, period, item, value_yuan from verification").fetchall()
    by: dict[tuple[str, str], dict[str, float]] = {}
    for c, p, item, v in rows:
        key = norm_item(item)
        if not key:
            continue
        by.setdefault((c, p), {})[key] = float(v or 0)
    checks_by_group: dict[tuple[str, str], list[tuple[str, bool]]] = {}
    for cp, vals in by.items():
        checks = []
        # C1: 现金流总勾稽（允许缺 FX，缺失视为 0）
        if all(k in vals for k in ("CFO", "CFI", "CFF", "NET")):
            fx = vals.get("FX", 0.0)
            checks.append(("C1", close(vals["CFO"] + vals["CFI"] + vals["CFF"] + fx, vals["NET"])))
        # C2: 期初 + 净增 = 期末
        if all(k in vals for k in ("BEGIN", "NET", "END")):
            checks.append(("C2", close(vals["BEGIN"] + vals["NET"], vals["END"])))
        # P1: 营业利润 + 营业外收入 - 营业外支出 = 利润总额
        if all(k in vals for k in ("OP", "TP")) and ("NOI" in vals or "NOE" in vals):
            checks.append(("P1", close(vals["OP"] + vals.get("NOI", 0) - vals.get("NOE", 0), vals["TP"])))
        # P2: 利润总额 - 所得税 = 净利润
        if all(k in vals for k in ("TP", "NP")) and "TAX" in vals:
            checks.append(("P2", close(vals["TP"] - vals["TAX"], vals["NP"])))
        # P3: 净利润 = 归母 + 少数股东
        if all(k in vals for k in ("NP", "NP_PARENT", "NP_MINORITY")):
            checks.append(("P3", close(vals["NP_PARENT"] + vals["NP_MINORITY"], vals["NP"])))
        # 资产负债表（沿用 c1 的 I1-I4 口径）
        if all(k in vals for k in ("ASSETS", "LIAB", "EQUITY")):
            checks.append(("I1", close(vals["LIAB"] + vals["EQUITY"], vals["ASSETS"])))
        if all(k in vals for k in ("ASSETS", "CA", "NCA")):
            checks.append(("I3", close(vals["CA"] + vals["NCA"], vals["ASSETS"])))
        if all(k in vals for k in ("LIAB", "CL", "NCL")):
            checks.append(("I4", close(vals["CL"] + vals["NCL"], vals["LIAB"])))
        checks_by_group[cp] = checks

    # 统计：单源事实按"所属报表勾稽是否通过"升级
    stats = Counter()
    upgraded = 0
    detail = Counter()
    new_tiers = []
    for c, p, item, v in rows:
        key = norm_item(item)
        checks = checks_by_group.get((c, p), [])
        passed = [name for name, ok in checks if ok]
        row = con.execute("select status from verification where company=? and period=? and item=?",
                          (c, p, item)).fetchone()
        status = row[0] if row else "single_source"
        tier = status
        if status == "single_source":
            statement = statement_of(item)
            avail_names = [name for name, _ in checks]
            I_avail = [n for n in avail_names if n.startswith("I")]
            Cash_avail = [n for n in avail_names if n in ("C1", "C2")]
            P_avail = [n for n in avail_names if n in ("P1", "P2", "P3")]
            # 组级门：该报表"可用勾稽全部通过"才升级（否则保持 single_source）
            bal_ok = bool(I_avail) and all(n in passed for n in I_avail)
            cash_ok = bool(Cash_avail) and all(n in passed for n in Cash_avail)
            income_ok = bool(P_avail) and all(n in passed for n in P_avail)
            ok = False
            if statement == "cash" and cash_ok:
                ok = True
                detail["cashflow_by_stmt"] += 1
            elif statement == "income" and income_ok:
                ok = True
                detail["income_by_stmt"] += 1
            elif statement == "balance" and bal_ok:
                ok = True
                detail["balance_by_stmt"] += 1
            if ok:
                tier = "internally_consistent"
        if tier != status:
            upgraded += 1
        new_tiers.append((c, p, item, v, tier))
        stats[tier] += 1
    con.execute("CREATE TABLE IF NOT EXISTS verification_tiers (company TEXT, period TEXT,"
                " item TEXT, value_yuan REAL, tier TEXT, PRIMARY KEY(company,period,item))")
    con.execute("DELETE FROM verification_tiers")
    con.executemany("INSERT OR REPLACE INTO verification_tiers VALUES (?,?,?,?,?)", new_tiers)
    con.commit()
    con.close()

    total = sum(stats.values())
    trusted = stats.get("confirmed", 0) + stats.get("internally_consistent", 0)
    rep = {"total": total, "tiers": dict(stats), "upgraded_by_statement": upgraded,
           "upgraded_detail": dict(detail),
           "trusted_coverage": round(trusted / total, 4) if total else None,
           "checks": {"C1": "经营+投资+筹资+汇率=净增加额", "C2": "期初+净增=期末",
                      "P1": "营业利润+营业外收入−支出=利润总额", "P2": "利润总额−所得税=净利润",
                      "P3": "归母+少数股东=净利润", "B1": "负债+权益=资产"},
           "note": "报表级勾稽补充后，单源事实可按所属报表升级；未通过者保持 single_source"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "c2_statement_checks.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                                  encoding="utf-8")
    md = ["# C2 报表级勾稽验证（补充说明）", "",
          f"事实 {total}；可信覆盖 **{rep['trusted_coverage']}**", "",
          "| 层级 | 条数 |", "|---|---:|"]
    for k, v in stats.items():
        md.append(f"| {k} | {v} |")
    md += ["", f"本次因报表勾稽升级单源事实：**{upgraded}** 条（现金流 {detail['cashflow_by_stmt']}，"
               f"损益 {detail['income_by_stmt']}）", "",
           "勾稽清单：", ""] + [f"- {k}：{v}" for k, v in rep["checks"].items()]
    (OUT / "c2_statement_checks.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"total": total, "tiers": dict(stats), "upgraded": upgraded,
                      "trusted_coverage": rep["trusted_coverage"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
