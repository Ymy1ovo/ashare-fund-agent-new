from __future__ import annotations

import pytest

from app.data.collectors.akshare_collector import AkshareCollector
from app.data.collectors.base import DataFetchError

HTML = """
<html><body><table>
<tr><td>基金全称</td><td>测试ETF</td><td>基金简称</td><td>测试ETF简称</td></tr>
<tr><td>基金代码</td><td>510300（主代码） 基金类型 指数型-股票</td><td>基金类型</td><td>指数型-股票</td></tr>
<tr><td>发行日期</td><td>2012年04月05日</td><td>成立日期/规模</td><td>2012年05月04日 / 329.686亿份</td></tr>
<tr><td>业绩比较基准</td><td>沪深300指数</td><td>跟踪标的</td><td>沪深300指数</td></tr>
</table></body></html>
"""


def test_parse_fund_profile() -> None:
    profile = AkshareCollector._parse_fund_profile(HTML, "510300")
    assert profile["code"] == "510300"
    assert profile["name"] == "测试ETF简称"
    assert profile["fund_type"] == "指数型-股票"
    assert profile["established_date"] == "2012-05-04"
    assert profile["tracking_index"] == "沪深300指数"


def test_parse_fund_profile_without_table_fails() -> None:
    with pytest.raises(DataFetchError):
        AkshareCollector._parse_fund_profile("<html>暂无数据</html>", "510300")
