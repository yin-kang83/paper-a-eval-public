# -*- coding: utf-8 -*-
"""数值事实查询路由：结构化行库直查（公司/年/科目）→ 数值答案；否则回落文本检索。

这是 E1a-v3 的工程化：真实年报数值问题不应走 3-gram 文本检索，应走"结构化事实库"。
接口示例：
  python scripts/fact_router.py "招商公路 2023 货币资金"
  python scripts/fact_router.py --json "中国国航 2023 租赁负债"
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

KB = Path(r"legalwiki-kb")
FACTS_DB = Path(r"data/astock\astock_facts.db")
VER_DB = Path(r"data/astock\fact_verification.db")
ITEMS = ["货币资金", "资产总计", "负债合计", "应收账款", "存货", "使用权资产", "租赁负债",
         "营业收入", "营业总收入", "净利润", "归属于母公司股东的净利润",
         "无形资产", "固定资产", "长期待摊费用", "应付账款", "合同负债", "预付款项",
         "其他应收款", "其他应付款", "一年内到期的非流动负债"]
NAME_TO_CODE = {}


def lookup(question: str) -> dict:
    """优先查双验证状态表；无验证表时回落到事实库（标 single_source）。"""
    year_m = re.search(r"(20\d{2})", question)
    item = next((i for i in ITEMS if i in question), None)
    if item is None:
        # 动态解析：用验证库的科目全名做子串匹配（取最长匹配）
        if VER_DB.exists():
            vcon = sqlite3.connect(f"file:{VER_DB}?mode=ro", uri=True)
            cands = [r[0] for r in vcon.execute("select distinct item from verification")]
            vcon.close()
            cands = [c for c in cands if c and c in question]
            if cands:
                item = max(cands, key=len)
    code = None
    if not (item):
        return {"matched": False, "reason": "缺科目"}
    con = sqlite3.connect(f"file:{FACTS_DB}?mode=ro", uri=True)
    if not code:
        for r in con.execute("select distinct company from facts"):
            if r[0] and r[0] in question:
                code = r[0]
                break
    if not code:
        idx = KB / "eval" / "astock" / "corpus_index_scale.json"
        if idx.exists():
            for r in json.loads(idx.read_text(encoding="utf-8")):
                if r.get("company_name") and r["company_name"] in question:
                    code = r["company_code"]
                    break
    if not code:
        con.close()
        return {"matched": False, "reason": "缺公司"}
    period = (year_m.group(1) + "1231") if year_m else None
    TIERS_DB = VER_DB
    if TIERS_DB.exists():
        vcon = sqlite3.connect(f"file:{TIERS_DB}?mode=ro", uri=True)
        try:
            sql = ("select period,value_yuan,tier,NULL,NULL from verification_tiers "
                   "where company=? and item=?")
            params = [code, item]
            if period:
                sql += " and period=?"
                params.append(period)
            row = vcon.execute(sql + " order by period desc", params).fetchone()
        except sqlite3.OperationalError:
            row = None
        vcon.close()
        con.close()
        if row:
            p_, value, status, src, sval = row
            return {"matched": True, "company": code, "period": p_, "item": item,
                    "value_yi": round(value / 1e8, 2), "status": status,
                    "second_source": src, "second_yi": None}
    if VER_DB.exists():
        vcon = sqlite3.connect(f"file:{VER_DB}?mode=ro", uri=True)
        sql = ("select period,value_yuan,status,second_source,second_value from verification "
               "where company=? and item=?")
        params = [code, item]
        if period:
            sql += " and period=?"
            params.append(period)
        row = vcon.execute(sql + " order by period desc", params).fetchone()
        vcon.close()
        con.close()
        if not row:
            return {"matched": False, "reason": "无该事实", "company": code, "item": item}
        p_, value, status, src, sval = row
        return {"matched": True, "company": code, "period": p_, "item": item,
                "value_yi": round(value / 1e8, 2), "status": status,
                "second_source": src, "second_yi": round(sval / 1e8, 2) if sval else None}
    con.close()
    return {"matched": False, "reason": "无验证表，请先跑 dual_verify_gate.py"}


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--json"]
    if not args:
        print(__doc__)
        return 1
    q = " ".join(args)
    res = lookup(q)
    if "--json" in sys.argv:
        print(json.dumps(res, ensure_ascii=False))
    else:
        if res.get("matched"):
            st = res.get("status", "single_source")
            base = f"{res['company']} {res['period']} {res['item']}：{res['value_yi']} 亿元"
            if st == "confirmed":
                print(base + "（双源确认）")
            elif st == "internally_consistent":
                print(base + "（单源+内部勾稽通过）")
            elif st == "single_source":
                print(base + "（单源，待补第二源）")
            elif st == "disputed":
                print(f"拒答：{res['company']} {res['period']} {res['item']} 双源冲突，待人工复核")
            elif st == "definition_diff":
                print(f"拒答：{res['company']} {res['period']} {res['item']} 口径差异，待核定义")
            elif st == "invalid_zero":
                print(f"不作答：{res['company']} {res['period']} {res['item']} 疑似缺失（0值）")
            else:
                print(base + f"（状态 {st}）")
        else:
            print("未命中：", res.get("reason"))
    return 0 if res.get("matched") else 2


if __name__ == "__main__":
    raise SystemExit(main())
