# A股基金量化分析 Agent

面向中国 A 股 ETF / 指数基金的个人量化研究项目。当前完成 **阶段1A（环境、数据源、观察池）**、**阶段1B（历史行情持久化、增量同步、行情 API、数据看板）**、**阶段1B.1（完整前复权刷新与调整快照一致性）**、**阶段2（统一价格口径与量化指标引擎）**、**阶段2.1（CAGR交易日口径与EMA/MACD断点修复）**、**阶段2.2（区间风险统计缺失交易日修复）**、**阶段3A（A股ETF历史回测引擎 V1.0）** 和 **阶段3A.1（风险口径与部分成交修复）** 和 **阶段3A.1.1（部分成交状态逻辑专项修复）**。

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
- 离线单元/集成测试 154 项（含58项回测测试）
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
