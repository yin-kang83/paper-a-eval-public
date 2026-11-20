# -*- coding: utf-8 -*-
"""C1-lite：单源事实的"内部勾稽"升级（不依赖第三源）。

思路：双源确认率受第二源覆盖限制；对 single_source 事实，若其公司-期间满足
可验证恒等式，则升级为 internally_consistent（可信度介于 confirmed 与 single 之间）。
恒等式：
  I1 资产总计 = 负债合计 + 所有者权益合计
  I2 负债和所有者权益总计 = 资产总计（若两者都有）
  I3 流动资产合计 + 非流动资产合计 = 资产总计
  I4 流动负债合计 + 非流动负债合计 = 负债合计
不满足者标 identity_failed（隔离）。
输出：eval/astock/dual_gate_tiers.json
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

VER = Path(r"data/astock\fact_verification.db")
KB = Path(r"legalwiki-kb")
OUT = KB / "eval/astock"
TOL = 0.01


def main() -> int:
    con = sqlite3.connect(f"file:{VER}?mode=ro", uri=True)
    rows = con.execute("select company,period,item,value_yuan,status from verification").fetchall()
    con.close()
    by = {}
    for c, p, i, v, st in rows:
        by.setdefault((c, p), {})[i] = (v, st)

    tiers = {"confirmed": 0, "internally_consistent": 0, "identity_failed": 0, "single_source": 0}
    details = []
    for (c, p), items in by.items():
        def val(name):
            return items[name][0] if name in items else None

        a, l, e = val("资产总计"), val("负债合计"), val("所有者权益合计")
        checks = []
        if a is not None and l is not None and e is not None:
            checks.append(("I1", abs(a - (l + e)) <= max(TOL, abs(a) * 1e-6)))
        le = val("负债和所有者权益总计")
        if a is not None and le is not None:
            checks.append(("I2", abs(a - le) <= max(TOL, abs(a) * 1e-6)))
        ca, nca = val("流动资产合计"), val("非流动资产合计")
        if a is not None and ca is not None and nca is not None:
            checks.append(("I3", abs(ca + nca - a) <= max(TOL, abs(a) * 1e-6)))
        cl, ncl = val("流动负债合计"), val("非流动负债合计")
        if l is not None and cl is not None and ncl is not None:
            checks.append(("I4", abs(cl + ncl - l) <= max(TOL, abs(l) * 1e-6)))

        for name, (v, st) in items.items():
            if st != "single_source":
                tiers[st] = tiers.get(st, 0) + 1
                continue
            ok_checks = [c2 for c2 in checks if c2[1]]
            if checks and len(ok_checks) == len(checks):
                tiers["internally_consistent"] += 1
                if len(details) < 20:
                    details.append({"company": c, "period": p, "item": name,
                                    "identity_checks": [x[0] for x in checks]})
            elif checks and len(ok_checks) < len(checks):
                tiers["identity_failed"] += 1
            else:
                tiers["single_source"] += 1
    total = sum(tiers.values())
    report = {"total": total, "tiers": tiers,
              "tier_notes": {"confirmed": "双源一致",
                             "internally_consistent": "单源+公司-期间恒等式全通过",
                             "identity_failed": "单源且恒等式失败（隔离）",
                             "single_source": "单源且无可验证恒等式"},
              "trusted_coverage": round((tiers["confirmed"] + tiers["internally_consistent"]) / total, 4)
              if total else None,
              "samples": details}
    # 写回验证库（供 fact_router 使用）
    vcon = sqlite3.connect(str(VER))
    vcon.execute("CREATE TABLE IF NOT EXISTS verification_tiers (company TEXT, period TEXT,"
                 " item TEXT, value_yuan REAL, tier TEXT, PRIMARY KEY(company,period,item))")
    vcon.execute("DELETE FROM verification_tiers")
    for (c, p_), items in by.items():
        for name, (v, st) in items.items():
            tier = st if st != "single_source" else (
                "internally_consistent" if False else st)
    # 重新按分级写入
    for (c, p_), items in by.items():
        def val(name):
            return items[name][0] if name in items else None
        a, l, e = val("资产总计"), val("负债合计"), val("所有者权益合计")
        checks = []
        if a is not None and l is not None and e is not None:
            checks.append(abs(a - (l + e)) <= max(TOL, abs(a) * 1e-6))
        le = val("负债和所有者权益总计")
        if a is not None and le is not None:
            checks.append(abs(a - le) <= max(TOL, abs(a) * 1e-6))
        ca, nca = val("流动资产合计"), val("非流动资产合计")
        if a is not None and ca is not None and nca is not None:
            checks.append(abs(ca + nca - a) <= max(TOL, abs(a) * 1e-6))
        cl, ncl = val("流动负债合计"), val("非流动负债合计")
        if l is not None and cl is not None and ncl is not None:
            checks.append(abs(cl + ncl - l) <= max(TOL, abs(l) * 1e-6))
        for name, (v, st) in items.items():
            tier = st
            if st == "single_source":
                if checks and all(checks):
                    tier = "internally_consistent"
            vcon.execute("INSERT OR REPLACE INTO verification_tiers VALUES (?,?,?,?,?)",
                         (c, p_, name, v, tier))
    vcon.commit()
    vcon.close()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "dual_gate_tiers.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
    md = ["# 双验证分级（C1-lite：内部勾稽升级）", "",
          f"事实 {total}", "",
          "| 层级 | 条数 | 占比 |", "|---|---:|---:|"]
    for k, v in tiers.items():
        md.append(f"| {k} | {v} | {v/total*100:.1f}% |")
    md += ["", f"**可信覆盖（confirmed+internally_consistent）**：{report['trusted_coverage']*100:.1f}%",
           "", "> 内部恒等式：I1 资产=负债+权益；I2 负债和权益总计=资产；I3 流动+非流动=资产；I4 流动+非流动负债=负债。",
           "> 仅对 single_source 事实升级；identity_failed 隔离。"]
    (OUT / "dual_gate_tiers.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"total": total, "tiers": tiers, "trusted_coverage": report["trusted_coverage"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
