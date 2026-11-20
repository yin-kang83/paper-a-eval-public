# paper-a-eval-public

> 论文 A《泄漏控制与双源验证：金融数值问答的评测方法研究》的公开代码与聚合证据包。
> 论文 DOI: https://doi.org/10.5281/zenodo.24191264

## 这是什么

- `scripts/`：论文 A 的评测/双源验证/勾稽/争议归因脚本（参考实现）；
- `results/`：论文 A 的**聚合统计 JSON/MD**（不含逐题 raw、不含真实年报原始文本）；
- `docs/`：测量规范、S3 盲标协议、论文初稿；
- 本包**不含** `fact_verification.db`、真实年报/公告数据、逐题 raw、客户数据、PII、密钥。

## 数据边界（重要）

论文 A 的完整数据来自公开年报/公告与财经门户，但原始库/逐题 raw 不随包分发：

- 不包含 `fact_verification.db`；
- 不包含 `s2b_results.jsonl`、`e1a_*.jsonl` 等逐题 raw；
- 不包含 S3 人工标注表/逐条标注 CSV；
- 复现需要自备合法来源数据，并按 `docs/论文A-测量规范表.md` 的口径重建。

## 脚本说明

| 文件 | 用途 |
|---|---|
| `c1_internal_tiers.py` | 内部证据分层 |
| `c2_statement_identities.py` | 三表勾稽 |
| `c2b_articulation_stats.py` | 勾稽统计 |
| `classify_disputes.py` | 双源冲突归因 |
| `dual_verify.py` / `dual_verify_gate.py` | 双源验证/门控 |
| `e1a_astock_qa*.py` / `e1a_v4_facts.py` | 文本检索轴实验 |
| `e1_eastmoney_facts.py` / `e1_sina_facts.py` | 结构化事实源 |
| `e1c_astock_structure_audit.py` | 结构审计 |
| `fact_router.py` | 事实路由 |
| `s3_stats.py` | S3 标注统计 |

脚本中的本机路径已替换为相对路径/占位路径；运行前请按 `docs/论文A-测量规范表.md` 准备数据。

## 许可

- 代码：MIT（见 `LICENSE`）。
- 文档/结果表：CC BY 4.0（见 `LICENSE-DOCS.md`）。
- 论文：以 Zenodo 记录为准（CC BY 4.0）。

## 引用

```bibtex
@misc{paper_a_eval_public_2026,
  title = {Paper A evaluation code and aggregate evidence},
  author = {Yin, Kang},
  year = {2026},
  note = {Code DOI: 10.5281/zenodo.XXXXXXX; Paper DOI: 10.5281/zenodo.24191264}
}
```
