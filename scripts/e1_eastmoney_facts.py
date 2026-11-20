# -*- coding: utf-8 -*-
"""第二结构化源：东方财富 F10 财报（与新浪交叉验证用）。

接口：https://datacenter-web.eastmoney.com/api/data/v1/get
报表：RPT_F10_FINANCE_GBALANCE（资产负债表）/ RPT_F10_FINANCE_GINCOME（利润表）
过滤：REPORT_DATE='YYYY-12-31'；字段映射见 FIELD_MAP。
落库：data/astock\eastmoney_facts.db(company, period, item, value_yuan)
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path

ASTOCK = Path(r"data/astock")
FACTS_DB = ASTOCK / "astock_facts.db"
EM_DB = ASTOCK / "eastmoney_facts.db"
UA = "Mozilla/5.0"
BASE = "https://datacenter-web.eastmoney.com/api/data/v1/get"
DATES = ("2020-12-31", "2021-12-31", "2022-12-31", "2023-12-31", "2024-12-31")

FIELD_MAP = {
    # 资产负债表
    "TOTAL_ASSETS": "资产总计",
    "TOTAL_CURRENT_ASSETS": "流动资产合计",
    "TOTAL_NONCURRENT_ASSETS": "非流动资产合计",
    "TOTAL_LIABILITIES": "负债合计",
    "TOTAL_CURRENT_LIAB": "流动负债合计",
    "TOTAL_NONCURRENT_LIAB": "非流动负债合计",
    "TOTAL_EQUITY": "所有者权益合计",
    "TOTAL_PARENT_EQUITY": "归属于母公司所有者权益合计",
    "MINORITY_EQUITY": "少数股东权益",
    "TOTAL_LIAB_EQUITY": "负债和所有者权益总计",
    "MONETARYFUNDS": "货币资金",
    "ACCOUNTS_RECE": "应收账款",
    "NOTE_RECE": "应收票据",
    "PREPAYMENT": "预付款项",
    "OTHER_RECE": "其他应收款",
    "INVENTORY": "存货",
    "FIXED_ASSET": "固定资产",
    "CIP": "在建工程",
    "INTANGIBLE_ASSET": "无形资产",
    "GOODWILL": "商誉",
    "LONG_PREPAID_EXPENSE": "长期待摊费用",
    "DEFER_TAX_ASSET": "递延所得税资产",
    "DEFER_TAX_LIAB": "递延所得税负债",
    "SHORT_LOAN": "短期借款",
    "ACCOUNTS_PAYABLE": "应付账款",
    "NOTE_PAYABLE": "应付票据",
    "ADVANCE_RECEIVABLES": "预收款项",
    "CONTRACT_LIAB": "合同负债",
    "STAFF_SALARY_PAYABLE": "应付职工薪酬",
    "TAX_PAYABLE": "应交税费",
    "OTHER_PAYABLE": "其他应付款",
    "NONCURRENT_LIAB_1YEAR": "一年内到期的非流动负债",
    "LONG_LOAN": "长期借款",
    "BOND_PAYABLE": "应付债券",
    "LEASE_LIAB": "租赁负债",
    "USERIGHT_ASSET": "使用权资产",
    "LONG_PAYABLE": "长期应付款",
    "DEFER_INCOME": "递延收益",
    "SHARE_CAPITAL": "实收资本",
    "CAPITAL_RESERVE": "资本公积",
    "SURPLUS_RESERVE": "盈余公积",
    "UNASSIGN_RPOFIT": "未分配利润",
    "OTHER_COMPRE_INCOME": "其他综合收益",
    # 利润表
    "TOTAL_OPERATE_INCOME": "营业总收入",
    "OPERATE_INCOME": "营业收入",
    "OPERATE_COST": "营业成本",
    "OPERATE_PROFIT": "营业利润",
    "TOTAL_PROFIT": "利润总额",
    "NETPROFIT": "净利润",
    "INCOME_TAX": "所得税费用",
    "SALE_EXPENSE": "销售费用",
    "MANAGE_EXPENSE": "管理费用",
    "FINANCE_EXPENSE": "财务费用",
    "RESEARCH_EXPENSE": "研发费用",
    "TOTAL_OPERATE_COST": "营业总成本",
    "TRADE_FINASSET": "交易性金融资产",
    "NOTE_ACCOUNTS_RECE": "应收票据及应收账款",
    "FINANCE_RECE": "应收款项融资",
    "NONCURRENT_ASSET_1YEAR": "一年内到期的非流动资产",
    "OTHER_CURRENT_ASSET": "其他流动资产",
    "LONG_EQUITY_INVEST": "长期股权投资",
    "OTHER_EQUITY_INVEST": "其他权益工具投资",
    "INVEST_REALESTATE": "投资性房地产",
    "PRODUCTIVE_BIOLOGY_ASSET": "生产性生物资产",
    "OIL_GAS_ASSET": "油气资产",
    "OTHER_NONCURRENT_ASSET": "其他非流动资产",
    "FIXED_ASSET_DISPOSAL": "固定资产清理",
    "PROJECT_MATERIAL": "工程物资",
    "DEVELOP_EXPENSE": "开发支出",
    "CONTRACT_ASSET": "合同资产",
    "HOLDSALE_ASSET": "持有待售资产",
    "DIVIDEND_RECE": "应收股利",
    "INTEREST_RECE": "应收利息",
    "TRADE_FINLIAB": "交易性金融负债",
    "DERIVE_FINLIAB": "衍生金融负债",
    "NOTE_ACCOUNTS_PAYABLE": "应付票据及应付账款",
    "SHORT_FIN_PAYABLE": "短期融资款",
    "ADVANCE_RECEIVABLES": "预收款项",
    "SELL_REPO_FINASSET": "卖出回购金融资产款",
    "FEE_COMMISSION_PAYABLE": "应付手续费及佣金",
    "DIVIDEND_PAYABLE": "应付股利",
    "INTEREST_PAYABLE": "应付利息",
    "PREDICT_LIAB": "预计负债",
    "PREDICT_CURRENT_LIAB": "预计流动负债",
    "HOLDSALE_LIAB": "持有待售负债",
    "LONG_STAFFSALARY_PAYABLE": "长期应付职工薪酬",
    "SPECIAL_PAYABLE": "专项应付款",
    "OTHER_NONCURRENT_LIAB": "其他非流动负债",
    "PERPETUAL_BOND": "永续债",
    "PREFERRED_SHARES": "优先股",
    "TREASURY_SHARES": "库存股",
    "SPECIAL_RESERVE": "专项储备",
    "GENERAL_RISK_RESERVE": "一般风险准备",
    "UNCONFIRM_INVEST_LOSS": "未确认投资损失",
    "CONVERT_DIFF": "外币报表折算差额",
    "MINORITY_EQUITY": "少数股东权益",
    "OPERATE_TAX_ADD": "税金及附加",
    "TOTAL_OPERATE_INCOME": "营业总收入",
    "TOTAL_OPERATE_COST": "营业总成本",
    "SALE_EXPENSE": "销售费用",
    "MANAGE_EXPENSE": "管理费用",
    "FINANCE_EXPENSE": "财务费用",
    "RESEARCH_EXPENSE": "研发费用",
    "OTHER_INCOME": "其他收益",
    "INVEST_INCOME": "投资收益",
    "FAIRVALUE_CHANGE_INCOME": "公允价值变动收益",
    "CREDIT_IMPAIRMENT_LOSS": "信用减值损失",
    "ASSET_IMPAIRMENT_LOSS": "资产减值损失",
    "ASSET_DISPOSAL_INCOME": "资产处置收益",
    "NONBUSINESS_INCOME": "营业外收入",
    "NONBUSINESS_EXPENSE": "营业外支出",
    "INCOME_TAX": "所得税费用",
    "NETPROFIT": "净利润",
    "PARENT_NETPROFIT": "归属于母公司股东的净利润",
}
REPORTS = ("RPT_F10_FINANCE_GBALANCE", "RPT_F10_FINANCE_GINCOME")


def canon(name: str) -> str:
    s = str(name or "")
    s = re.sub(r"[（(][^）)]*[）)]", "", s)
    return re.sub(r"\s+", "", s)


def fetch(report: str, code: str, date: str) -> dict:
    params = {"reportName": report, "columns": "ALL",
              "filter": f'(SECURITY_CODE="{code}")(REPORT_DATE=\'{date}\')',
              "pageNumber": 1, "pageSize": 10, "source": "WEB", "client": "WEB"}
    url = BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Referer": "https://data.eastmoney.com/"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode())
    data = (d.get("result") or {}).get("data") or []
    return data[0] if data else {}


def main() -> int:
    con = sqlite3.connect(f"file:{FACTS_DB}?mode=ro", uri=True)
    companies = [r[0] for r in con.execute("select distinct company from facts order by company")]
    con.close()
    if EM_DB.exists():
        EM_DB.unlink()
    out = sqlite3.connect(EM_DB)
    out.execute("CREATE TABLE facts (company TEXT, period TEXT, item TEXT, value_yuan REAL,"
                " report TEXT, PRIMARY KEY(company,period,item))")
    total = 0
    for i, code in enumerate(companies, 1):
        for report in REPORTS:
            for date in DATES:
                try:
                    row = fetch(report, code, date)
                except Exception as e:  # noqa: BLE001
                    print("fail", code, date, report, type(e).__name__)
                    continue
                if not row:
                    continue
                period = date.replace("-", "")
                for field, item in FIELD_MAP.items():
                    v = row.get(field)
                    if isinstance(v, (int, float)):
                        out.execute("INSERT OR REPLACE INTO facts VALUES (?,?,?,?,?)",
                                    (code, period, canon(item), float(v), report))
                        total += 1
                time.sleep(0.6)
        if i % 5 == 0:
            print(f"[{i}/{len(companies)}] rows={total}", flush=True)
    out.commit()
    n = out.execute("select count(*) from facts").fetchone()[0]
    by = dict(out.execute("select item,count(*) from facts group by item"))
    out.close()
    print(json.dumps({"companies": len(companies), "rows": n, "by_item": by}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
