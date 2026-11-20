# -*- coding: utf-8 -*-
"""E1a · A股年报真实问答：闭卷 vs 检索（同源/held-out）。

数据：data/astock\*.txt（6 份 2023 年报，★官方巨潮下载）
题：从案例库 facts.items 的期末金额自动生成（单位亿元，两位小数），答案逐字于年报。
三条件：
  A 闭卷（无文档）
  B 检索 k=3（语料含本公司年报 = 同源）
  C 检索 k=3（语料剔除本公司年报 = held-out）
评分：数值比较（亿元，容差 0.02 或 0.5%）
输出：eval/astock/e1a_results.jsonl + e1a_report.json/md
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import sys
import time
from pathlib import Path

KB = Path(r"legalwiki-kb")
sys.path.insert(0, str(KB))
sys.path.insert(0, str(KB / "scripts"))
import x1_run as xr  # noqa: E402
from legalwiki.retrieval import rerank  # noqa: E402

ASTOCK = Path(r"data/astock")
OUT = KB / "eval" / "astock"
DB = ASTOCK / "astock_corpus.db"
LC = Path(r"data\E迁移-20261111\康正财务智能体\data\listed_companies")
COMPANIES = {"601111", "601919", "601186", "601669", "001965", "600377"}


def build_corpus() -> None:
    if DB.exists():
        return
    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE docs (id TEXT PRIMARY KEY, parent_id TEXT, title TEXT, full_text TEXT, "
                "char_count INTEGER)")
    con.execute("CREATE VIRTUAL TABLE docs_fts USING fts5(title, full_text, tokenize='trigram')")
    n = 0
    for idx in json.loads((OUT / "corpus_index.json").read_text(encoding="utf-8")):
        text = Path(idx["txt"]).read_text(encoding="utf-8")
        parent = f"{idx['company_code']}-{idx['year']}"
        # 按行切块 ~1500 字符，带标题
        chunks, cur = [], ""
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if len(cur) + len(line) > 1500:
                chunks.append(cur)
                cur = line
            else:
                cur += "\n" + line
        if cur:
            chunks.append(cur)
        for i, ch in enumerate(chunks):
            import hashlib
            did = hashlib.sha256(ch.encode()).hexdigest()[:32]
            title = f"{idx['company_name']} {idx['year']}年报 §{i+1}"
            con.execute("INSERT OR IGNORE INTO docs VALUES (?,?,?,?,?)",
                        (did, parent, title, ch, len(ch)))
            con.execute("INSERT OR IGNORE INTO docs_fts (rowid,title,full_text) "
                        "SELECT rowid,title,full_text FROM docs WHERE id=?", (did,))
            n += 1
    con.commit()
    con.close()
    print("corpus chunks:", n)


def load_cases():
    out = []
    for f in ("structured_cases_20261026.jsonl", "expansion_cases_20261026.jsonl",
              "financial_assets_cases_20261026.jsonl"):
        p = LC / f
        if p.exists():
            out.extend(json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip())
    return out


def make_questions(cases):
    qs = []
    for c in cases:
        code = str(c.get("company_code", ""))
        if code not in COMPANIES or c.get("report_year") != 2023:
            continue
        items = (c.get("facts") or {}).get("items") or {}
        ranked = []
        for name, v in items.items():
            if isinstance(v, dict) and isinstance(v.get("period_end_yuan"), (int, float)):
                ranked.append((abs(v["period_end_yuan"]), name, v["period_end_yuan"]))
        ranked.sort(reverse=True)
        for _amt, name, val in ranked[:2]:
            yi = val / 1e8
            qs.append({
                "qid": f"E1a-{c['case_id']}-{name}", "company": code,
                "company_name": c.get("company_name"), "item": name,
                "question": (f"{c.get('company_name')}（{code}）2023 年年度报告的合并资产负债表中，"
                             f"“{name}”期末金额是多少？请以亿元为单位回答，保留两位小数。"),
                "gold_yi": round(yi, 2),
            })
    return qs


def parse_number(text: str):
    t = text.replace(",", "")
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
    v = parse_number(ans)
    if v is None:
        return 0
    tol = max(0.02, abs(gold) * 0.005)
    return 1 if abs(v - gold) <= tol else 0


def answer(question: str, docs) -> str:
    if docs:
        ctx = "\n\n".join(f"【材料{i+1}】{t}\n{txt[:1600]}"
                          for i, (_id, t, txt) in enumerate(docs))
    else:
        ctx = "（无检索材料）"
    prompt = f"依据以下材料回答。\n{ctx}\n\n问题：{question}\n只给最终答案（数字+单位），不要解释。"
    try:
        return xr.chat(xr.DS_URL, xr.DS_KEY, "deepseek-chat",
                       [{"role": "user", "content": prompt}], max_tokens=60)
    except Exception as e:  # noqa: BLE001
        return f"[ERR:{type(e).__name__}]"


def fetch(con, q: str, k: int, exclude_company: str | None):
    hits = rerank.search_domain(con, q, None, k=k * 5)
    out = []
    for h in hits:
        row = con.execute("select id,parent_id,title,full_text from docs where id=?", (h["id"],)).fetchone()
        if not row:
            continue
        if exclude_company and str(row[1]).startswith(exclude_company):
            continue
        out.append((row[0], row[2], row[3]))
        if len(out) >= k:
            break
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    build_corpus()
    questions = make_questions(load_cases())
    print("questions:", len(questions))
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    results = []
    t0 = time.perf_counter()
    for i, q in enumerate(questions, 1):
        for cond, k, excl in (("A_closed_book", 0, None), ("B_full_corpus", 3, None),
                              ("C_heldout", 3, q["company"])):
            docs = fetch(con, q["question"], k, excl) if k else []
            ans = answer(q["question"], docs)
            score = grade(ans, q["gold_yi"]) if not ans.startswith("[ERR") else 0
            results.append({**q, "condition": cond, "answer": ans, "score": score})
        if i % 10 == 0:
            print(f"[{i}/{len(questions)}] {time.perf_counter()-t0:.0f}s", flush=True)
    con.close()
    (OUT / "e1a_results.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in results) + "\n",
                                           encoding="utf-8")
    rep = {"experiment": "E1a real annual-report QA (6 companies, 2023)", "questions": len(questions),
           "by_condition": {}, "elapsed_s": round(time.perf_counter() - t0, 1)}
    for cond in ("A_closed_book", "B_full_corpus", "C_heldout"):
        rs = [r["score"] for r in results if r["condition"] == cond]
        rep["by_condition"][cond] = {"n": len(rs), "accuracy": round(sum(rs) / len(rs), 4) if rs else None}
    (OUT / "e1a_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# E1a · A股年报真实问答（6 家 2023 年报）", "",
          "| 条件 | 题数 | 准确率 |", "|---|---:|---:|"]
    for k, d in rep["by_condition"].items():
        md.append(f"| {k} | {d['n']} | {d['accuracy']} |")
    md += ["", "> 数值题（亿元，容差 2% 或 0.02 亿）；B=同源（语料含本公司年报），C=held-out（剔除本公司）。"]
    (OUT / "e1a_report.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
