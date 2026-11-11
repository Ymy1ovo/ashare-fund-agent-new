"""初始 ETF 候选池。

这里只保存候选代码与人工分类，不保存基金名称、跟踪指数、上市日期等
需要由数据源核验的字段。构建脚本会逐只调用真实接口验证。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EtfSeed:
    code: str
    category: str


ETF_SEEDS: tuple[EtfSeed, ...] = (
    # 宽基指数 ETF
    EtfSeed("510300", "宽基指数ETF"),
    EtfSeed("510050", "宽基指数ETF"),
    EtfSeed("510500", "宽基指数ETF"),
    EtfSeed("512100", "宽基指数ETF"),
    EtfSeed("159915", "宽基指数ETF"),
    EtfSeed("588000", "宽基指数ETF"),
    EtfSeed("159901", "宽基指数ETF"),
    EtfSeed("510880", "宽基指数ETF"),
    EtfSeed("512890", "宽基指数ETF"),
    # 科技成长 ETF
    EtfSeed("512480", "科技成长ETF"),
    EtfSeed("159995", "科技成长ETF"),
    EtfSeed("515070", "科技成长ETF"),
    EtfSeed("515880", "科技成长ETF"),
    EtfSeed("159819", "科技成长ETF"),
    EtfSeed("515230", "科技成长ETF"),
    EtfSeed("516010", "科技成长ETF"),
    EtfSeed("588200", "科技成长ETF"),
    EtfSeed("159852", "科技成长ETF"),
    # 消费与医药 ETF
    EtfSeed("159928", "消费与医药ETF"),
    EtfSeed("512690", "消费与医药ETF"),
    EtfSeed("510150", "消费与医药ETF"),
    EtfSeed("159936", "消费与医药ETF"),
    EtfSeed("159929", "消费与医药ETF"),
    EtfSeed("512010", "消费与医药ETF"),
    EtfSeed("159992", "消费与医药ETF"),
    EtfSeed("512170", "消费与医药ETF"),
    EtfSeed("512290", "消费与医药ETF"),
    # 债券 ETF
    EtfSeed("511010", "债券ETF"),
    EtfSeed("511260", "债券ETF"),
    EtfSeed("511220", "债券ETF"),
    EtfSeed("511380", "债券ETF"),
    EtfSeed("159972", "债券ETF"),
    EtfSeed("511360", "债券ETF"),
    EtfSeed("511030", "债券ETF"),
    # 黄金 ETF
    EtfSeed("518880", "黄金ETF"),
    EtfSeed("159934", "黄金ETF"),
    EtfSeed("518800", "黄金ETF"),
    EtfSeed("159937", "黄金ETF"),
    # 跨境 ETF
    EtfSeed("513100", "跨境ETF"),
    EtfSeed("513500", "跨境ETF"),
    EtfSeed("513050", "跨境ETF"),
    EtfSeed("513180", "跨境ETF"),
    EtfSeed("159920", "跨境ETF"),
    EtfSeed("513030", "跨境ETF"),
    EtfSeed("513520", "跨境ETF"),
    EtfSeed("159941", "跨境ETF"),
)
