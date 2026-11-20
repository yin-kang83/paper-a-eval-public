# -*- coding: utf-8 -*-
"""结构化财务事实库（新浪财经下载接口，替代 PDF 抽取）。

接口（GBK/Tab 分隔）：
  资产负债表 https://money.finance.sina.com.cn/corp/go.php/vDOWN_BalanceSheet/displaytype/4/stockid/{code}.phtml
  利润表     .../vDOWN_ProfitStatement/...
  现金流量表 .../vDOWN_CashFlow/...
解析：第 1 行=报告日期，第 2 行=单位（元/千元…），其余行=科目+各期数值。
落库：data/astock\astock_facts.db(company,statement,item,period,value_yuan)
校验：与康正案例真值对照。
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.request
from pathlib import Path

ASTOCK = Path(r"data/astock")
LC = Path(r"data\E迁移-20261111\康正财务智能体\data\listed_companies")
KB = Path(r"legalwiki-kb")
FACTS_DB = ASTOCK / "astock_facts.db"
UA = "Mozilla/5.0"
BASE = "https://money.finance.sina.com.cn/corp/go.php"
STATEMENTS = {"BALANCE": "vDOWN_BalanceSheet", "PROFIT": "vDOWN_ProfitStatement",
              "CASHFLOW": "vDOWN_CashFlow"}


def fetch_statement(code: str, key: str, year: int) -> str:
    url = f"{BASE}/{STATEMENTS[key]}/displaytype/4/stockid/{code}/ctrl/{year}.phtml"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://finance.sina.com.cn/"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    for enc in ("gb18030", "utf-8", "gbk"):
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        if "资产负债表" in text or "利润表" in text or "货币资金" in text or "营业收入" in text:
            return text
    return raw.decode("gb18030", errors="replace")


def unit_factor(line: str) -> float:
    if "千元" in line:
        return 1e3
    if "万元" in line:
        return 1e4
    if "百万元" in line:
        return 1e6
    return 1.0


def parse(code: str, text: str, statement: str) -> list[tuple]:
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) < 3:
        return []
    dates = [d.strip() for d in lines[0].split("\t")[1:] if d.strip()]
    unit_line = lines[1]
    factor = unit_factor(unit_line)
    rows = []
    for line in lines[2:]:
        cells = line.split("\t")
        if len(cells) < 2:
            continue
        item = cells[0].strip()
        if not item or item in ("单位", "报表日期"):
            continue
        for i, d in enumerate(dates):
            if i + 1 >= len(cells):
                break
            v = cells[i + 1].strip().replace(",", "")
            if not re.match(r"^-?\d+(?:\.\d+)?$", v):
                continue
            try:
                val = float(v) * factor
            except ValueError:
                continue
            rows.append((code, statement, item, d[:8], val))
    return rows


def build(codes: list[str]) -> dict:
    if FACTS_DB.exists():
        FACTS_DB.unlink()
    con = sqlite3.connect(FACTS_DB)
    con.execute("CREATE TABLE facts (company TEXT, statement TEXT, item TEXT, period TEXT,"
                " value_yuan REAL, PRIMARY KEY(company,statement,item,period))")
    total = 0
    for code in codes:
        for key in STATEMENTS:
            for year in (2020, 2021, 2022, 2023, 2024):
                try:
                    text = fetch_statement(code, key, year)
                    rows = parse(code, text, key)
                    con.executemany("INSERT OR REPLACE INTO facts VALUES (?,?,?,?,?)", rows)
                    total += len(rows)
                    time.sleep(1.0)
                except Exception as e:  # noqa: BLE001
                    print("fail", code, key, year, type(e).__name__, str(e)[:60])
    con.commit()
    con.close()
    return {"companies": len(codes), "rows": total}


def validate() -> dict:
    con = sqlite3.connect(f"file:{FACTS_DB}?mode=ro", uri=True)
    checked, hit, miss = 0, 0, []
    for f in ("structured_cases_20261026.jsonl", "financial_assets_cases_20261026.jsonl",
              "expansion_cases_20261026.jsonl"):
        p = LC / f
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            c = json.loads(line)
            code, year = str(c.get("company_code")), c.get("report_year")
            period = f"{year}1231"
            for name, v in ((c.get("facts") or {}).get("items") or {}).items():
                if not isinstance(v, dict) or not isinstance(v.get("period_end_yuan"), (int, float)):
                    continue
                row = con.execute("select value_yuan from facts where company=? and item=? and period=?",
                                  (code, name, period)).fetchone()
                if not row:
                    continue
                checked += 1
                truth, got = v["period_end_yuan"], row[0]
                rel = abs(got - truth) / (truth or 1)
                if rel <= 0.005:
                    hit += 1
                else:
                    miss.append({"case": c["case_id"], "item": name,
                                 "truth_yi": round(truth / 1e8, 2), "got_yi": round(got / 1e8, 2),
                                 "ratio": round(got / truth, 3)})
    con.close()
    return {"checked": checked, "hit": hit,
            "hit_rate": round(hit / checked, 4) if checked else None,
            "misses": miss[:20], "miss_count": len(miss)}


if __name__ == "__main__":
    existing = {"601111", "601919", "601186", "601669", "001965", "600377",
                "000001", "000002", "000063", "000100", "000651", "000858",
                "600000", "600036", "600519", "601318", "601398", "601857"}
    import json as _json
    sample = Path(r"data\E迁移-20261111\康正财务智能体\data\listed_companies\sample_300_20261026.json")
    codes = list(existing)
    if sample.exists():
        for r in _json.loads(sample.read_text(encoding="utf-8")):
            code = str(r.get("code") or "")
            if code and code not in existing:
                codes.append(code)
            if len(codes) >= 50:
                break
    print("companies:", len(codes))
    print("build:", build(codes))
    rep = validate()
    (KB / "eval" / "astock" / "e1_facts_validation.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print("validation:", json.dumps({k: rep[k] for k in ("checked", "hit", "hit_rate", "miss_count")},
                                    ensure_ascii=False))
    for m in rep["misses"][:10]:
        print(m)
