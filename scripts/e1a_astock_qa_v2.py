# -*- coding: utf-8 -*-
"""E1a v2：改进检索（科目名+公司名直查，避免 TOC 噪声）+ gold 源文校验。

检索：SQL 先筛 title 含公司名 & full_text 含科目名 → 按"含数字/表格密度"排序取 top3；
     不够再退回 rerank。
gold 校验：gold 数值（去逗号/空格）必须出现在本公司年报全文，否则该题剔除（数据质量门）。
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
from legalwiki.retrieval import rerank  # noqa: E402

ASTOCK = Path(r"data/astock")
OUT = KB / "eval" / "astock"
DB = ASTOCK / "astock_corpus.db"
CORPUS_IDX = OUT / "corpus_index.json"


def norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s or ""))


def fmt_variants(v: float) -> list[str]:
    out = []
    for vv in (v, v / 1e4, v / 1e8):  # 元/万元/亿元 文本形态
        for f in (f"{vv:.2f}", f"{vv:.0f}", f"{vv:,.2f}", f"{vv:,}"):
            out.append(f.replace(",", ""))
    return list(dict.fromkeys(out))


def gold_in_text(gold_yuan: float, text: str) -> bool:
    t = norm(text)
    return any(v in t for v in fmt_variants(gold_yuan))


def load_questions() -> list[dict]:
    # 复用 e1a 生成的 29 题（从结果文件取唯一题目）
    rows = [json.loads(l) for l in (OUT / "e1a_results.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    seen, qs = set(), []
    for r in rows:
        if r["qid"] in seen:
            continue
        seen.add(r["qid"])
        qs.append(r)
    return qs


def fetch(con, q: dict, k: int, exclude_company: bool) -> list[tuple]:
    company = q["company"]
    item = q.get("item", "")
    sql = ("select id,parent_id,title,full_text from docs where title like ? and full_text like ? "
           "order by length(full_text) desc limit 40")
    rows = con.execute(sql, (f"%{q['company_name']}%", f"%{item}%")).fetchall()
    if not rows:
        hits = rerank.search_domain(con, q["question"], None, k=k * 5)
        rows = []
        for h in hits:
            r = con.execute("select id,parent_id,title,full_text from docs where id=?", (h["id"],)).fetchone()
            if r:
                rows.append(r)
    out = []
    for r in rows:
        parent = str(r[1] or "")
        if exclude_company and parent.startswith(company):
            continue
        # 表格密度：数字个数
        score = len(re.findall(r"\d", r[3]))
        out.append((score, r))
    out.sort(key=lambda x: -x[0])
    return [(r[0], r[2], r[3]) for _s, r in out[:k]]


def answer(question: str, docs) -> str:
    ctx = ("\n\n".join(f"【材料{i+1}】{t}\n{txt[:1800]}" for i, (_id, t, txt) in enumerate(docs))
           if docs else "（无检索材料）")
    prompt = (f"依据以下材料回答。\n{ctx}\n\n问题：{question}\n"
              f"只给最终答案（数字+单位），不要解释；材料中找不到就回答“无法确定”。")
    try:
        return xr.chat(xr.DS_URL, xr.DS_KEY, "deepseek-chat",
                       [{"role": "user", "content": prompt}], max_tokens=60)
    except Exception as e:  # noqa: BLE001
        return f"[ERR:{type(e).__name__}]"


def parse_number(text: str):
    t = str(text).replace(",", "")
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
    return 1 if abs(v - gold) <= max(0.02, abs(gold) * 0.005) else 0


def main() -> int:
    idx = {i["company_code"]: Path(i["txt"]) for i in json.loads(CORPUS_IDX.read_text(encoding="utf-8"))}
    texts = {c: p.read_text(encoding="utf-8") for c, p in idx.items()}
    qs = load_questions()
    # gold 源文校验（用 gold_yi*1e8 元）
    valid = []
    for q in qs:
        gold_yuan = q["gold_yi"] * 1e8
        if gold_in_text(gold_yuan, texts.get(q["company"], "")):
            valid.append(q)
    print("questions:", len(qs), "valid after gold-source check:", len(valid))
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    results, t0 = [], time.perf_counter()
    for i, q in enumerate(valid, 1):
        for cond, k, excl in (("A_closed_book", 0, False), ("B_full_corpus", 3, False),
                              ("C_heldout", 3, True)):
            docs = fetch(con, q, k, excl) if k else []
            ans = answer(q["question"], docs)
            results.append({**q, "condition": cond, "answer": ans,
                            "score": grade(ans, q["gold_yi"]) if not ans.startswith("[ERR") else 0})
        if i % 10 == 0:
            print(f"[{i}/{len(valid)}] {time.perf_counter()-t0:.0f}s", flush=True)
    con.close()
    (OUT / "e1a_results_v2.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in results) + "\n", encoding="utf-8")
    rep = {"experiment": "E1a v2 real annual-report QA", "questions_total": len(qs),
           "questions_valid": len(valid), "by_condition": {},
           "elapsed_s": round(time.perf_counter() - t0, 1)}
    for cond in ("A_closed_book", "B_full_corpus", "C_heldout"):
        rs = [r["score"] for r in results if r["condition"] == cond]
        rep["by_condition"][cond] = {"n": len(rs), "accuracy": round(sum(rs) / len(rs), 4) if rs else None}
    (OUT / "e1a_report_v2.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# E1a v2 · A股年报真实问答（6 家 2023 年报，gold 已过源文校验）", "",
          f"题 {len(valid)}/{len(qs)}（剔除 gold 不在源文的题）", "",
          "| 条件 | 题数 | 准确率 |", "|---|---:|---:|"]
    for k, d in rep["by_condition"].items():
        md.append(f"| {k} | {d['n']} | {d['accuracy']} |")
    md += ["", "> A=闭卷；B=检索（语料含本公司年报，同源）；C=held-out（剔除本公司年报）。",
           "> 数值题，亿元，容差 0.5%/0.02 亿。"]
    (OUT / "e1a_report_v2.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
