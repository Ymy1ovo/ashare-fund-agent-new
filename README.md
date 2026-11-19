# A股基金量化分析 Agent

面向中国 A 股 ETF / 指数基金的个人量化研究项目。当前完成 **阶段1A（环境、数据源、观察池）**、**阶段1B（历史行情持久化、增量同步、行情 API、数据看板）**、**阶段1B.1（完整前复权刷新与调整快照一致性）**、**阶段2（统一价格口径与量化指标引擎）**、**阶段2.1（CAGR交易日口径与EMA/MACD断点修复）**、**阶段2.2（区间风险统计缺失交易日修复）**、**阶段3A（A股ETF历史回测引擎 V1.0）** 和 **阶段3A.1（风险口径与部分成交修复）** 、**阶段3A.1.1（部分成交状态逻辑专项修复）**、**阶段3A.2（策略可信度验证体系）**、**阶段3A.2.1（验证体系缺陷整改）**、**阶段3A.2.1.1（全池压力测试阻塞修复）**、**阶段3A.2.1.1.2（佣金累计模型与零碎股清仓修复）**、**阶段3A.2.1.1.2.1（佣金与税费累计混用修复）**、**阶段3A.2.1.1.2.1.1（绩效总成本口径修复）**、**阶段3A.2.1.2（验证体系工程收尾）**、**阶段3A.2.1.2.1（最终验收缺陷修复）** 和 **阶段3A.2.1.2.2（统一入口锁与报告校准）**、**阶段3A.3.1（MA 趋势策略失效归因）** 和 **阶段3A.3.2（价格口径与基金份额变动处理）**。

> 仅用于研究，不构成投资建议；不接入券商交易接口，不自动实盘交易。

## 1. 当前已完成

- FastAPI + Streamlit + SQLite + AKShare 模块化单体
- 46 只 ETF 观察池，六类覆盖
- 116,609 条 ETF 历史日线已写入 SQLite（46/46 只，真实接口数据）
- 原始 OHLC 与前复权收盘价分开保存
- 前复权完整历史刷新，不拼接增量 qfq
- 每只 ETF 当前调整快照唯一，行级记录 `adjustment_snapshot_id`
- 独立子进程硬超时、有限重试、并发限制
- 全量入库脚本、增量同步脚本、单只更新
- 统一复权 OHLC 口径，转换后价格关系校验
- 收益、趋势、动量、波动/回撤、风险收益五组指标
- 指标版本、参数哈希、复权快照和 run_id 可追溯
- CAGR 使用实际交易日跨度，缺失日计入年化时间
- EMA/MACD 遇缺失断点重置，不沿用旧状态
- 区间摘要波动率/夏普/索提诺只使用真实相邻日收益，不压缩缺失日
- 指标 API、指标看板、覆盖率与数据质量报告
- 行情摘要 API、按代码行情查询 API（日期范围、limit/offset）
- 调整快照一致性检查与数据质量报告
- 历史回测引擎：T+1 撮合、FIFO 账本、交易成本、绩效报告
- 公司行为事件表：拆分 / 合并 / 现金分红逐条记录官方来源与确认状态
- 账本按事件调整份额与现金，成交与估值仍用原始价格
- 离线单元/集成测试 412 项（含策略验证、并发安全、公司行为会计恒等式专项测试）
- 不含 `.venv`、缓存和 `.env` 的交付 ZIP

## 2. 环境与依赖

实际运行环境：

- Windows 10/11
- Python 3.11.2
- 项目虚拟环境：`D:\ymy\jj-agent\.venv`
- SQLite 3.39.4
- AKShare 1.20.36
- pandas 2.3.3 / NumPy 2.4.6
- FastAPI 0.162.2 / Streamlit 1.67.0
- pytest 9.2.0 / httpx 0.28.1

## 3. Windows PowerShell 初始化

```powershell
cd D:\ymy\jj-agent

python -m venv .venv
.\.venv\Scripts\Activate.ps1
# 如被策略拦截，仅当前窗口临时放开：
# Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Copy-Item .env.example .env
```

`.env` 不提交、不打进 ZIP。当前不需要任何 API Token；Tushare 未启用。

## 4. 数据任务

```powershell
cd D:\ymy\jj-agent
.\.venv\Scripts\Activate.ps1

# 1) 环境检查
python scripts\check_environment.py

# 2) 外部数据源调用 + 数据质量测试
python scripts\check_data_sources.py

# 3) 构建/重建 ETF 观察池（46只）
python scripts\build_etf_pool.py

# 4) 全量历史行情入库（46只，原始 + 前复权）
python scripts\ingest_history.py

# 5) 日常同步：原始行情增量 + 全历史复权刷新
python scripts\sync_data.py

# 单只 ETF：原始增量 + 完整复权刷新
python scripts\sync_data.py --code 510300

# 6) 仅完整刷新前复权快照（不改原始 OHLC）
python scripts\refresh_adjusted_prices.py
python scripts\refresh_adjusted_prices.py --code 510300

# 7) 一致性检查：同一 ETF 是否只有一个当前快照、原始 OHLC 是否未变
python scripts\check_adjustment_consistency.py

# 8) 同步交易日历（指标缺口判断）
python scripts\sync_trade_calendar.py

# 9) 计算指标：全池 / 单只 / 全量重算
python scripts\calculate_indicators.py --all
python scripts\calculate_indicators.py --code 510300
python scripts\calculate_indicators.py --code 510300 --full-rebuild

# 10) 生成行情与指标数据质量报告
python scripts\data_quality_report.py
python scripts\indicator_quality_report.py

# 10.1) 生成阶段2.1修复前后对比
python scripts\compare_phase21.py

# 10.2) 生成阶段2.2区间风险前后对比
python scripts\compare_phase22.py

# 11) 复权口径实测（原始/前复权/后复权）
python scripts\check_adjustment.py

# 12) 离线测试
python -m pytest -v

# 13) 启动/接口/看板冒烟测试
python scripts\smoke_test_servers.py

# 13.5) 运行回测
python scripts
un_backtest.py --strategy buy_and_hold --codes 510300 --start 2024-01-02 --end 2026-11-09
python scripts
un_backtest.py --strategy ma_trend --ma-window 20 --all --start 2024-01-02 --end 2026-11-09

# 14) 默认生成轻量源码包
python scripts\package_project.py --mode source-only

# 数据库变化时额外生成独立快照
python scripts\package_project.py --mode data-snapshot

# 阶段验收时生成完整发布包
python scripts\package_project.py --mode full-release
```

## 5. 启动服务

FastAPI：

```powershell
cd D:\ymy\jj-agent
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

接口：

| 接口 | 说明 |
| --- | --- |
| `GET /health` | 数据库、观察池、行情记录、同步运行数量 |
| `GET /api/etf-pool` | 46 只 ETF 观察池 |
| `GET /api/data-source-tests` | 最近接口测试记录，含调用状态与质量状态 |
| `GET /api/market-data/summary` | 入库数量、覆盖区间、最近同步、缺失与异常 |
| `GET /api/market-data/{code}` | 按代码查询行情，支持 `start_date`、`end_date`、`limit`、`offset` |
| `GET /api/sync/runs` | 最近原始行情同步运行记录 |
| `GET /api/adjustment/runs` | 最近完整前复权刷新运行记录 |
| `GET /api/indicators/{code}` | 读取已计算指标，支持日期、指标列、版本 |
| `GET /api/indicators/{code}/latest` | 最新一日指标 |
| `GET /api/indicators/overview` | 指标计算覆盖与过期概览 |
| `GET /api/indicators/ranking` | 按指标排序；不构成投资建议 |
| `GET /api/backtests` | 最近回测记录 |
| `GET /api/backtests/{run_id}` | 回测元信息与绩效摘要 |
| `GET /api/backtests/{run_id}/nav` | 每日净值曲线 |
| `GET /api/backtests/{run_id}/trades` | 成交记录 |
| `GET /api/backtests/{run_id}/orders` | 订单记录 |
| `GET /api/backtests/{run_id}/positions` | 每日持仓 |
| `GET /docs` | OpenAPI 文档 |

示例：

```powershell
curl.exe "http://127.0.0.1:8000/api/market-data/summary"
curl.exe "http://127.0.0.1:8000/api/market-data/510300?start_date=2026-01-01&end_date=2026-11-09&limit=100"
```

行情明细默认最多 500 条，硬上限 2,000 条；使用 `offset` 分页。

Streamlit：

```powershell
cd D:\ymy\jj-agent
.\.venv\Scripts\Activate.ps1
streamlit run dashboard\app.py
```

看板展示：观察池数量、已入库数量、行情总记录、异常记录、每只 ETF 覆盖区间、质量状态、最近同步运行与逐基金结果、单只 ETF 最近 30 条行情。侧边栏“量化指标”页面提供 ETF/日期/版本选择，以及概览、收益、趋势、动量、波动回撤、质量六个标签页。

## 6. 超时与并发设计

早期版本的守护线程超时只会放弃等待，AKShare 内部网络请求仍在后台运行，重试可能叠加未结束请求。阶段1B已改为：

1. 每个 AKShare/F10 网络调用在独立 `spawn` 子进程中执行。
2. 超时后调用 `terminate()`，必要时 `kill()`，并 `join()` 确认子进程退出，错误信息明确写“已终止子进程 pid=...”。
3. 只有旧子进程确认结束后才进入下一次重试，不会叠加重试。
4. `threading.BoundedSemaphore` 限制同进程并发采集数，默认 1，可通过 `FETCH_MAX_CONCURRENCY` 调整。
5. 保留有限重试与指数退避；F10 HTTP 请求本身还有显式 `requests.get(timeout=...)`。
6. 超时/失败会记录到日志和同步明细。

该机制不依赖线程取消，适合无法直接传入 timeout 的 AKShare 内部请求。

## 7. 数据库

数据库：`data/fund_agent.db`

旧库通过 `PRAGMA table_info` + `ALTER TABLE` 幂等升级，不删除旧数据。

### `etf_daily_prices`

| 字段 | 说明 |
| --- | --- |
| `code` | 六位基金代码 |
| `trade_date` | 交易日 |
| `open/high/low/close` | 原始 OHLC，不因复权改写 |
| `volume/amount` | 成交量/成交额 |
| `adjusted_close` | 前复权收盘价 |
| `adjustment_type` | `qfq` 或 `none` |
| `adjustment_snapshot_id` | 当前行引用的完整调整快照 ID |
| `adjustment_collected_at` | 该快照采集时间 |
| `adjustment_source` | 该快照来源 |
| `adjustment_coverage_start/end` | 该快照前复权覆盖区间 |
| `quality_status` | `valid` / `warning` / `suspect` |
| `quality_notes` | 异常标记，不修正原始数据 |
| `source` | 原始行情来源 |
| `collected_at` | 原始行情采集时间 |

主键：`PRIMARY KEY (code, trade_date)`。写入使用 `INSERT ... ON CONFLICT DO UPDATE`，重复运行不产生重复记录；空数据不会清空或覆盖旧数据。

### 其他表

- `etf_pool`：观察池
- `data_source_tests`：接口调用状态、质量状态、覆盖区间、字段
- `sync_runs`：每次原始行情全量/增量同步汇总
- `sync_details`：每只基金的原始行情同步状态、行数、覆盖区间、质量、错误
- `adjustment_runs`：每次完整前复权刷新汇总
- `etf_adjustment_snapshots`：每只基金每轮完整刷新快照；`is_current=1` 表示当前有效快照，记录状态、采集时间、来源、覆盖区间、匹配/缺失行数
- `trade_calendar`：A 股交易日历，用于缺失交易日判断，不把节假日当缺失
- `indicator_runs`：每次指标计算任务、参数、版本、快照、状态、质量
- `etf_indicator_daily`：每日指标，主键 `(etf_code, trade_date, calculation_version, adjustment_snapshot_id)`

## 8. 入库规则与复权快照

### 8.1 原始行情

- 全量入库从 `20000101` 开始，实际覆盖长度由各基金上市时间决定，不假设都有 5 年历史。
- 日常 `sync_data.py` 只对原始 OHLC 做增量 UPSERT；不复权、不碰 `adjusted_close` 和快照字段。
- 原始行情缺失/失败不覆盖已有行，重复执行不产生重复记录。

### 8.2 前复权快照

- `refresh_adjusted_prices.py` 每次对选中 ETF 获取 **完整历史 qfq**。
- 新 qfq 与数据库现有原始交易日期逐日对应；只更新 `adjusted_close` 与快照元数据，不修改原始 OHLC、不删除原始行情。
- 每次完整刷新生成一个新的 `etf_adjustment_snapshots` 记录；同一基金同一时刻只有一个 `is_current=1`。
- 所有行的 `adjustment_snapshot_id` 指向当前快照，因此可以判断是否混合不同调整基准。
- 数据源失败或返回空数据：只新增失败快照记录，旧当前快照和旧 `adjusted_close` 原样保留。
- 数据源成功但部分日期缺少 qfq：状态为 `partial`，所有行切换至新快照，缺失日期的 `adjusted_close` 置空并记录 missing；不会保留旧基准的复权值，避免混快照。
- 每只基金单事务执行，单只失败不影响其他基金。
- 已入库 46 只，116,609 条；44 只完整快照、2 只部分覆盖（510050 缺 108 行，510880 缺 41 行）。

复权实测（2024-01-02 至 2026-11-09）：

| 代码 | 原始首日/最新 | 前复权首日/最新 | 后复权首日/最新 |
| --- | --- | --- | --- |
| 510300 | 3.453 / 4.138 | 3.173 / 4.138 | 4.053 / 5.017 |
| 511010 | 133.252 / 141.456 | 129.142 / 141.453 | 134.532 / 146.844 |
| 513100 | 1.210 / 2.148 | 1.210 / 2.147 | 6.050 / 10.735 |

前复权/后复权为分别调用的盘中快照，最新价可能有数秒级差异；收盘后同步会刷新为收盘值。详细见 `data/adjustment_check.json`。

## 9. 数据质量

`scripts/data_quality_report.py` 生成 `reports/phase1B_data_quality.md`，检查：

- 日期重复、无效日期、未来日期
- OHLC 关系、收盘价非正
- 成交量/成交额异常、零成交
- 明显行情中断（>20 个日历日）
- 同代码不同来源冲突（当前为单一行情来源）
- 每只 ETF 覆盖区间与异常记录数
- 当前调整快照数量、部分覆盖、混合快照、无快照引用、复权缺失行
- 逐基金快照 ID、状态、采集时间、复权覆盖区间

`scripts/check_adjustment_consistency.py` 额外检查：

- 每只 ETF 是否恰好有一个当前快照；
- 每只 ETF 所有行是否引用同一个快照 ID；
- 快照缺失行数与 `adjusted_close IS NULL` 行数是否一致；
- 刷新前后原始 OHLC 行数和 SHA256 是否完全一致。

异常只标记，不修改成看似正常的数据。当前 116,609 条中有 116,416 条 `valid`、193 条 `warning`，其中前复权缺失 149 条（510050 108 条、510880 41 条），零成交 44 条（511030 42 条、511220 2 条）。原始 OHLC 均保留，复权缺失不会被伪造成 0。

## 10. 测试

离线测试不访问网络，使用临时 SQLite 数据库：

```powershell
python -m pytest -v
```

覆盖：超时终止、行情标准化/排序、最新有效记录、批量 UPSERT、重复写入、事务与空数据保护、异常识别、失败隔离、原始行情增量、完整复权刷新、调整基准切换、失败/空数据保留旧快照、部分覆盖隔离、快照区分、旧库迁移、行情 API；阶段2新增价格口径、收益/趋势/动量/波动/风险公式、未来函数、指标版本/快照、指标 API。测试全部使用临时 SQLite 数据库。

外部接口测试单独运行：

```powershell
python scripts\check_data_sources.py
python scripts\verify_etf_pool.py   # 阶段1A观察池真实性复核
python scripts\check_adjustment.py
python scripts\smoke_test_servers.py
```

## 11. 目录

```text
D:\ymy\jj-agent
├─ app/
│  ├─ data/collectors/       子进程任务、AKShare 采集、超时重试
│  ├─ data/processors/       行情清洗、原始入库、完整复权快照流程
│  ├─ data/validators/       观察池、行情质量、数据源质量
│  ├─ database/              SQLite 初始化、迁移、仓储
│  ├─ quant/                 价格口径、收益/趋势/动量/波动/风险、指标引擎
│  ├─ backtest/              回测引擎：配置/撮合/账本/绩效/策略
│  ├─ agent/                 后续 Agent（暂空）
│  ├─ api/                   后续 API 扩展（暂空）
│  ├─ config.py
│  ├─ logging_config.py
│  └─ main.py                FastAPI 入口
├─ dashboard/app.py          Streamlit 数据看板
├─ dashboard/pages/2_量化指标.py 指标分析页
├─ migrations/               阶段2指标表迁移说明
├─ scripts/                  环境/接口/建池/入库/同步/指标/质量/测试/打包
├─ scripts/package_project.py 三种交付打包模式
├─ tests/                    离线测试（含打包测试）
├─ CHANGELOG.md              变更日志
├─ RELEASE_NOTES.md          发布说明
├─ data/                     CSV、SQLite、测试结果、备份
├─ logs/                     运行日志
├─ reports/                  阶段报告
├─ requirements.txt
├─ .env.example
└─ .gitignore
```

## 12. 交付打包：源码包、数据库快照、完整发布

统一使用 `scripts/package_project.py`：

```powershell
# 默认：轻量源码包，不含数据库和日志
python scripts\package_project.py --mode source-only

# 数据库内容/指标版本发生变化时单独生成
python scripts\package_project.py --mode data-snapshot

# 阶段里程碑：源码包 + 数据库快照 + 报告
python scripts\package_project.py --mode full-release
```

### source-only

用于日常代码提交。包含 `app/`、`dashboard/`、`scripts/`、`tests/`、`migrations/`、`reports/`、`README.md`、`requirements.txt`、`.env.example`、`CHANGELOG.md`、`RELEASE_NOTES.md` 和 `data/etf_pool.csv`。排除数据库、logs、`.venv`、缓存、临时文件、真实 `.env`。

源码包不会包含或覆盖用户本地数据库。更新源码包后，`data/fund_agent.db` 保持原样。

### data-snapshot

用于数据库结构、行情或指标版本独立验收。使用 SQLite `backup()` API 生成一致性快照，不直接复制正在写入的文件；执行 `PRAGMA integrity_check`，记录：

- 数据库版本、SQLite user_version
- 行情记录数、指标记录数、当前复权快照数
- 最新指标版本
- 生成时间、数据库 SHA256、文件大小
- 迁移文件

快照包与源码包独立压缩，不包含 API 密钥。

### full-release

仅阶段里程碑使用。包含嵌套的 `source-only` 包、`data-snapshot` 包，以及测试报告、数据质量报告、`CHANGELOG.md`、`RELEASE_NOTES.md`。

### 打包安全

- 打包前打印文件数量/数据库大小。
- 打包后校验 ZIP 完整性、必要条目和禁止文件。
- 输出 ZIP SHA256 和 `<zip>.manifest.json`。
- 失败时删除未完成 ZIP，CLI 返回非零。
- 数据库快照前后校验源库 SHA256，不修改原始数据库。

### 使用约定

- 平时只需要提交 `source-only`。
- 数据库内容、结构、行情或指标版本发生变化时，再额外提交 `data-snapshot`。
- 阶段验收时提交 `full-release`。
- 用户本地数据库不得因为更新源码包而被覆盖；源码包不含 `data/fund_agent.db`。

## 13. 已知限制

- 数据来自公开免费接口，可能限流、字段变化或停服。
- 复权价是接口口径，未独立用分红公告逐笔重算；回测时应明确使用 raw 还是 qfq。
- 上市日期仍采用历史日线首个交易日口径，未逐只与交易所公告核对。
- 观察池是当前可交易品种；历史全量基金池（含退市/清盘）尚未建立，后续回测需单独处理幸存者偏差。
- 当前只支持单一行情来源的冲突标记，跨源自动对账尚未接入。
- 2 只 ETF 的 qfq 覆盖不完整，已标记 `partial`，缺失复权价保持为空，不猜测。
- 阶段2/2.1有 20 只 ETF 指标为 `partial`：主要是交易日历缺口、510050/510880 共 149 条复权价缺失，以及 44 条零成交量；0 只计算失败。
- 250 日与 252 日风险指标在上市初期覆盖不足，属于窗口不足，不是数据伪造。
- 指标日表包含 155 条日历缺失占位行，价格为空、指标为空，用于明确展示缺口，不代表真实成交。
- CAGR 的早期绝对变化可能较大，是年化时间分母修正导致；没有通过填充价格消除缺失。
- 阶段2.1/2.2保留旧指标版本；当前版本为 `v1.0.2-...`，旧版本可查询但不覆盖。
- 区间摘要的年化波动率/夏普/索提诺对缺失日保留 NaN，不把跨缺口收益当单日收益；样本不足返回空值。
- 20 只 partial 的区间风险样本数少于价格天数，这是真实缺口，不是计算失败。
- 后复权只做了口径实测，没有写入主表；如回测需要，可新增独立的 hfq 快照表。
- 全池完整复权刷新当前约需 110 秒（46 次接口调用，进程隔离），适合每日手动同步；未来可评估调整因子版本化以降低成本。
- 阶段3A 已实现历史回测引擎（T+1、成本、账本、绩效），但仍不接券商、不产生实盘指令。
- 回测是价格收益口径：没有分红/拆分事件数据，会低估分红贡献；不伪造分红记录。
- 滑点为固定 bp，无冲击成本、无成交量约束；涨跌停为整日近似。
- 债券ETF/商品ETF 交易规则未逐一确认，使用保守上限并在回测记录中提示。
- 回测结果仅用于验证引擎正确性，不构成收益承诺。
- Tushare 未启用，未接入付费源、券商接口或自动交易。

## 14. 阶段1B.1报告

- 总报告：`reports/phase1B1_report.md`
- 一致性检查：`reports/phase1B1_consistency.md`
- 数据质量：`reports/phase1B_data_quality.md`
- 测试报告：`reports/phase1B1_test_report.md`
- API 与看板：`reports/phase1B1_api_test.md`
- 实际刷新日志：`logs/refresh_final.console.log`
- 新日常同步日志：`logs/sync_data_1b1.console.log`

当前数据库：46 只 ETF、116,609 条行情、46 个当前调整快照、0 个混合快照、2 个 partial 快照、0 个 failed 当前快照。

## 15. 阶段2指标与报告

- 指标公式说明：`reports/phase2_formula_spec.md`
- 指标数据质量：`reports/phase2_indicator_quality.md`
- 指标计算摘要：`data/indicator_calculation_summary.json`
- 指示计算日志：`logs/calc_all.log`
- 实际覆盖：46 只 ETF，当前版本 116,764 个指标行；26 只 success、20 只 partial、0 failed
- 实际测试：96 passed，0 failed（93项指标/回归 + 3项交付打包）
- 交付打包测试报告：`reports/package_delivery_report.md`
- 当前指标版本：`v1.0.2-30b821a1af15`
- 历史指标版本：`v1.0.0-30b821a1af15`、`v1.0.1-30b821a1af15`（各保留 116,764 行）
- 快照版本：按 ETF 分别记录，当前均未过期
- 阶段2报告：`reports/phase2_report.md`
- 阶段2测试报告：`reports/phase2_test_report.md`
- 阶段2 API 报告：`reports/phase2_api_test.md`
- 阶段2.1报告：`reports/phase2.1_report.md`
- 阶段2.1测试报告：`reports/phase2.1_test_report.md`
- 阶段2.1 API 报告：`reports/phase2.1_api_test.md`
- CAGR前后对比：`reports/phase2.1_cagr_comparison.md`
- EMA/MACD前后对比：`reports/phase2.1_ema_macd.md`
- 阶段2.2报告：`reports/phase2.2_report.md`
- 区间风险前后对比：`reports/phase2.2_risk_comparison.md`
- 5只ETF抽查：`reports/phase2.2_spot_check.md`
- 阶段2.2测试报告：`reports/phase2.2_test_report.md`
- 阶段2.2 API报告：`reports/phase2.2_api_test.md`

指标口径、缺失处理、Wilder RSI/ATR、MACD 柱、波动率 ddof、回撤、夏普/索提诺/Calmar 和风险窗口均以 `phase2_formula_spec.md` 为准。

## 17. 阶段3A 历史回测引擎

```powershell
# 单只买入持有
python scripts
un_backtest.py --strategy buy_and_hold --codes 510300 --start 2024-01-02 --end 2026-11-09

