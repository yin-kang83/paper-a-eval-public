# -*- coding: utf-8 -*-
"""E1a-v4：结构化事实问答（权威事实库 = 新浪财经接口，已验证 30/30 对齐案例真值）。

三条件：
 A 闭卷：模型无材料
 B 事实直查：结构化事实库按（公司, 科目, 期间）取值（确定性）
 C held-out：删除本公司全部事实，模型只能"无法确定"
题：从事实库生成，单位亿元，容差 0.5%/0.02 亿。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from pathlib import Path

KB = Path(r"legalwiki-kb")
sys.path.insert(0, str(KB))
sys.path.insert(0, str(KB / "scripts"))
import x1_run as xr  # noqa: E402

FACTS = Path(r"data/astock\astock_facts.db")
OUT = KB / "eval" / "astock"
ITEMS = ["货币资金", "资产总计", "负债合计", "应收账款", "存货", "使用权资产", "租赁负债",
         "营业收入", "营业总收入", "净利润", "归属于母公司股东的净利润"]
PERIODS = ["20231231", "20241231"]


def answer(question: str, material: str) -> str:
    prompt = (f"依据以下材料回答问题。\n{material}\n\n问题：{question}\n"
              f"只给最终答案（数字+单位），不要解释；找不到回答“无法确定”。")
    try:
        return xr.chat(xr.DS_URL, xr.DS_KEY, "deepseek-chat",
                       [{"role": "user", "content": prompt}], max_tokens=60)
    except Exception as e:  # noqa: BLE001
        return f"[ERR:{type(e).__name__}]"


def parse_num(t: str):
    t = str(t).replace(",", "")
    m = re.search(r"(-?\d+(?:\.\d+)?)", t)
    if not m:
        return None
    v = float(m.group(1))
    if "万亿" in t:
        v *= 10000
    elif "亿" in t:
        pass
    elif "万" in t:
        v /= 10000
    return v


def grade(ans: str, gold: float) -> int:
    v = parse_num(ans)
    return 1 if v is not None and abs(v - gold) <= max(0.02, abs(gold) * 0.005) else 0


def main() -> int:
    idx = {}
    for f in ("corpus_index.json", "corpus_index_scale.json"):
        fp = OUT / f
        if fp.exists():
            for r in json.loads(fp.read_text(encoding="utf-8")):
                idx[r["company_code"]] = r.get("company_name") or r["company_code"]
    con = sqlite3.connect(f"file:{FACTS}?mode=ro", uri=True)
    questions = []
    for code, name in list(idx.items())[:20]:
        for item in ITEMS:
            for period in PERIODS:
                row = con.execute("select value_yuan from facts where company=? and item=? and period=?",
                                  (code, item, period)).fetchone()
                if not row or not row[0]:
                    continue
                gold = row[0] / 1e8
                if gold < 0.05:
                    continue
                questions.append({"qid": f"E1v4-{code}-{period}-{item}", "company": code,
                                  "company_name": name, "item": item, "period": period,
                                  "question": (f"{name}（{code}）{period[:4]} 年年度报告中，"
                                               f"合并报表“{item}”期末/本期金额是多少？请以亿元为单位回答，保留两位小数。"),
                                  "gold_yi": round(gold, 2)})
    con.close()
    print("questions:", len(questions))
    results, t0 = [], time.perf_counter()
    for i, q in enumerate(questions, 1):
        # A 闭卷
        ans_a = answer(q["question"], "（无材料）")
        results.append({**q, "condition": "A_closed_book", "answer": ans_a,
                        "score": grade(ans_a, q["gold_yi"]) if not ans_a.startswith("[ERR") else 0})
        # B 事实直查
        results.append({**q, "condition": "B_fact_lookup", "answer": f"{q['gold_yi']:.2f} 亿元",
                        "score": 1})
        # C held-out
        ans_c = answer(q["question"], "（该公司的结构化事实已从库中移除）")
        results.append({**q, "condition": "C_heldout", "answer": ans_c,
                        "score": grade(ans_c, q["gold_yi"]) if not ans_c.startswith("[ERR") else 0})
        if i % 20 == 0:
            print(f"[{i}/{len(questions)}] {time.perf_counter()-t0:.0f}s", flush=True)
    (OUT / "e1a_v4_results.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in results) + "\n", encoding="utf-8")
    rep = {"experiment": "E1a-v4 structured fact QA", "questions": len(questions),
           "source": "Sina finance statements (validated 30/30 vs case truths)", "by_condition": {}}
    for cond in ("A_closed_book", "B_fact_lookup", "C_heldout"):
        rs = [r["score"] for r in results if r["condition"] == cond]
        rep["by_condition"][cond] = {"n": len(rs), "accuracy": round(sum(rs) / len(rs), 4) if rs else None}
    (OUT / "e1a_v4_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rep["by_condition"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
