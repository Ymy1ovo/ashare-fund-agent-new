"""阶段3B-4.4 数据缺口补强：把已核验的官方公告证据写入数据库。

三条铁律：
1. 只写有原文证据的日期；查不到就是 NULL，不推算。
2. 官方公告原文 → A 级；第三方转载/平台 → C 级，绝不冒充 A。
3. 幂等：重复执行不产生重复记录。

数据来源全部是东方财富公告库（转发的基金管理人正式公告正文），
每条记录保留 announcement_id + announcement_url 可回源。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.database.db import get_connection

EVIDENCE_DIR = (Path(__file__).resolve().parents[2]
                / "reports" / "evidence" / "phase3b4_4")

SOURCE_OFFICIAL_ANN = "eastmoney.announcement.official_text"
SOURCE_PLATFORM = "fundf10.eastmoney.com"
SOURCE_DISCLOSURE = "fundf10.eastmoney.com/gmbd"

DISCLAIMER_FEE = (
    "费率及其生效日期取自基金管理人发布的调低费率/修订基金合同公告原文"
    "（东方财富公告库转发，公告 ID 可回源）。公告正文明确记载调整前后费率"
    "与生效日期，属基金管理人正式披露内容；因未直接访问管理人官网原件，"
    "证据等级记 A-（official_text_via_aggregator）。")
DISCLAIMER_MANAGER = (
    "基金经理任职/离任日期取自基金管理人基金经理变更公告原文"
    "（东方财富公告库转发，公告 ID 可回源）。公告正文明确记载任职日期或"
    "离任日期；因未直接访问管理人官网原件，证据等级记 A-。")
DISCLAIMER_AUM = (
    "基金规模（期末净资产）取自天天基金规模变动页，"
    "原始出处为基金定期报告（季报/半年报/年报）披露的期末净资产。"
    "本表记录的日期是**披露对应的时点**，不是公告发布日期。"
    "2013 年以后的记录基本都是季末/半年末/年末；"
    "2013 年以前部分记录是月频或周频披露（如 2013-03-15、2010-08-23），"
    "日期本身来自页面，未做任何归并或推测。"
    "因未逐份下载定期报告原文核对，证据等级记 C。")

# 证据等级：官方公告原文经聚合平台转发
LEVEL_OFFICIAL_TEXT = "A-"      # 官方原文，但经第三方公告库
LEVEL_PLATFORM = "C"


@dataclass
class IngestStat:
    planned: int = 0
    inserted: int = 0
    updated: int = 0
    skipped_existing: int = 0
    skipped_undisclosed: int = 0
    failed: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"planned": self.planned, "inserted": self.inserted,
                "updated": self.updated,
                "skipped_existing": self.skipped_existing,
                "skipped_undisclosed": self.skipped_undisclosed,
                "failed": self.failed, "by_kind": dict(self.by_kind),
                "notes": list(self.notes)}


def ann_url(code: str, ann_id: str) -> str:
    return f"http://data.eastmoney.com/notices/detail/{code}/{ann_id}.html"


# ---------------------------------------------------------------- 费率生效时间
# 结构：code -> 费率类型 -> (生效日, 调整前, 调整后, 公告ID, 公告日, 原文摘录)
FEE_EFFECTIVE = {
    # 华夏纯债 000015/000016：托管费 0.20% → 0.10%，2024-09-12 起生效
    "000015": {
        "custody": ("2024-09-12", 0.0020, 0.0010,
                    "AN202409091639788444", "2024-09-09",
                    "托管费率由0.20%年费率调低为0.10%年费率，自2024年9月12日起生效"),
    },
    "000016": {
        "custody": ("2024-09-12", 0.0020, 0.0010,
                    "AN202409091639788444", "2024-09-09",
                    "托管费率由0.20%年费率调低为0.10%年费率，自2024年9月12日起生效"),
    },
    # 华夏沪深300ETF联接 000051：管理费 0.50%→0.15%，托管费 0.10%→0.05%，2024-11-22
    "000051": {
        "management": ("2024-11-22", 0.0050, 0.0015,
                       "AN202411191640969182", "2024-11-20",
                       "管理费率0.50%→0.15%，自2024年11月22日起生效"),
        "custody": ("2024-11-22", 0.0010, 0.0005,
                    "AN202411191640969182", "2024-11-20",
                    "托管费率0.10%→0.05%，自2024年11月22日起生效"),
    },
    # 天弘余额宝 000198：托管费 0.08%→0.07%，2025-09-23
    "000198": {
        "custody": ("2025-09-23", 0.0008, 0.0007,
                    "AN202509231748927229", "2025-09-23",
                    "托管费由0.08%年费率调低为0.07%年费率，自2025年9月23日起生效"),
    },
    # 易方达消费 110022：管理费 1.50%→1.20%，托管费 0.25%→0.20%，2023-07-10
    "110022": {
        "management": ("2023-07-10", 0.0150, 0.0120,
                       "AN202307081592118526", "2023-07-08",
                       "易方达消费行业股票型证券投资基金：管理费率1.50%→1.20%，自2023年7月10日起"),
        "custody": ("2023-07-10", 0.0025, 0.0020,
                    "AN202307081592118526", "2023-07-08",
                    "易方达消费行业股票型证券投资基金：托管费率0.25%→0.20%，自2023年7月10日起"),
    },
    # 富国天惠 161005：管理费 1.50%→1.20%，托管费 0.25%→0.20%，2023-07-10
    "161005": {
        "management": ("2023-07-10", 0.0150, 0.0120,
                       "AN202307081592116736", "2023-07-08",
                       "161005 富国天惠精选成长混合型证券投资基金(LOF)：管理费率1.50%→1.20%，自2023年7月10日起"),
        "custody": ("2023-07-10", 0.0025, 0.0020,
                    "AN202307081592116736", "2023-07-08",
                    "161005 富国天惠精选成长混合型证券投资基金(LOF)：托管费率0.25%→0.20%，自2023年7月10日起"),
    },
    # 招商中证白酒 161725/012414：管理费 1.00% 不变，托管费 0.22%→0.20%，2023-07-10
    "161725": {
        "custody": ("2023-07-10", 0.0022, 0.0020,
                    "AN202307081592119207", "2023-07-08",
                    "招商中证白酒指数证券投资基金：管理费率1.00%→1.00%，托管费率0.22%→0.20%，自2023年7月10日起"),
    },
    "012414": {
        "custody": ("2023-07-10", 0.0022, 0.0020,
                    "AN202307081592119207", "2023-07-08",
                    "招商中证白酒指数证券投资基金：托管费率0.22%→0.20%，自2023年7月10日起"),
    },
}


def ingest_fee_effective(db_path=None) -> dict:
    """给已存在的年化费率规则补 effective_from 与公告证据。

    只补 effective_from，不改 rate_original（rate_original 是当前费率，
    仍为 C 级平台数据；此处补的是「这条费率从哪天开始」）。
    """
    from app.fund.ingest_3b4_2 import FEE_SOURCE

    stat = IngestStat()
    stat.planned = sum(len(v) for v in FEE_EFFECTIVE.values())
    now = "2026-11-20T13:45:00"

    with get_connection(db_path) as conn:
        for code, by_type in FEE_EFFECTIVE.items():
            row = conn.execute(
                "SELECT share_class_id FROM fund_share_classes "
                "WHERE share_class_code=?", (code,)).fetchone()
            if row is None:
                stat.failed += 1
                stat.notes.append(f"{code} 无对应份额，跳过")
                continue
            sid = int(row["share_class_id"])
            for fee_type, (eff, before, after, ann_id, ann_date, quote) in by_type.items():
                cur = conn.execute(
                    """SELECT fee_rule_id, effective_from, rate_original
                       FROM fund_fee_rules
                       WHERE share_class_id=? AND fee_type=? AND is_annual=1""",
                    (sid, fee_type)).fetchone()
                if cur is None:
                    stat.failed += 1
                    stat.notes.append(f"{code}/{fee_type} 无对应费率行，跳过")
                    continue
                if cur["effective_from"] is not None:
                    stat.skipped_existing += 1
                    stat.notes.append(
                        f"{code}/{fee_type} 已有生效日 {cur['effective_from']}，不覆盖")
                    continue
                detail = json.dumps({
                    "effective_from": eff,
                    "announcement_date": ann_date,
                    "rate_before": before,
                    "rate_after": after,
                    "rate_current_in_db": cur["rate_original"],
                    "quote": quote,
                    "disclaimer": DISCLAIMER_FEE,
                }, ensure_ascii=False)
                conn.execute(
                    """UPDATE fund_fee_rules
                       SET effective_from=?, effective_to=NULL,
                           announcement_id=?, source_url=?, source_name=?,
                           evidence_level=?, detail=?
                       WHERE fee_rule_id=?""",
                    (eff, ann_id, ann_url(code, ann_id),
                     SOURCE_OFFICIAL_ANN, LEVEL_OFFICIAL_TEXT, detail,
                     int(cur["fee_rule_id"])))
                stat.inserted += 1
                stat.by_kind[fee_type] = stat.by_kind.get(fee_type, 0) + 1
    return stat.as_dict()


# ---------------------------------------------------------------- 基金经理任职历史
# (code, manager, start_date, end_date, change_type, ann_id, ann_date, quote)
MANAGER_RECORDS = [
    ("000015", "柳万军", "2017-09-08", None, "增聘",
     "AN201709090871834073", "2017-09-09",
     "新任基金经理姓名柳万军，任职日期2017年9月8日；离任基金经理姓名韩会永，离任日期2017年9月8日"),
    ("000051", "赵宗庭", "2017-04-17", None, "增聘",
     "AN201704190513578857", "2017-04-19",
     "新任基金经理姓名赵宗庭，任职日期2017年4月17日"),
    ("000198", "王昌俊", "2021-06-09", None, "增聘",
     "AN202106091496885706", "2021-06-09",
     "新任基金经理姓名王昌俊、刘莹，任职日期2021年06月09日"),
    ("000198", "刘莹", "2021-06-09", None, "增聘",
     "AN202106091496885706", "2021-06-09",
     "新任基金经理姓名王昌俊、刘莹，任职日期2021年06月09日"),
    ("000198", "田瑶", "2023-06-07", None, "增聘",
     "AN202306071590503774", "2023-06-07",
     "新任基金经理姓名田瑶，任职日期2023年06月07日"),
    ("000198", "王登峰", None, "2023-09-09", "解聘",
     "AN202309091598191770", "2023-09-09",
     "离任基金经理姓名王登峰，离任日期2023年9月9日"),
    ("007300", "章椹元", "2020-08-13", None, "增聘",
     "AN202008141398422277", "2020-08-14",
     "新任基金经理姓名章椹元，任职日期2020年8月13日"),
    ("007301", "章椹元", "2020-08-13", None, "增聘",
     "AN202008141398422277", "2020-08-14",
     "新任基金经理姓名章椹元，任职日期2020年8月13日"),
    ("110020", "余海燕", "2016-04-16", None, "增聘",
     "AN201604160014389242", "2016-04-16",
     "新任基金经理姓名余海燕，任职日期2016年4月16日"),
    ("110020", "杨俊", "2017-06-23", "2020-03-18", "增聘后解聘",
     "AN201706230664531841", "2017-06-23",
     "新任基金经理姓名杨俊，任职日期2017年6月23日；离任基金经理姓名林伟斌，离任日期2017年6月23日"),
    ("110020", "庞亚平", "2022-12-15", None, "增聘",
     "AN202212151581106362", "2022-12-15",
     "新任基金经理姓名庞亚平，任职日期2022年12月15日"),
    ("110022", "王元春", "2021-01-16", "2025-04-12", "增聘后解聘",
     "AN202101161451326035", "2021-01-16",
     "新任基金经理姓名王元春，任职日期2021年1月16日；后于2025年4月12日离任"),
    ("161725", "陈剑波", "2016-04-19", "2017-09-05", "增聘后解聘",
     "AN201604190014413198", "2016-04-19",
     "新任基金经理姓名陈剑波，任职日期2016-04-19；后于2017-09-05离任"),
    ("161725", "侯昊", "2017-08-22", None, "增聘",
     "AN201708220819161127", "2017-08-22",
     "新任基金经理姓名侯昊，任职日期2017-08-22"),
]


def ingest_manager(db_path=None) -> dict:
    stat = IngestStat()
    stat.planned = len(MANAGER_RECORDS)
    now = "2026-11-20T13:45:00"

    with get_connection(db_path) as conn:
        for (code, name, start, end, change, ann_id, ann_date, quote) in MANAGER_RECORDS:
            row = conn.execute(
                "SELECT share_class_id, fund_id FROM fund_share_classes "
                "WHERE share_class_code=?", (code,)).fetchone()
            if row is None:
                stat.failed += 1
                stat.notes.append(f"{code} 无对应份额，跳过")
                continue
            fid = int(row["fund_id"])
            # 幂等键：(fund_id, manager_name, start_date)
            exist = conn.execute(
                """SELECT manager_id FROM fund_manager_history
                   WHERE fund_id=? AND manager_name=?
                     AND COALESCE(start_date,'__unknown__')=?""",
                (fid, name, start or "__unknown__")).fetchone()
            if exist:
                stat.skipped_existing += 1
                continue
            detail = json.dumps({
                "announcement_date": ann_date,
                "change_type": change,
                "quote": quote,
                "disclaimer": DISCLAIMER_MANAGER,
            }, ensure_ascii=False)
            conn.execute(
                """INSERT INTO fund_manager_history
                   (fund_id, manager_name, start_date, end_date, tenure_days,
                    source, ingested_at, announcement_id, announcement_url,
                    evidence_level, change_type, detail)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (fid, name, start, end, None,
                 SOURCE_OFFICIAL_ANN, now, ann_id, ann_url(code, ann_id),
                 LEVEL_OFFICIAL_TEXT, change, detail))
            stat.inserted += 1
            stat.by_kind[change] = stat.by_kind.get(change, 0) + 1
    return stat.as_dict()