# 全池均线趋势
python scripts
un_backtest.py --strategy ma_trend --ma-window 20 --all --start 2024-01-02 --end 2026-11-09

# 不写库，只生成报告
python scripts
un_backtest.py --strategy buy_and_hold --codes 510300 --start 2024-01-02 --end 2026-11-09 --no-save
```

| 模块 | 职责 |
| --- | --- |
| `app/backtest/config.py` | 回测参数、成本、ETF 交易规则 |
| `app/backtest/models.py` | 订单、成交、批次、持仓、每日快照 |
| `app/backtest/data.py` | 行情/日历/快照读取与可交易判定 |
| `app/backtest/costs.py` | 佣金、最低佣金、滑点、税费 |
| `app/backtest/execution.py` | 成交价、涨跌停、整手、T+N |
| `app/backtest/broker.py` | 撮合、拒单、延期、缩减 |
| `app/backtest/portfolio.py` | 现金与 FIFO 持仓账本 |
| `app/backtest/engine.py` | T+1 主循环、信号→订单→净值 |
| `app/backtest/metrics.py` | 绩效指标与账本核对 |
| `app/backtest/storage.py` | 回测结果持久化 |
| `app/backtest/report.py` | Markdown 报告 |
| `app/backtest/strategies/` | `buy_and_hold`、`ma_trend` |

- 迁移：`migrations/phase3a_backtest.sql`（5 张新表，不影响原表）
- 报告：`reports/phase3A_design.md`、`phase3A_report.md`、`phase3A_test_report.md`、`phase3A_backtest_case.md`
- 看板：Streamlit「回测结果」页面

**交易时序**：T 日收盘生成信号 → 最早 T+1 开盘成交；停牌/零成交/涨跌停不可成交时延期，超期过期。

**价格口径**：成交与估值只用原始 OHLC；前复权价只用于指标信号，不混用。

**账本核对**：每日 `总资产 = 现金 + 持仓市值`，并独立推演期末现金，`reconciliation.ok` 必须为 true。

## 18. 阶段3A.1 风险口径与部分成交修复

### Sharpe / Sortino

```text
daily_rf  = (1 + risk_free_rate) ^ (1 / 252) - 1
excess_t  = r_t - daily_rf
Sharpe    = mean(excess) × 252 / (std(r, ddof=1) × sqrt(252))
下行波动率 = sqrt(mean(min(excess,0)^2)) × sqrt(252)
Sortino   = mean(excess) × 252 / 下行波动率
```

- CAGR 单独计算，不参与 Sharpe/Sortino。
- 零波动、样本不足、无下跌日 → 返回空值，不输出无穷大。

### 缺失行情

- 只有「当日实际持仓 > 0 的 ETF 缺有效报价」才算缺口。
- 缺口当日与次日日收益置 NaN，不把 stale 估值当单日收益。
- 未持仓 ETF 缺行情不影响组合风险统计。
- 最大回撤仍用估值净值，但报告标注缺口天数与排除天数。

### 部分成交

- 订单新增 `remaining_quantity`（迁移 `phase3a1_backtest_partial_fill.sql`）。
- 只有 `filled_quantity >= quantity` 才是 `filled`，否则严格 `partial`。
- 剩余部分在 `max_defer_days > 0` 时继续挂单；否则标记 `remainder_cancelled`。
- 费用只按实际成交金额计算，累计成交量永不超过原始订单量。

报告：`reports/phase3A1_report.md`、`phase3A1_test_report.md`、`phase3A1_risk_comparison.md`、`phase3A1_manual_case.md`。

## 19. Git 仓库与协作

代码仓库：`https://gitee.com/y-mingyu/ashare-fund-agent`

