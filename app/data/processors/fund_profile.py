"""基金档案解析工具。

独立成模块，既供子进程采集器调用，也便于离线单元测试。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from app.data.collectors.base import DataFetchError
from app.data.processors.normalize import parse_date


def parse_fund_profile(html: str, code: str) -> dict[str, Any]:
    """解析东方财富 F10 基本概况表；缺少表结构时明确失败。"""
    soup = BeautifulSoup(html, "html.parser")
    fields: dict[str, str] = {}
    keys = {"基金全称", "基金简称", "基金代码", "基金类型", "发行日期", "成立日期/规模", "跟踪标的"}
    for row in soup.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
        for index in range(0, len(cells) - 1, 2):
            if cells[index] in keys:
                fields[cells[index]] = cells[index + 1]
    if not fields:
        raise DataFetchError(f"fund_profile({code}) 未解析到基本概况表，可能页面结构变化或被限流")

    established_raw = fields.get("成立日期/规模", "")
    established_text = established_raw.split("/")[0].strip() if established_raw else ""
    established = parse_date(established_text)
    # 部分页面的“基金代码”单元格会粘连“基金类型”，只取六位数字。
    code_matches = re.findall(r"\d{6}", fields.get("基金代码", ""))
    official_code = code_matches[0] if code_matches else code
    if official_code != code:
        raise DataFetchError(f"fund_profile({code}) 返回代码不一致：{official_code}")

    return {
        "code": official_code,
        "name": fields.get("基金简称", "").strip(),
        "fund_type": fields.get("基金类型", "").strip(),
        "established_date": established.isoformat() if established else "",
        "tracking_index": fields.get("跟踪标的", "").strip(),
        "source": "东方财富基金档案F10",
        "source_url": f"https://fundf10.eastmoney.com/jbgk_{code}.html",
        "collected_at": datetime.now().isoformat(timespec="seconds"),
    }
