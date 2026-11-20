# 论文 A 补充统计（P0）

## 覆盖率敏感性

| 口径 | 分母 | 覆盖 |
|---|---:|---:|
| all_facts | 44390 | **66.46%** |
| exclude_invalid_zero | 30356 | **97.19%** |
| exclude_invalid_and_nonverifiable | 30270 | **97.47%** |

## κ bootstrap 95% CI（2000 次）

| 对照 | κ | 95% CI |
|---|---:|---|
| human_vs_rule | 0.7334 | [0.6333, 0.8307] |
| human_vs_modelA | 0.7361 | [0.6407, 0.828] |
| human_vs_modelB | 0.6844 | [0.5867, 0.7809] |
| modelA_vs_modelB | 0.6844 | [0.5905, 0.7837] |

## 效应量
- 泄漏 A→C：Cohen's h = **3.1416**（极大）
- v7b：Δ=3.16pp，p=0.091（不显著）