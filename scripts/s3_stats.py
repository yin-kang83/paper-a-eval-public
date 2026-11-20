# -*- coding: utf-8 -*-
"""论文 A · S3 统计：标注样本组成 + 双人一致性 κ + 规则初标 vs 人工一致率。

输入：eval/astock/s3_annotation_sheet.csv（人工填写 label(人工)/reviewer/notes）
输出：eval/astock/s3_stats.json / .md

用法：
  python scripts/s3_stats.py            # 生成/刷新统计（未标注时输出样本组成）
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

KB = Path(r"legalwiki-kb")
SHEET = KB / "eval/astock/s3_annotation_sheet.csv"
OUT = KB / "eval/astock"


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """两标注者一致性 κ（支持多标签；样本不足返回 None）。"""
    n = len(pairs)
    if n == 0:
        return None
    labels = sorted({x for p in pairs for x in p})
    po = sum(1 for a, b in pairs if a == b) / n
    pe = 0.0
    for lab in labels:
        pa = sum(1 for a, _ in pairs if a == lab) / n
        pb = sum(1 for _, b in pairs if b == lab) / n
        pe += pa * pb
    if pe >= 1.0:
        return 1.0
    return round((po - pe) / (1 - pe), 4)


def main() -> int:
    if not SHEET.exists():
        print("S3 标注表不存在，先运行 scripts/s3_annotation_sheet.py")
        return 2
    with SHEET.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))

    tiers = Counter(r["auto_tier"] for r in rows)
    proposals = Counter(r.get("rule_proposal", "") for r in rows)
    labeled = [r for r in rows if (r.get("label(人工)") or "").strip()]
    reviewer_a = [r for r in rows if (r.get("reviewer") or "").strip() in ("A", "乙", "reviewer_a")]
    reviewer_b = [r for r in rows if (r.get("reviewer") or "").strip() in ("B", "丙", "reviewer_b")]
    by_id = {r["id"]: r for r in rows}
    pairs = []
    for rid, ra in by_id.items():
        la = (ra.get("label(人工)") or "").strip()
        rb = next((x for x in rows if x["id"] == rid and (x.get("reviewer") or "").strip() in ("B", "reviewer_b")), None)
        lb = (rb.get("label(人工)") or "").strip() if rb else ""
        if la and lb:
            pairs.append((la, lb))

    rule_vs_human = [(r.get("rule_proposal", ""), (r.get("label(人工)") or "").strip())
                     for r in rows if (r.get("label(人工)") or "").strip()]
    stats = {
        "n_sampled": len(rows),
        "by_auto_tier": dict(tiers),
        "by_rule_proposal": dict(proposals),
        "n_labeled": len(labeled),
        "n_reviewer_a": len(reviewer_a),
        "n_reviewer_b": len(reviewer_b),
        "n_paired": len(pairs),
        "kappa_human": cohen_kappa(pairs) if pairs else None,
        "rule_vs_human_agreement": round(sum(1 for a, b in rule_vs_human if a and a == b) / len(rule_vs_human), 4)
        if rule_vs_human else None,
        "n_rule_vs_human": len(rule_vs_human),
        "status": "open" if len(labeled) < len(rows) else "complete",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "s3_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# 论文 A · S3 标注统计", "",
          f"样本 {stats['n_sampled']}；已标注 {stats['n_labeled']}（状态：{stats['status']}）", "",
          "## 样本组成（auto_tier）", "", "| tier | 条数 |", "|---|---:|"]
    for k, v in tiers.items():
        md.append(f"| {k} | {v} |")
    md += ["", "## 规则初标分布", "", "| proposal | 条数 |", "|---|---:|"]
    for k, v in proposals.items():
        md.append(f"| {k} | {v} |")
    md += ["", "## 一致性", "",
           f"- 双人配对 {stats['n_paired']} 条：κ = **{stats['kappa_human']}**（≥0.6 可接受）",
           f"- 规则初标 vs 人工：{stats['n_rule_vs_human']} 条，一致率 **{stats['rule_vs_human_agreement']}**",
           "", "> 填写方式：`label(人工)` + `reviewer`（A/B）+ `notes`；填完重跑本脚本。"]
    (OUT / "s3_stats.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({k: stats[k] for k in ("n_sampled", "n_labeled", "status",
                                            "kappa_human", "rule_vs_human_agreement")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