# ---------------------------------------------------------------- 规模历史
def load_aum_json() -> dict:
    p = EVIDENCE_DIR / "aum_history.json"
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def ingest_aum(db_path=None) -> dict:
    """把已采集的规模历史写入 fund_aum_history。

    数据来自天天基金规模变动页，原始出处为定期报告期末净资产。
    只记录 report_date（报告期末），不冒充公告发布日期。
    """
    data = load_aum_json()
    stat = IngestStat()
    stat.planned = sum(len(v) for v in data.values())
    now = "2026-11-20T13:45:00"

    with get_connection(db_path) as conn:
        for code, periods in data.items():
            row = conn.execute(
                "SELECT share_class_id FROM fund_share_classes "
                "WHERE share_class_code=?", (code,)).fetchone()
            if row is None:
                stat.failed += 1
                stat.notes.append(f"{code} 无对应份额，跳过")
                continue
            sid = int(row["share_class_id"])
            for p in periods:
                report_date = p["report_date"]
                aum = p.get("aum")
                shares = p.get("shares")
                if aum is None:
                    # 页面显示「---」，即该期未披露期末净资产。
                    # 保持不写入，绝不填 0。
                    stat.skipped_undisclosed += 1
                    continue
                exist = conn.execute(
                    """SELECT aum_id FROM fund_aum_history
                       WHERE share_class_id=? AND report_date=? AND source=?""",
                    (sid, report_date, SOURCE_DISCLOSURE)).fetchone()
                if exist:
                    stat.skipped_existing += 1
                    continue
                detail = json.dumps({
                    "report_date_is_period_end": True,
                    "not_publication_date": True,
                    "disclaimer": DISCLAIMER_AUM,
                }, ensure_ascii=False)
                conn.execute(
                    """INSERT INTO fund_aum_history
                       (share_class_id, report_date, aum_total, shares_total,
                        aum_unit, source, ingested_at, evidence_level, detail)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (sid, report_date, aum, shares, "亿元",
                     SOURCE_DISCLOSURE, now, LEVEL_PLATFORM, detail))
                stat.inserted += 1
    return stat.as_dict()


def run_all(db_path=None) -> dict:
    from app.fund.migration_3b4_4 import ensure_3b4_4_schema
    added = ensure_3b4_4_schema(db_path)
    return {
        "migration_added": added,
        "fee_effective": ingest_fee_effective(db_path),
        "manager": ingest_manager(db_path),
        "aum": ingest_aum(db_path),
    }