```powershell
git clone https://gitee.com/y-mingyu/ashare-fund-agent.git
cd ashare-fund-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

### 纳入版本控制

源码（`app/`、`dashboard/`、`scripts/`、`tests/`）、迁移文件（`migrations/`）、阶段报告（`reports/`）、`README.md`、`CHANGELOG.md`、`RELEASE_NOTES.md`、`requirements.txt`、`.env.example`、`data/etf_pool.csv`。

### 不纳入版本控制

`.venv/`、`__pycache__/`、`.pytest_cache/`、`logs/`、`dist/`、`data/*.db` 及其 WAL/SHM、`data/backups/`、真实 `.env`、单次回测产物（`reports/backtest_*.md`、`data/backtest_summary_*.json`）和运行摘要 JSON。

数据库不进 Git；需要数据库验收时用 `python scripts/package_project.py --mode data-snapshot` 单独生成快照包。

### 日常提交流程

```powershell
git status
git add -A
git commit -m "feat: 说明本次改动"
git push origin main
```

### 版本追踪与回滚

```powershell
git log --oneline            # 查看 Commit 列表与 ID
git show <commit-id>         # 查看某次改动明细
git checkout <commit-id> -- .   # 单次回滚工作区到某个 Commit
git revert <commit-id>       # 生成反向提交，保留历史
```

### 阶段标签

```powershell
git tag -a phase3A.1 -m "阶段3A.1 风险口径与部分成交修复"
git push origin phase3A.1
git tag                       # 查看全部标签
```

### 安全约定

- `.env` 永远不提交；密钥只通过环境变量或本机配置文件提供。
- `.gitignore` 已排除数据库、日志、缓存、密钥文件。
- 提交前可执行密钥扫描，确认无 Token 进入仓库。

## 20. 阶段3A.1.1 部分成交状态专项修复

### 统一状态规则

以 `Order.sync_status()` 为唯一收敛入口，Broker 与 Engine 不再各自覆盖状态：

```text
filled_quantity >= quantity        → filled
filled_quantity >  0               → partial（无论剩余被拒/取消/延期/回测结束）
filled_quantity == 0               → 才允许 pending / rejected / expired / unfilled / cancelled
```

### 修复内容

- `app/backtest/models.py`：新增 `has_fill` 属性与 `sync_status(terminal=None)`。
- `app/backtest/broker.py`：新增 `append_reason()`、`_defer()`、`_terminate()`；
  已完成订单在 `execute()` 入口返回 `already_fully_filled`，不产生成交、不动账本、不收费。
- `app/backtest/engine.py`：移除 `order.status not in ("rejected",)` 的跳过逻辑；
  回测结束按有无成交分别收敛为 `partial` / `unfilled`。

### 数量与费用不变量

```text
0 <= filled_quantity <= quantity
remaining_quantity = quantity - filled_quantity
Order.fee == Σ Trade.commission
Order.slippage_cost == Σ Trade.slippage_cost
```

### 验证结果

- 全量测试：154 passed，0 failed（原 144 项无回退，新增 10 项）
- 真实数据回测 `cabbfe77035d40f3`：941 笔订单中 151 笔 partial，
  「有成交却标 rejected/unfilled/expired」0 笔，「有成交有剩余却标 filled」0 笔，账本核对通过
- 修复前同一策略回测 `dbf4bc0e46104b23`：partial 0 笔，错误标 filled 222 笔

报告：`reports/phase3A1_1_partial_fill_fix_report.md`

## 21. 阶段3A.2 策略可信度验证体系

### 运行方式

```powershell
# 完整验证（默认代表性池，约 4 分钟）
python scripts
un_validation.py

# 指定区间
python scripts
un_validation.py --is-start 2021-01-01 --is-end 2024-12-31   --oos-start 2025-01-01 --oos-end 2026-11-09

# API 冒烟
python scripts\smoke_validation_api.py
```

### 验证内容

| 模块 | 说明 |
| --- | --- |
| 样本内外切分 | 按 `trade_calendar` 真实交易日，严格不重叠 |
| Walk-Forward | 训练 24 个月、验证 6 个月、步长 6 个月，共 8 窗 |
| 市场环境 | 510300 相对 MA250 偏离 ±5% 划分牛/熊/震荡，样本不足标记 unclassified |
| 参数敏感性 | MA 5/10/20/30/60/120/250 全网格，展示全部组合 |
| 基准比较 | 买入持有、沪深300（510300 代理）、中证500（510500 代理）、ma_trend |
| 压力测试 | 成本 +50%/+100%、滑点 ×2/×3，只改配置不改行情 |

### 数据库

新增 4 张表（`migrations/phase3a2_validation.sql`）：
`validation_runs`、`validation_windows`、`validation_grid`、`validation_stress`。
既有表一行未动。

### 结论（`validation_id` = `5ec77faf42d64162` 代表性池 / `e725034e46ff47e5` 全池）

| 验证池 | 结论 | 关键依据 |
| --- | --- | --- |
| 代表性池（6 只） | 不通过 | 样本内 0/7 组合正收益，最优参数无稳定区域 |
| 全池（41 只） | 有条件通过 | 样本外 Sharpe 0.7637，但样本内普遍亏损 |

**综合：`ma_trend` 未通过稳健性验证。** 样本外等权买入持有（31.97%、Sharpe 0.8805）
优于 MA250 趋势（30.71%、Sharpe 0.7637），趋势择时未创造超额收益。

报告：`reports/phase3A2_report.md`、`reports/phase3A2_design.md`、
`reports/phase3A2_test_report.md`

## 22. 阶段3A.2.1 验证体系缺陷整改

### 整改内容

| 问题 | 整改 |
| --- | --- |
| 市场环境缺 OOS 预热 | 加载 OOS 前全部历史交易日（实测 3,064 天）做 MA250 预热，预热不进输出、不计绩效 |
| 行情指纹过弱 | 新增 `market-fingerprint-v2`，覆盖 10 个字段的 SHA256，算法版本纳入 `input_hash` |
| `sparse_data` 被跳过 | 在 SQLite 独立副本上实跑，源库零写入 |
| `insufficient` 被跳过 | 截短区间实跑，指标隐藏，状态 `insufficient` |
| 环境统计可能压缩缺失日 | `regime_stats()` 改为保留 NaN 的原始交易日序列，统计 `total_days` / `valid_days` / `missing_days` |

### 数据指纹

```text
算法：market-fingerprint-v2
字段：code, trade_date, open, high, low, close,
      volume, amount, adjusted_close, adjustment_snapshot_id
规范化：None/NaN → "null"；价格 6 位定点；成交量 3 位定点
排序：(code, trade_date)
摘要：逐行 SHA256
```

当前全库指纹：`394024221c09d310f520e3e39cdd83faca944b7f5f89e3eec0a2c0835b92084a`（116,609 行）

### 实测结果

| 项目 | 整改前 | 整改后 |
| --- | ---: | ---: |
| OOS `unclassified` 天数 | 246 | **0** |
| `sparse_data` 状态 | skipped | **success** |
| `insufficient` 状态 | skipped | **insufficient** |
| 测试数 | 209 | **249** |

### 关键结论

工程整改通过，但**策略结论不变**：`ma_trend` 仍未通过稳健性验证。
样本外等权买入持有（31.97%、Sharpe 0.8805）依旧优于 MA250 趋势（30.71%、Sharpe 0.7637）。

报告：`reports/phase3A2_1_design.md`、`reports/phase3A2_1_test_report.md`、
`reports/phase3A2_1_validation_report.md`

## 23. 阶段3A.2.1.1 全池压力测试阻塞修复

### 碎股卖出根因

卖单申报数量用了 `round_lot(..., allow_odd=True)`（等价 `floor()`）：

```text
持仓 130,400 股 → 策略算出 130,399.7 → 申报 130,399 → 剩 1 股
后续卖 1 股 → 成交额 0.3738 元 < 最低佣金 5.00 元 → 现金 3.99 → -1.01
```

### 修复

| 项目 | 内容 |
| --- | --- |
| 卖出申报 | `sell_quantity()`：整手优先，可卖不足一手才整笔清零股 |
| 兜底防护 | 卖出净收入<费用且现金不够 → 拒单 `sell_proceeds_below_fee` |
| 最低佣金 | 每笔成交一次 `max(金额×费率, 5元)`，不重复 |
| 指纹 | v3，新增 `adjustment_type`、`adjustment_coverage_start/end` |
| MA250 预热 | 按有效价格计数，`db_rows` / `valid_prices` / `invalid_prices` 分离 |

### 全池 sparse_data 实测

| 项目 | 结果 |
| --- | ---: |
| 状态 | **success** |
| ETF | 41 |
| 删除行情行 | 4,079（零散 4,047 + 连续 32） |
| 订单 / 成交 | 2,004 / 1,235 |
| 部分成交订单 | 222 |
| 负现金天数 | **0** |
| 指纹前后 | 一致 |

### 测试

全量 **276 passed**（原 249 项全保留 + 新增 27 项）。

报告：`reports/phase3A2_1_1_design.md`、`reports/phase3A2_1_1_test_report.md`、
`reports/phase3A2_1_1_validation_report.md`

## 24. 阶段3A.2.1.1.2 佣金累计模型与零碎股清仓

### 佣金模型

| 模型 | 定义 | 是否默认 |
| --- | --- | --- |
| `per_order` | 同一订单多次成交共用一份最低佣金（按累计金额算应收 − 已收） | **是** |
| `per_fill` | 每笔成交独立收取 `max(金额×费率, 最低佣金)` | 可选 |

配置：`CostConfig(min_commission_model="per_order")`

实测：卖出 737 股分两日成交（500 + 237）

| 模型 | 第 1 笔 | 第 2 笔 | 累计 |
| --- | ---: | ---: | ---: |
| per_order | 5.00 | 0.00 | **5.00** |
| per_fill | 5.00 | 5.00 | 10.00 |

**声明**：per_order 是本项目的模拟假设，不代表所有券商实际结算方式。

### 零碎股清仓

| 意图 | 判定 | 申报 |
| --- | --- | --- |
| 全部清仓 | `Order.liquidate=True` | 全部可卖数量，整手+零股一笔 |
| 部分减仓 | `liquidate=False` | 整手向下取整 |
| 部分减仓只剩零股 | 可卖 < 一手 | 整笔卖零股 |

实测 7 场景全部清仓后剩余为 0，含 130,400 / 537 / 1,237 / 99 / 100。

### 统一统计口径

新增 `metrics.return_sample_stats()`：

```text
nav_days = first_day + held_price_gap + prior_day_price_gap + missing_nav + valid_return_days
```

两池实测：

| 池 | 快照 | 首日 | 缺口 | 缺净值 | 有效 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 代表性池 6 只 | 447 | 1 | 176 | 0 | 270 |
| 全池 41 只 | 447 | 1 | 177 | 0 | 269 |

报告：`reports/phase3A2_1_1_2_design.md`、`reports/phase3A2_1_1_2_test_report.md`、
`reports/phase3A2_1_1_2_validation_report.md`

## 25. 阶段3A.2.1.1.2.1 佣金与交易税费分离

### 修复的问题

`broker.py` 曾把 `order.fee`（含税费）当作「已收佣金」传给 `incremental_commission()`，
导致部分成交时少收佣金。

| 成交 | 累计金额 | 应收佣金 | 传入已收 | 实际增量 | 应收增量 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 10,000 | 5.00 | 0 | 5.00 | 5.00 |
| 2 | 20,000 | 6.00 | 10.10 | **0.00** | **1.00** |

### 字段语义

| 层级 | 字段 | 含义 |
| --- | --- | --- |
| Order | `commission` | 累计佣金（不含税费） |
| Order | `stamp_tax` / `transfer_fee` | 累计印花税 / 过户费 |
| Order | `fee` | 累计全部费用 = 三项之和 |
| Trade | `commission` | **只含佣金** |
| Trade | `stamp_tax` / `transfer_fee` / `total_fees` | 税费与总费用 |

### 佣金公式

```python
commission_due   = max(order.gross_amount + gross) × rate, min_commission)
commission_delta = max(0, commission_due - order.commission)
stamp            = gross × stamp_rate
transfer         = gross × transfer_fee_rate
fee              = commission_delta + stamp + transfer
```

### 数据库

新增 5 列（`migrations/phase3a2_1_1_2_1_fee_split.sql`）：
`backtest_orders.commission/stamp_tax/transfer_fee`、
`backtest_trades.stamp_tax/transfer_fee`。

历史订单 `commission` 回填为 `fee`（前提：旧 `stamp_duty_rate` 与
`transfer_fee_rate` 均为 0，已逐条实测确认）。旧列全部保留。

### 验证

| 项目 | 结果 |
| --- | ---: |
| 全量测试 | **322 passed** |
| 原有 310 项 | 全部保留通过 |
| 新增 12 项 | 全部通过 |
| 真实数据对账 | 264 笔成交四项全部一致 |
| `reconcile` 期末现金 | 修复前差 51,041.98 → 修复后 True |
| 行情指纹 | 前后一致 |

报告：`reports/phase3A2_1_1_2_1_design.md`、`reports/phase3A2_1_1_2_1_test_report.md`、
`reports/phase3A2_1_1_2_1_validation_report.md`

## 26. 阶段3A.2.1.1.2.1.1 绩效总成本口径

### 修复的问题

`Trade.commission` 收窄为纯佣金后，`total_cost` 公式未同步，漏掉印花税与过户费。

| 版本 | 公式 |
| --- | --- |
| 修复前 | `total_cost = total_commission + total_slippage` |
| 修复后 | `total_cost = total_trade_fees + total_slippage` |

### 成本字段

| 字段 | 含义 |
| --- | --- |
| `total_commission` | 只含佣金 |
| `total_stamp_tax` | 只含印花税 |
| `total_transfer_fee` | 只含过户费 |
| `total_trade_fees` | 佣金 + 印花税 + 过户费 |
| `total_slippage` | 只含滑点 |
| `total_cost` | 费用合计 + 滑点 |

### 实测差异

3 只 ETF、264 笔成交、非零税费：

| 指标 | 修复前 | 修复后 |
| --- | ---: | ---: |
| total_cost | 72,389.11 | **123,431.09** |
| 漏计 | — | **51,041.98（41.4%）** |

### 历史兼容

新回测写入 `summary_json.cost_semantics = "commission+taxes+slippage"`；
历史记录无该字段，判定为 `legacy`（当时税率为 0，数值等价），
**不补造历史税费、不重算历史结果**。

### 验证

| 项目 | 结果 |
| --- | ---: |
| 全量测试 | **337 passed** |
| 原有 322 项 | 全部保留通过 |
| 新增 15 项 | 全部通过 |
| 真实数据 264 笔对账 | 逐笔累加一致 |
| 数据库 | 结构未变、无迁移 |

报告：`reports/phase3A2_1_1_2_1_1_design.md`、
`reports/phase3A2_1_1_2_1_1_test_report.md`、
`reports/phase3A2_1_1_2_1_1_validation_report.md`

## 27. 阶段3A.2.1.2 验证体系工程收尾（历史章节）

> **本节为阶段3A.2.1.2 的历史验收状态，其中部分结论已在
> 阶段3A.2.1.2.1 被更正（见第 28 节），测试数字已被第 30 节覆盖。**
> 当前全量测试为 **373 项**。本节保留历史记录，但下列内容**不再有效**：
> 「回撤被高估」断言、「74 笔均因现金充足」归因、「串行写入/推荐 4 任务」旧表述。

### 三项任务

| 任务 | 模块 | 实测 |
| --- | --- | --- |
| sparse 敏感性扫描 | `app/validation/sensitivity_scan.py` | **42 场景**（代表性池 30 + 全池 12） |
| 并发安全 | `app/validation/concurrency.py` | 2 / 4 任务并发均通过 |
| 卖出费用不足链路 | `app/validation/sell_probe.py` | 受控副本 2 场景 + 6 档阈值 |

### 敏感性关键结论

| 问题 | 结论 |
| --- | --- |
| 收益随删除比例 | 22.43% → 17.31%（-5.12 pp） |
| Sharpe 是否失真 | **是**，3~5% 档掉到 0.50~0.66，不单调 |
| 回撤变化 | 相对 0% 基准**加深 1.45~2.45 pp**（当时写成「被高估」，该断言已被 3A.2.1.2.1 撤回） |
| 连续 vs 随机 | 连续更差 2.22 pp |
| 恢复日是否异常 | 否 |

### 并发结论

- 2 任务并发：**安全**
- 4 任务并发：**安全**（840 秒，integrity ok）
- 执行模型：**全流程串行排队**（当时写成「串行写入」，后更正为整任务串行）
- 推荐安全并发：**4 个任务**（8 任务及以上未验证）

### 卖出费用不足结论

| 验证方式 | 结果 |
| --- | --- |
| 历史真实数据自然触发 | **否**（74 笔按护栏分界：护栏前 72 笔分支不存在 + 护栏后 2 笔现金足够） |
| 受控完整链路 | **是**（`rejected`，无负现金） |
| 现金足够对照 | **是**（正常 `filled`） |

### 验证

| 项目 | 结果 |
| --- | ---: |
| 全量测试（历史阶段） | **351 passed**（当前为 373） |
| 原有 337 项 | 全部保留通过 |
| 新增 14 项 | 全部通过（历史阶段） |
| 行情指纹 | 前后一致 |
| 历史 validation（历史阶段） | 13 条完整保留，新增 9 条（当前总数 37） |

报告：`reports/phase3A2_1_2_*.md`（6 份）

**真实券商交割单核验：`deferred_external_evidence`。**

## 28. 阶段3A.2.1.2.1 最终验收缺陷修复（历史章节）

> **本节为阶段3A.2.1.2.1 的历史验收状态，测试数字已被第 30 节覆盖。**
> 当前全量测试为 **373 项**。

### 修复清单

| # | 缺陷 | 整改 |
| ---: | --- | --- |
| 1 | 信号附近删除忽略 `ratio` | 按 `round(可删×ratio)` 抽样，至少 1 个 |
| 2 | CLI 未传持仓/信号日期 | 先跑基准回测提取再传入 |
| 3 | 声称计算并行 | 改为**全流程串行排队** |
| 4 | 跨进程锁目录随机 | 固定 `data/.validation_write.lock` |
| 5 | 源库指纹只用行数求和 | 复用 `market-fingerprint-v3` |
| 6 | 报告断言回撤被高估 | 改为「相对基准变化」 |
| 7 | 74 笔错误归因现金充足 | 分界为 72（护栏前）+ 2（护栏后） |

### 信号附近六档实测

| ratio | 删除行 | 实际比例 |
| ---: | ---: | ---: |
| 0.00 | 0 | 0.0 |
| 0.01 | 11 | 0.0108 |
| 0.03 | 30 | 0.0295 |
| 0.05 | 52 | 0.0511 |
| 0.10 | 101 | 0.0992 |
| 0.20 | 204 | 0.2004 |

### 并发模型（修订）

```text
execution_model = full-pipeline-serial
compute_parallel = false
lock = data/.validation_write.lock（正式库同目录）
```

| 并发方式 | 耗时 | 结果 |
| --- | ---: | --- |
| 2 线程 | 434.3s | 安全排队 |
| 4 线程 | 1311.6s | 安全排队 |
| 2 独立进程 | 556.7s | 安全排队，事件严格串行 |

（后续 3A.2.1.2.2 / .3 又补测了公开入口 2 线程、公开入口 2 进程、
临时库 2 线程任务，见第 29、30 节。）

**不宣称计算并行，不宣称 8 任务及以上已验证。**

### 验证

| 项目 | 结果 |
| --- | ---: |
| 全量测试（历史阶段） | **365 passed**（当前为 373） |
| 原有 351 项（历史阶段） | 全部保留通过 |
| 新增 14 项 | 全部通过（历史阶段） |
| 行情完整指纹 | 前后一致 |

报告：`reports/phase3A2_1_2_*.md`（6 份，已修订）

## 29. 阶段3A.2.1.2.2 统一入口锁与报告校准（历史章节）

> **本节为阶段3A.2.1.2.2 的历史验收状态，已被第 30 节（阶段3A.2.1.2.3）覆盖。**
> 当前全量测试为 **373 项**，本节出现的 369 passed / 原有 365 项 / 新增 4 项
> 均为该历史阶段的数字，不是当前状态。

### 统一入口锁

```text
runner.py
├─ _run_validation_unlocked()   内部实现，不加锁
└─ run_validation()             公开入口，自动经过全流程串行锁

重入保护：contextvars.ContextVar（每执行上下文独立，不用全局布尔）
```

| 正式调用入口 | 是否加锁 |
| --- | --- |
| `scripts/run_validation.py` | **是**（自动） |
| `concurrency.run_concurrent_tasks()` | **是**（内部调公开入口，不重复加锁） |
| 测试临时库 | 是（锁文件跟随临时库目录） |

### 入口级实测

| 验证 | 结果 |
| --- | --- |
| 两线程直接调 `run_validation()` | 484.5s，串行（T1 242.7s / T2 484.5s） |
| 两独立进程直接调 | 496.7s，串行，exitcode 均 0 |
| 结束后持锁标记 | 均 `False`，无残留 |

### 报告校准

| 项 | 校准 |
| --- | --- |
| 最大回撤 | 删「高估/低估」，改「相对 0% 基准加深 1.45~2.45 pp」 |
| 74 笔 | 护栏前 72（分支不存在）+ 护栏后 2（现金足够） |
| 并发 | 全流程串行，不宣称计算并行，未验证 8 以上 |
| 测试数量（历史） | 337 → 351 → 365 → **369**（当前为 373） |
| 外部证据 | `deferred_external_evidence` |

### 验证（阶段3A.2.1.2.2 历史数据）

| 项目 | 结果 |
| --- | ---: |
| 全量测试 | **369 passed**（历史阶段，当前为 373） |
| 原有 365 项 | 全部保留通过（历史阶段） |
| 新增 4 项 | 全部通过（历史阶段） |
| 行情完整指纹 | 前后一致 |

## 30. 阶段3A.2.1.2.3 临时库嵌套加锁缺陷修复

### 缺陷

`concurrency._make_single_task()` 的临时库分支写成了：

```python
result = run_with_write_lock(run_validation, cfg, lock_dir=lock_dir)
```

而 `run_validation()` 自 3A.2.1.2.2 起自身也会加锁，于是**同一线程**内两次
获取 `threading.Lock`。该锁不可重入，第二次 `acquire()` 永久阻塞：任务无声
挂死，不报错、不超时、不释放。两层锁目标还不同（外层临时目录、内层数据库
目录），本就不是同一把锁，跨进程互斥也不成立。

### 修复

| 项 | 修改前 | 修改后 |
| --- | --- | --- |
| 加锁点 | 外层 + 入口共 2 次 | **仅公开入口 1 次** |
| 临时库调用 | `run_with_write_lock(run_validation, cfg, lock_dir=…)` | `run_validation(cfg, db_path=…, lock_dir=…)` |
| 锁文件位置 | 外层临时目录、内层数据库目录 | 统一跟随被写的数据库目录 |
| 持锁标记置位 | 拿锁**之前** | 真正拿到锁之后（`_locked()` 闭包内），`finally` 复位 |
| 同线程重复获取 | 永久挂死 | 立刻抛 `ConcurrencyError` |
| 进程内锁等待 | `with _WRITE_LOCK`（无限） | `acquire(timeout=…)`，超时抛 `ConcurrencyError` |

**不使用 `threading.RLock`**：它只让嵌套「看起来能跑」，两把不同的锁跨进程
语义仍然错乱。正确做法是把加锁点收敛为一处。
`_run_validation_unlocked()` 仍是内部函数，未成为对外入口。

### 顺带修掉的第二个缺陷

临时库场景读 `input_hash` 时未传 `db_path`，读到的是**正式库**，必然为空：

```python
task.input_hash = record.get("input_hash")   # record = get_validation(vid) → None（临时库场景）
```

`input_hash=None` 会让 `_check_hash_consistency()` 跳过空值，
「一致性检查」退化成永远通过。已改为 `get_validation(vid, db_path=db_path)`。

### 测试改写（不再用 `inspect.getsource()`）

| 测试 | 断言的真实行为 |
| --- | --- |
| `test_run_validation_public_entry_acquires_lock` | 执行期间持锁标记 True 且其他线程拿不到锁；返回后 False |
| `test_locked_context_does_not_reacquire` | 持锁期间重入不重复加锁、不死锁、深度为 2 |
| `test_run_concurrent_tasks_does_not_double_lock` | 临时库任务跑通、`input_hash` 非空、锁文件落在临时库目录 |
| `test_temp_db_two_threads_no_deadlock` | 两个临时库任务并行调度均完成 |
| `test_public_entry_timeout_raises_concurrency_error` | 外部持锁 → `ConcurrencyError` 且流程未执行；释放后可重新获取 |
| `test_public_entry_releases_lock_on_exception` | 异常后标记复位、锁可被他人获取、后续调用成功 |
| `test_nested_lock_raises_instead_of_hanging` | 同线程嵌套加锁 5 秒内报错；报错后锁完全释放 |

### 真实运行证据（非单测）

| 项 | 结果 |
| --- | --- |
| 单临时库任务（`_make_single_task`） | `success`，253.2s，`validation_id=87328a95ea394e76` |
| 该任务 `input_hash` | `dc5137ab80c92d71`，与临时库 `validation_runs` 记录一致 |
| 执行期间其他线程探测拿锁 | 拿不到 |
| 结束后持锁标记 | `false` |
| 两临时库任务并发调度 | 579.1s，273.6s + 577.7s 严格串行，`hash_consistency=true`，ids 唯一 |

### 验证

| 项目 | 结果 |
| --- | ---: |
| 全量测试 | **373 passed**，0 failed / 0 skipped / 0 未执行 |
| 原有 337 项（阶段3A.2.1.2 之前） | 全部保留通过（未删除、未跳过、未弱化） |
| 新增合计 | **36 项**（14 + 14 + 4 + 4） |
| 本轮（3A.2.1.2.3）净增 | 4 项 |
| 行情完整指纹 | `market-fingerprint-v3:d54727c0...ac49`，前后一致 |
| 历史 validation 记录 | 原有 13 条完整保留 |
| 数据库 `integrity_check` | ok |

### 本轮不改变的结论

| 结论 | 状态 |
| --- | --- |
| `ma_trend` 策略 | **仍未通过稳健性验证**（样本内外方向相反，风险调整后跑不赢等权买入持有） |
| 全流程串行排队 | 维持，不宣称计算并行 |
| 8 任务及以上 | 维持未验证 |
| 真实券商交割单核验 | 维持 `deferred_external_evidence` |

### 报告校准

| 报告 | 校准内容 |
| --- | --- |
| design | 新增第 11 节（缺陷、修复设计、三处配套修正、未验证项）；文件清单补 3A.2.1.2.3 |
| test_report | 数量统一为 373；新增缺陷修复与真实运行证据章节；修正「多进程未执行」的过期表述 |
| concurrency | 新增 5.5 节（复现、修复对照、真实运行）与 7.6 节（唯一加锁点形态） |
| validation | 新增缺陷整改表；数量统一为 373 |
| sparse / sell_proceeds | 结论与数据不变（本轮未触碰这两块逻辑） |

### 未验证（不宣称通过）

- 临时库 4 并发、临时库多进程调度
- 8 及以上并发、跨机器共享数据库、小时级长压测
- 真实券商交割单核验仍为 `deferred_external_evidence`

## 31. 阶段3A.3.1 MA 趋势策略失效归因（只读研究）

### 性质

只读研究：不开发策略、不改回测引擎、不改数据库、不改历史验证记录。
新增 `app/research/attribution.py`（纯计算）+ `scripts/research_3a3_1.py`（只读脚本）
+ `tests/test_research_3a3_1.py`（14 项）。

### 研究方法

```text
输入：验证记录 32aead3291734f91（样本外 2025-01-02 ~ 2026-11-09，41 只 ETF）
       MA 窗口 = 250（样本内选出，本轮不调参）
重跑：MA250 与等权买入持有，同池、同区间、同成本、同执行价
分解：Δ总资产 = 持有收益 + 交易执行价差 − 交易费用（逐日恒等式，残差 0.00）
校验：运行前后各取一次 market-fingerprint-v3，不一致即失败
```

### 核心结果

| 指标 | MA250 | 等权买入持有 |
| --- | ---: | ---: |
| 总收益 | 31.79% | **31.97%** |
| CAGR | 16.88% | 16.97% |
| 年化波动率 | 24.13% | **20.83%** |
| Sharpe | 0.7818 | **0.8805** |
| 最大回撤 | -25.12% | **-18.58%** |
| Calmar | 0.6719 | **0.9130** |
| 成交笔数 | 425 | 41 |
| 总成本 | 10,639.52 元 | 697.70 元 |
| 成本 / 毛收益 | 3.24% | 0.22% |

### 结论

1. **成本是「抹平优势」的临界因素**：MA250 毛利多 8,181 元，成本多付 9,942 元，净输 1,761 元；
2. **风险控制没有实现**：波动更高、回撤更深、Sharpe/Calmar 全面落后；
3. **组合从未真正降仓**：447 天只有 1 天空仓，平均暴露度 97.70%，
   策略只「换标的」不「降敞口」；
4. **震荡市是净损失来源**：97 天交易 184 笔（43.3%），收益低于买入持有；
5. **`ma_trend` 不值得在现有形态上继续调参**——问题不在 MA 窗口，而在结构。

### 发现的数据缺陷（本轮最重要）

原始收盘价存在 **22 处份额折算/拆分断点**（样本外 6 处 + 样本内 16 处），
隐含比例都是整数级（10.0 / 0.5 / 0.333）。回测引擎按「不复权收盘 × 持仓数量」估值，
份额折算后价格变了、持仓数量没变，导致市值凭空跳变。

| 项目 | MA250 | 等权买入持有 |
| --- | ---: | ---: |
| 累计虚增 | +73,368.40 元 | +70,374.68 元 |
| 占初始资金 | 7.34% | 7.04% |
| 观测收益 → 剔除后估计 | 31.79% → 24.46% | 31.97% → 24.93% |
| 观测回撤 → 剔除后估计 | -25.12% → -18.38% | -18.58% → -13.27% |

**本轮只记录、不修复**：修复需改数据层与引擎层，建议单独立项阶段3A.3.2。
剔除污染后 MA250 仍然跑输且回撤仍然更深，**结论方向不变**。

### 下一阶段建议

| 优先级 | 方向 |
| ---: | --- |
| P0 | 数据口径与份额折算处理（3A.3.2） |
| P1 | 等权持有 + 定期再平衡（月/季/半年/年，一次性全跑） |
| P1 | 跨类别分散（与 P1 合并验证） |
| P2 | 波动率风险预算 |
| P3 | 市场级趋势过滤（个股级已被本轮证伪） |
| P4 | 波动率目标 + 现金管理 |

### 验证

| 项目 | 结果 |
| --- | ---: |
| 全量测试 | **387 passed**，0 failed / 0 skipped |
| 原有 373 项 | 全部保留通过 |
| 新增研究测试 | 14 项 |
| 行情完整指纹 | 前后一致 |
| validation_runs | 37 条未变 |
| 数据库 integrity_check | ok |

### 报告

- `reports/phase3A3_1_research_design.md`
- `reports/phase3A3_1_attribution_report.md`
- `reports/phase3A3_1_research_recommendations.md`

## 32. 阶段3A.3.2 价格口径与基金份额变动处理

阶段3A.3.1 发现原始收盘价存在份额折算断点后，本阶段完成**先核查、后修复**。
目标不是让策略收益变好，而是让历史回测账本可信。

### 核查结论

从数据库重新提取全部异常（8% 阈值命中 342 处，回测区间内 22 处），
逐条匹配官方公告，**没有从价格跳变反推任何比例**：

| 类型 | 数量 |
| --- | ---: |
| 份额拆分 | 19 |
| 份额合并 | 2 |
| 现金分红 | 1 |
| 无法确认 | **0** |

进一步发现：**回测期内实际有 80 个公司行为**（23 拆分 + 57 分红，
涉及 26 只 ETF），远超阈值能捕获的 22 处。小额分红不会造成大幅跳变，
此前被完全忽略。

### 修复内容

| 缺陷 | 修复 |
| --- | --- |
| 拆分/合并后不调整持仓数量 | 新增 `corporate_actions` 事件表，按事件调整数量 |
| 现金分红不入账 | 事件驱动现金入账 |
| 估算公式错误 | `implied_ratio - 1` 废弃，改 `r_raw - r_adj`，标注为近似 |
| 8% 阈值漏检 | 改为读事件表，不再依赖阈值 |

**三个价格口径各司其职**：

| 口径 | 用途 |
| --- | --- |
| 原始 OHLC | 撮合成交价、每日估值价 |
| 前复权 `adjusted_close` | 技术指标、收益分析 |
| 公司行为事件 | 持仓数量、现金账本 |

### 重放结果

新记录 `c46fa37b932944c2`，旧记录 `32aead3291734f91` **完整保留**：

| 区间 | 指标 | 修复前 | 修复后 |
| --- | --- | ---: | ---: |
| 样本内 | 总收益 | -16.33% | **+10.87%** |
| 样本内 | 最大回撤 | -32.81% | **-13.73%** |
| 样本外 | 总收益 | +32.21% | **+20.24%** |
| 样本外 | 年化波动率 | 24.27% | **16.94%** |
| 样本外 | 最大回撤 | -24.54% | **-18.11%** |

**样本内外的错误方向相反**：样本内合并事件虚减市值，样本外拆分事件虚增，
这也解释了为什么单看净值曲线发现不了。

### 推翻 3A.3.1 的部分结论

| 3A.3.1 结论 | 修复后 |
| --- | --- |
| MA250 波动率明显更高 | **不成立**（16.94% vs 17.16%，反而更低） |
| MA250 回撤明显更深 | **不成立**（-18.11% vs -19.03%，反而更浅） |
| 剔除污染后 MA250 仍跑输 | **不成立**（+20.24% vs +19.31%，略优但优势不显著） |
| 交易成本拖累、交易次数过多 | **仍然成立**（419 vs 41 笔，成本 13.7 倍） |

3A.3.1 报告保留不改，新结论以
`reports/phase3A3_2_backtest_replay_report.md` 为准。

### 验证

| 项目 | 结果 |
| --- | ---: |
| 全量测试 | **412 passed**，0 failed / 0 skipped / 0 xfail |
| 原有 387 项 | 全部保留通过 |
| 新增公司行为测试 | 25 项（覆盖 18 项会计恒等式场景） |
| API 冒烟 | 通过（含新记录查询） |
| Streamlit AppTest | 2 个页面无异常 |
| 行情指纹 | 前后一致（116,609 行） |
| `PRAGMA integrity_check` | ok |
| 旧验证/回测记录 | 一条未删、一条未改 |
| 迁移幂等 | 连续执行两次结果一致 |

### 报告

- `reports/phase3A3_2_corporate_action_audit.md`
- `reports/phase3A3_2_accounting_design.md`
- `reports/phase3A3_2_repair_report.md`
- `reports/phase3A3_2_backtest_replay_report.md`
- `reports/phase3A3_2_data_snapshot.md`
- `reports/phase3A3_2_test_report.md`

### 局限

1. 其余 36 条历史验证记录未重放（全池单次约 20 分钟，全部重放约 12 小时）。
2. 事件数据 165/166 条只有单一第三方来源。
3. 分红按除息日而非发放日入账，不模拟现金到账时点。
4. 零碎股按收盘价折现金，非官方规则（实测合计 188.49 元，< 0.02%）。

## 33. 阶段3A.3.2.1 公司行为账本关键缺陷整改

3A.3.2 通过代码审查后暴露四处问题，本阶段定向整改。
唯一目标：**让公司行为事件、现金与份额账本、历史回测输入指纹真正可追溯、可复现。**

### 33.1 现金分红入账时点

上一阶段把分红和拆分套用同一条「次一交易日」规则：

| 日期 | 价格 | 现金 | 结果 |
| --- | --- | --- | --- |
| 除息日 | 已除息下跌 | 未增加 | **虚假日亏损** |
| 次日 | 恢复 | 才增加 | 时点错误 |

`510300` 2021-01-19 除息（0.072 元/份）：

| 口径 | 当日收益 |
| --- | ---: |
| 修复前 | −1.343% |
| 修复后 | **−0.054%** |

改为**两段式**：

```
除息日 → 确认应收（dividend_receivable +，cash 不变）
发放日 → 应收转现金（receivable −，cash +）
总资产 = cash + market_value + receivable
```

分红金额按**权益登记日收盘持仓**计算，不是除息日持仓。
拆分/合并仍按官方 `effective_date`，没有套用分红规则。

### 33.2 证据等级

上一阶段 166 条事件全部标 `confirmed`，属于过度声称。
本阶段抓取基金管理人公告原文（34 只标的、343 条公告），逐条核对：

| 等级 | 数量 | 样本内 | 样本外 | 区间外 |
| --- | ---: | ---: | ---: | ---: |
| `official_confirmed` | **144** | 49 | 32 | 63 |
| `secondary_confirmed` | 12 | 0 | 0 | 12 |
| `unverified` | **10** | 0 | 0 | 10 |
| `rejected` | 0 | 0 | 0 | 0 |

**回测区间内 81 条 100% 为 official。** `unverified` 事件完全不进回测。

### 33.3 事件数量对账

上一阶段有四个互相不一致的数字，本阶段逐项澄清：

| 口径 | 数量 |
| --- | ---: |
| 原始抓取 / 去重后 / 全库 | 166 |
| 区间内（按 `effective_date`） | **81** |
| 样本内 / 样本外 / 区间外 | 49 / 32 / 85 |
| 应用事件数（去重） | 79 |
| 应用行数 | 2,788 |

`scripts/reconcile_events.py` 输出 **14 项校验，失败 0**。

### 33.4 输入指纹

上一阶段 `_input_hash()` 只加了固定字符串 `ca-v1`，事件内容变化不会改变指纹。

本阶段两级指纹：

| 层级 | 函数 | 覆盖 |
| --- | --- | --- |
| 单事件 | `compute_event_fingerprint` | 11 个字段 |
| 事件集合 | `compute_events_digest` | 稳定顺序 + 条数 + 逐条哈希 |

同时纳入回测层与验证层的 `input_hash`：

| 区间 | 事件数 | 指纹 |
| --- | ---: | --- |
| 样本内 | 49 | `3622b154eef724d6…` |
| 样本外 | 31 | `60f9ae2cd3b43adb…` |

### 33.5 事件版本管理

`save_action()` 不再静默 `UPDATE` 覆盖：

| 表 | 作用 |
| --- | --- |
| `corporate_actions` | 当前生效版本 |
| `corporate_action_versions` | 历史快照 + `change_reason` |

本阶段 166 条事件全部产生 version 2，共 **338 个版本**，旧版本完整保留。

### 33.6 账本边界

| 检查项 | 结果 |
| --- | --- |
| 多批次份额调整 `sum(lot) == new_quantity` | 最大余数法，3~13 批次 × 8 种比例全部通过 |
| 批次成本基准守恒 | 数量 ×N 则单价 ÷N |
| 可卖日期不前移 | T+1 保持 |
| 同 ETF 同日拆分 + 分红 | 先调份额，再按登记日份额算分红 |
| 公司行为不计入成交统计 | 走独立表，不进 `backtest_trades` |

### 33.7 历史记录

| 表 | legacy 标记 | 新口径 |
| --- | ---: | ---: |
| `validation_runs` | 39 | **2** |
| `backtest_runs` | 11 | 0 |

39 条未重放记录禁止作为新口径评价依据。

### 33.8 重放结果

| 区间 | 指标 | 3A.3.2 | **本阶段** |
| --- | --- | ---: | ---: |
| 样本内 | 总收益 | +10.87% | **+13.68%** |
| 样本内 | Sharpe | 0.1776 | **0.2522** |
| 样本外 | 总收益 | +20.24% | **+20.11%** |
| 样本外 | Sharpe | 0.7290 | **0.7208** |
| 样本外 | 最大回撤 | −18.11% | **−18.29%** |

MA250 vs 等权持有（样本外）：

| 指标 | MA250 | 买入持有 |
| --- | ---: | ---: |
| 总收益 | **20.11%** | 19.31% |
| 年化波动率 | **16.97%** | 17.17% |
| Sharpe | 0.7208 | **0.7225** |
| 最大回撤 | **−18.29%** | −19.03% |
| 交易次数 | 417 | 41 |
| 总成本 | 9,482.76 | 697.70 |

收益优势 +0.80 pp **不显著**；Sharpe 略低；成本高 **13.6 倍**。
「MA250 风险控制未实现」的结论仍被推翻，但「换手与成本过高」依然成立。

### 33.9 验证

| 项目 | 结果 |
| --- | ---: |
| 全量测试 | **425 passed**，0 failed / 0 skipped |
| 原有 387 项 | 全部保留通过 |
| 新增测试 | 13 项 |
| 事件对账校验 | 14 项，失败 0 |
| API 冒烟 | 通过 |
| Streamlit AppTest | 2 页无异常 |
| 行情指纹 | 未变（116,609 行） |
| `integrity_check` | ok |
| 迁移幂等 | 连续两次结果一致 |

### 33.10 报告

- `reports/phase3A3_2_1_event_reconciliation.md`
- `reports/phase3A3_2_1_dividend_accounting_fix.md`
- `reports/phase3A3_2_1_evidence_quality_report.md`
- `reports/phase3A3_2_1_fingerprint_version_report.md`
- `reports/phase3A3_2_1_backtest_replay_report.md`
- `reports/phase3A3_2_1_test_report.md`
- `reports/phase3A3_2_1_data_snapshot.md`

### 33.11 局限

1. 39 条历史验证记录未重放（单次约 28 分钟，全量约 17 小时）
2. 事件数据来自转载站（东方财富转载基金管理人公告全文），非基金公司官网 PDF
3. 未做人工逐条复核 144 条公告
4. 分红发放日按公告字面使用，不模拟银行延迟

## 34. 阶段3A.3.2.2 零碎份额成本基准与证据指纹

### 34.1 零碎份额成本基准

上一阶段用 `new_quantity / old_quantity` 折成本。这个比例已被取整污染：

| 项 | 值 |
| --- | ---: |
| 官方比例 | 1.145 |
| 理论份额（100 份） | 114.5 |
| 实际份额 | 114 |
| **上一阶段用的比例** | **1.14** |

结果：零碎 0.5 份的成本没转出，10,000 元全压在 114 份上。

修复后（1.145 拆分 100 份）：

| 项 | 修复前 | 修复后 |
| --- | ---: | ---: |
| 剩余成本 | 10,000.00 | **9,956.33** |
| 转出成本 | 0 | **43.67** |
| 已实现盈亏 | 0 | 与补偿现金配平 |

零碎成本按**组合层面**转出（`总成本 × 零碎份额 / 理论份额`），
再按各批次成本占比分摊。不用逐批次余数——
最大余数法把整数份额分给哪个批次只是账本拆分方式。

### 34.2 零碎处置必须按公告

| 口径 | 含义 | 条数 |
| --- | --- | ---: |
| `truncate` | 尾差计入基金财产 | **161** |
| `round_up` | 小数点后进位补足 | **5** |
| `cash_compensation` | 现金补偿 | **0** |

**没有一条公告规定现金补偿。** 上一阶段「按收盘价折现金」
是虚构了一个不存在的处置方式。

### 34.3 事件日期边界

`load_actions()` 原来统一按 `effective_date` 筛。但引擎实际：

- 现金分红 → `ex_date`
- 拆分 / 合并 → `effective_date`

改为按类型分别筛，避免「除息日在最后一天、生效日在之后」的分红被漏掉。

### 34.4 事件指纹

字段从 11 个扩到 **16 个**：

```
经济要素：code, action_type, ex_date, effective_date,
         share_ratio, cash_per_share, record_date, pay_date, fractional_policy
证据元数据：evidence_status, source, announcement_title,
          announcement_date, announcement_url, manager_name, evidence
数据版本：data_version
```

排除：`notes`、`version_no`、`action_id`、时间戳。

| 区间 | 事件数 | 指纹 |
| --- | ---: | --- |
| 样本内 | 49 | `27e331cfbbae…` |
| 样本外 | 31 | `2b4b24e468cb…` |

### 34.5 证据分级严格化

规则从「分数达标 + 至少 2 项核对」改为「**全部核对项通过**」：

| 等级 | 3A.3.2.1 | 本阶段 |
| --- | ---: | ---: |
| `official_confirmed` | 144 | **137** |
| `secondary_confirmed` | 12 | **19** |
| `unverified` | 10 | 10 |

**这 137 条是「程序自动匹配公告正文成功」，不是「人工逐条复核」。**
区间内还有 5 条 secondary（公告 URL 可核，但登记日/发放日未对到）。

### 34.6 统计口径复检

上一阶段把 80→81 的差异归因于 2018 年 `159920`，**归因错误**。

真实原因：

| 口径 | 区间内 |
| --- | ---: |
| 全 46 只池 | **81** |
| 41 只回测池 | **80** |

差值是 `588200`（2026-07-20 拆分），它在 46 只池但不在 41 只回测池。
`159920` 2018-06-22 那条完整在区间外，与差异无关。

### 34.7 重放结果

| 指标 | 3A.3.2.1 | 本阶段 |
| --- | ---: | ---: |
| 样本内总收益 | 13.6776% | **13.6776%** |
| 样本内 Sharpe | 0.2522 | **0.2522** |
| 样本外总收益 | 20.1070% | **20.1186%** |
| 样本外 Sharpe | 0.7211 | **0.7211** |
| 样本外最大回撤 | −18.2937% | **−18.2853%** |
| 交易次数（外） | 417 | **419** |
| 结论 | 有条件通过 | **有条件通过** |

差异 +0.01 pp，全部来自零碎成本修复，不是策略改善。

### 34.8 验证

| 项目 | 结果 |
| --- | ---: |
| 全量测试 | **454 passed**，0 failed / 0 skipped |
| 原有 425 项 | 全部保留通过 |
| 新增测试 | 29 项 |
| 事件对账校验 | 14 项，失败 0 |
| API 冒烟 | 通过 |
| Streamlit AppTest | 2 页无异常 |
| 行情指纹 | 未变（116,609 行） |
| `integrity_check` | ok |
| 迁移幂等 | 连续两次一致 |

### 34.9 报告

- `reports/phase3A3_2_2_fractional_cost_basis_report.md`
- `reports/phase3A3_2_2_event_date_boundary_report.md`
- `reports/phase3A3_2_2_event_fingerprint_report.md`
- `reports/phase3A3_2_2_test_report.md`
- `reports/phase3A3_2_2_data_snapshot.md`

### 34.10 局限

1. 21 条公告未明说零碎处置口径，按默认 truncate
2. 39 条历史验证记录未重放
3. 本库无跨界事件，边界修复只有构造测试覆盖
4. 137 条 official 是程序匹配，未人工逐条复核
5. 事件指纹常量名仍为 `ca-events-v2`，但字段集已扩展（旧值不受影响）

## 35. 阶段3A.3.2.2.1 会计口径收尾

### 35.1 零碎规则不再默认 truncate

上一版本把 31 条「公告没说」的事件默认成 `truncate` 并当作规则上报：

| 分类 | 3A.3.2.2 | 本阶段 |
| --- | ---: | ---: |
| 公告明示 `truncate` | 9 | **9** |
| 公告明示 `round_up` | 5 | **5** |
| 公告未载明 | 默认 `truncate` 21 | **`unknown` 21** |
| 无公告正文 | 默认 `truncate` 10 | **`unknown` 10** |

新增 `unknown` 状态，默认值改为 `unknown`。

### 35.2 用真实持仓判定是否需要规则

区间内 19 条 `unknown` 事件，逐条用应用记录里的实际持仓验算：

```
零碎份额 = 持仓 × 官方比例 - floor(持仓 × 官方比例)
```

| 项 | 数量 |
| --- | ---: |
| 区间内 `unknown` 事件 | **19** |
| 实际产生零碎份额 | **0** |
| 被阻断 | **0** |

这 19 条的官方比例全是整数（2/3/4/5/10/12），
持仓是整数时折算结果必然是整数，**零碎份额恒为 0**。
所以「零碎怎么处置」这个问题在这些事件上根本不成立。

一旦将来产生零碎份额，引擎 fail closed 阻断。

### 35.3 5 条 secondary 分红修正

公告把日期排成两列：

```
权益登记日 2025年9月22日（场内） 2025年9月23日（场外）
现金红利发放日 2025年9月26日（场内） 2025年9月24日（场外）
```

ETF 是场内品种，必须取场内列。旧解析器取错列，匹配失败时
`record_date` 退回 `ex_date`、`pay_date` 退回 T+1。

| 代码 | 除息日 | 登记日 | 发放日 |
| --- | --- | --- | --- |
| `511260` | 2025-09-23 | 09-23 → **09-22** | 09-24 → **09-26** |
| `159901` | 2025-11-17 | 11-17 → **11-14** | 11-18 → **11-19** |
| `511260` | 2025-12-26 | 12-26 → **12-25** | 12-29 → **12-31** |
| `511260` | 2026-06-25 | 06-25 → **06-24** | 06-26 → **06-30** |
| `511260` | 2026-09-18 | 09-18 → **09-17** | 09-21 → **09-23** |

修正后 5 条全部升级 `official_confirmed`。

| 等级 | 3A.3.2.2 | 本阶段 |
| --- | ---: | ---: |
| `official_confirmed` | 137 | **142** |
| `secondary_confirmed` | 19 | **14** |
| `unverified` | 10 | 10 |

**区间内 81 条 100% official。**

### 35.4 登记日资格 fail closed

旧代码：

```python
else:
    holding = portfolio.quantity(action.code)   # ← 退回除息日持仓
```

会让回测起点后才买入的份额凭空获得分红资格。

新代码直接阻断，记 `reason_code=missing_record_date_holding`。
本库 57 条区间内分红的登记日全部落区间内，**0 条触发**。

### 35.5 cash_compensation 强制官方价格

| 字段 | 作用 |
| --- | --- |
| `compensation_price` | 官方补偿价格 |
| `compensation_price_source` | 价格依据（公告条款原文） |

缺依据 → `__post_init__` 和 `compute_impact` 都抛错。
两个字段都进事件指纹。

本库**无 `cash_compensation` 事件**，只有单元测试覆盖。

### 35.6 版本表 176 行差异

| 时间 | 条数 | 原因 |
| --- | ---: | --- |
| 11:24 | 5 | 口径判定：明示进位 |
| 11:29 | 5 | 口径判定：明示进位（**重复**） |
| 11:34 | 137 | 证据等级 official |
| 11:34 | 19 | 证据等级 secondary |
| 11:34 | 10 | 证据等级 unverified |
| **合计** | **176** | |

上一报告算成 171，漏了 11:24 那 5 行。
多出的 5 行来自 `save_action` 幂等缺陷（指纹已更新但关键列未落库时反复写入），
已在 3A.3.2.2 修复。**重复版本保留不删**，166 条版本号全部连续。

### 35.7 重放结果

| 指标 | 3A.3.2.2 | 本阶段 |
| --- | ---: | ---: |
| 样本外总收益 | 20.1186% | **20.1146%** |
| 样本外 Sharpe | 0.7211 | **0.7210** |
| 样本外最大回撤 | −18.2904% | **−18.2881%** |
| 样本内总收益 | 13.6776% | **13.6776%** |
| 样本内 Sharpe | 0.2522 | **0.2522** |
| 交易次数（外） | 419 | **419** |
| 结论 | 有条件通过 | **有条件通过** |

样本外 −0.0040 pp 来自 5 条分红发放日推后（现金可用时点变准），
样本内完全不变。**不是策略改善或恶化。**

### 35.8 验证

| 项目 | 结果 |
| --- | ---: |
| 全量测试 | **469 passed**，0 failed / 0 skipped / 0 xfail |
| 历史 454 项 | 全部保留通过 |
| 本阶段新增 | 15 项 |
| 事件对账校验 | 14 项，失败 0 |
| API 冒烟 | 通过 |
| Streamlit AppTest | 2 页无异常 |
| 行情指纹 | 未变（116,609 行） |
| `integrity_check` | ok |
| 迁移幂等 | 连续两次一致 |

### 35.9 局限

1. 21 条公告未载明零碎处置方式，标记 `unknown`
2. 10 条无公告正文的事件仍 `unverified`
3. 4 条区间外 `secondary`（`511220` 2015-2016，公告无金额字段）
4. 39 条历史验证记录未重放
5. 只用东方财富转载全文，无法核对基金公司官网原始 PDF
6. 不支持非空初始持仓
7. `cash_compensation` 路径无真实案例
8. 测试结果是 DSH 会话内本地执行结果，不是外部独立测试

## 36. 阶段3A.3.2.2.2 公司行为安全边界

### 36.1 加载失败必须 fail closed

旧代码：

```python
try:
    actions = load_actions(...)
except Exception as exc:
    self.notes.append(f"公司行为：事件表不可用（{type(exc).__name__}），按旧口径回测")
    return []        # ← 静默降级
```

后果：表缺失 / 迁移未完成 / SQL 失败 / 反序列化失败
→ 引擎拿到空事件集 → 按旧口径跑完
→ 产出 `status=success`、账面正常、**但漏记全部公司行为**的记录。

修复：

| 情形 | 处理 |
| --- | --- |
| 表不存在 | 抛 `CorporateActionLoadError` |
| 迁移未完成（缺列） | 抛 |
| SQL 查询异常 | 抛 |
| 反序列化异常 | 抛 |
| 事件结构不合法 | 抛（不静默过滤） |

`apply_corporate_actions=False` 是唯一关闭入口，且必须打标记：

| 字段 | 正式 | 关闭时 |
| --- | --- | --- |
| `accounting_basis` | `formal_receivable` | `disabled_non_official` |
| `formal_valuation` | `True` | `False` |

### 36.2 分红强制真实登记日

删除 `record_date or ex_date` 全部回退（grep 结果 0 处）。

`__post_init__` 强制：

| 字段 | 要求 |
| --- | --- |
| `record_date` | 必须存在 |
| `pay_date` | 必须存在 |
| `cash_per_share` | > 0 |
| `record_date <= ex_date` | 必须 |
| `pay_date >= ex_date` | 必须 |

阻断原因细分：

| reason_code | 条件 |
| --- | --- |
| `missing_record_date` | 登记日缺失 |
| `missing_record_date_holding` | 区间内但无日终快照 / 早于起点 |
| `invalid_record_date` | 登记日不是交易日 |
| `missing_pay_date` | 发放日缺失 |

### 36.3 同日登记日与除息日的时序

旧顺序：开盘前就应用分红 → 当日成交尚未发生 → 拿错持仓。

新顺序：

```
开盘前：份额调整 + 登记日已过去的现金分红
        若 record_date == ex_date → 进 _deferred_dividends，跳过
开盘撮合
收盘后：锁定登记日持仓 → 确认同日分红应收 → 收盘估值
```

同时加 `_confirm_receivable()` 幂等保护，消除重复确认与重复写库。

### 36.4 本库实际影响

| 项 | 数量 |
| --- | ---: |
| `record_date == ex_date` 的分红事件 | **4** |
| 其中在回测区间内 | **0** |
| `record_date` 缺失 | **0** |
| `pay_date` 缺失 | **0** |

4 条同日事件全在 2021 年前（`159901` 2007-07-11、`511220` 2015-06-18、
`511220` 2015-09-21、`159920` 2018-06-22）。

**三处修复不改变任何指标**：

| 指标 | 3A.3.2.2.1 | 本轮 |
| --- | ---: | ---: |
| 样本外总收益 | 20.1146% | **20.1146%** |
| 样本外 Sharpe | 0.7210 | **0.7210** |
| 样本内总收益 | 13.6776% | **13.6776%** |
| 交易次数（外） | 419 | **419** |

安全加固不该改变数字；若变了，说明修复侵入了正常路径。

### 36.5 验证

| 项目 | 结果 |
| --- | ---: |
| 全量测试 | **484 passed**，0 failed / 0 skipped / 0 xfail |
| 基线 469 项 | 全部保留通过 |
| 本轮新增 | 15 项 |
| 事件对账校验 | 14 项，失败 0 |
| API 冒烟 | 通过 |
| Streamlit AppTest | 2 页无异常 |
| 行情指纹 | 未变（116,609 行） |
| `integrity_check` | ok |
| 迁移幂等 | 连续两次一致 |
| schema 变更 | **无** |

### 36.6 局限

1. 4 条同日事件在区间外，时序修复只有构造测试覆盖
2. 加载失败测试用 DROP/ALTER TABLE 模拟，未覆盖磁盘损坏
3. 39 条历史验证记录未重放
4. 测试结果是 DSH 会话内本地执行结果，不是外部独立测试

## 37. 阶段3A.3.2.2.3 非正式口径持久化

### 37.1 问题：标记在内存里有，落盘就没了

`BacktestResult` 自 3A.3.2.2.2 起携带：

| 字段 | 正式回测 | `apply_corporate_actions=False` |
| --- | --- | --- |
| `accounting_basis` | `formal_receivable` | `disabled_non_official` |
| `formal_valuation` | `True` | `False` |

但 `save_result()` 写 `summary_json` 时没带上它们。结果：

```
引擎内存有标记 → save_result 丢掉 → 库里只有净值
              → API / Streamlit 读回来无从判断
              → 非正式结果与正式结果在读取端完全同形
```

### 37.2 修复：默认值一律朝向「不正式」

```python
accounting_basis = getattr(result, "accounting_basis", None)
if not isinstance(accounting_basis, str) or not accounting_basis:
    accounting_basis = "unknown_legacy"
formal = getattr(result, "formal_valuation", None)
formal = bool(formal) if isinstance(formal, bool) else False
if accounting_basis != "formal_receivable":
    formal = False
```

方向很重要：旧逻辑「缺字段即正式」等于把无法证明的口径当成已证明。

读取端新增三个判定函数：

| 函数 | 语义 |
| --- | --- |
| `accounting_basis_of(summary)` | 缺失 → `unknown_legacy` |
| `formal_valuation_of(summary)` | 缺失 → `False` |
| `is_formal_run(summary)` | 两字段**同时**满足才为 `True` |

`get_run()` / `list_runs()` 把两字段提到顶层返回。

### 37.3 验证层的两个绕过口

| 位置 | 原行为 | 后果 |
| --- | --- | --- |
| `_events_digest_for()` | `except Exception: return "unavailable"` | 加载失败时指纹退化成常量，验证照跑 |
| `_run_backtest()` | 不看口径，只取 daily/trades/orders | 非正式指标直接进结论 |

后者是关键：`_run_backtest()` 是样本内、样本外、Walk-Forward、基准、
压力测试的唯一回测入口。

修复：

- `_events_digest_for()` 改为抛 `ValidationError`
- 新增 `_require_formal(result, where)`，在 `_run_backtest()` 与
  `_build_regime_payload()` 内的直接引擎调用处检查
- 三处 `except Exception` 前置 `except ValidationError: raise`，
  否则 `ValidationError` 会被「单格失败不终止整体」转成一行
  `status=failed` 记录，非正式结果仍会以部分形式留在结论里

### 37.4 边界

```
apply_corporate_actions=True（默认）
  ├─ 加载失败 → CorporateActionLoadError → 中止，不产生记录
  └─ 正常     → formal_receivable + True → 可进验证

apply_corporate_actions=False（唯一关闭入口）
  └─ 事件集为空 → disabled_non_official + False
                → 落盘标记强制非正式
                → 验证层抛 ValidationError，进不去
```

历史 11 条 `backtest_runs` 读取为 `unknown_legacy` + `False`。
**不回填**——回填等于给旧记录补造一个当时的会计口径证据。

### 37.5 验证

| 项 | 结果 |
| --- | ---: |
| 全量测试 | **496 passed**，0 failed / 0 skipped / 0 xfail |
| 基线 484 项 | 全部保留通过 |
| 本轮新增 | 12 项 |
| 事件对账校验 | 14 项，失败 0 |
| API 冒烟 | 通过 |
| Streamlit AppTest | 2 页无异常 |
| 行情指纹 | 未变（116,609 行） |
| `integrity_check` | ok |
| 迁移幂等 | 连续两次一致 |
| schema 变更 | **无** |
| 数据库行数变化 | **0** |

样本外重放与 3A.3.2.2.2 完全一致：+20.1146% / Sharpe 0.7210 /
回撤 −18.2881% / 419 笔。本轮不动会计逻辑，指标本就不该变。

### 37.6 局限

1. 39 条历史验证记录仍未重放
2. 11 条历史回测读取为非正式；要恢复正式身份必须重跑，不能回填字段
3. 两字段存于 `summary_json`，无独立列，无法用 SQL 索引快速筛选
4. 测试结果是 DSH 会话内本地执行结果，不是外部独立测试

## 38. 阶段3A.3.2.2.4 正式口径闸门一致性

### 38.1 缺陷：闸门只看一个字段

3A.3.2.2.3 引入的 `_require_formal()` 只做了这一件事：

```python
if not getattr(result, "formal_valuation", False):
    raise ValidationError(...)
```

`accounting_basis` 虽然出现在错误信息里，却**没有参与判断**。
于是这三类记录能穿过闸门：

| 记录 | `formal_valuation` | `accounting_basis` | 旧闸门 |
| --- | --- | --- | --- |
| 自相矛盾 | `True` | `disabled_non_official` | **放行** |
| 自相矛盾 | `True` | `unknown_legacy` | **放行** |
| 类型污染 | `1` / `"yes"` / `[1]` / `{"a":1}` | 任意 | **放行** |

第一行最危险：3A.3.2.2.3 只在 `save_result()` 落盘时强制纠正
（口径非正式 → 布尔强制 `False`），**内存对象没有这层保护**，
而验证流程拿的正是内存对象。

第三行是同一问题的另一面：`not getattr(...)` 对 `1`、`"yes"`、`[1]`、
非空字典都判为「真」，把一个不是 `True` 的值当成了正式布尔标记。

根因：正式性由两个字段共同定义，只检查其中一个的实现必然有绕过口。

### 38.2 修复：严格白名单

```python
FORMAL_ACCOUNTING_BASIS = "formal_receivable"

basis = getattr(result, "accounting_basis", None)
formal = getattr(result, "formal_valuation", None)

problems = []
if not isinstance(basis, str) or basis != FORMAL_ACCOUNTING_BASIS:
    problems.append(f"accounting_basis={basis!r}")
if not isinstance(formal, bool) or formal is not True:
    problems.append(f"formal_valuation={formal!r}")
```

三处刻意严格：

| 检查 | 拒绝的例子 | 理由 |
| --- | --- | --- |
| `isinstance(basis, str)` | `["formal_receivable"]` | 口径只能是字符串 |
| `basis != FORMAL_ACCOUNTING_BASIS` | `"FORMAL_RECEIVABLE"`、`"formal"` | 精确等值，不做归一与前缀匹配 |
| `formal is not True` | `1`、`1.0`、`"yes"`、`[1]` | `1 == True` 但 `1 is not True` |

### 38.3 覆盖范围

`_require_formal()` 的调用点未变，因此自动覆盖全部验证环节：

| 调用点 | 覆盖 |
| --- | --- |
| `_run_backtest()` | 样本内网格、样本外、Walk-Forward、基准、压力测试、稀疏副本 |
| `_build_regime_payload()` | 市场环境分组统计 |

### 38.4 验证

| 项 | 结果 |
| --- | ---: |
| 全量测试 | **518 passed**，0 failed / 0 skipped / 0 xfail |
| 基线 496 项 | 全部保留通过 |
| 本轮新增 | 22 项 |
| API 冒烟 | 通过 |
| Streamlit AppTest | 2 页无异常 |
| `integrity_check` | ok |
| schema 变更 | **无** |
| 数据库行数变化 | **0** |
| 公司行为核心逻辑 | 未修改 |

### 38.5 局限

1. 「两字段矛盾」在真实数据中不会自然出现——`save_result()` 会强制纠正落盘值。
   这是内存对象的防御性校验，只有构造测试能覆盖，属纵深防御而非已观测缺陷
2. `formal_valuation` 存于 `summary_json`，无独立列，无法用 SQL 快速筛选
3. 测试结果是 DSH 会话内本地执行结果，不是外部独立测试

## 39. 阶段3A.3.2.3.1 历史记录重放体系

### 39.1 问题：历史记录里混着旧会计口径，且无法判断哪些能重放

`backtest_runs` 11 条、`validation_runs` 44 条，其中绝大多数写在公司行为
整改之前。要判断「哪些是当前正式口径、哪些需要重放、哪些根本重放不了」，
之前只能靠报告里的说法，没有可复算的依据。

### 39.2 盘点：五类归档，每条都有理由

```bash
python scripts/audit_replay_history.py
```

| 分类 | 判定 |
| --- | --- |
| `current_formal` | `accounting_version == 'ca-v2-receivable'` |
| `replayed` | `replay_attempts` 里有该源的 `success` 行 |
| `legacy` | legacy 会计版本 + 全部关键参数可读 |
| `unknown_legacy` | `accounting_version` 为空或未知 |
| `non_replayable` | 缺关键参数，或源记录本身失败 |

实测（本轮）：

| 类别 | backtest | validation |
| --- | ---: | ---: |
| 总数 | 12 | 44 |
| `current_formal` | 1 | 5 |
| `replayed` | 1 | 0 |
| `legacy`（待重放） | 1 | 37 |
| `non_replayable` | 9 | 2 |

### 39.3 参数忠实性：反证，不是重建

`validation_runs` 只有区间、池、网格几列；资金、佣金、最低佣金、滑点、
执行价、指标版本、Walk-Forward 网格、池模式全都没有独立列，
只体现为一列 `config_hash`。

```python
for 字段集 in (当前 28 字段, 历史 26 字段):
  for pool_mode in ("all", "representative"):
    for dates in 日期候选:          # 存储值 / 该月 1 日
      if params_hash(候选参数) == 存库的 config_hash:
          return 参数              # 命中即全部证明
return None                        # 不可证明，判 non_replayable
```

日期候选是必需的：库里存的是「请求日对齐到下一交易日」后的日期，
请求 2021-01-01 存成 2021-01-04。

### 39.4 backtest 的真实缺陷

11 条历史回测的 `config_json.strategy_params` 恒为 `{}`。
`ma_trend` 唯一的真实参数是 `ma_window`，它当时是命令行参数、
从未落库。没有 `ma_window` 就无法复现同一批信号。

**9 条因此永久不可重放。** 没有用默认 20 兜底，没有从 `input_hash`
或报告数字反推——那三种做法都会产出一条「看起来一样、其实不知道是不是
同一次回测」的记录。

### 39.5 对应关系表 `replay_attempts`

```sql
CREATE TABLE replay_attempts (
    attempt_id, record_kind, source_record_id, replay_record_id,
    source_input_hash, replay_input_hash,
    source_accounting_version, replay_accounting_version,
    source_config_hash, replay_params_json,
    status, reason, started_at, finished_at, replay_timestamp
);
```

为什么用独立表而不是给历史表加列：加列意味着 UPDATE 历史行。
独立表只追加。

### 39.6 幂等与恢复

| 场景 | 行为 |
| --- | --- |
| 重复执行同一源 | `skipped`，不写新行、不建新记录 |
| `--force` | 新建记录，旧 attempt 保留 |
| 单条失败 | 记 `failed` + 原因，同批其他条继续 |
| 中断后 | 重跑同一命令，已成功的自动跳过 |

幂等**不是靠改历史行**实现的，是靠查 `replay_attempts` 里有没有 success。

### 39.7 命令

```bash
python scripts/audit_replay_history.py --pending-only
python scripts/replay_3a3_2.py --source ac8f4cc7cf234d7e
python scripts/replay_validation_3a3_2.py --source 32aead3291734f91
python scripts/replay_validation_3a3_2.py --pending --dry-run
```

### 39.8 本轮真实重放

`ac8f4cc7cf234d7e` → `355948ec40224eb5`（buy_and_hold，5 只）：

| 项 | 源 | 新 |
| --- | --- | --- |
| accounting_version | `legacy_corporate_action_accounting` | `ca-v2-receivable` |
| input_hash | `783858ffd0a628c5` | `9a107ccaff142b43` |

新记录 `accounting_basis=formal_receivable`、`formal_valuation=True`。
行情指纹前后一致。

### 39.9 验证

| 项 | 结果 |
| --- | ---: |
| 全量测试 | **538 passed**，0 failed / 0 skipped / 0 xfail |
| 基线 518 项 | 全部保留通过 |
| 本轮新增 | 20 项 |
| API 冒烟 | 通过 |
| Streamlit AppTest | 2 页无异常 |
| `integrity_check` | ok |
| 迁移幂等 | 连续两次一致 |
| 行情指纹 | 未变（116,609 行） |
| 事件对账 | 14 项，失败 0 |

### 39.10 局限

1. **未执行全量批量重放**：38 条待重放（1 backtest + 37 validation），
   预估 13~15 小时，清单见 `reports/phase3A3_2_3_1_replay_checklist.md`
2. 9 条 backtest 因 `ma_window` 从未落库而永久不可重放
3. 2 条 validation 因 `config_hash` 无法反证且源记录本身失败而不可重放
4. `config_hash` 反证依赖当时的字段集；未来 `ValidationConfig` 再增字段时
   需同步新增变体
5. 测试结果是 DSH 会话内本地执行结果，不是外部独立测试

## 40. 阶段3A.3.2.3.2 重放失败闸门修复

### 40.1 缺陷一：validation 闸门三值短路

```python
row = conn.execute("SELECT input_hash, accounting_version ...").fetchone()
replay_acct = str(row[1]) if row and row[1] else None

if replay_acct and replay_acct != CURRENT_ACCOUNTING:   # ← 为 None 时短路
    ... FAILED
# 落到 STATUS_SUCCESS
```

| 新记录实况 | 修复前 | 修复后 |
| --- | --- | --- |
| 记录不存在 | **success** | failed |
| `accounting_version = None` | **success** | failed |
| `accounting_version = ''` | **success** | failed |
| `legacy` / 未知版本 | failed | failed |

修复后：

```python
if row is None:
    ... FAILED
replay_acct = row[1]
if not isinstance(replay_acct, str) or replay_acct != CURRENT_ACCOUNTING:
    ... FAILED
```

### 40.2 缺陷二：backtest 闸门真值判断

```python
if result.accounting_basis != ACCOUNTING_FORMAL or not result.formal_valuation:
```

`not 1` 为 `False`，`formal_valuation=1` 能穿过并调用 `save_result`。

修复为与 `_require_formal()` 同一语义：

```python
basis = getattr(result, "accounting_basis", None)
formal = getattr(result, "formal_valuation", None)
if (basis != ACCOUNTING_FORMAL
        or not isinstance(formal, bool) or formal is not True):
    raise ReplayError(...)
```

### 40.3 可测缝隙

抽出 `_fetch_validation_record()`。原实现把回查内联在 `replay_validation()` 里，
「查不到记录」这条失败路径无法在不替换整个数据库连接时测试；
第一版测试用了替换 `get_connection` 的方式，反而把建表初始化一起挡掉了。

### 40.4 验证

| 项 | 结果 |
| --- | ---: |
| 全量测试 | **564 passed**，0 failed / 0 skipped / 0 xfail |
| 基线 538 项 | 全部保留通过 |
| 本轮新增 | 26 项 |
| 前置条件复检 | 六项全通过 |

新增测试的每条都核实数据库最终状态，而不只断言抛异常。

## 41. 阶段3A.3.2.3.3 P0 历史验证记录受控重放

### 41.1 结果

| source | → | 新记录 | 结论 |
| --- | --- | --- | --- |
| `32aead3291734f91` | → | `03410886d1f64fa7` | 有条件通过 |
| `c46fa37b932944c2` | → | `321caeb581e54d3b` | 有条件通过 |

两条新记录 `accounting_version=ca-v2-receivable`，**所有绩效指标逐项相同**。

### 41.2 新旧对照

| 指标 | 第一条旧 → 新 | 第二条旧 → 新 |
| --- | --- | --- |
| 样本内总收益 | −16.33% → **+13.68%** | +10.87% → **+13.68%** |
| 样本内 Sharpe | 0.1058 → 0.2522 | 0.1776 → 0.2522 |
| 样本外总收益 | +32.21% → **+20.11%** | +20.24% → **+20.11%** |
| 样本外 Sharpe | 0.7859 → 0.7210 | 0.7290 → 0.7210 |
| 样本外回撤 | −24.54% → −18.29% | −18.11% → −18.29% |

差异全部来自会计口径：旧口径把分红当成价格下跌，从不入账。
行情指纹（`d54727c0…`）、策略参数、算法均未变。

### 41.3 执行中暴露的第三个缺陷

`save_validation_run()` 的 INSERT **不含 `accounting_version` 列**——
历史记录那一列是 `mark_legacy_records.py` / `finalize_replay_records.py`
事后 UPDATE 上去的。而重放器从不补这一步，于是新记录该列天生为 `NULL`，
闸门永远过不去。

第一次执行 `32aead3291734f91` 就是这样失败的：

```
[FAIL] 32aead3291734f91 -> 397118a140c44f47（重放记录会计版本异常：None）
```

修复两处：

| 函数 | 作用 |
| --- | --- |
| `_stamp_replay_validation()` | 给新建记录补 `ca-v2-receivable`，只写刚创建的 ID |
| `_reject_replay_record()` | 闸门失败时把孤立记录降级为 `failed` + 原因，不删除 |

`397118a140c44f47` 作为首次执行的审计痕迹保留在库内。

### 41.4 三项口径不可比（必须标注）

**① `validation_runs.summary_json` 没有正式会计标记**

`backtest_runs.summary_json` 有 `accounting_basis` / `formal_valuation`，
`validation_runs.summary_json` **没有**——验证层从不写这两个键，
历史 44 条也没有。验证记录的正式性由
`accounting_version=ca-v2-receivable` + 重放闸门共同保证。

**② 各市场环境收益不可比较**

`regime` 分组统计从未落库（无对应表，summary 里也没有）。
只能读到一句「市场环境覆盖 3 类且样本充足」。不给 bull/bear/range 分组数字。

**③ 分红应收与到账不可比较**

`corporate_action_applications` / `dividend_receivables` 的键是
**回测 run_id**，不是 validation_id。验证流程内部每次生成临时 run_id，
所以本轮 3 条新记录在这两张表里**行数为 0**——历史 44 条 legacy 验证记录
同样如此，属既有设计。

后果：能核对「事件集 digest 一致」「池内 80 条全可应用」，
但**无法从数据库给出「本次重放的分红应收金额与到账笔数」**。
该数字只能在单策略内存回测里得到。不伪造。

### 41.4b input_hash 可独立复现

用「当前行情指纹 + 池内 80 条事件 digest + resolved_params」重算 `_input_hash()`：

| 记录 | 库内 | 重算 | 一致 |
| --- | --- | --- | --- |
| `03410886d1f64fa7` | `1263f78d8a63e309` | 同 | **是** |
| `321caeb581e54d3b` | `6da51a1c462b7c65` | 同 | **是** |
| 两条旧记录 | — | 不等 | 预期（旧算法无事件指纹） |

### 41.4c 样本内反转的成因

| 参数 | 旧口径 IS | 新口径 IS | 改善 |
| --- | ---: | ---: | ---: |
| MA5 | −40.84% | −29.87% | +10.97 pp |
| MA20 | −16.58% | −7.43% | +9.14 pp |
| MA60 | −19.15% | −0.69% | +18.46 pp |
| MA250 | **−16.33%** | **+13.68%** | **+30.00 pp** |

全部档位都改善，MA250 改善最大——换手最低、持仓最久、累积分红应收最多，
被旧口径系统性压低最深。这也是「仅 0/7 → 1/7 个参数组合在样本内取得正收益」的由来。

### 41.5 幂等

两条重复执行均返回 `skipped`，`validation_runs` 保持 47 条不变，
不新增 record、不重复入账、不改变已有新记录。

### 41.6 验证

| 项 | 结果 |
| --- | ---: |
| 全量测试 | **568 passed**，0 failed / 0 skipped / 0 xfail |
| 基线 538 项 | 全部保留通过 |
| 本轮新增 | 30 项（26 闸门 + 4 执行缺陷与链路） |
| 行情指纹 | 未变 |
| `integrity_check` | ok |
| 源记录 | 全字段与执行前快照逐字段相等 |

### 41.7 是否建议扩大

建议扩大，但要先补两件事：

1. 验证层的会计明细可追溯（当前查不到分红应收/到账）
2. 35 条待重放里有一半是重复参数（12 条共用同一 `input_hash`），
   真正有信息增益的只剩 2 条 41 只全池记录

不建议无条件跑完 35 条。

## 42. 阶段索引

| 阶段 | 内容 | 测试数 | 报告 |
| --- | --- | ---: | --- |
| 3A.3.1 | MA 趋势策略失效归因（只读研究） | — | `phase3A3_1_*.md` |
| 3A.3.2 | 价格口径与基金份额变动处理 | 412 | `phase3A3_2_*.md` |
| 3A.3.2.1 | 公司行为账本关键缺陷整改 | 425 | `phase3A3_2_1_*.md` |
| 3A.3.2.2 | 零碎份额成本基准与证据指纹 | 454 | `phase3A3_2_2_*.md` |
| 3A.3.2.2.1 | 会计口径收尾（unknown 规则 / 登记日 fail closed） | 469 | `phase3A3_2_2_1_*.md` |
| 3A.3.2.2.2 | 公司行为安全边界（加载 fail closed / 同日时序） | 484 | `phase3A3_2_2_2_*.md` |
| 3A.3.2.2.3 | 非正式口径持久化与验证闸门 | 496 | `phase3A3_2_2_3_*.md` |
| 3A.3.2.2.4 | 正式口径闸门一致性（双字段白名单） | 518 | `phase3A3_2_2_4_*.md` |
| 3A.3.2.3.1 | 历史记录重放体系（盘点 / 反证 / 幂等登记） | 538 | `phase3A3_2_3_1_*.md` |
| 3A.3.2.3.2 | 重放失败闸门（三值短路 / 非布尔真值） | 564 | `phase3A3_2_3_2_*.md` |
| 3A.3.2.3.3 | P0 两条历史验证记录受控重放 | 568 | `phase3A3_2_3_3_*.md` |
| 3A.3.2.3.4 | 验证内部回测与公司行为审计追溯 | 618 | `phase3A3_2_3_4_*.md` |
| 3A.3.2.3.4.1 | 审计完整性闸门与明细持久化整改 | 632 | `phase3A3_2_3_4_1_audit*.md` |
| 3A.3.2.3.4.1.1 | 审计完整性与 Sparse 明细原子化 | 688 | `phase3A3_2_3_4_1_1_*.md` |
| 3A.3.2.3.5 | 历史回测与验证记录重放候选清点 | 688 | `phase3A3_2_3_5_*.md` |
| 3A.3.2.3.6 | 第一批历史记录受控重放（5 条，执行 2 条后暂停） | 688 | `phase3A3_2_3_6_*.md` |
| 3A.3.2.3.6.1 | 修复重放审计缺陷并重新执行前两条 | 702 | `phase3A3_2_3_6_1_*.md` |
| 3A.3.2.3.6.2 | 第二批历史记录受控重放（G7/G8/G1） | 702 | `phase3A3_2_3_6_2_*.md` |
| 3A 最终收口 | 剩余历史配置重放（G2/G3/G4/G5） | 702 | `phase3A_final_replay_closure.md` |
| 3B-1 | 正式会计口径下的策略有效性基线研究 | 702 | `phase3B1_strategy_effectiveness_baseline.md` |
| 3B-1.1 | 研究统计去重与结论校准 | 723 | `phase3B1_strategy_effectiveness_baseline.md`（v2） |
| 3B-2 | 新策略候选研究与第一轮验证 | 747 | `phase3B2_strategy_candidates.md` |
| 3B-3 | 支付宝场外基金数据体系可行性审计 | 784 | `phase3B3_fund_data_feasibility.md` |
| 3B-3.1 | 场外基金历史净值连续性审计补强 | **808** | `phase3B3_fund_data_feasibility.md`（v2 §6.0） |

当前正式会计版本：`ca-v2-receivable`；正式会计基础：`formal_receivable`；正式估值标记：`formal_valuation=True`。

行情指纹 `market-fingerprint-v3` / 116,609 行 / `d54727c0a76a1b09531accd04b3d66ff4ea2374592b1d4a8cb8381602cbbac49`，自 3A.3.2 起连续六个阶段未变。

## 43. 阶段3A.3.2.3.4 验证内部回测与公司行为审计追溯

### 43.1 解决的问题

此前 `validation_runs` 与内部各次 BacktestEngine 运行**完全断链**：
明细表按 `run_id` 存 264 个不同 run，从 `validation_id` 查不到任何一条。
审查中还发现两个真实缺陷：

1. `BacktestEngine.run()` 返回的 `run_id` 与写明细用的 `_run_id_for_actions`
   不是同一个 UUID —— 结果与明细关联错位。
2. `_run_backtest()` 未解析 `db_path`，传 `None` 时引擎走
   `if self.db_path is not None` 守卫，**validation 内部回测根本不写明细**。

### 43.2 新增结构

| 表 | 主键约束 | 用途 |
| --- | --- | --- |
| `validation_backtest_runs` | `UNIQUE(validation_id, backtest_run_id)` | validation → 内部回测 |
| `validation_regime_stats` | `UNIQUE(validation_id, regime_label)` | 市场环境分组 |

九类内部回测全部登记：`in_sample_grid` / `out_of_sample` /
`walkforward_train` / `walkforward_test` / `regime_grouping` / `benchmark` /
`stress_cost_slippage` / `stress_sparse_data` / `stress_insufficient`。

### 43.3 追溯链路

```
validation_id
  → validation_backtest_runs（52 条，九类角色全覆盖）
  → corporate_action_applications / dividend_receivables（按 run_id）
  → corporate_actions / corporate_action_versions（事件与版本）
```

三个查询端点：`/api/validations/{id}/audit`、`/backtest-runs`、`/regime`。
dashboard「策略验证」页新增「审计追溯」tab。

### 43.4 新 validation 的实测数据

| 项 | 值 |
| --- | ---: |
| validation_id | `aad7935a2bac4cc4` |
| 内部回测 | 52 |
| 应用事件 | 818 |
| 应收 / 到账 | 650 笔 / 585,663.95 元 |
| 未到账 | 0 笔 / 0.00 元 |
| 事件去重 | 78 条（分红 56 / 拆分 18 / 反向拆分 4） |
| 完整性校验 | complete，problems = [] |

样本外一次回测：区间内池内 31 条可应用事件，应用 30 条，
应收 23 笔 12,821.78 元、全部到账——与 3A.3.2.1 报告一致。
未应用的 1 条是 `515880` 的 1:3 拆分（2026-02-03 生效），当期未持仓。

### 43.5 市场环境分组（已落库）

| 环境 | 状态 | 总日 | 有效 | 缺失 | 累计 | Sharpe | Sortino | 回撤 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bull | ok | 324 | 321 | 3 | +53.24% | 2.1879 | 3.3656 | −7.46% |
| bear | ok | 26 | 24 | 2 | −4.81% | −5.6095 | −5.9579 | −4.99% |
| range | ok | 97 | 97 | 0 | −17.16% | −2.2385 | −2.5833 | −18.39% |
| unclassified | insufficient_sample | 0 | 0 | 0 | — | — | — | — |

`unclassified` 有效样本 0 < 20，标 `insufficient_sample` 并写明原因，
不填 0、不并入 range。分组总日数 324+26+97 = 447 = OOS 交易日总数，
缺失日单独记在 `missing_days`，没有 dropna。

### 43.6 跨库明细的标注

`stress_sparse_data` 的 23 笔 12,728.18 元写在稀疏副本库，不在主库。
审计结果按登记表实际计数呈现，并带 `detail_location="external_copy_db"`
与 `detail_note`。既不显示为 0，也不假装在主库。

### 43.7 旧记录兼容

| 记录 | audit_status |
| --- | --- |
| `32aead3291734f91` / `c46fa37b932944c2` | `unavailable_legacy` |
| `03410886d1f64fa7` / `321caeb581e54d3b` | `unavailable_legacy` |

生成时未记录 run_id，明细表里也查不到对应 run（当时根本不写），
无从恢复。**不猜测补齐、不改原始绩效、不伪造审计记录。**

### 43.8 完整性校验会抓住什么

`audit_completeness()` 按库内可推出的期望值核对：网格档位数、
WF 窗口数、压力场景数、基准数逐项比对，并逐个核对网格档位与场景键。

实测案例：某次试跑的 MA5 因 `database is locked` 失败，系统正确报出
「in_sample_grid 登记 6 条，期望 7 条」+「样本内 MA5 未登记」，
没有把它当成完整审计成功。

### 43.9 验证

| 项 | 结果 |
| --- | ---: |
| 全量测试 | **618 passed**，0 failed / 0 skipped / 0 xfail |
| 耗时 | 161.82 秒 |
| 新增测试 | 50 项（43 审计 + 7 API） |
| 行情指纹 | `d54727c0…` 未变 |
| `integrity_check` | ok |
| 四条历史记录 | 全字段逐字段相等 |
| 两次重放绩效 | 逐位相同 |

## 44. 阶段3A.3.2.3.4.1 审计完整性闸门与明细持久化整改

### 44.1 修掉的核心问题

| 问题 | 修复前 | 修复后 |
| --- | --- | --- |
| ghost_run | 关联表写一行 `success` 就判 `complete` | 登记期拦截 + 追溯期拦截，双重拒绝 |
| 明细只有计数 | sparse 副本删除后只剩 23 笔 / 12,728.18 元 | 逐笔明细落主库审计表，7 项对账 |
| regime 失败 | 写条 warning 仍返回 `success` | validation 标 `failed` 并抛错 |
| 版本追溯 | 只查 `corporate_actions` | 补 `corporate_action_versions`，缺版本标 `version_unavailable` |

### 44.2 存在性凭证

新增 `backtest_runs.run_scope`：

| 值 | 含义 | 现有 |
| --- | --- | ---: |
| `standalone` | 用户直接跑的回测 | 12 |
| `validation_internal` | validation 内部回测 | 0（本轮未重跑） |

`register_run_evidence()` 由真实回测路径在拿到 `BacktestResult` 后调用，
凭证只在真跑过时产生。`list_runs()` 与盘点按 `standalone` 过滤。

### 44.3 完整性判定 8 类校验

1. validation 自身 `status == success`
2. 每个 `backtest_run_id` 在 `backtest_runs` 存在
3. 凭证 `run_scope == validation_internal`
4. `accounting_basis == formal_receivable`
5. `formal_valuation == 1`
6. `status == success`
7. 有应用时逐笔明细必须查得到且数量金额一致
8. 角色数量、压力场景、网格档位、regime 落库

任一项不满足即 `complete=False` 并给出具体原因。

### 44.4 sparse 明细主库审计区

| 表 | 唯一键 |
| --- | --- |
| `audit_sparse_applications` | `(validation_id, run_id, action_id)` |
| `audit_sparse_receivables` | `(validation_id, run_id, action_id)` |

执行顺序不可调换：回测 → 复制 → 7 项对账 → 更新位置 → 删副本。
对账不通过则副本保留、主库不留半条。复制幂等（连跑 3 次恒为 1 行）。

### 44.5 存量记录状态

| 状态 | 数量 | 含义 |
| --- | ---: | --- |
| `unavailable_legacy` | 47 | 完全没有内部回测登记 |
| `unavailable_legacy_evidence` | 7 | 有登记但全部 52 条缺存在性凭证 |
| `complete` | **0** | 本轮未产生新的合格记录 |

`aad7935a2bac4cc4` 的 sparse 关联行标 `unavailable_external_detail`，
绩效与会计数据零改动。

### 44.6 验证

| 项 | 结果 |
| --- | ---: |
| 全量测试 | **632 passed**，0 failed / 0 skipped / 0 xfail |
| 耗时 | 171.55 秒 |
| 新增测试 | +14（含 12 项反向场景） |
| `audit_trace` 与 `audit_completeness` 不一致 | 0 / 54 |
| 行情指纹 | `d54727c0…` 未变 |
| `integrity_check` | ok |
| 新增表唯一性 | 实测拦截重复插入 |

### 44.7 遗留

- 存量 7 条永久 `unavailable_legacy_evidence`，补写凭证等于伪造，不做
- `aad7935a2bac4cc4` 的 sparse 逐笔明细永久不可恢复
- 版本回退策略（精确未命中取末版）与精确命中的语义不同

## 45. 阶段3A.3.2.3.4.1.1 审计完整性与 Sparse 明细持久化整改

### 45.1 修掉的 6 个缺陷

| # | 缺陷 | 后果 |
| ---: | --- | --- |
| 1 | `copy_info = {...},` 尾随逗号 | dict 变 tuple，`copy_info["copy_path"]` 抛 TypeError |
| 2 | 插入与对账不在同一事务 | 对账失败留半条 |
| 3 | 只比计数与合计 | 单条单字段错误查不出 |
| 4 | WF 只查 `walkforward_test` | 缺训练窗口仍判 complete |
| 5 | 压力测试只看场景是否登记 | 登记了但执行失败也通过 |
| 6 | `_version_of()` 回退最新版 | 掩盖历史版本缺失 |

### 45.2 事务与对账

`persist_sparse_details()` 现在是单事务：插入 + 逐字段对账在同一个
`with get_connection()` 块内，对账不通过就块内 raise，整体 rollback。

| 明细 | 参与对账的字段数 |
| --- | ---: |
| `audit_sparse_applications` | 15 |
| `audit_sparse_receivables` | 10 |

精度规则：数值字段绝对误差 `<= 1e-6`（与库内 `round(...,6)` 对齐），
整数与文本严格相等。失败信息精确到 `action_id + 字段名 + 双方值`。

### 45.3 Walk-Forward 完整性

逐窗口核对，不再只看总数：

1. 每个已执行窗口 × `wf_grid` 每个候选，必须有 `walkforward_train` 记录
2. 训练记录数 = 已执行窗口数 × 候选数
3. 每个窗口必须有 `walkforward_test` 记录
4. 训练/测试记录状态必须 `success`
5. `insufficient_data` 窗口单列一条 problem

### 45.4 压力测试三态

| 状态组合 | 判定 |
| --- | --- |
| 场景 `insufficient` + 回测 `success` | 执行成功但样本不足，不报执行失败 |
| 场景 `insufficient` + 回测 `failed` | 报「回测执行状态为 failed」 |
| `insufficient` 挂在非样本量场景 | 报「只有样本量类场景允许该状态」 |

### 45.5 版本严格匹配

`_version_of()` 只按 `(action_key, version_no)` 精确查，查不到返回 None，
**不再回退到最新版本**。`version_no` 为空也返回 None。

Sparse 明细表新增 `version_no` 与 `event_fingerprint` 两列保留版本证据。

### 45.6 验证

| 项 | 结果 |
| --- | ---: |
| 全量测试 | **688 passed**，0 failed / 0 skipped / 0 xfail（阶段终值） |
| 耗时 | 248.12 ~ 267.12 秒（多次执行） |
| 本轮新增测试 | +56（.4.1.1 的 38 + 验收补充 11 + 预期独立性 7） |
| 字段篡改测试 | 23 项（应用 14 + 应收 9） |
| `audit_trace` 与 `audit_completeness` 不一致 | 0 / 54 |
| `integrity_check` | ok |
| 行情指纹 | `d54727c0…` 未变 |
| 历史记录数据变化 | 0（只有两张 sparse 表加了两列） |

### 45.7 尚未解决

- **真实 sparse 端到端未跑**：本轮禁止重跑内部回测，tuple 修复与事务原子性
  只在单元测试层面验证（测试里造了真实副本库、真实事件行、真实明细行）。
  下次真实跑带 sparse 的 validation 才能确认端到端。
- 存量 7 条永久 `unavailable_legacy_evidence`，补写凭证等于伪造
- `aad7935a2bac4cc4` 的 sparse 逐笔明细永久不可恢复
- 事务原子性依赖 SQLite 隐式事务，高并发下有锁等待风险（失败会整体回滚）

### 45.8 验收补充（2026-11-17）

**sparse 成功路径测试的弱断言已修**

原测试用条件断言 `if status == "success": ...`，但构造的临时库缺指标行与
公司行为事件，`_run_data_stress()` 实际返回 `failed`，分支从未进入。

新 fixture 补齐三个必要条件：行情 + `etf_indicator_daily` 指标行 + 公司行为
事件与持仓。测试改为强制断言 13 项，包括 `status == success`、
`data_copy` 是 dict、`removed is True`、副本文件与目录都已删除、
主库审计表真的有行、`version_no` 与 `event_fingerprint` 完整、
金额合计差 ≤ 1e-6、审计登记行状态与计数正确。

**压力测试预期场景覆盖已补**

`runner.py` 成功收尾时把本次真实使用的场景集合落到
`validation_runs.stress_config.expected_keys`，同时把 `wf_grid` 落到
`walkforward_config`。

`audit_completeness()` 现在比对：

| 检查 | 失败表现 |
| --- | --- |
| 预期场景是否都登记 | `压力测试缺少预期场景 [...]` |
| 是否出现不属于配置的场景 | `压力测试出现不属于本次配置的场景 [...]` |
| 场景是否重复 | `压力测试场景重复登记 [...]` |
| 配置缺失或为空 | `预期场景无法确定`（fail closed，不当成没有要求） |

存量 54 条记录 `stress_config` 全为空（生成于配置落库之前），按 fail closed
原则报「无法确定」——它们本来就是 `unavailable_legacy*`，不构成放行风险。

### 45.9 压力预期场景独立于执行结果（2026-11-17 二轮修复）

上一轮把 `expected_keys` 写成 `[row["key"] for row in stress_rows]`，
这是**从实际执行结果反推预期**：某场景在生成阶段丢失时，
预期会跟着缩水，审计永远发现不了。

**修复**：新增 `stress.expected_scenario_keys()`，来源只有显式请求的
`keys` 或 `default_scenarios()` 完整集合，函数体不读数据库、不读
`stress_rows`（测试用 `inspect.getsource()` 断言）。

`runner.py` 在任何场景执行**之前**调用它，`executed_keys` 只作对照记录。

`audit_completeness()` 增加时序校验：读到旧实现的
`source == "actual_stress_rows"` 时判为「反推配置，不构成独立预期」。

| 场景 | 预期集合 | 实际执行 | 审计结果 |
| --- | --- | --- | --- |
| 默认 7 个，只跑 2 个 | 7 个（配置） | 2 个 | 报缺 5 个 |
| 显式请求 3 个，只跑 2 个 | 3 个（请求） | 2 个 | 只报缺被请求的那个 |
| 默认 7 个全部执行 | 7 个 | 7 个 | 压力部分无 problem |
| 某场景执行失败 | 仍含该场景 | 有该场景行但 failed | 报执行失败，不报缺场景 |
| 配置缺失/为空 | 无法确定 | — | fail closed |

### 45.10 报告口径统一

阶段报告 `phase3A3_2_3_4_1_1_audit_atomicity_fix.md` 修正了三处不一致：

1. 测试总数统一为最终实际执行的 **688 passed / 0 failed / 0 skipped**
2. Sparse 端到端结论统一为「已用真实引擎端到端验证」，
   删除此前「部分通过 / 真实端到端未跑」的过时描述
3. 验收表补入 `test_sparse_success_path_end_to_end` 的实测证据

并在 §10.3 明确标注：全部结果为本会话本地执行，非 ChatGPT 独立验证。

## 46. 阶段3A.3.2.3.5 历史回测与验证记录重放候选清点

本阶段**只清点，不重放**。未执行任何历史回测或验证重放，
未修改任何历史记录、策略、撮合、会计、指标算法或行情数据。

### 46.1 总量与分类

| 分类 | backtest | validation | 合计 |
| --- | ---: | ---: | ---: |
| `current_formal` | 1 | 14 | **15** |
| `replayed` | 1 | 2 | **3** |
| `legacy_replayable` | 1 | 35 | **36** |
| `non_replayable` | 9 | 0 | **9** |
| `failed_attempt` | 0 | 3 | **3** |
| **合计** | **12** | **54** | **66** |

`failed_attempt` 是呈现层新增的分类，不新增数据库字段、不新增代码常量——
只是把「源记录自己就失败了」从 `non_replayable` 里拆出来单独统计。

### 46.2 35 条 legacy 实为 9 个唯一配置

按 `config_hash` 去重后只有 9 组，其余是同一配置的重复执行：

| 组 | config_hash | 条数 | 代码数 | 网格 |
| ---: | --- | ---: | ---: | --- |
| G1 | `b6b1babace517bdc` | 18 | 6 | 7 档 |
| G2 | `b1de1d7323a8a35d` | 5 | 6 | 3 档 |
| G3 | `177a329b6fd72cec` | 5 | 6 | 3 档 |
| G4 | `86e4b4e8bac296ad` | 2 | 6 | 7 档 |
| G5 | `4457e246afad6e79` | 1 | 41 | 7 档 |
| G6 | `11ce7469245afab0` | 1 | 41 | 7 档 |
| G7 | `9c245d882cb1cc72` | 1 | 6 | 7 档 |
| G8 | `88d40b3069c50f0a` | 1 | 6 | 7 档 |
| G9 | `39bac25b0ec4ce91` | 1 | 6 | 7 档 |

按记录条数安排重放要跑 35 次；按唯一配置只要 9 次。

### 46.3 参数恢复方式

validation 的参数**只存在于 `config_hash`**。恢复的唯一诚实做法是把候选参数
代入哈希函数，完全命中才算证明。哈希覆盖 28 个字段（`_VALIDATION_FIELDS_CURRENT`），
同时试历史的 26 字段集、`pool_mode` 的 `all`/`representative`、日期原值/月初值。

实测用 `build_validation_config()` 重建 9 组代表，**7 组可完全重建**；
G4/G5 两组走 historical 字段集，当前 `ValidationConfig` 多了
`regime_ma_window` / `min_validation_days` 两个新字段，重建哈希对不上——
参数本身已被证明，只是构造器无法复现旧哈希。

backtest 侧只有 `8412fc1cefb4437e` 可重放，因为它的 `params_source` 全部为
`recorded`，没有一个字段走默认值。

### 46.4 不可重放原因

9 条 backtest 全部缺 `strategy_param:ma_window` 或 `config:rebalance_tolerance`：
这些是 2024-01-02~2026-11-09 的短区间用户回测，策略参数写在当时的调用代码里、
没进 `config_json`。不根据「同期其他记录都用某个值」这类间接推断补值。

3 条 `failed_attempt`：两条是样本内无可用参数组合/手动中断，
一条（`397118a140c44f47`）是重放尝试本身失败（会计版本为 None）。

### 46.5 推荐第一批重放

| 优先级 | 记录 | 理由 |
| ---: | --- | --- |
| 1 | `8412fc1cefb4437e` | 唯一参数 100% `recorded` 的 backtest，1 只标的最快 |
| 2 | `b3f1e2c89ebc4b95`（G9） | 6 只池 7 档，hash 可完全重建，最干净的 legacy 样本 |
| 3 | `f9898c695b394808`（G4） | 验证「历史字段集重放」路径 |
| 4 | `c5589f7dcd1a4a5d`（G7） | 覆盖「短样本内」分支 |
| 5 | `838a58fa5f3b4025`（G8） | 覆盖「短样本外」分支 |
| 6 | `7d884a1a03d94915`（G1） | 18 条重复组代表 |

### 46.6 已重放的两条 P0 记录

`32aead3291734f91` → `03410886d1f64fa7`（1 次成功）
`c46fa37b932944c2` → `aad7935a2bac4cc4`（8 次成功尝试）

两条当前分类均为 `replayed`，不在待重放清单里。本轮**未重复执行**。

### 46.7 数据库前后对照

全部 16 张表行数 0 变化，`validation_runs` 内容指纹
`9c40fcbf2e7b010c65a2fa4b62313fe6`、`backtest_runs` 内容指纹
`449be0fda8b7c24ddca7f6a7ae6ac3b3`、行情指纹 `d54727c0…` 前后一致，
`PRAGMA integrity_check` ok。

## 47. 阶段3A.3.2.3.6 第一批历史记录受控重放

**本轮中途暂停。** 计划 5 条，完成 2 条，剩余 3 条因发现两个代码层面缺陷而停止。

### 47.1 执行结果

| source_id | 类型 | attempt | 新记录 | status |
| --- | --- | --- | --- | --- |
| `8412fc1cefb4437e` | backtest | `2ecb1651d5a3473a` | `6d4045e45b5f4e0d` | success |
| `b3f1e2c89ebc4b95` | validation G9 | `b1240a8c3d2847a0` | `4d5da66a81da4d52` | success |
| `c5589f7dcd1a4a5d` | validation G7 | — | — | 未执行 |
| `838a58fa5f3b4025` | validation G8 | — | — | 未执行 |
| `7d884a1a03d94915` | validation G1 | — | — | 未执行 |

两条均 `force=False`，源记录 `input_hash` 前后未变，行情与公司行为指纹未变。

### 47.2 两个代码缺陷

**缺陷 A：`replay_backtest()` 不落公司行为明细**

`app/replay/runner.py` 第 203 行 `BacktestEngine(config, strategy, db_path=db_path)`
默认 `db_path=None`，引擎内 `if self.db_path is not None` 守卫使明细不写；
但 `save_result()` 用 `db_path=None` 走 `settings.database_path` 落库了。
结果：记录落库、明细为空。

实测 `6d4045e45b5f4e0d` 的 notes 写「已应用 3 条事件」，
但 `corporate_action_applications` / `dividend_receivables` 均 0 行。

**缺陷 B：`_build_regime_payload()` 缺存在性凭证（高危）**

`app/validation/runner.py` 第 694-699 行直接调 `audit.register_backtest()`，
未先 `register_run_evidence()`。3A.3.2.3.4.1（提交 `5a4af82`，2026-11-17 09:15:30）
给 `register_backtest()` 加了凭证闸门，导致此路径抛 `AuditError`，
被外层 `except` 吞掉，regime 四项统计全部 `unavailable`。

时间线证据：最后一次成功登记 `regime_grouping` 是 2026-11-16 **16:10:40**，
早于闸门上线时间。**即闸门上线后所有新 validation 重放都会丢失 regime 数据。**

这是 3A.3.2.3.4.1 引入的回归，不是本阶段造成的。

### 47.3 绩效对照

**backtest `8412fc1cefb4437e`**

| 指标 | 源 | 新 | 差异 |
| --- | ---: | ---: | ---: |
| total_return | 0.197338 | 0.278426 | +0.081088 |
| cagr | 0.068192 | 0.094140 | +0.025948 |
| max_drawdown | -0.201356 | -0.190868 | +0.010488 |

差异 `0.081088 × 1,000,000 = 81,088.00` 元，与三次分红合计**精确相等**，
是两阶段分红口径差异，不是计算错误。

**validation G9 `b3f1e2c89ebc4b95`**

| 指标 | 源 | 新 | 差异 |
| --- | ---: | ---: | ---: |
| IS total_return | 0.041007 | 0.041007 | **0** |
| IS cagr | 0.010517 | 0.010517 | **0** |
| IS max_drawdown | -0.198785 | -0.198785 | **0** |
| OOS total_return | 0.178324 | 0.181437 | +0.003113 |
| OOS cagr | 0.097151 | 0.098787 | +0.001636 |
| OOS max_drawdown | -0.170868 | -0.168672 | +0.002195 |

样本内**完全一致**，样本外差 0.31% 来自分红口径。

### 47.4 G1 专项：同 config_hash 不同 input_hash

G9 已验证这一判断：`config_hash` 完全相同（`39bac25b0ec4ce91`），
但 `input_hash` 从 `451bdcc990343464` 变为 `a8669b514793eab7`。
`config_hash` 只覆盖 28 个验证参数，`input_hash` 还覆盖实际数据
（行情快照、指标版本、公司行为事件集）。

G1（`7d884a1a03d94915`，`config_hash=b6b1babace517bdc`，源 `input_hash=3e064b6673929193`）
未执行，执行时需照此记录。

### 47.5 数据库对照

| 表 | 前 | 后 | 变化 |
| --- | ---: | ---: | ---: |
| `backtest_runs` | 12 | 64 | +52 |
| `validation_runs` | 54 | 55 | +1 |
| `replay_attempts` | 11 | 13 | +2 |
| `validation_backtest_runs` | 361 | 412 | +51 |
| `validation_regime_stats` | 28 | 32 | +4 |
| `corporate_actions` | 166 | 166 | 0 |
| `corporate_action_versions` | 704 | 704 | 0 |
| `etf_daily_prices` | 116,609 | 116,609 | 0 |

`integrity_check` ok，行情指纹 `d54727c0…` 未变，全量 pytest **688 passed**。

### 47.6 待验收决定

1. 缺陷 A / B 是否现在修（各 2~3 行最小改动）
2. 已产生的两条记录如何处置（保留 / 删除重跑 / 保留并标注）
3. `audit_completeness` 判 `incomplete` 是否可接受
4. 剩余 3 条是否等修复后再跑（建议如此）

## 48. 阶段3A.3.2.3.6.1 修复重放审计缺陷并重新执行前两条记录

### 48.1 两个缺陷的修复

**缺陷 A：独立回测明细不落库**

`replay_backtest()` 把 `db_path=None` 传给引擎，引擎内
`if self.db_path is not None` 守卫使明细不写，但 `save_result()`
走默认库路径落库了。

新增 `effective_db_path()`：`db_path` 非空用它、为空用
`settings.database_path`，返回值保持 `Path`。
`replay_backtest()` 与 `replay_validation()` 入口各解析一次，
引擎、保存、标记、attempt 登记全部复用。

**缺陷 B：regime 回测缺存在性凭证**

`_build_regime_payload()` 直接调 `register_backtest()` 而没先
`register_run_evidence()`，撞上 3A.3.2.3.4.1 加的凭证闸门，
抛出的 `AuditError` 被外层 `except` 吞掉。

修复：登记顺序改为 `执行 → _require_formal → register_run_evidence
→ register_backtest`；`db_path` 空时同样解析成正式库；
外层 `except` 遇到 `AuditError` 一律向外抛，不再降级。

### 48.2 追加式失效机制

新增 `replay_supersessions` 表：

| 字段 | 含义 |
| --- | --- |
| `superseded_attempt_id` | 旧 attempt（唯一索引，不可重复失效） |
| `superseded_record_id` | 旧结果 |
| `replacement_attempt_id` / `replacement_record_id` | 新 attempt / 新结果 |
| `reason` | `missing_corporate_action_details` / `regime_audit_incomplete` |

旧 attempt 行**全字段原样保留**（`status` 仍是当年真实的 `success`），
只新增关系记录。`find_success()` / `success_map()` 增加
`NOT EXISTS replay_supersessions` 排除，被取代的旧结果不再算成功重放，
重新执行不需要 `force`。

### 48.3 重新执行结果

| 项 | Backtest | Validation G9 |
| --- | --- | --- |
| 旧 attempt | `2ecb1651d5a3473a` | `b1240a8c3d2847a0` |
| 旧结果 | `6d4045e45b5f4e0d` | `4d5da66a81da4d52` |
| 失效原因 | `missing_corporate_action_details` | `regime_audit_incomplete` |
| 新 attempt | `44e6f14f4185417d` | `8a05c4fa1e4d456b` |
| 新结果 | `a56ffe74f3ca48fb` | `c5505f0145e34bbd` |
| accounting_version | `ca-v2-receivable` | `ca-v2-receivable` |
| accounting_basis | `formal_receivable` | `formal_receivable` |
| formal_valuation | `True` | `True` |
| status | success | success |
| audit_trace | 不适用（standalone） | **complete** |
| audit_completeness | 不适用 | **True**，problems `[]` |

**Backtest 明细（修复目标）**

| action_id | ex_date | shares_at_ex | cash_per_share | amount | status |
| ---: | --- | ---: | ---: | ---: | --- |
| 126 | 2024-01-18 | 289,600 | 0.069 | 19,982.40 | settled |
| 140 | 2025-06-18 | 289,600 | 0.088 | 25,484.80 | settled |
| 150 | 2026-01-19 | 289,600 | 0.123 | 35,620.80 | settled |

合计 81,088.00 元，与 `total_return` 增量 `0.081088` 精确对应。

**Validation regime 统计（修复目标）**

| regime | status | samples | cumulative_return |
| --- | --- | ---: | ---: |
| bull | **ok** | 323 | +0.422566 |
| bear | **ok** | 26 | -0.022231 |
| range | **ok** | 97 | -0.150620 |
| unclassified | insufficient_sample | 0 | — |

### 48.4 绩效对照

| 指标 | Backtest 源 | Backtest 新 | G9 源 | G9 新 |
| --- | ---: | ---: | ---: | ---: |
| IS/OOS total_return | 0.197338 | **0.278426** | 0.178324 | **0.181437** |
| cagr | 0.068192 | **0.094140** | 0.097151 | **0.098787** |
| max_drawdown | -0.201356 | **-0.190868** | -0.170868 | **-0.168672** |

新轮与旧轮绩效**完全一致**——两个缺陷都只影响审计证据，不影响绩效计算。

G9 的 `config_hash` 相同（`39bac25b0ec4ce91`）但 `input_hash` 不同
（`451bdcc990343464` → `a8669b514793eab7`），再次印证
「同 config_hash 不代表同数据证据」。

### 48.5 数据库对照

| 表 | 前 | 后 | 变化 |
| --- | ---: | ---: | ---: |
| `backtest_runs` | 64 | 117 | +53 |
| `validation_runs` | 55 | 56 | +1 |
| `replay_attempts` | 13 | 15 | +2 |
| `replay_supersessions` | 新建 | 2 | +2 |
| `validation_backtest_runs` | 412 | 464 | +52 |
| `validation_regime_stats` | 32 | 36 | +4 |
| `corporate_action_applications` | 6,910 | 7,194 | +284 |
| `dividend_receivables` | 3,274 | 3,529 | +255 |
| `corporate_actions` | 166 | 166 | **0** |
| `corporate_action_versions` | 704 | 704 | **0** |
| `etf_daily_prices` | 116,609 | 116,609 | **0** |

`integrity_check` ok，行情指纹 `d54727c0…` 未变，
源记录 `input_hash` 未变。

### 48.6 测试

| 项 | 结果 |
| --- | ---: |
| 专项测试 | 14 passed（16.48 秒） |
| 全量 pytest | **702 passed** / 0 failed / 0 skipped（269.53 秒） |
| API smoke | `SMOKE_FAILED: 无` |
| AppTest | 两页 exception 0 / error 0 |

基线 688 → 702（+14）。

## 49. 阶段3A.3.2.3.6.2 第二批历史记录受控重放

执行 G7 / G8 / G1 三条，全部成功。未执行 G2/G3/G4/G5，未进入 3A.3.3/3B。

### 49.1 结果

| source_id | 分组 | attempt | 新记录 | status |
| --- | --- | --- | --- | --- |
| `c5589f7dcd1a4a5d` | G7 | `2d304aa91fd44f31` | `a52af390b0d5442e` | success |
| `838a58fa5f3b4025` | G8 | `1da2e9ecc4b14698` | `c68bf2840ebf4f08` | success |
| `7d884a1a03d94915` | G1 | `7f9a7886abfc4454` | `ea21b9d50eb14c74` | success |

全部 `force=False`，`accounting_version=ca-v2-receivable`、
`accounting_basis=formal_receivable`、`formal_valuation=True`、
`audit_trace=complete`、`audit_completeness=True`（problems `[]`）。

### 49.2 过程异常

G8 第一次执行被 shell 300 秒上限中断，留下 running attempt
`37e017afb1514fd4` 与孤儿记录 `371b81de27e64f21`。
未删除任何行：attempt 标 `failed`、孤儿记录标 `failed` 并写明原因，
随后重新执行成功。

### 49.3 参数忠实恢复

| 组 | 关键差异 | 是否保留 |
| --- | --- | --- |
| G7 | IS 起点 `2021-06-01`（晚 5 个月） | ✅ |
| G8 | OOS 起点 `2025-06-03`（晚 5 个月） | ✅ |
| G1 | 与 G9 同参数，仅历史更早 | ✅ |

三组的 ETF 池、MA 网格、WF 配置、成本参数、指标版本均逐项比对一致。

### 49.4 G1 的 config_hash 与 input_hash

| 项 | 值 |
| --- | --- |
| source `config_hash` | `b6b1babace517bdc` |
| replay `config_hash` | `b6b1babace517bdc`（**相同**） |
| source `input_hash` | `3e064b6673929193` |
| replay `input_hash` | `68433a7834546dbd`（**不同**） |

差异来源：源记录不应用公司行为（应用数 0），新记录应用 151 次。
行情指纹、指标版本、快照均相同。即**同参数、不同会计口径**，
不能宣称数据证据相同。

### 49.5 绩效差异归因

三组呈现同一模式：IS 网格里 **MA250 一档**的收益被分红口径放大最多
（G7 +0.2597、G8 +0.2006、G1 +0.1889），其余档位差异均在 ±0.02 内。

| 组 | MA250 源 | MA250 新 | 最优参数变化 |
| --- | ---: | ---: | --- |
| G7 | -0.209494 | +0.050236 | MA60 → MA250 |
| G8 | -0.159543 | +0.041007 | MA60 → MA250 |
| G1 | -0.147898 | +0.041007 | MA60 → MA250 |

MA250 持仓周期最长，2021-01~2024-12 期间经历的除息事件最多，
旧口径不确认分红、新口径全额确认，差距被持仓时长放大。
最优参数一致切换是**分红口径改变 IS 排序**的结果，不是策略逻辑变化。

### 49.6 数据库对照

| 表 | 前 | 后 | 变化 |
| --- | ---: | ---: | ---: |
| `backtest_runs` | 117 | 307 | +190 |
| `validation_runs` | 56 | 60 | +4 |
| `replay_attempts` | 15 | 19 | +4 |
| `validation_backtest_runs` | 464 | 654 | +190 |
| `validation_regime_stats` | 36 | 48 | +12 |
| `corporate_action_applications` | 7,194 | 7,650 | +456 |
| `dividend_receivables` | 3,529 | 3,934 | +405 |
| `corporate_actions` | 166 | 166 | **0** |
| `corporate_action_versions` | 704 | 704 | **0** |
| `etf_daily_prices` | 116,609 | 116,609 | **0** |

`integrity_check` ok，行情指纹 `d54727c0…` 未变，三条源记录 `input_hash` 未变。

### 49.7 测试

| 项 | 结果 |
| --- | ---: |
| 重放专项 | 177 passed（171.79 秒） |
| 全量 pytest | **702 passed** / 0 failed / 0 skipped（304.94 秒） |
| API smoke | `SMOKE_FAILED: 无` |
| AppTest | 两页 exception 0 / error 0 |

## 50. 阶段3A 最终收口：剩余历史配置重放

处理 G2 / G3 / G4 / G5 四个配置组的代表记录，**阶段3A 正式冻结**。

### 50.1 四个配置组

| 组 | config_hash | 源条数 | 代码数 | 网格 | 字段集 | 代表 |
| ---: | --- | ---: | ---: | --- | --- | --- |
| G2 | `b1de1d7323a8a35d` | 5 | 6 | 3 档 | current 28 | `c84356bd50ca4bb5` |
| G3 | `177a329b6fd72cec` | 5 | 6 | 3 档 | current 28 | `2b21ca9b2c434444` |
| G4 | `86e4b4e8bac296ad` | 2 | 6 | 7 档 | historical 26 | `f9898c695b394808` |
| G5 | `4457e246afad6e79` | 1 | 41 | 7 档 | historical 26 | `e725034e46ff47e5` |

每组只重放 1 条代表，其余同配置记录标记为「同配置组，未重复重放」。

### 50.2 重放结果

| 组 | attempt | 新记录 | 新 config_hash | status |
| ---: | --- | --- | --- | --- |
| G2 | `fdb0e78069284fb1` | `bde29001291a456b` | `b1de1d7323a8a35d`（同源） | success |
| G3 | `ce071b8979b5427c` | `df2f811d52d04155` | `177a329b6fd72cec`（同源） | success |
| G4 | `3508b65202a64aea` | `93c170ca1402419f` | `b6b1babace517bdc`（legacy 映射） | success |
| G5 | `3337840f523d49e6` | `1c5832e27c6c4f3c` | `11ce7469245afab0`（legacy 映射） | success |

四条全部 `ca-v2-receivable` / `formal_receivable` / `True`、
`audit_trace=complete`、`audit_completeness=True`（problems `[]`）、`force=False`。

### 50.3 G4/G5 的 legacy 兼容映射

两条记录创建于 2026-11-11 14:29 / 14:39，而 `regime_ma_window` 与
`min_validation_days` 两个字段由提交 `66db49e`（2026-11-11 16:47:29）引入。

旧版虽未把两者暴露成 `ValidationConfig` 字段，但**行为上一直在用**：

| 字段 | 旧版等价来源 | 值 |
| --- | --- | ---: |
| `regime_ma_window` | `regime.py::build_regime_series(ma_window=REGIME_MA_WINDOW)` | 250 |
| `min_validation_days` | `split.py::split_time_range(min_days=MIN_VALIDATION_TRADING_DAYS)` | 120 |

这是**情况 B**：字段本身不存在，但有可追溯的等价来源，不是「无法证明」。

**不声称字节级相同**：`schema_version` 从 `historical 26` 变为 `current 28`，
`config_hash` 重新生成（`86e4b4e8bac296ad` → `b6b1babace517bdc`、
`4457e246afad6e79` → `11ce7469245afab0`），报告标注为 legacy-compatible replay。

**等价性反向验证**：G4 重建后参数与已重放的 G1 **完全相同**
（`as_dict()` 相等、hash 同为 `b6b1babace517bdc`）；
G5 重建后与 `b6e1155d19ba4b6a` **完全相同**。
两条独立路径殊途同归，证明映射值选对了。

### 50.4 绩效差异

| 组 | 选参变化 | IS ret 源→新 | OOS ret 源→新 | 分红金额 |
| ---: | --- | --- | --- | ---: |
| G2 | MA60 未变 | -0.1000 → -0.0841 | +0.2243 → +0.1927 | 428,699.54 |
| G3 | MA30 未变 | -0.1649 → -0.1646 | +0.2191 → +0.2200 | 447,293.28 |
| G4 | MA60 → MA250 | -0.0853 → +0.0410 | +0.2144 → +0.1814 | 475,647.38 |
| G5 | MA250 未变 | -0.1456 → +0.1368 | +0.3071 → +0.2011 | 598,485.73 |

G3 差异在 0.04% 以内（与 G2 一样选参未变），是口径切换影响的**对照样本**；
G4 与第一批 G1 同参数，绩效完全一致；
G5 选参未变，差异纯来自分红（848 应用、598,485.73 元）。

### 50.5 阶段3A 最终分类

| 类别 | backtest | validation | 合计 |
| --- | ---: | ---: | ---: |
| `current_formal` | 3 | 23 | 26 |
| `replayed` | 2 | 10 | 12 |
| `legacy_replayable` | 0 | 27 | 27 |
| `non_replayable` | 9 | 0 | 9 |
| `failed_attempt` | 0 | 4 | 4 |
| **合计** | **14** | **64** | **78** |

27 条 `legacy_replayable` **不是待重放**，而是「配置组已被代表覆盖、
本身不重复执行」的最终态。验证：剩余 27 条里只有 1 条
（`5ec77faf42d64162`）的 hash 不在已重放组内，而它与 G4 代表参数完全相同。
**不存在未覆盖的新配置。**

### 50.6 剩余问题

**No remaining P0/P1 blockers.**

| 级别 | # | 内容 |
| --- | ---: | --- |
| P2 | 1 | 27 条 legacy 保持旧口径，不可与 current_formal 混用比较 |
| P2 | 2 | 9 条 backtest 永久 non_replayable（缺 `ma_window` / `rebalance_tolerance`） |
| P2 | 3 | 4 条 failed_attempt（源记录本身失败） |
| P2 | 4 | G4/G5 的 config_hash 与源不同（由 28 字段集生成） |

### 50.7 数据完整性

| 表 | 前 | 后 | 变化 |
| --- | ---: | ---: | ---: |
| `backtest_runs` | 307 | 507 | +200 |
| `validation_runs` | 60 | 64 | +4 |
| `replay_attempts` | 19 | 23 | +4 |
| `validation_backtest_runs` | 654 | 854 | +200 |
| `validation_regime_stats` | 48 | 64 | +16 |
| `corporate_action_applications` | 7,650 | 8,873 | +1,223 |
| `dividend_receivables` | 3,934 | 4,947 | +1,013 |
| `corporate_actions` | 166 | 166 | **0** |
| `corporate_action_versions` | 704 | 704 | **0** |
| `etf_daily_prices` | 116,609 | 116,609 | **0** |

`integrity_check` ok，行情指纹 `d54727c0…` 未变，
四条源记录 `input_hash` 未变，越界 source 为空。

### 50.8 封板

**PHASE 3A CLOSED**

下一阶段：3B-1 正式会计口径下的策略有效性基线验证。

## 51. 阶段3B-1 正式会计口径下的策略有效性基线研究

### 51.1 结论

**核心问题：现有 MA 趋势策略在正式会计口径下是否具有稳定、可重复、样本外可验证的超额收益？**

> **当前没有足够证据证明有效。** 证据等级 **C**（仅少数样本或特定区间有效，接近 D）。

四条决定性事实：

1. **IS 最优在 OOS 几乎不复现**：8 组唯一配置里 IS 最优有 6 组是 MA250，
   OOS 最优只有 2 组一致（25.0%）。OOS 最优是 MA30（5 次）、MA60（2 次）、
   MA120（1 次）——**MA250 从未在 OOS 排第一**。
2. **MA250 是边界效应**：MA120→MA250 在 IS 一律改善（+0.188~+0.240），
   OOS 一律退化（MA250 在 7 档里排 4~5 名）。**7/8** 的 IS 最优落在网格上限。
3. **跑不赢等权买入持有**：8 组唯一配置里跑赢 4 组、跑输 4 组，
   超额区间 -2.30%~+5.42%、**中位数只有 +0.37%**；而交易成本是 B&H 的 **13~112 倍**。
4. **收益集中在单窗口**：8 组唯一配置里 **6/8** 在扣掉最好窗口后合计为负。

正面证据（不隐瞒）：bull 环境下策略确实赚钱（+30.8%~+55.1%），回撤控制
部分优于 B&H；G7 超额 +5.42% 是真实的；分红贡献占 OOS 收益 6.4%~19.5%。
但这些都依附于特定配置 + 特定区间，无跨配置稳定性。

### 51.2 研究数据来源（三层计数）

> **v2 修正**：原版汇总函数误用 9 条正式记录（含 G1/G4 完全重复），
> 已改为按唯一配置统计。逐条审计明细全部保留。

| 层级 | 数量 |
| --- | ---: |
| 正式记录 | 9 |
| 唯一配置（`config_hash` + `input_hash`） | **8** |
| 唯一 OOS 结果指纹 | **6** |
| 统计独立样本数 | **`not_estimable`** |

**唯一配置数与结果指纹数都不是独立样本数。** 全部记录共享同一行情库、
同一策略代码、同一成本参数、同一会计口径，主要 OOS 区间基本相同
（2025-01-02~2026-11-09），无法据此严谨定义独立样本量。

G1 与 G4 的 `config_hash`（`b6b1babace517bdc`）和 `input_hash`
（`68433a7834546dbd`）完全相同（G4 是 legacy-compatible 映射，重建后即同一配置），
汇总时只算一组；G4 的逐条明细仍完整保留。

唯一被排除的记录是 `P0a`（`03410886d1f64fa7`）——正式口径 + success，
但 `validation_backtest_runs` 一行明细都没有，无法核验公司行为与分红应收。
它与 `G5` 的 `config_hash`/`input_hash` 完全相同，同配置已由 `G5` 覆盖。

### 51.3 关键数据（8 组唯一配置）

| 配置 | 池 | IS 最优 | OOS 最优 | OOS 收益 | 等权 B&H | 超额 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| G1（含 G4） | 6 | MA250 | MA30 | +0.1814 | +0.1933 | -1.18% |
| G2 | 6 | MA60 | MA60 | +0.1927 | +0.1933 | -0.06% |
| G3 | 6 | MA30 | MA30 | +0.2200 | +0.1933 | **+2.67%** |
| G5 | 41 | MA250 | MA30 | +0.2011 | +0.1931 | **+0.81%** |
| G7 | 6 | MA250 | MA60 | +0.2410 | +0.1868 | **+5.42%** |
| G8 | 6 | MA250 | MA120 | +0.0778 | +0.1008 | -2.30% |
| G9 | 6 | MA250 | MA30 | +0.1814 | +0.1933 | -1.18% |
| P0b | 41 | MA250 | MA30 | +0.2011 | +0.1931 | **+0.81%** |

汇总：**跑赢 4/8，跑输 4/8；超额区间 -2.30% ~ +5.42%，中位数 +0.37%**。

参数统计（8 组唯一配置）：

| 指标 | 数值 |
| --- | ---: |
| IS 最优为 MA250 | **6/8（75.0%）** |
| IS 最优落在网格边界 | **7/8（87.5%）** |
| IS/OOS 最优一致 | **2/8（25.0%）** |
| OOS 最优 MA30 / MA60 / MA120 | **5 / 2 / 1** |
| MA250 在 OOS 排名第一 | **0** |

### 51.4 分红与成本

分红只取 `run_role='out_of_sample'` 的已结清金额（不用全角色合计，避免重复计算）。

| 项 | 数值 |
| --- | --- |
| 分红/初始资金 | 1.28%~1.66% |
| 分红占 OOS 收益 | 6.4%~19.5% |
| MA 成本/初始资金 | 0.95%~8.34% |
| B&H 成本/初始资金 | 0.07% |
| 成本倍数 | 13~112× |

分红确实系统性地改变了 IS 参数排名：持仓越久→跨除息事件越多→确认分红越多，
把 IS 最优从 MA60 推到 MA250。这是会计口径的算术结果，不是信号质量。

### 51.5 局限

OOS 逐参数表现由脚本只读重算（不写库），属研究数据不是正式验证；
沪深300/中证500 用 ETF 代理且只在 41 只池可用（6 只池标 unavailable）；
OOS 仅约 22 个月；bear regime 只有 26 天样本。
**统计独立样本数不可估计（`not_estimable`）**，因此**不做统计显著性检验**。

### 51.6 工程边界

全程只读：`db_path=None` 调用引擎，引擎在此时不写公司行为/应收明细。
未修改策略/撮合/会计/公司行为/成本/历史记录；未新增数据库表；
未生成新最优参数、未写回策略配置。

全部表行数前后 **变化为 0**，`integrity_check` ok，行情指纹未变。
全量测试 **723 passed / 0 failed / 0 skipped**（251.02 秒）
= 封板 702 + 本轮新增 21 项研究专项测试；工程代码零改动。

### 51.7 下一阶段假设（仅记录，本阶段不验证）

| 编号 | 假设 |
| --- | --- |
| H1 | MA250 优势来自分红会计的持仓时长效应，扩展网格到 MA300+ 只会放大 IS 假象 |
| H2 | 收益主要由 bull 的 beta 暴露驱动，range/bear 无防守能力 |
| H3 | 单窗口集中度说明策略依赖特定行情（2025 年中） |
| H4 | 交易成本是拖累主因，降频或加换手惩罚可改善净收益 |
| H5 | 41 只大池分散度优于 6 只小池，但被更高分红处理复杂度抵消 |

### 51.8 产物

| 项 | 路径 |
| --- | --- |
| 研究脚本 | `scripts/research_3b1_baseline.py` |
| 报告 | `reports/phase3B1_strategy_effectiveness_baseline.md` |
| 机器可读结果 | `reports/phase3B1_strategy_effectiveness_baseline.json` |
| 图表 | `reports/figures/fig1~fig6_*.png`（6 张，均基于 8 组唯一配置） |
| 专项测试 | `tests/test_research_3b1_dedup.py`（21 项） |

## 52. 阶段3B-2 新策略候选研究与第一轮验证

### 52.1 结论

> **三个候选全部不合格，不建议进入下一轮正式验证。**

不是因为没有收益——候选B/C 的 OOS 净收益 **+44.21%** 确实很高。
而是因为收益的来源和稳定性都不成立：

1. **回撤严重恶化**：候选B/C OOS 最大回撤 **-42.31%**，等权 B&H 是 -30.66%，
   现有 MA 策略只有 **-17.82%**。承担近 2.4 倍深度回撤，不满足「回撤不能明显恶化」。
2. **收益集中在单窗口**：12 个半年窗口里最好一个（2026 上半年）+59.98%
   **大于全部窗口之和**（+49.99%），扣掉后其余 11 个窗口合计 **亏损 -9.99%**。
3. **IS 全线为负**：三个候选 IS 分别是 -28.04%、-18.04%、-18.07%。
   规则不是「历史上有效」，是「某段行情里爆发」。

| 候选 | OOS 收益 | 相对 B&H 超额 | 最大回撤 | 判定 |
| --- | ---: | ---: | ---: | --- |
| A 相对强弱轮动 | +21.32% | -2.42% | -51.36% | ❌ |
| B 动量+趋势过滤 | +44.21% | +20.48% | -42.31% | ❌ |
| C 攻守切换 | +44.22% | +20.49% | -42.31% | ❌ |

### 52.2 候选之间的真实差异

**A vs B（MA200 趋势过滤确实有用）**：

| 指标 | A（无过滤） | B（有过滤） |
| --- | ---: | ---: |
| OOS 收益 | +21.32% | **+44.21%** |
| OOS 回撤 | -51.36% | **-42.31%** |
| OOS Sharpe | 0.478 | **0.745** |

趋势过滤让收益翻倍、回撤改善 9 个百分点。这是本阶段唯一可认为「有效」的机制。
但 B 的回撤仍远差于 B&H 的 -30.66%，「改善」只是相对 A。

**B vs C（防守切换几乎没起作用）**：OOS 收益差仅 **0.0096%**，
防守只在 2022-11、2024-01 触发 2 次。**C 不是独立策略，是 B 加了几乎不触发的保险。**
把它当「三个独立候选」会高估证据强度。

### 52.3 ETF 池审计与幸存者偏差

46 只池按 `fund_type` 分四类：股票 27、海外股票 8、固收 7、黄金/其他 4。

**固定 universe = 「2021-01-04 前已上市」∩「指数型-股票」= 23 只。**
排除的 4 只晚上市标的：`159852`(2021-02-09)、`515230`(2021-03-02)、
`516010`(2021-03-05)、`588200`(2022-10-26)。

**幸存者偏差无法消除**：数据库只有当前存续的 46 只，没有退市 ETF 历史。
研究只能避免「把未来上市标的提前纳入历史排名」，不能声称已消除幸存者偏差。

防守标的选择 `511010` 国债ETF国泰（`fund_type=指数型-固收`，覆盖 2021-01-04 起），
满足「历史覆盖充分、分类明确」的条件，因此候选C 用它而非只能持现金。

### 52.4 固定规则（未做任何参数搜索）

| 项 | 值 |
| --- | --- |
| 调仓 | 每月首个交易日收盘出信号，次一交易日开盘成交 |
| 动量窗口 | 120 交易日（≈6 个月） |
| 选股数 | 前 3 名等权 |
| 趋势过滤 | MA200 |
| 防守标的 | `511010` |
| IS / OOS | 2021-01-04~2024-12-31 / 2025-01-02~2026-11-09（沿用 3B-1） |

120 / 3 / 200 全是常量，不是从候选值里挑的。**不存在 IS 参数过拟合**，
但也没有「换参数会不会更好」的结论。

### 52.5 基准对照（OOS，同一 23 只池）

| 策略 | 总收益 | Sharpe | 最大回撤 | 换手率 | 成本 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 候选A | +21.32% | 0.478 | -51.36% | 48.05 | 9,189 |
| 候选B | +44.21% | 0.745 | -42.31% | 41.04 | 9,812 |
| 候选C | +44.22% | 0.745 | -42.31% | 44.25 | 9,809 |
| 等权 B&H | +23.73% | 0.631 | -30.66% | 0 | 0 |
| 等权 B&H+国债 | +22.52% | 0.624 | -29.56% | 0 | 0 |
| 现有 MA(60) | +25.37% | 0.680 | **-17.82%** | 291.29 | 54,568 |
| 沪深300 | +10.29% | 0.444 | -18.34% | 0 | 0 |
| 中证500 | +22.29% | 0.599 | -29.03% | 0 | 0 |
| 现金 | 0.00% | n/a | 0.00% | 0 | 0 |

五个基准全部可用（共用同一 23 只池），**没有需要标 unavailable 的项**。

### 52.6 分红与成本

**分红口径**：按「应收余额正向增量之和」计算，不用期末余额冒充总额。
除息日确认计入、发放日转现金不重复计。专项测试用手工序列验证过。

**关键事实**：候选A/B/C 的 OOS 分红**全部为 0**。
原因不是算错，是标的本身不分红——23 只股票类里只有 7 只有分红记录，
而动量策略长期持有 `515880`/`512480`/`159995` 等科技类，2021 年后从无分红。
唯一吃到分红的是候选A 在 2023-01 / 2024-01 持有 `510880`，合计 20,655.60 元，全在 IS。

**成本是本阶段最扎实的正面发现**：月度调仓成本约 2.8~3.0 万，
是现有 MA 策略（17.91 万）的 **16%**，降幅 84%。
但成本优势没转化为净值优势——因为回撤恶化了 2.4 倍。

### 52.7 市场环境

| 策略 | bull（324 天） | range（97 天） | bear（26 天） |
| --- | ---: | ---: | ---: |
| 候选B/C | +127.50% | -29.65% | -13.59% |
| 等权 B&H | +75.25% | -19.09% | -15.24% |
| 现有 MA(60) | +57.87% | -21.75% | -1.72% |
| 沪深300 | +36.16% | -14.57% | -7.67% |

**所有策略都是 bull 大赚、range/bear 全亏。** 候选在 bull 赚得更多、
在 range 也亏得更多——**这是把 beta 放大，不是改善择时**。
bear 仅 26 天样本，置信度极低。

### 52.8 局限

幸存者偏差无法消除；OOS 仅约 22 个月；bear 仅 26 天样本；
沪深300/中证500 用 ETF 代理；候选B/C 差异极小不算独立证据；
23 只池只有 7 只有分红；规则固定未搜索（无法判断更优参数）；
回测 `db_path=None` 不写库，结果是研究数据不构成正式 validation 结论。

### 52.9 工程边界

候选策略**只存在于研究脚本**，未写入 `app/backtest/strategies/`（专项测试断言）。
未修改 MA 策略、引擎、会计、公司行为、撮合、成本；未写入正式 validation 记录；
未新增数据库表；未接入券商；未根据 OOS 优化参数。

全部表行数前后 **变化为 0**，`integrity_check` ok，行情指纹 `d54727c0…` 未变。
全量测试 **747 passed / 0 failed / 0 skipped**（295.55 秒）
= 3B-1.1 的 723 + 本阶段 24 项专项测试；工程代码零改动。

### 52.10 下一阶段建议（仅建议，未执行）

| 编号 | 建议 |
| --- | --- |
| S1 | 重点不是提高收益，而是**控制回撤** |
| S2 | 趋势过滤（MA200）值得保留到后续研究 |
| S3 | 防守切换需要更敏感的条件（C 只触发 2 次等于没做） |
| S4 | 单窗口依赖必须解决（最好窗口 > 全部窗口合计） |
| S5 | 幸存者偏差需补历史退市名单才能根本改善 |

### 52.11 产物

| 项 | 路径 |
| --- | --- |
| 研究脚本 | `scripts/research_3b2_candidates.py` |
| 报告 | `reports/phase3B2_strategy_candidates.md` |
| 机器可读结果 | `reports/phase3B2_strategy_candidates.json` |
| 图表 | `reports/figures/fig3b2_1~6_*.png`（6 张） |
| 专项测试 | `tests/test_research_3b2_candidates.py`（24 项） |

## 53. 阶段3B-3 支付宝场外基金数据体系可行性审计

### 53.1 结论

> **场外基金的净值数据完全可用，但「能不能买、卖的时候扣多少、会不会清盘」
> 这三件事现在都没有可靠数据源——所以可以做净值分析，还不能做真实回测。**

| 层次 | 状态 |
| --- | --- |
| **历史净值**（最关键） | ✅ **完全可用**，单只基金可取成立至今全历史 |
| **基本信息/分红/拆分** | ✅ 可用 |
| **清盘基金名录** | ❌ **完全没有**，`survivorship_bias_unresolved` |
| **赎回费阶梯/持有期规则/基金转换** | ❌ **完全没有结构化数据** |
| **支付宝可购买状态** | ⚠️ **unknown**，无可信证据 |

### 53.2 数据源审计（14 个接口全部成功）

| 接口 | 行数 | 稳定性 |
| --- | ---: | --- |
| `fund_name_em` 全量代码表 | 28,380 | 中 |
| `fund_open_fund_daily_em` 当日净值 | 24,398 | 中 |
| `fund_purchase_em` 申购状态限额 | 28,075 | 中 |
| `fund_manager_em` 基金经理 | 36,935 | 中 |
| `fund_scale_open_sina` 开放规模 | 7,222 | 中 |
| `fund_scale_close_sina` 封闭规模 | 209 | 中 |
| `fund_hold_structure_em` 持有人结构 | 45 | 中 |
| `fund_open_fund_info_em` 单位净值 | 4,220 | **高** |
| `fund_open_fund_info_em` 累计净值 | 4,220 | **高** |
| `fund_open_fund_info_em` 分红送配 | 3 | **高** |
| `fund_open_fund_info_em` 拆分详情 | 9 | **高** |
| `fund_money_fund_info_em` 货币收益 | 4,919 | **高** |
| `fund_individual_basic_info_xq` 基本信息 | 14 | 中 |
| `fund_portfolio_hold_em` 季度持仓 | 137 | 中 |

全部公开、无需认证。但「本次可访问」不等于「长期稳定」，每行都记录稳定性依据。

### 53.3 12 只样本基金验证（全部通过）

| 代码 | 类别 | 名称 | 净值行数 | 单位净值 | 累计净值 | 分红 | 拆分 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `000051` | 宽基指数 | 华夏沪深300ETF联接A | 4,220 | 1.5402 | 1.5402 | 0 | 0 |
| `110020` | 宽基指数 | 易方达沪深300ETF联接A | 4,186 | 1.6526 | 1.6526 | 0 | 0 |
| `161725` | 行业指数 | 招商中证白酒A | 2,794 | 0.5791 | 2.2952 | 3 | 9 |
| `012414` | 行业指数 | 招商中证白酒C | 1,338 | 0.5760 | 0.6610 | 3 | 0 |
| `007300` | ETF联接 | 国联安半导体ETF联接A | 1,799 | 3.0432 | 3.0432 | 0 | 0 |
| `007301` | ETF联接 | 国联安半导体ETF联接C | 1,799 | 2.9802 | 2.9802 | 0 | 0 |
| `110022` | 主动权益 | 易方达消费行业 | 3,927 | 3.0100 | 3.0100 | 0 | 0 |
| `161005` | 主动权益 | 富国天惠成长A | 5,124 | 2.4727 | 5.5207 | 16 | 0 |
| `000478` | 指数增强 | 建信中证500增强A | 3,096 | 2.8419 | 2.8419 | 0 | 0 |
| `000015` | 债券 | 华夏纯债A | 3,310 | 1.2109 | 1.6015 | 9 | 0 |
| `000016` | 债券 | 华夏纯债C | 3,310 | 1.1968 | 1.5276 | 9 | 0 |
| `000198` | 货币 | 天弘余额宝货币 | 4,919 | （万份收益） | — | — | — |

### 53.4 关键验证发现

**1. 单位净值 vs 累计净值**：有分红的基金累计净值恒高于单位净值，差额随分红次数增加。
`161725` 单位净值 0.5791 但累计 2.2952——**只看单位净值会把 9 次份额折算误判成亏损 42%**。

**2. 每10份分红必须除以 10**：`每10份派现金0.2100元` → 每份 0.021 元。
若直接取第一个数字会把「10」当金额，每份恒为 1.0 元（差 10 倍）。此 bug 已用回归测试锁住。

**3. 净值跳变必须能归因**：样本 5 次跳变全部由拆分（3 次）或分红除息（2 次）解释，
未解释 = 0。归因不上的跳变才是数据异常。

**4. 分红接口会返回不完整列表**：实测 `000016` 一次 9 条、一次 5 条。
按内容取并集 + 记录 `fetch_stable`，直接采信单次会静默丢记录。

**5. 货币基金是另一套数据结构**：没有单位净值，用「每万份收益 + 7 日年化」；
雪球基本信息接口对它直接 `KeyError: 'data'`，必须走兜底。

### 53.5 幸存者偏差：survivorship_bias_unresolved

| 检查 | 结果 |
| --- | --- |
| `fund_name_em` 是否含清盘基金 | ❌ 28,380 条全是当前清单 |
| `fund_purchase_em` 是否有终止状态 | ❌ 取值只有 7 种，无终止类 |
| 专门的清盘基金接口 | ❌ 无 |
| `fund_scale_close_sina` 是清盘基金吗 | ❌ **不是**，是「封闭式基金」，极易误读 |

**特别警告**：`fund_scale_close_sina` 名字里有 `close`，209 行，看起来像清盘名录——
**实际是仍在运作的封闭式基金**。把它当清盘数据会得出完全错误的结论。

补充方案：①短期明确标注该限制；②中期从协会/证监会/天天基金清盘公告自建
`fund_lifecycle_events`；③长期建立「全量清单按日快照」机制，用差异反推清盘时点。

### 53.6 交易规则审计（10 条，8 条无数据源）

| ID | 规则 | 数据源 | 说明 |
| --- | --- | --- | --- |
| T1 | 15:00 截止时间 | ❌ | 行业通则，需人工核实 |
| T2 | 提交时间对应净值日 | ❌ | 同上 |
| T3 | 申购确认时间 | ❌ | 不能统一假设 T+1 |
| T4 | 赎回确认与到账 | ❌ | 到账受渠道影响 |
| T5 | 申购费及平台折扣 | ✅ | 只有列表页展示值，非合同费率 |
| T6 | **赎回费阶梯** | ❌ | **完全没有字段** |
| T7 | A/C 费用差异 | ❌ | 只能看到申购费不同，销售服务费无字段 |
| T8 | 暂停申购/限购 | ✅ | 只有当日快照，无历史 |
| T9 | 基金转换 | ❌ | 完全无接口 |
| T10 | 支付宝可购买状态 | ❌ | **unknown**，无证据 |

### 53.7 数据库模型设计（10 张表，未迁移）

`fund_master` / `fund_share_classes` / `fund_nav_daily` / `fund_dividends` /
`fund_manager_history` / `fund_aum_history` / `fund_fee_rules` /
`fund_subscription_status` / `fund_lifecycle_events` / `fund_data_quality`

**核心原则**：

- 基金本体与份额分两级，A/C 不重复计数（否则 28,380 会虚增成约 2 倍基金数）
- 单位净值与累计净值分列，禁止混用
- 所有表保留 source / ingested_at / data_version
- 申购状态按日快照才有历史
- 费率按阶梯存，赎回费必须有 holding_days 区间

### 53.8 模块复用

| 可复用（6） | 需新建（5） |
| --- | --- |
| 指标计算、风险指标、组合分析、报告生成、数据质量检查、研究框架 | 场外基金净值数据层、申购赎回执行模型、基金费率模型、基金经理与份额管理、场外基金回测适配层 |

**硬边界**：不把场内 ETF 回测引擎改造成场外基金引擎。
撮合 vs 确认、日内 vs T+1、价格 vs 净值——差异是结构性的，改造成本高于重建。

### 53.9 不能解决的问题

| 严重性 | 问题 |
| --- | --- |
| 🔴 高 | **清盘基金名录完全缺失** |
| 🔴 高 | **赎回费阶梯无数据源** |
| 🟡 中 | 销售服务费无字段、基金转换无接口、支付宝状态 unknown、申购状态无历史 |
| 🟢 低 | 规模历史、经理任职起止、货币基金兜底、分红接口偶发不完整 |

前两个是真正阻塞项：不解决就只能做净值分析，不能做策略回测。

### 53.10 下一阶段建议（未执行）

| 优先级 | 事项 |
| --- | --- |
| P0 | 补清盘基金名录 `fund_lifecycle_events` |
| P0 | 补赎回费阶梯 `fund_fee_rules` |
| P1 | 建 `fund_nav_daily` 数据层（已有可靠源，可立即做） |
| P1 | 建全量清单按日快照机制 |
| P2 | 申购状态按日快照、规模与经理历史 |
| P3 | 支付宝可购买状态（需外部证据） |

### 53.11 工程边界

未修改 `app/backtest/` `app/validation/` `app/quant/`；未修改会计/公司行为/撮合；
未写正式 backtest_runs / validation_runs；未执行数据库迁移；未新增场外基金引擎；
未接入支付宝、未绕过平台限制、未自动交易。

全部表行数 **变化为 0**，`fund*` 表 **0 个**，`integrity_check` ok，
行情指纹 `d54727c0…` 未变（116,609 行）。

全量测试 **784 passed / 0 failed / 0 skipped**（274.09 秒）
= 3B-2 的 747 + 本阶段 37 项专项测试；工程代码零改动。

### 53.12 产物

| 项 | 路径 |
| --- | --- |
| 审计脚本 | `scripts/research_3b3_fund_data.py` |
| 报告 | `reports/phase3B3_fund_data_feasibility.md` |
| 机器可读结果 | `reports/phase3B3_fund_data_feasibility.json` |
| 专项测试 | `tests/test_research_3b3_fund_data.py`（37 项） |

## 54. 阶段3B-3.1 场外基金历史净值连续性审计补强

### 54.1 修正的问题

3B-3 报告写了「12 只样本历史净值全部连续、无空洞」，但当时**并没有做日期连续性验证**。
本轮补做，结论已改变：

| 结论 | 数量 |
| --- | ---: |
| `verified_against_trading_calendar`（已验证连续） | **4** |
| `gaps_found`（发现真实缺口） | **8** |
| `cannot_verify`（无可靠日历无法判定） | **0** |

**12 只合计缺失 135 个交易日**，但全部集中在成立初期，没有一个是日频运作期的随机断档。

### 54.2 七项检查与三档结论

| # | 检查项 | 是否依赖日历 |
| ---: | --- | --- |
| 1 | 净值日期重复 | ❌ 不依赖 |
| 2 | 净值日期排序 | ❌ 不依赖 |
| 3 | 净值日期空值 | ❌ 不依赖 |
| 4 | 与公布日历对照找缺失 | ✅ 依赖（只能代理验证） |
| 5 | 区分周末/节假日/暂停估值与真实缺口 | ⚠️ 部分 |
| 6 | 最长连续缺失区间 | ❌ 不依赖 |
| 7 | 首末日期与有效行数 | ❌ 不依赖 |

**关键**：重复/乱序/空值这三项**不需要日历**就能判定，
所以即使拿不到日历，只要这三项有问题，结论必须是 `gaps_found` 而不是降级。

### 54.3 日历的限制（必须诚实说明）

项目数据库的 `trade_calendar`（8,797 天，1990-12-19 ~ 2026-12-31）是
**A 股交易日历，不是基金净值公布日历**。

差异来源：新基金成立初期按周公布、季末年末额外估值日、暂停估值等。
因此所有结论标注 `verification_level = proxy`，**不构成绝对证明**。

### 54.4 缺口归因（关键发现）

| 类型 | 数量 | 性质 | 是否算缺口 |
| --- | ---: | --- | --- |
| 成立初期周公布期缺失 | 126 | 新基金按周公布 | 已由公布频率解释 |
| 成立初期缺口 | 4 | 成立后最初几个交易日未披露 | **算缺口** |
| 过渡期缺口 | 5 | 周公布转日频接缝 | **算缺口** |
| 日频期内未解释 | 0 | — | — |

**「周公布」怎么判定**：不靠猜，看**公布密度**。
日频期密度应接近 1.0，实测周公布段只有 **0.18 ~ 0.29**。

举例：`000478` 建信中证500增强，2014-01-27 成立后到 2014-03-21 按周公布，
之后才转日频。这段缺的 25 天不是数据丢失，是**当时就没有每天公布**。

### 54.5 本轮修正的两个自身 bug（都会把缺口洗白）

| bug | 后果 | 修正 |
| --- | --- | --- |
| 用「平均间隔 > 3 交易日」判周公布期 | `161725` 间隔 `[2,4]` 平均 3.0，漏判 → 4 个缺口算成未解释 | 改**公布密度 ≤ 0.5** |
| 全序列扫描找「最后大间隔」定日频起点 | 会把日频期连续缺失误判成周公布，**把真实缺口洗成已解释** | **限制在成立初期 120 天窗口内** |

第二条尤其危险：它不会报错，只会让结论变好看。必须用测试防住。

### 54.6 不能声称的事

| 不能声称 | 原因 |
| --- | --- |
| 「12 只净值全部连续、无空洞」 | **错误**。4 只完全连续，8 只有缺口 |
| 「缺口已消除」 | 缺口仍在，只是归因清楚了 |
| 「净值公布日历与交易日历一致」 | 无证据；季末估值日已实测存在 |
| 「已验证 = 绝对无缺失」 | 只是「交易日历代理下未发现额外缺失」 |

### 54.7 新增测试

61 项专项测试（原 37 + 新增 24），全部用**人工构造的小型数据**验证，
不依赖真实样本恰好没有异常：

| 覆盖点 | 测试 |
| --- | --- |
| 重复净值日期 | `test_continuity_detects_duplicate_dates` |
| 缺失净值日期 | `test_continuity_detects_missing_trading_day` |
| 周末不误报 | `test_weekend_net_value_not_reported_as_gap` |
| 节假日不误报 | `test_holiday_not_reported_as_gap` |
| 连续多日缺失 | `test_continuity_detects_consecutive_missing` |
| 净值日期乱序 | `test_continuity_detects_unsorted_dates` |
| 空值日期 | `test_continuity_detects_null_dates` |
| 无日历降级 | `test_continuity_degrades_without_calendar` |
| 无日历仍查结构 | `test_continuity_still_detects_structure_without_calendar` |
| 过渡期缺口仍算缺口 | `test_transition_gap_still_counts_as_gap` |
| 货币按自然日 | `test_calendar_day_mode_for_money_fund` |
| 跨周末合并 | `test_missing_runs_merges_across_weekend` |

### 54.8 工程边界

未修改 `app/backtest/` `app/validation/` `app/quant/`；未改会计/公司行为/撮合；
未改数据库表结构；未写正式回测验证记录；未新增基金引擎；未做策略开发。

全部表行数 **变化为 0**，`fund*` 表 **0 个**，`integrity_check` ok，
行情指纹 `d54727c0…` 未变（116,609 行）。

全量测试 **808 passed / 0 failed / 0 skipped**
= 3B-3 的 784 + 本轮新增 24 项连续性测试 = 808。

### 54.9 产物

| 项 | 路径 |
| --- | --- |
| 审计脚本（含连续性检查） | `scripts/research_3b3_fund_data.py` |
| 报告（v2，新增 §6.0） | `reports/phase3B3_fund_data_feasibility.md` |
| 机器可读结果 | `reports/phase3B3_fund_data_feasibility.json` |
| 专项测试 | `tests/test_research_3b3_fund_data.py`（61 项） |

