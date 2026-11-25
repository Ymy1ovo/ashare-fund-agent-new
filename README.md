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
| 3B-3.1 | 场外基金历史净值连续性审计补强 | 808 | `phase3B3_fund_data_feasibility.md`（v2 §6.0） |
| 3B-4.0 | 场外基金数据层基础设施落地 | 856 | `phase3B4_fund_data_layer.md` |
| 3B-4.1 | 场外基金关键历史数据源补齐审计 | 905 | `phase3B4_1_critical_data_sources.md` |
| 3B-4.1.1 | 历史终止样本代表性修正与费率边界审计 | 942 | `phase3B4_1_1_historical_roster_fee_audit.md` |
| 3B-4.1.1-c | 类型分类、证据等级与支付宝口径收口 | 990 | `phase3B4_1_1_types_evidence_calibration.md` |
| 3B-4.2 | 关键历史数据正式入库（清盘 41 + 费率 90） | 1051 | `phase3B4_2_data_ingestion_report.md` |
| 3B-4.3 | 数据质量与幸存者偏差验收 | 1123 | `phase3B4_3_data_quality_report.md` |
| 3B-4.4 | 数据缺口补强与来源收口 | 1199 | `phase3B4_4_data_gap_research.md` |
| 3B-5.0 | 研究性分析框架设计 | 1283 | `phase3B5_0_research_framework.md` |
| 3B-5.1 | 研究性分析引擎 V1.0 | 1386 | `phase3B5_1_research_engine_report.md` |
| 3B-5.2 | 自选基金代码查询 | 1418 | `phase3B5_2_code_lookup_report.md` |
| 3B-5.3 | 自选基金受控接入 | 1445 | `phase3B5_3_user_ingest_report.md` |
| 3B-5.3.1 | 事务原子性与内容指纹修复 | 1465 | `phase3B5_3_1_atomic_fix_report.md` |
| 3B-5.3.2 | 外键约束与指纹序列化修正 | 1482 | `phase3B5_3_2_fk_serialization_report.md` |
| 3B-5.4 | 多类型场外基金真实接入验证 | 1517 | `phase3B5_4_ingestion_report.md` |
| 3B-5.5 | 数据质量分级与指标可信度 | 1577 | `phase3B5_5_quality_framework.md` |
| 3B-5.5.1 | 同类可验证性与年化证据修正 | 1629 | `phase3B5_5_test_report.md` |
| 3B-6.0.1 | 基准与指数数据源审计 | 1662 | `phase3B6_0_1_benchmark_coverage.md` |
| 3B-6.0.1.1 | 指数验证范围与覆盖结论修正 | 1690 | `phase3B6_0_1_test_report.md` |
| 3B-6.0.2 | 指数与基准数据层建设 | 1736 | `phase3B6_0_2_index_data_layer.md` |
| 3B-6.0.2.1 | 原始质检顺序与基准口径修正 | 1758 | `phase3B6_0_2_test_report.md` |
| 3B-6.0.2.2 | 复合基准有效行情判定 | 1782 | `phase3B6_0_2_test_report.md` |
| 3B-6.0.2.3 | 有效行情有限正数校验 | 1814 | `phase3B6_0_2_test_report.md` |
| 3B-6.0.3 | 研究池扩容 | 1814 | `phase3B6_0_3_universe_expansion.md` |
| 3B-6.0.4 | 同类比较与超额收益边界 | 1864 | `phase3B6_0_4_05_peer_comparison.md` |
| 3B-6.0.4.1 | LOF分类与等级修正 | 1902 | `phase3B6_0_4_1_01_lof_fix.md` |
| 3B-6.1.0 | 基准与无风险利率源可行性审计 | 1919 | `phase3B6_1_0_01_index_return_basis.md` |
| 3B-6.1.0.1 | 指数口径与复合基准语义修正 | 1945 | `phase3B6_1_0_01_index_return_basis.md` |
| 3B-6.1.0.2 | 指数证据统计与基准语义一致性修正 | 1979 | `phase3B6_1_0_01_index_return_basis.md` |
| 3B-6.1.0.3 | 历史数据获取与连续覆盖质量分离 | **2001** | `phase3B6_1_0_01_index_return_basis.md` |

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

## 55. 阶段3B-4.0 场外基金数据层基础设施落地

### 55.1 结论

> **10 张表全部落地，12 只样本基金完成真实入库，迁移与导入均可重复执行。**

| 验收标准 | 结果 |
| --- | --- |
| 10 张表全部落地 | ✅ |
| 迁移可重复执行 | ✅ 三次无变化 |
| 本体与份额关系正确 | ✅ 9 本体 / 12 份额 |
| 12 只样本真实入库 | ✅ |
| 单位/累计净值/分红口径正确 | ✅ |
| 重复导入无重复 | ✅ |
| 未知字段不被伪造 | ✅ |
| 新增测试通过 | ✅ 48 项 |
| 原有 ETF 数据未变 | ✅ 行数 0 变化，指纹一致 |

### 55.2 新增 10 张表（全部在 `migrations/phase3b4_fund_data_layer.sql`）

| 表 | 行数 | 用途 |
| --- | ---: | --- |
| `fund_master` | 9 | 基金本体（A/C 共用一行） |
| `fund_share_classes` | 12 | 份额类别（A/C/E/I） |
| `fund_nav_daily` | 39,822 | 每日净值（单位/累计分列） |
| `fund_dividends` | 44 | 分红（保留每10份原文 + 归一化） |
| `fund_manager_history` | 8 | 经理任职（A/C 共用本体，8 个本体有经理） |
| `fund_aum_history` | 8 | 规模（货币基金无基本信息，未入库） |
| `fund_fee_rules` | **0** | 费率规则（无数据源，rate=NULL） |
| `fund_subscription_status` | 12 | 申购状态按日快照 |
| `fund_lifecycle_events` | 8 | 生命周期事件（established，货币基金无） |
| `fund_data_quality` | 31 | 数据质量 |

### 55.3 关键约束

| 约束 | 作用 |
| --- | --- |
| `fund_share_classes.share_class_code UNIQUE` | 份额代码独立，不被合并 |
| `fund_nav_daily` 主键 `(share_class_id, nav_date, nav_kind)` | 同日期同类型只一行 |
| `fund_nav_daily` CHECK | 净值型必须有 unit_nav 且不能有 per_10k_yield；货币型反之 |
| `fund_dividends` UNIQUE `(share_class_id, ex_date, source)` | 同源幂等，**不同源各留一条**保留差异 |
| `fund_subscription_status` UNIQUE `(share_class_id, as_of_date, source)` | 按日快照，历史不被覆盖 |
| `alipay_purchasable` CHECK | 只允许 unknown/yes/no，默认 unknown |
| `lifecycle_status` CHECK | 只允许 active/terminated/merged/unknown |

### 55.4 数据层结构（不堆在一个大文件里）

| 模块 | 职责 |
| --- | --- |
| `app/fund/migration.py` | 建表入口 |
| `app/fund/models.py` | 10 类记录 dataclass |
| `app/fund/normalize.py` | 归一化纯函数（每10份换算、份额类别识别） |
| `app/fund/repo_base.py` | 来源置信度与覆盖规则 |
| `app/fund/repository.py` | 本体/份额/生命周期/经理/规模 |
| `app/fund/repo_nav.py` | 净值与分红 |
| `app/fund/repo_status.py` | 状态快照与费率 |
| `app/fund/repo_quality.py` | 数据质量 |
| `app/fund/ingest.py` | 导入流程（Mock 注入点齐全） |

### 55.5 A/C 归属（本轮关键修正）

12 个份额代码 → **9 个基金本体**。

| 本体 | 份额 |
| --- | --- |
| 招商中证白酒 | `161725`(A) + `012414`(C) |
| 国联安半导体ETF联接 | `007300`(A) + `007301`(C) |
| 华夏纯债债券 | `000015`(A) + `000016`(C) |

归属依据是「去掉份额后缀后名称一致」——这是**弱依据**，所以：

- 单成员组 → 天然独立本体，不标待核实；
- 多成员且基础名一致 → 合并为一个本体，A 类作主代码；
- 多成员但基础名不一致 → **各自独立成体并标 `needs_review=1`，不强行合并**。

第一版实现把「12 只样本」当成 12 只独立基金，导致 A/C 各自成体（12 个 master）。
改为按本体分组后修正为 9 个。

### 55.6 幂等验证

同一批真实数据导入三次：

| 表 | 第1次 | 第2次 | 第3次 | 结果 |
| --- | ---: | ---: | ---: | --- |
| `fund_master` | 9 | 9 | 9 | ✅ 收敛 |
| `fund_share_classes` | 12 | 12 | 12 | ✅ 收敛 |
| `fund_nav_daily` | 39,822 | 39,822 | 39,822 | ✅ 收敛 |
| `fund_dividends` | 40 | 44 | 44 | ⚠️ 见下 |
| `fund_data_quality` | 31 | 31 | 31 | ✅ 收敛 |

**分红 40→44 不是重复写入**：3B-3.1 已实测分红接口单次返回会不完整。
第 1 次抓 40 条，第 2、3 次抓到更完整 44 条后收敛。
按 `(share_class_id, ex_date, source)` 分组重复组数 = **0**，只是补全不是重复。

### 55.7 未知字段处理

| 字段 | 处理 |
| --- | --- |
| 赎回费率 | **NULL**，未填行业平均（`fund_fee_rules` 0 行） |
| 清盘日期 | **NULL**，未推测 |
| 经理任职起止 | **NULL**，未用今天伪造 |
| 支付宝可购买 | **unknown**，DDL CHECK 约束强制 |
| 成立日期（货币基金） | **NULL**，接口不支持 |

### 55.8 仍未解决

| 严重性 | 问题 |
| --- | --- |
| 🔴 高 | **清盘基金名录缺失**，`survivorship_bias_unresolved` 未解决 |
| 🔴 高 | **赎回费阶梯无数据源**，表建了但 0 行 |
| 🟡 中 | 销售服务费、基金转换、支付宝状态、申购状态历史 |
| 🟢 低 | 规模历史、经理任职、货币基本信息、分红完整 |

本轮只解决**基础设施**问题（表、仓储、导入、幂等、留痕），
**没有**解决数据可得性问题。前两条不解决仍不能做正式回测。

### 55.9 工程边界

未修改 `app/backtest/` `app/validation/` `app/quant/`；未改 ETF 公司行为/会计/撮合；
未开发场外回测引擎；未开发策略；未接实盘。

| 检查 | 结果 |
| --- | --- |
| ETF 侧全部表行数变化 | **0** |
| `integrity_check` | ok |
| 行情指纹 | `d54727c0…` 未变（116,609 行） |

### 55.10 产物

| 项 | 路径 |
| --- | --- |
| 迁移 | `migrations/phase3b4_fund_data_layer.sql` |
| 数据层 | `app/fund/`（9 个模块） |
| 导入脚本 | `scripts/ingest_3b4_fund_sample.py` |
| 专项测试 | `tests/test_fund_data_layer.py`（48 项） |
| 报告 | `reports/phase3B4_fund_data_layer.md` |
| 机器可读 | `reports/phase3B4_fund_data_layer.json` |

## 56. 阶段3B-4.1 场外基金关键历史数据源补齐审计

### 56.1 结论

| # | 问题 | 答案 |
| ---: | --- | --- |
| 1 | 历史清盘/合并基金能否形成可靠名录？ | **部分可以**：25 只样本全部找到公告，24 只正文可读，24 只提取到终止日期 |
| 2 | 赎回费阶梯能否可靠获取？ | **存续基金可以**：12 只中 11 只解析成功 |
| 3 | 历史费率能否恢复？ | **不能**：探测 4 只已终止基金，0 只可恢复 |
| 4 | 支付宝可购买状态能否自动获取？ | **不能**：`not_obtainable` |
| 5 | 哪些值得自动化？ | 历史终止名录（A 级）、存续基金费率（C 级） |
| 6 | 哪些必须人工？ | 支付宝状态、已终止基金历史费率、合并承接代码 |

### 56.2 最重要的发现

> **「历史清盘名录完全没有」这个判断需要修正——它有，只是不成册。**

天天基金公告接口 `api.fund.eastmoney.com/f10/JJGG/` **能查到已注销代码的全部历史公告**，
并且能直接下到基金公司公告原文（PDF 或 HTML），是 **A 级证据**。

| 数据源 | 覆盖已终止 | 证据等级 | 可自动化 |
| --- | --- | --- | --- |
| 天天基金公告列表 | ✅ | B | ✅ |
| 东财公告原文 | ✅ | **A** | ✅ |
| 天天基金 F10 费率页 | ❌ | C | ✅（仅存续） |
| 支付宝购买状态 | ❌ | D | ❌ |

### 56.3 公告原文有两种形态（本轮踩的坑）

| 公告年代 | 实测返回 | 处理 |
| --- | --- | --- |
| 约 2015 年后 | 真 PDF | `pypdf` 提取 |
| 约 2015 年前 | **HTML 正文** | 剥标签取文本 |

第一版只判 `%PDF` 魔数，把 2014 年前的老公告全判成不可读（17/25）。
兼容 HTML 后变成 **24/25**。
**数据源返回格式会随年代变化，不能只测新样本就下结论。**

### 56.4 25 只历史终止样本

| 项 | 数量 |
| --- | ---: |
| 样本总数 | 25 |
| 不在当前存续名册 | 25 / 25 |
| 找到公告 | 25 |
| 正文可读 | 24 |
| 提取到终止日期 | 24 |
| 提取到承接基金名 | 18 |
| A 级证据 | 24 |

覆盖 8 个年份（2011~2020），4 种事件类型：清盘 2、份额终止 4、终止上市 18、未知 1。

**四类事件必须分开**（清盘 / 合并 / 转型 / 份额终止）。本轮踩过两个分类错误：

| 错误 | 后果 |
| --- | --- |
| 「终止分级运作变更而来」判成 `liquidation` | 份额终止误报成基金清盘 |
| 「终止上市及转型期间…变更」判成 `delisting` | 转型误报成终止上市 |

如果混进名录，「历史上有多少基金清盘」这个统计会完全失真。

### 56.5 费率解析

| 项 | 成功 |
| --- | ---: |
| 赎回费阶梯 | 11 / 12 |
| 申购费阶梯 | 8 / 12 |
| 年化费率（管理/托管/销售服务） | 12 / 12 |
| A/C 配对 | 3 组 |

**赎回费阶梯实例 `161725`**：<7 天 1.50%、7~365 天 0.50%、365~730 天 0.25%、≥730 天 0。

**A/C 差异完全一致**：A 收申购费（0.8~1.0%）、销售服务费 0；
C 免申购费、销售服务费 0.10~0.40%；管理费两者相同。
这验证了 3B-4.0 的两级结构设计是对的。

**注意**：销售服务费 `0.0000%`（页面写 0.00%）与 `n/a`（页面写 `---`）是两回事，
不能把 `---` 当 0。

### 56.6 历史费率不可恢复

探测 4 只已终止基金（150008 / 150019 / 150020 / 184688），
页面能打开（200）但**费率区域是空的**——东财在基金终止后会清掉 F10 费率数据。

**结论：历史费率在公开渠道基本不可恢复**，只能从合同/招募说明书 PDF 人工提取。

### 56.7 支付宝状态：not_obtainable

| 概念 | 含义 | 数据源 |
| --- | --- | --- |
| 基金开放申购 | 合同层面开放 | 天天基金状态近似 |
| 天天基金可购买 | 该渠道可买 | `fund_purchase_em` |
| **支付宝可购买** | 支付宝渠道可买 | **无** |

**明确禁止**：绕登录/验证码、用非公开接口、拿天天基金状态冒充。

**推荐**：`alipay_purchasable` 保持 `unknown`（3B-4.0 的 DDL 已用 CHECK 约束落实），
人工核实后录入 `verified_by='manual'` + 截图。

### 56.8 幸存者偏差立场

| 项 | 状态 |
| --- | --- |
| 能否建立已终止基金名录 | ✅ 能（A 级） |
| 能否保证名录完整 | ❌ 不能 |
| 能否计算覆盖率 | ❌ 不能（无权威全量清单） |
| 幸存者偏差是否消除 | ❌ **未消除** |

**本轮没有解决幸存者偏差**，只是提供了可行的采集路径。
基于存续基金的历史回测仍必须标 `survivorship_bias_unresolved`。

### 56.9 分项判定

| 问题 | 判定 |
| --- | --- |
| 历史清盘名录 | **有限继续**（能按事件建立，无法保证全量） |
| 赎回费阶梯 | **继续**（存续基金可稳定解析） |
| 历史费率 | **停止**（公开渠道不可恢复） |
| 支付宝状态 | **停止**（无公开合法接口） |

### 56.10 工程边界

未修改 `app/fund/` 正式数据层；未修改迁移文件（`CREATE TABLE` 仍为 10 张）；
未写正式数据库；未改 `app/backtest/` `app/validation/` `app/quant/`；
未开发回测、策略、自动交易。

全部网络调用有超时与重试；专项测试全部用人工构造数据 + Mock，不联网。

### 56.11 产物

| 项 | 路径 |
| --- | --- |
| 研究脚本 | `scripts/research_3b4_1_critical_sources.py` |
| 报告 | `reports/phase3B4_1_critical_data_sources.md` |
| 机器可读 | `reports/phase3B4_1_critical_data_sources.json` |
| 专项测试 | `tests/test_research_3b4_1_critical_sources.py`（49 项） |

## 57. 阶段3B-4.1.1 历史终止样本代表性修正与费率解析边界审计

### 57.1 对 3B-4.1 的自我修正

3B-4.1 报「25 只历史终止样本」**口径有问题**：

| 旧说法 | 实际情况 |
| --- | --- |
| 「25 只独立基金」 | 25 条**代码记录**，150008/150009 是同一基金的 A/B 份额 |
| 「25 个独立事件」 | 分级 A/B 共用同一条公告，实际是 **1 个事件** |
| 代表性 | 18 条终止上市 + 4 条份额终止，**真正清盘只有 2 只** |

### 57.2 重新审计结果

| 口径 | 数量 |
| --- | ---: |
| 扫描的非存续代码 | 844 |
| 原始代码记录 | 310 |
| 原始公告事件 | 216 |
| **去重后独立事件** | **59** |
| **去重后基金本体** | **58** |
| 合并掉的重复记录 | 251 |
| 终止上市并入清盘 | 12 |

### 57.3 事件分布（关键修正）

| 事件类型 | 3B-4.1 | 3B-4.1.1 |
| --- | ---: | ---: |
| `liquidation` 清盘 | 2 | **43** |
| `merge` 合并 | 0 | **0**（如实报告） |
| `transformation` 转型 | 1 | 4 |
| `share_termination` 份额终止 | 4 | 0 |
| `delisting` 终止上市 | 18 | 12 |

**清盘样本从 2 只扩到 43 个独立基金本体**，且全部是普通开放式/LOF/ETF 联接，
不再是「分级基金 + 老封闭式」的畸形样本。

### 57.4 去重规则（本轮核心）

| # | 规则 |
| ---: | --- |
| 1 | 同一 `announcement_id` = 同一事件（分级 A/B 共用公告不能算两个） |
| 2 | 同一（本体 + 类型）的多条公告 = 同一事件的披露链（提示→合同终止→清算报告） |
| 3 | 同一本体已有 `liquidation` 时，其 `delisting` **并入清盘**（终止上市是清盘前置程序） |
| 4 | 本体按公告标题抽取的基金全名归并 |
| 5 | 抽不出基金名时用整条标题作键，**宁可多算不错误合并** |

压缩率 251/310 = 81%。

### 57.5 合并事件：0 个

扫了 844 个非存续代码、16 个代码段、全部公告标题，**0 条含「合并」**。
网络检索只有 REITs 吸收合并和基金公司股权合并，都不是基金合并。

**不凑数。** 中国公募基金实践中「基金合并」极少：
法规路径窄（需持有人大会特别决议）、流程成本高于直接清盘，
多数选择「清盘 + 重新发行」。

但必须区分：合并的持有人拿到承接基金份额，清盘的拿到现金。
对回测而言前者是「换标的继续持有」，后者是「强制赎回」，**不能互相替代**。

### 57.6 费率边界审计：修复 3 个真 bug

| # | Bug | 后果 | 修复 |
| ---: | --- | --- | --- |
| 1 | 比较符按短到长匹配 | 「小于等于6天」被拆成「小于」+「6天」，首档误判为无上限 | 改为按长度从长到短 |
| 2 | 区间连续性不看闭区间 | 364（含）→365 被误判为空洞 | 闭区间上界 +1 再比 |
| 3 | 首档无显式下界 | `holding_days_min=None`，无法表达区间 | 补 0 并标 `min_inferred=True` |

**修复前** `with_gaps=2`（110020、110022 各 2 处空洞）→ **修复后 `with_gaps=0`**。

### 57.7 当前字段不足以表达区间

`fund_fee_rules` 只有 `holding_days_min` / `holding_days_max`，缺三个关键信息：

| 缺失 | 反例 |
| --- | --- |
| `min_inclusive` / `max_inclusive` | 「小于365天」与「小于等于365天」在第 365 天费率完全不同 |
| `min_inferred` | 「小于7天」的下界 0 是推断的，不是原文写的 |

**具体反例**：`110020` 是「小于等于364天→0.50%」，`161725` 是「小于365天→0.50%」。
两者用 `holding_days_max` 存分别是 364 和 365，**看起来不同但实际等价**。

### 57.8 最小化字段设计建议（本轮不落地）

| 建议字段 | 类型 |
| --- | --- |
| `holding_days_min_inclusive` | INTEGER 0/1 |
| `holding_days_min_inferred` | INTEGER 0/1 |
| `holding_days_max_inclusive` | INTEGER 0/1 |
| `rate_original` / `rate_platform` | REAL（拆分现有 `rate`） |
| `platform_name` | TEXT（eastmoney / alipay / contract） |
| `is_annual` | INTEGER 0/1 |

只加 6 个字段就能无歧义表达所有已见形态，不需要区间表或 JSON blob。

### 57.9 还剩的 2 处问题（都是数据性质，不是解析 bug）

| 代码 | 问题 |
| --- | --- |
| `110022` | 销售服务费页面写 `---`，**页面无此字段**，不能当 0 |
| `000198` | 货币基金无赎回阶梯，**本来就没有** |

### 57.10 能否进入正式入库阶段

| 数据块 | 可以入库吗 | 理由 |
| --- | --- | --- |
| 清盘名录（43 个本体） | ✅ **可以** | A 级证据、字段完整、幂等键明确 |
| 存续基金费率（C 级） | ⚠️ 可以但须标 C | 需先补 6 个字段，否则区间有歧义 |
| 合并事件 | ❌ 不建议 | 0 个样本，无法验证 schema |
| 历史费率 | ❌ 不行 | 数据不存在 |
| 支付宝状态 | ❌ 不行 | 只能 unknown |

**建议入库顺序**：清盘名录（可立即）→ 费率字段扩展（需改迁移）→ 费率数据 → 合并事件（等样本）。

### 57.11 幸存者偏差立场

> **现在具备「按已知清盘基金剔除幸存者偏差」的能力，
> 但不足以声称「覆盖全部清盘基金」。**

回测仍须标 `survivorship_bias_partially_mitigated`，不是 `resolved`。

### 57.12 产物

| 项 | 路径 |
| --- | --- |
| 研究脚本 | `scripts/research_3b4_1_1_roster_fee_audit.py` |
| 报告 | `reports/phase3B4_1_1_historical_roster_fee_audit.md` |
| 机器可读 | `reports/phase3B4_1_1_historical_roster_fee_audit.json` |
| 专项测试 | `tests/test_research_3b4_1_critical_sources.py`（86 项） |

## 58. 阶段3B-4.1.1 验收修正：基金类型分类与证据等级校准

### 58.1 修正的三个错误

| # | 原报告的错误 | 修正后 |
| ---: | --- | --- |
| 1 | 「43 条清盘全部 A 级证据」 | **全部 B 级**（公告链接均为东财转载） |
| 2 | 未区分场内 ETF / ETF 联接 / LOF / 普通开放式 | 新增 `product_structure` 五类 |
| 3 | 4 只 ETF 联接基金名称漏「联接基金」 | 已按公告原文补全 |

### 58.2 核心数字

| 项 | 数量 |
| --- | ---: |
| 清盘事件总数 | 43 |
| **支付宝场外可买** | **41** |
| 其中 ETF 联接基金 | 3 |
| 其中 LOF | 11 |
| 其中普通开放式 | 27 |
| **场内 ETF（剔除）** | **2**（511000、511050） |
| 无法确认类型 | 0 |

> **43 个清盘本体里只有 41 个属于支付宝场外可买范围。**

### 58.3 两个独立维度，不得混为一谈

原报告只有「基金类型」一个模糊概念，把**投资类型**（股/债/混）
和**交易形式**（场内/场外/LOF）混在一起。本轮拆成两个独立字段。

| 维度 | 枚举 |
| --- | --- |
| `product_structure`（交易形式） | `ordinary_open_ended` / `etf_linked` / `etf` / `lof` / `other` / `unknown` |
| `investment_type`（投资类型） | `money_market` / `bond` / `mixed` / `equity` / `index` / `other` / `unknown` |

### 58.4 判定依据：不得只凭代码前缀

| 优先级 | 线索 |
| ---: | --- |
| 1 | 公告正文的基金全称（最可靠） |
| 2 | 公告标题 |
| 3 | 正文里的运作方式描述 |
| — | 代码前缀 **只记录为 `prefix_hint`，不采信** |

例：`501041` 以 501 开头（LOF 段）但公告原文未写 LOF，判为普通开放式，
并标 `prefix_conflict`。

### 58.5 场内 ETF 必须剔除

| 项 | 场内 ETF | 支付宝场外基金 |
| --- | --- | --- |
| 交易场所 | 证券交易所 | 基金销售平台 |
| 交易方式 | 二级市场竞价 | 按净值申购赎回 |
| 价格形成 | 实时市价（有折溢价） | 每日净值 |
| 最小单位 | 100 份 | 1 元起 |
| 支付宝可买 | ❌ | ✅ |

**混进场外样本会让回测的成交价、折溢价、最小单位全部失真。**

### 58.6 证据等级校准

**原报告错误根源**：把「PDF 能下载、内容完整」当成 A 级的充分条件。
但证据分级看的是**发布渠道**，不是**可读性**。

| 等级 | 标准 |
| --- | --- |
| **A** | 基金管理人官网 / 交易所官网 / 证监会电子披露平台的原始公告 |
| **B** | 第三方转载（东方财富等），原文完整可读、可追溯，但发布主体非官方 |
| **C** | 可靠第三方结构化摘要，无原文 |
| **D** | 无法确认来源 |

**实测：43 条公告链接域名全部是 `pdf.dfcfw.com`（东方财富转载）。**

| 等级 | 数量 | 占比 |
| --- | ---: | ---: |
| A | **0** | 0% |
| B | **43** | 100% |
| C | 0 | 0% |
| D | 0 | 0% |

**转型和终止上市同样只有 B 级**，原报告标 A 也偏高。

### 58.7 三类样本明确区分

| 集合 | 数量 |
| --- | ---: |
| 历史公募基金清盘样本 | 43 |
| **支付宝场外基金相关清盘样本** | **41** |
| 场内 ETF 清盘样本 | 2 |

41 + 2 = 43。**场外样本是清盘样本的真子集。**

| 用途 | 应使用集合 |
| --- | --- |
| 讨论「中国公募基金清盘历史」 | 全部 43 |
| **做支付宝场外基金回测的幸存者偏差修正** | **41** |
| 讨论「ETF 清盘」 | 2 |

### 58.8 费率部分：未改动

三个 Bug 修复全部保留，四条边界全部保留。

| 边界 | 状态 |
| --- | --- |
| 天天基金 F10 费率 = **C 级** | ✅ 未提升 |
| 不是支付宝实际费率 | ✅ |
| 当前费率不是历史费率 | ✅ |
| 持有期限按自然日还是交易日 | ⚠️ **原始合同未明确，不自行认定** |

最后一条本轮进一步收紧：原报告说按自然日，但公告与费率页都没写明，现在标为**未确认**。

### 58.9 更新后的入库建议

| 数据块 | 可以入库吗 | 变化 |
| --- | --- | --- |
| 清盘名录（41 个场外本体） | ✅ 可以 | 数量从 43 降为 41 |
| 场内 ETF 清盘（2 个） | ⚠️ 可入库但**单独标记** | 新增要求 |
| 存续基金费率（C 级） | ⚠️ 须先补字段 | 不变 |
| 合并事件 | ❌ 0 个样本 | 不变 |

**新增一条入库硬要求**：`fund_lifecycle_events` 入库时必须写 `evidence_level='B'`，
且 `detail` 注明「来源为东方财富转载，未经官方回源验证」。

### 58.10 产物

| 项 | 路径 |
| --- | --- |
| 校准脚本 | `scripts/calibrate_3b4_1_1_types_evidence.py` |
| 校准报告 | `reports/phase3B4_1_1_types_evidence_calibration.md` |
| 校准 JSON | `reports/phase3B4_1_1_types_evidence_calibration.json` |
| 专项测试 | `tests/test_research_3b4_1_critical_sources.py`（117 项） |

## 59. 阶段3B-4.1.1 最终验收修正：支付宝可购买状态与主报告口径收口

### 59.1 本轮只改报告与统计口径

不重新扫描、不重新采集、不改数据层。只做三件事：

| # | 事项 |
| ---: | --- |
| 1 | 把 41 从「支付宝可买」收窄为「**场外产品结构范围**」 |
| 2 | 实际修正主报告，消除新旧冲突 |
| 3 | 两份 JSON + 两份 MD 口径统一 |

### 59.2 关键澄清：场外结构 ≠ 支付宝可买

| 概念 | 依据 | 状态 |
| --- | --- | --- |
| 场外**产品结构** | 基金合同约定的运作方式 | ✅ 可从公告判定，41 只 |
| 支付宝**实际可购买** | 支付宝渠道当前是否在售 | ❌ **unknown，无数据源** |

3B-4.1 已结论 `alipay_purchasable` = `not_obtainable`。本轮**没有**新证据改变它。

**不能推出的三个结论**：

| 不能推出 | 原因 |
| --- | --- |
| 「这 41 只支付宝能买」 | 支付宝状态 unknown |
| 「这 41 只曾在支付宝上架」 | 无历史渠道数据 |
| 「其余 2 只支付宝不能买」 | 场内 ETF 走证券账户，与支付宝无关 |

### 59.3 字段改名与语义声明

| 旧字段 | 新字段 | 语义 |
| --- | --- | --- |
| `offmarket_count` | `offmarket_structure_count` | 场外**结构范围**数量（41） |
| ~~`alipay_purchasable_count`~~ | **已废弃** | 名字易被误读为「实际可购买总数」 |
| — | `alipay_confirmed_yes_count` | **已确认**可购买数量（0） |
| — | `alipay_unknown_count` | 状态未知数量（43） |
| — | `alipay_status` | 恒为 `unknown` |

旧名保留为兼容别名，语义已收窄。JSON 增加 `field_semantics` 块显式声明，
防止调用方把结构范围误读成可购买数量。

**关于「0」的语义（本轮修正）**：

| 字段 | 值 | 它表示 | 它**不**表示 |
| --- | ---: | --- | --- |
| `alipay_confirmed_yes_count` | 0 | 没有任何一条被确认可买 | 实际可购买数量是 0 |
| `alipay_unknown_count` | 43 | 全部状态未知 | 这 43 只都不能买 |

**`unknown` 不等于 `no`。没有证据 ≠ 证据表明没有。**

因此 `alipay_purchasable_count` 已废弃——那个名字会让读者以为「实际可购买 = 0」。

### 59.4 主报告实际修正（不是只在新报告里解释）

`reports/phase3B4_1_1_historical_roster_fee_audit.md` 已实际改动：

| 位置 | 修改 |
| --- | --- |
| 文件头 | 新增 ⚠️ 权威口径声明块，引用校准报告 |
| §0.3 | 「全部是普通开放式/LOF/ETF 联接」→ 明确 41 场外结构 + 2 场内 ETF |
| §2.2 | 删除「能代表支付宝可买的场外基金」表述，改为「场外产品结构」 |
| §2.2 新增 | 投资类型 + 产品结构两张表（27/11/3/2/41） |
| §2.4 新增 | 「场外结构 ≠ 支付宝可买」澄清小节 |
| §2.5 新增 | 「证据等级：原表述已被校准纠正」 |
| §8 / §11 | 「A 级证据」→「B 级证据」，正文加 unknown 标注 |
| §2.1 整表重建 | 43 条逐条名称/证据等级以校准 JSON 为准，新增「结构」列 |

**测试锁死**：`test_411c_main_report_no_old_claim` 禁止三个旧结论字符串出现；
`test_411c_main_report_no_bare_a_level` 要求主报告里每处「A 级」都必须带纠正语境。

### 59.5 保留的有效结论

| 结论 | 状态 |
| --- | --- |
| 费率解析器三个 Bug 修复 | ✅ 保留，测试锁死 |
| 天天基金 F10 = C 级 | ✅ 保留 |
| 不是支付宝实际费率 | ✅ 保留 |
| 当前费率不是历史费率 | ✅ 保留 |
| 持有期按自然日/交易日 | ⚠️ **未确认**，不自行认定 |
| 43 条清盘事件 | ✅ 保留 |
| 43 条 B 级证据 | ✅ 保留 |
| 合并事件 0 个 | ✅ 保留 |

### 59.6 测试结果

| 项 | 数量 |
| --- | ---: |
| 专项测试 | **134 passed** |
| 全量测试 | **990 passed / 0 failed** |
| 耗时 | 257.37 秒 |

新增 17 项覆盖本轮 8 项要求：场外结构数不等于可买数、支付宝保持 unknown、
511000/511050 仍是场内 ETF、020025 等仍是联接、43 条全 B 级、两份报告一致、
主报告无旧结论、费率三修复未回退。

## 60. 阶段3B-4.2 场外基金关键历史数据正式入库

### 60.1 结论

| 项 | 结果 |
| --- | --- |
| 生命周期事件 | **41** 条（场内 ETF 2 条排除） |
| 费率规则 | **90** 条 |
| 证据等级 | 生命周期 **B** / 费率 **C** |
| 幂等 | ✅ 二次导入 0 新增 |
| SQLite 完整性 | **ok**，外键违规 0 |
| 支付宝状态 | ✅ 全部 unknown，未改变 |
| ETF 侧数据 | ✅ 前后行数完全一致 |

> **核心原则：宁可保留 NULL 和 unknown，也不为填满数据库制造数据。**

### 60.2 迁移（只补列，不重构）

`migrations/phase3b4_2_lifecycle_fee_ingestion.sql`

| 表 | 新增列 | 用途 |
| --- | ---: | --- |
| `fund_lifecycle_events` | +5 | `announcement_id` / `product_structure` / `fund_codes` / `event_fingerprint` / `fetched_at` |
| `fund_fee_rules` | +15 | 区间开闭、推断标记、原始/平台费率分列、平台名、年化、持有期口径、来源追溯、detail |

新增索引：`uq_fund_life_fingerprint`（UNIQUE）、`idx_fund_life_announcement`、
`idx_fund_life_structure`、`idx_fund_fee_type`、`idx_fund_fee_platform`。

SQLite 的 `ALTER TABLE ADD COLUMN` 不支持 `IF NOT EXISTS`，
实际执行由 `app/fund/migration_3b4_2.py` 先查 `PRAGMA table_info` 再逐列补。

**兼容性**：保留全部旧列，旧 Repository 方法不改一行仍可用。

### 60.3 生命周期事件入库

| 项 | 数量 |
| --- | ---: |
| 清盘事件总数（校准 JSON） | 43 |
| 排除（场内 ETF） | 2（`511000`、`511050`） |
| **实际入库** | **41** |

| 结构 | 数量 |
| --- | ---: |
| 普通开放式 | 27 |
| LOF | 11 |
| ETF 联接 | 3 |

| 检查 | 结果 |
| --- | --- |
| 场内 ETF 泄漏 | **0** |
| 证据等级 B | **41 / 41** |
| URL + ID 齐全 | **41 / 41** |
| detail 含来源声明 | **41 / 41** |
| `event_date` 为 NULL | 12（公告未写清算开始日） |
| 多份额→多本体 | **0**（每事件唯一 fund_id） |

每条 detail 写明：

```
来源为东方财富转载，未经基金管理人官网或交易所官网逐条回源验证，证据等级B。
```

**关键验证**：12 条 `event_date IS NULL` 的记录，`announcement_date` 都有值，
且**没有一条**把公告日期复制成事件日期。

### 60.4 费率阶梯入库

| 费率类型 | 数量 |
| --- | ---: |
| `purchase` 申购（金额阶梯） | 20 |
| `redemption` 赎回（持有期阶梯） | 34 |
| `management` 管理费 | 12 |
| `custody` 托管费 | 12 |
| `sales_service` 销售服务费 | 12 |
| **合计** | **90** |

| 边界保护 | 结果 |
| --- | --- |
| 原始/平台费率分列 | ✅ `rate_original` / `rate_platform` |
| `platform_name` = alipay | **0**（全部 eastmoney） |
| 推断下界已标记 | 19 条 `*_inferred = 1` |
| `rate_original` 为 NULL | 1（`110022` 销售服务费 `---`，不当 0） |
| `effective_from` 为 NULL | **90 / 90**（抓取日期不冒充生效日期） |
| `holding_days_basis` 为 NULL | **90 / 90**（自然日/交易日未确认） |
| 货币基金伪造赎回阶梯 | **0**（`000198` 赎回 0 行） |
| 证据等级 | **C**（天天基金 F10，非合同原文） |

**闭区间可表达**（3B-4.0 做不到的）：

| 档 | min | min含 | max | max含 | 推断 | 费率 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 0 | 1 | 6 | 1 | **1** | 1.50% |
| 1 | 7 | 1 | 364 | 1 | 0 | 0.50% |
| 2 | 365 | 1 | 729 | 1 | 0 | 0.25% |
| 3 | 730 | 1 | NULL | NULL | 0 | 0.00% |

`max=6, inclusive=1` 与 `max=7, inclusive=0` 是两种不同含义，单列 `holding_days_max` 无法区分。

### 60.5 幂等验证

| 表 | 导入前 | 第1次后 | 第2次后 |
| --- | ---: | ---: | ---: |
| `fund_lifecycle_events` | 8 | 49 | **49** |
| `fund_fee_rules` | 0 | 90 | **90** |
| `fund_master` | 9 | 50 | **50** |

第二次导入：新增 **0**，跳过 41 + 90，失败 0。

幂等键：

| 表 | 键 | 兜底 |
| --- | --- | --- |
| 生命周期 | `event_fingerprint` = `life:{announcement_id}:{fund_code}` | UNIQUE 索引 |
| 费率 | `(share_class_id, fee_type, tier_order, effective_from)` | UNIQUE 索引 |

### 60.6 备份

| 项 | 值 |
| --- | --- |
| 路径 | `data/backups/fund_agent_before_ingest_3b4_2_*.db` |
| 方式 | `sqlite3` backup API（一致性快照） |
| 时机 | 迁移与导入**之前** |
| 是否入 Git | ❌ `.gitignore` 已排除 `data/backups/` |

### 60.7 专项测试

`tests/test_ingest_3b4_2.py`，**41 项**，独立临时库 + JSON 数据源，不联网。

| 类别 | 测试数 |
| --- | ---: |
| 迁移 | 5 |
| 范围筛选 | 4 |
| 生命周期 | 9 |
| 费率 | 15 |
| 数据库 | 6 |
| 数据源不变 | 2 |

### 60.8 产物

| 项 | 路径 |
| --- | --- |
| 迁移 SQL | `migrations/phase3b4_2_lifecycle_fee_ingestion.sql` |
| 迁移模块 | `app/fund/migration_3b4_2.py` |
| 导入模块 | `app/fund/ingest_3b4_2.py` |
| 导入脚本 | `scripts/ingest_3b4_2.py` |
| 专项测试 | `tests/test_ingest_3b4_2.py`（41 项） |
| 报告 | `reports/phase3B4_2_data_ingestion_report.md` |
| 统计 JSON | `reports/phase3B4_2_data_ingestion.json` |

### 60.9 仍未解决

| # | 问题 |
| ---: | --- |
| 1 | 43 条清盘公告仅 B 级（东财转载，未回源官方） |
| 2 | 12 条清盘记录缺 `event_date`（公告未写清算开始日） |
| 3 | 费率仅 C 级（天天基金 F10 非合同原文） |
| 4 | `effective_from` 全 NULL，无法做历史费率模拟 |
| 5 | `holding_days_basis` 全 NULL，自然日/交易日未确认 |
| 6 | 支付宝可购买状态全 unknown |
| 7 | 合并事件 0 个 |
| 8 | 清盘名录覆盖率不可量化 |

### 60.10 验收修正：多份额基金主从标记

**发现的 Bug**：`_ensure_share()` 为非主份额建记录时也用了 `is_primary=1`，
导致同一基金本体出现多个主份额。修复前 41 个本体里只有 21 个合规，共 63 个主份额。

另一个问题：已存在的份额代码直接返回，**没校验是否属于传入的 `fund_id`**。

**函数修复**：

| 项 | 修复前 | 修复后 |
| --- | --- | --- |
| 非主份额 `is_primary` | 1（错） | **0** |
| 归属校验 | 无 | 不一致抛 `ShareOwnershipError` |
| 冲突处理 | 静默返回 | 抛错 + 记入 `stat.conflicts` |
| 主份额创建 | 两处都可建 | **只由 `_ensure_master()` 建** |

**正式库修复**（`scripts/fix_3b4_2_primary_flags.py`，范围限于 41 个清盘本体）：

| 项 | 修复前 | 修复后 |
| --- | ---: | ---: |
| 基金本体 | 41 | 41 |
| 份额记录 | 63 | 63 |
| 主份额 | **63** | **41** |
| 非主份额 | 0 | **22** |
| 恰好一个主份额 | 21 / 41 | **41 / 41** |
| 违规本体 | 20 | **0** |
| 变更行数 | — | **22** |

| 审计项 | 结果 |
| --- | --- |
| 主份额代码与 `_pick_primary_code()` 一致 | ✅ |
| 跨本体错误关联 | ✅ 0 |
| 冲突 | **0** |
| 3B-4.0 的 12 只存续基金主从 | ✅ 未变 |
| 41 个清盘事件 / 90 条费率 | ✅ 不变 |
| `integrity_check` / 外键 | ✅ ok / 0 |

**幂等**：第 1 次变更 22 行，第 2 次 0 行。

**新增测试 11 项**（41 → 52），全量 **1051 passed**。

## 61. 阶段3B-4.3 场外基金数据质量与幸存者偏差验收

### 61.1 结论

> **数据层能支撑「研究性分析」，但不足以支撑「正式回测成本模拟」。**
> **场外基金回测（3B-5）被明确阻塞。**

| # | 问题 | 答案 |
| ---: | --- | --- |
| 1 | 数据有多少可信？ | 净值 **C**、清盘 **B**、费率 **C**、分红 **C 且不完整**、经理/规模 **C 但只有快照** |
| 2 | 有哪些缺失偏差？ | 6 类（见下） |
| 3 | 有幸存者偏差吗？ | **有，未消除**（41 条已知清盘，覆盖率不可量化） |
| 4 | 够做历史回测吗？ | **不够** |
| 5 | 哪些能直接用？ | 2 项直接、4 项有条件、2 项仅辅助、5 项禁止 |
| 6 | 策略研发前必须解决？ | 5 项 |

### 61.11b 统计口径修正（本体 vs 份额）

> **旧表述把「12 个份额」当成了「12 只基金」。**

| 口径 | 数量 |
| --- | ---: |
| **非清盘样本基金本体** | **9** |
| 非清盘样本**份额** | **12** |
| **已知清盘基金本体** | **41** |
| 已知清盘**份额** | **63** |
| 已确认存续本体（`active`） | **0** |

**单位规则**：`fund` = 本体（`fund_master` 一行），`share` = 份额（`fund_share_classes` 一行）。
A/C 是同一本体的两个份额。**比较必须同口径：本体比本体、份额比份额。**

正确表述：**9 个非清盘本体 vs 41 个已知清盘本体**，不是「12 : 41」。

净值表主键是 `share_class_id`，所以有净值的 12 行是**份额**，对应 **9 个本体**。

`unknown` **不等于**已确认仍在运作，也不等于已清盘——它只是没证据。

### 61.2 六类缺失

| 缺失 | 数量 |
| --- | ---: |
| 净值空值 / 重复日期 | 0 / 0 |
| 清盘缺事件日期 | **12 条** |
| 费率 rate 为 NULL | 1 条 |
| 费率推断下界 | 19 条 |
| 经理起止日期 NULL | **8 / 8** |
| 规模报告日 | 只有 **1 个** |
| 分红 | 44 条，接口返回不完整 |

### 61.3 净值：canot_verify

> **A 股交易日历只是代理，不代表基金真实净值公布日历。**

| 不能做的判断 |
| --- |
| 「某天是交易日但没净值 → 数据缺失」 |
| 「周末没净值 → 异常」 |
| 「净值序列连续」 |

最大间隔全部落在春节/国庆长假（11~12 天），属正常休市。
但**不产出任何「连续/不连续」结论**，只报告可观测事实。

### 61.4 幸存者偏差：未消除

| 项 | 状态 |
| --- | --- |
| 已知清盘本体 | 41（B 级） |
| 存续样本 | 12 |
| 覆盖率可量化 | **否**（无权威全量清单） |
| 幸存者偏差 | **not_eliminated** |

**只用存续基金回测 → 高估收益**（业绩差的已清盘被剔除），偏差大小无法量化。

### 61.5 费率：不能做历史成本模拟

| 障碍 | 后果 |
| --- | --- |
| `effective_from` 全 NULL | 不知道 2015 年是否也是这个费率 |
| `holding_days_basis` 全 NULL | 自然日还是交易日，成本差几个费率档 |
| 平台优惠 ≠ 支付宝 | 用东财优惠费率会算错 |
| C 级证据 | 非合同原文 |

**90 条 ≠ 90 条有效费率**：89 条有数值、1 条 NULL、19 条下界为推断。

### 61.6 分红：修了一个解析陷阱

> 原文 `每10份派现金0.4500元`，用 `([0-9]+(?:\.[0-9]+)?)` 直接搜数字
> 会先匹配「**每10份**」里的 `10`，把每份现金算成 1.0 元。
> 已改为匹配 `现金\s*(数字)`。

修正后 **44 条全部换算正确，0 错误**。

### 61.7 四档使用门槛

| 档 | 数量 | 内容 |
| --- | ---: | --- |
| **第一档：可直接用于研究** | 2 | 单位净值（单序列）、清盘事件清单 |
| **第二档：有条件可用** | 4 | 累计净值、申购费、年化费率、分红（仅辅助核对） |
| **第三档：仅辅助分析** | 2 | 经理历史、规模历史（**从待判定降级**） |
| **第四档：禁止用于正式回测** | 5 | 支付宝状态、支付宝费率、历史费率、净值连续性结论、完整清盘名录 |

**两处降级理由**：

1. 基金经理历史 → 第三档：起止日期全 NULL，任何「在任期内」判断都要编造时间
2. 基金规模历史 → 第三档：只有 1 个报告日，用快照做时序研究就是未来信息

### 61.8 存续 12 只为何是 unknown 而非 active

> 本项目从未取得「该基金当前仍在运作」的正式公告证据。
> 按「宁可保留 unknown 也不制造数据」的原则保持 unknown。

这是**如实记录**，不是缺失，不得为了好看改成 active。

### 61.9 交易规则必须分四类

| 类别 | 能否统一套用 |
| --- | --- |
| 行业通则 | ⚠️ 非强制 |
| 基金合同规定 | ✅ 各基金可不同 |
| 销售平台实际执行 | ✅ 各平台可不同 |
| 尚未核实 | ❌ |

**不得把 15:00 截止、T+1 确认不加区分套用到所有基金。**

### 61.10 测试

| 项 | 数量 |
| --- | ---: |
| 专项测试 | **58** |
| 全量测试 | **1109** |

### 61.11 门禁结论

| 项 | 结果 |
| --- | --- |
| `ready_for_next_stage` | **False** |
| 允许的下一步 | 3B-4.4 数据缺口补强 或 研究性分析（非回测） |
| **被阻塞** | **3B-5 场外基金回测** |

### 61.12 产物

| 项 | 路径 |
| --- | --- |
| 审计脚本 | `scripts/audit_3b4_3_data_quality.py` |
| 报告 | `reports/phase3B4_3_data_quality_report.md` |
| JSON | `reports/phase3B4_3_data_quality.json` |
| 专项测试 | `tests/test_3b4_3_data_quality.py`（58 项） |

## 62. 阶段3B-4.4 数据缺口补强与数据来源收口

### 62.1 结论

| 类别 | 数量 | 内容 |
| --- | ---: | --- |
| **实际改善** | 3 | 费率生效日、经理任职日、规模历史序列（仅描述性） |
| **仍然缺失** | 6 | 79 条费率无生效日、分红不完整、经理快照、规模公告日、清盘覆盖率、支付宝 |
| **不再追逐** | 3 | 支付宝状态、净值公布日历、清盘名录完整性 |

| 项 | 补强前 | 补强后 |
| --- | ---: | ---: |
| 有官方生效日的费率规则 | 0 | **11** |
| 有任职起始日的经理记录 | 0 | **12** |
| 规模平台观测日期数 | 1 | **138** |
| 规模记录数 | 8 | **675** |

### 62.2 数据库变更（只补列）

`migrations/phase3b4_4_evidence_columns.sql`

| 表 | 新增列 |
| --- | ---: |
| `fund_manager_history` | +5（announcement_id / announcement_url / evidence_level / change_type / detail） |
| `fund_aum_history` | +5（同上 + disclosed_at） |
| `fund_fee_rules` | +1（announcement_id） |

新增 5 个索引。**不改已有列、不删数据**，旧数据一行未动。

### 62.3 费率生效日：11 条 A- 级

| 份额 | 类型 | 生效日 | 调整前 → 调整后 |
| --- | --- | --- | --- |
| `000015` `000016` | 托管费 | 2024-09-12 | 0.20% → 0.10% |
| `000051` | 管理费 | 2024-11-22 | 0.50% → 0.15% |
| `000051` | 托管费 | 2024-11-22 | 0.10% → 0.05% |
| `000198` | 托管费 | 2025-09-23 | 0.08% → 0.07% |
| `110022` `161005` | 管理费 | 2023-07-10 | 1.50% → 1.20% |
| `110022` `161005` `161725` `012414` | 托管费 | 2023-07-10 | 0.25%/0.22% → 0.20% |

**只补年化费率**：申购费/赎回费阶梯没有「某天起生效」的官方公告，
继续保留 `effective_from = NULL`，**不倒填**。

**A- 是什么**：基金管理人公告原文，可追溯到公告 ID，
但经第三方公告库转发而非直接访问官网原件，**不冒充 A**。

### 62.4 经理任职历史：12 条 A- 级

从基金经理变更公告原文提取任职/离任日期，新增 12 条有日期的记录。
剩下 9 条仍是原有 akshare 快照（无日期），**未删除、未编造日期**。

### 62.5 规模历史：从 1 个快照到 138 个平台观测日期

| 项 | 值 |
| --- | --- |
| 记录数 | 675 |
| 平台观测日期数 | 138 |
| 最早 | 2005-12-31 |
| 最新 | 2026-09-30 |
| 证据等级 | C（天天基金规模变动页） |
| 日期语义 | **`platform_observation_date`**（平台观测日期） |
| 报告期末已核实 | **false** |
| 可作为时点特征 | **false** |

**日期不是验证过的报告期末**——138 个日期中 84 个季末、54 个不是季末。
`disclosed_at`（公告发布日期）全 NULL，公开可见时间 unknown。
页面显示 `---` 的期次跳过，**不填 0**。

### 62.6 分红：核验了但没补

| 项 | 数量 |
| --- | ---: |
| DB 分红记录 | 44 |
| 与公告匹配 | 35 |
| 公告有但 DB 缺 | 4 |
| **新增记录** | **0** |
| 日期/金额冲突 | 0 |

差异无法判定哪一方正确时，**不补入、不删改、只记录**。
分红仍**禁止用于修正历史收益**。

### 62.7 三项正式决策

| 问题 | 决策 | 不再追逐 |
| --- | --- | --- |
| 支付宝可购买状态 | 放弃自动采集，转人工核验（带时效） | ✅ |
| 净值公布日历 | 接受 `cannot_verify` | ✅ |
| 清盘名录完整性 | 记录为 `not_quantifiable` 长期限制 | ✅ |

人工核验流程字段：`fund_code` / `share_class_code` / `verified_at` / `result` /
`evidence_type` / `evidence_note`，**超过 90 天视为过期需复核**。

### 62.8 使用门槛变化

| 项 | 3B-4.3 | 3B-4.4 |
| --- | --- | --- |
| 规模历史 | 第三档（单快照） | **仍为第三档**（平台观测日期序列，仅描述性辅助分析，不可作为历史时点特征） |
| 基金经理历史 | 第三档（无日期） | **仍为第三档**（部分记录有公告任职日期、部分仍为快照，不能回填历史） |
| 年化费率 | 第二档 | 第二档，11 条有公告生效日期的记录可按生效日期切分 |
| 申购赎回阶梯 | 第二档 | 第二档，仅当前费率情景估算，不能还原完整历史成本 |
| 分红 | 第二档 | 第二档，仅辅助核对，不能用于修正历史收益 |

### 62.9 门禁

| 项 | 结果 |
| --- | --- |
| `ready_for_next_stage` | **False** |
| `ready_for_backtest` | **False** |
| **被阻塞** | **3B-5 场外基金正式回测** |
| 不得降低门槛 | **True** |

### 62.10 产物

| 项 | 路径 |
| --- | --- |
| 迁移 SQL | `migrations/phase3b4_4_evidence_columns.sql` |
| 迁移模块 | `app/fund/migration_3b4_4.py` |
| 导入模块 | `app/fund/ingest_3b4_4.py` |
| 导入脚本 | `scripts/ingest_3b4_4.py` |
| 审计脚本 | `scripts/audit_3b4_4_data_gap.py` |
| 专项测试 | `tests/test_3b4_4_data_gap.py`（76 项） |
| 报告 | `reports/phase3B4_4_data_gap_research.md` |
| JSON | `reports/phase3B4_4_data_gap_research.json` |
| 证据 | `reports/evidence/phase3b4_4/` |

### 62.11 验收修正：规模日期语义

**问题**：原报告把 675 条规模记录的日期一律当成「报告期末」，
并宣称可作为历史时点特征。但平台页面里存在大量非季末日期：

| 日期 | 类型 |
| --- | --- |
| `2010-08-23` ~ `2010-09-08` | 周频/日频（连续多日同值） |
| `2013-03-08` / `2013-03-15` / `2013-03-22` / `2013-03-29` | 周频 |
| `2013-04-03` / `2013-04-12` | 非标准季度末 |

138 个不同日期中，**84 个是季末、54 个不是**。

**修正后的语义**：

| 项 | 修正前 | 修正后 |
| --- | --- | --- |
| 日期语义 | `report_date_is_period_end=true` | **`platform_observation_date`** |
| 报告期末已核实 | true | **false** |
| 公告发布日期已核实 | false | **false** |
| 可作为时点特征 | true | **false** |
| `disclosed_at` | 全 NULL | 全 NULL（不变） |

**修正范围**：只改 `detail` 元数据，
`report_date` / `aum_total` / `shares_total` / `source` / `evidence_level` **全部不变**（有逐行比对验证）。

**实际执行**：`rows_changed = 0`——语义修正在同轮工作内已由重新导入完成，
修正脚本执行时数据库已无待修正记录。当前 675 条有证据记录的日期语义均符合新规则。

**使用门槛**：规模历史**留在第三档**（辅助研究），不升第一档。

| 用途 | 是否允许 |
| --- | --- |
| 描述性统计 | ✅ |
| 历史时点因子 | ❌ 未来信息泄漏 |
| 回测已知信息 | ❌ |

核心问题：**即使该日期是报告期末，也不代表投资者在该日已经知道这个数据。**
`disclosed_at` 全 NULL，公开可见时间 unknown。

### 62.12 11 条费率逐条核验

| 核验项 | 结果 |
| --- | --- |
| `rate_original` = 公告调整后费率 | **11 / 11** ✅ |
| `effective_from` = 公告生效日 | **11 / 11** ✅ |
| `announcement_id` 对应正确 | **11 / 11** ✅ |
| 同一公告多份额归属 | ✅ 正确 |

**重要**：数据库 `rate_original` 恰好等于公告「调整后」费率，
说明天天基金 F10 展示的是**当前有效费率**。所以：

- ✅ 可用于该生效日**之后**的成本模拟
- ❌ 生效日**之前**必须用 `detail.rate_before` 的调整前费率
- ⚠️ 直接把 `rate_original` 用于整个历史区间 = 把降费后费率倒填到降费前

## 63. 阶段3B-5.0 支付宝场外公募基金研究性分析框架设计

### 63.1 结论

> **只做框架设计与数据准入审计。不写库、不采集、不计排名、不出信号、不开回测门禁。**

| 项 | 结果 |
| --- | --- |
| 产品分类体系 | **9 类**（8 类场外 + 场内 ETF 隔离） |
| 12 个非清盘份额 | 全部可分类 |
| 41 个清盘本体 | 库字段**全 NULL**，只能依赖 3B-4.1.1 校准 JSON |
| 数据准入项 | **15** 项 |
| 研究指标 | 收益 8 + 风险 7 + 稳定性 5 |
| 评分框架 | 5 维度，**不生成排名** |
| 研究池分档 | 4 档，**按字段**给等级 |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |
| `ready_for_research_analysis` | **True** |

### 63.2 九类产品

| 类 | 默认研究池 | 关键约束 |
| --- | --- | --- |
| 普通开放式指数 | ✅ | 宽基与行业主题必须分开比较；**不含 LOF、不含 ETF 联接** |
| ETF 联接 | ✅ | 与直接指数基金可比，注明折溢价传导 |
| 主动权益 | ✅ | 必须按可验证业绩基准分组 |
| 普通债券 | ✅ | 按久期分层，字段缺失标 unknown |
| 混合债券 | ✅ | 不得与纯债混排 |
| 货币基金 | ✅ | **独立收益口径**，不得与净值型混算 |
| QDII | ❌ | 样本 0，本轮不纳入 |
| LOF | ✅ | **独立产品结构类别**，内部按 `investment_subtype` 再分 index/active；**不得**与普通开放式指数归为一类 |
| **场内 ETF** | ❌ | **仅保留历史研究，禁止混入场外池** |

### 63.3 A/C 份额规则

| 场景 | 规则 |
| --- | --- |
| 比较策略表现 | 先按 `fund_id` 归并到本体，用主份额净值代表组合 |
| 比较持有成本 | 再按份额单独比较（销售服务费、申购费差异） |
| 禁止 | 不同 `fund_id` 不得归并；货币份额不得与净值型归并 |

### 63.4 数据准入：三个关键「false」

| 数据 | 描述性 | 时点 | 成本模拟 | 禁回测 |
| --- | --- | --- | --- | --- |
| 单位净值 | ✅ | ❌ | ❌ | ❌ |
| 基金规模 | ✅ | **❌** | ❌ | **⚠️ 是** |
| 分红 | ✅ | ❌ | ❌ | **⚠️ 是** |
| 申购费/赎回费 | ✅ | ❌ | ⚠️ 仅当前情景 | **⚠️ 是** |
| 年化费率（11 条有生效日） | ✅ | ❌ | ⚠️ 仅生效日后 | **⚠️ 是** |
| 经理历史 | ✅ | ❌ | ❌ | **⚠️ 是** |
| 清盘事件 | ✅ | ✅ | ❌ | 否 |
| 支付宝状态 | **❌** | ❌ | ❌ | **⚠️ 是** |

**字段语义**：`cost_simulation_ok=true` 只表示**当前费率情景**下能估成本，
不等于能还原历史。与 `forbidden_for_backtest=true` 不矛盾。

### 63.5 五条不可越界的处理

| 禁止 | 原因 |
| --- | --- |
| 规模记录当时点因子 | 日期是 `platform_observation_date`，公开可见时间 unknown |
| 不完整分红修正历史收益 | 44 条未通过完整性验证 |
| 当前费率倒填历史 | 79 条无 `effective_from` |
| 经理快照回填历史 | 部分记录无任职日期 |
| 支付宝 unknown 当可买/不可买 | 无合法数据源 |

### 63.6 评分框架（只设计，不平分）

| 维度 | 权重 | 依据 |
| --- | ---: | --- |
| 收益 | 30% | 中长期为主，1/3 月只作参考 |
| 风险 | 30% | **与收益等权**，防纯收益排序 |
| 风险调整收益 | 20% | Sharpe/Sortino/Calmar，需无风险利率（缺失→降级） |
| 稳定性 | 15% | 防靠单月暴涨刷分 |
| 数据质量 | 5% | 门槛而非主导 |

缺失处理：关键指标缺失 → **排除**不补零；非关键缺失 → 降权并标注。

### 63.7 四档按字段给等级

| 档 | 名称 | 当前实例 |
| --- | --- | --- |
| A | 可直接用于研究 | 单位净值（单序列）、清盘清单 |
| B | 有条件用于研究 | 累计净值、11 条有生效日费率、有日期的经理记录 |
| C | 仅辅助观察 | **规模历史**、分红、79 条无生效日费率、经理快照 |
| D | 禁止相关用途 | **支付宝状态**、规模当时点因子、清盘当全量名录 |

**同一基金不同字段等级不同**。示例 `110022`：净值 A、管理费 B、销售服务费 C、支付宝 D。

### 63.8 尚未解决

| # | 问题 | 阻塞的研究能力 |
| ---: | --- | --- |
| 1 | 基准收益序列未采集 | 超额收益、与基准偏离 |
| 2 | 无风险利率未定 | Sharpe / Sortino |
| 3 | 持仓数据未采集 | 风格稳定性 |
| 4 | 久期/信用/转债字段缺失 | 债券基金分层 |
| 5 | 清盘本体分类字段全 NULL | 清盘样本入池 |
| 6 | 净值公布日历未知 | 所有指标带 cannot_verify |

### 63.9 产物

| 项 | 路径 |
| --- | --- |
| 框架报告 | `reports/phase3B5_0_research_framework.md` |
| 框架 JSON | `reports/phase3B5_0_research_framework.json` |
| 准入矩阵 | `reports/phase3B5_0_data_admission_matrix.md` |
| 准入 JSON | `reports/phase3B5_0_data_admission_matrix.json` |
| 审计脚本 | `scripts/audit_3b5_0_research_framework.py`（只读） |
| 专项测试 | `tests/test_3b5_0_research_framework.py`（62 项） |

### 63.10 验收修正：LOF 分类优先级与统计口径

### LOF 分类修正

**问题**：`161725 招商中证白酒指数(LOF)` 被判成 `ordinary_index`——
因为代码先看 `is_index_fund=1`，把指数型 LOF 归进了普通开放式指数基金。

**修正**：LOF 是**产品结构**类别，优先级高于「是否跟踪指数」。

| 代码 | 名称 | 修正前 | 修正后 product_class | 修正后 subtype |
| --- | --- | --- | --- | --- |
| `161725` | 招商中证白酒指数(LOF) | ~~`ordinary_index`~~ | **`lof`** | **`index`** |
| `161005` | 富国天惠成长混合(LOF) | `lof` | **`lof`** | **`active`** |

新增字段 `investment_subtype`：LOF 内部再分 index / active。

**普通开放式指数基金当前只剩 `000478`**（非 ETF 联接、非 LOF）。
ETF 联接分类不受影响：`000051` / `007300` / `110020` 仍为 `etf_linked`。

### 统计口径统一（9 / 12 / 41 / 43）

| 口径 | 数量 | 定义 |
| --- | ---: | --- |
| 非清盘基金**本体** | **9** | `lifecycle_status='unknown'` |
| 非清盘基金**份额** | **12** | 上述 9 个本体下的 `fund_share_classes` |
| 已知**场外清盘基金本体** | **41** | 排除 2 条场内 ETF 后的场外结构 |
| **公告候选事件** | **43** | 3B-4.1.1 校准 JSON 全部候选（含 2 条场内 ETF） |

> **本体比本体、份额比份额、公告候选比公告候选。四者单位不同，不得混用。**

原报告「11 个非清盘份额」是错的，已改为 **9 本体 / 12 份额**。

### 43 与 41 的统计口径限制

| 维度 | 分布 | 合计 | 口径 |
| --- | --- | ---: | --- |
| `product_structure` | 27 + 3 + 11 + **2(etf)** | **43** | 全部公告候选 |
| `product_structure`（排除 ETF） | 27 + 3 + 11 | **41** | 场外本体 |
| `investment_type` | 8 + 15 + 18 + 1 + 1 | **43** | **全部公告候选（含 2 条 ETF）** |

🔴 **投资类型分布是 43 条公告候选口径，不是 41 个场外本体口径。**

校准 JSON **没有提供**「投资类型 × 是否场内 ETF」交叉表，
因此**无法**准确拆出「41 个场外本体的投资类型分布」。
强行拆分就是把 2 条 ETF 的投资类型随意摊到某一类上，属于**编造**。
**本阶段不做这种拆分，只标注口径限制。**

## 64. 阶段3B-5.1 研究性分析引擎 V1.0

### 64.1 用法

```bash
python -m app.fund.research --list            # 列出研究池
python -m app.fund.research --code 110022     # 单只基金完整报告
python -m app.fund.research --all             # 全部研究池
python -m app.fund.research --all --json out.json
python -m app.fund.research --codes-file my_funds.txt --json my.json
```

**只读**：不写库、不采集、不排名、不出信号。

### 64.2 模块

| 模块 | 职责 |
| --- | --- |
| `app/fund/research/data_access.py` | 研究池加载、净值序列、货币序列、费率、质量审计 |
| `app/fund/research/indicators.py` | 窗口收益、年化、回撤、波动率、滚动稳定性 |
| `app/fund/research/classification.py` | 九类产品、LOF 独立结构、宽基/行业、同类组键 |
| `app/fund/research/fees.py` | 费率边界、阶梯费率、份额成本对比 |
| `app/fund/research/engine.py` | 单基金报告、A/C 归并、同类分析 |
| `app/fund/research/__main__.py` | CLI 入口 |

### 64.3 关键口径

| 项 | 口径 |
| --- | --- |
| 窗口收益 | 自然日窗口，**端点必须精确命中**，不向前后找近似值 |
| 缺口 | 超过 15 天拒绝计算，**不跨越缺口** |
| 年化收益 | `(end/start)^(365.25/span_days) - 1`，不足 1 年不输出 |
| 波动率年化 | 需「1 天间隔 ≥60% + 无超阈值缺口 + 跨度 ≥1 年」，按**观测频率**年化，**不硬套 252** |
| 回撤修复 | 谷底到恢复前高的自然日数；未恢复标 `ongoing` |
| Sharpe | **不输出**（无风险利率缺失）；可输出 `zero_hurdle_sharpe` 并标注 |
| 货币基金 | 独立口径（万份收益/7日年化），**不参与净值型指标** |
| 缺失值 | **不填 0**，返回 `insufficient_data` + 原因 |

### 64.4 实测结果（真实运行）

| 项 | 值 |
| --- | --- |
| 研究池 | 12 份额 / 9 本体 |
| 同类成员 | **9**（按 `fund_id` 去重，A/C/E 只算一个本体） |
| 同类组 | 8 个（按跟踪指数/基准族分组） |
| 场内 ETF 混入 | **否** |
| 生成排名 | **否** |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |

### 64.5 不可算指标

| 指标 | 原因 |
| --- | --- |
| 超额收益 / IR / Beta | 无基准收益序列 |
| 风格稳定性 | 无持仓数据 |
| 常规 Sharpe / Sortino | 无风险利率缺失 |
| 完整历史成本模拟 | 79 条费率无生效日 + 阶梯不完整 |
| 支付宝费率 / 可购买状态 | 无公开合法数据源 |

### 64.6 产物

| 项 | 路径 |
| --- | --- |
| 引擎报告 | `reports/phase3B5_1_research_engine_report.md` |
| 引擎 JSON | `reports/phase3B5_1_research_engine_report.json` |
| 样本运行结果 | `reports/phase3B5_1_sample_run.json` |
| 专项测试 | `tests/test_3b5_1_fund_research.py`（103 项） |

### 64.7 验收修正（3B-5.1 修正轮）

### 同类分析按本体去重

`peer_analysis()` 现在接收 `merge_by_fund()` 的**本体级**结果，
内部再用 `seen[fund_id]` 双保险去重。**12 份额 → 9 个同类成员**。

| 项 | 规则 |
| --- | --- |
| 代表份额 | ① 主份额且有净值 → ② 记录最多者 → ③ `insufficient_data` |
| 记录原因 | `representative_reason` 明确写出为什么选它 |
| 费用比较 | **保留份额维度**，`share_count` 仍是全部份额 |
| 记录数未知 | 不当 0，原因里说明「数据充分性未确认」 |

### 分组依据可验证基准

新增 `normalize_benchmark()`：只做保守标准化，**不新增未验证映射表**。

| 情况 | 结果 |
| --- | --- |
| 已知写法完全一致 | `high` |
| 含唯一指数族 | 取该族（加权复合降 `medium`） |
| 含多个指数族 | **`unknown`**，不强行归组 |
| 为空 / 认不出 | `unknown` |

分组键：`{产品类}|{宽基或行业}|{指数族}`。
**沪深300 与 中证500 已分到不同组**。
债券久期/信用/转债全 `unknown`，不解释成相同风险。

### 缺口安全统一

| 指标 | 修正 |
| --- | --- |
| 年化收益 | 查区间缺口 + 空值，命中即 `insufficient_data` |
| 滚动稳定性 | 每窗口独立查缺口/空值（缺口用**区间相交**判断），跳过并计数 |
| 最大回撤 | 各段**独立**算，全区间 = `max(各段)`；标 `degraded` + `complete_interval=false` |
| 回撤修复 | 只在同一连续段内找 |
| Calmar | 继承底层状态，底层降级则降级 |

阈值仍为 `MAX_GAP_DAYS_FOR_RETURN = 15`，全部指标共用同一入口。

### 64.8 最终验收修正（3B-5.1 终轮）

### 最大回撤不再跨段重算

上一版切段后又把 segments 拼回 `pts` 重算 peak/worst，前段高点会污染后段。

| 项 | 修正后 |
| --- | --- |
| 每段回撤 | **独立**计算 |
| 全区间值 | `max(各段最大回撤)`，**不拼接重算** |
| 并列规则 | 取**时间最早**的段 |
| `detail` | 严格来自产生最大回撤的那段 |
| `recovery` | 只在**同一段内**找，不跨段 |

反例：段1 峰值 2.0→1.5（25%）、段2 从 1.0→0.8（20%）→ 正确 **25%**，
错误拼接会得到 60%。

### 滚动窗口缺口用区间相交

```python
gap['from'] < window_end and gap['to'] > window_start
```

覆盖：完全在窗内 / 从外延伸到窗内 / 从内延伸到窗外 / 完全覆盖窗口 / 不相交（保留）。

### 指数类 tracking_index 优先

| 产品类 | 分组依据 |
| --- | --- |
| 普通指数 / ETF联接 / 指数型LOF | **tracking_index 优先**，不可识别才回落 benchmark |
| 主动权益 | 只用 benchmark |

新增 `grouping_source` 与 `tracking_fallback_reason` 记录实际依据。
**不根据基金名称猜测跟踪指数**。

## 65. 阶段3B-5.2 自选基金代码查询 V1.0

### 65.1 CLI

```bash
python -m app.fund.research --code 110022     # 份额代码
python -m app.fund.research --code 161725     # 本体代码 → 全部份额
python -m app.fund.research --codes-file my_funds.txt --json my.json
```

`--code` 现在**直接查库**，不再限于默认 12 份额研究池。

`--codes-file` 一行一个 6 位代码，支持 `#` 注释与空行；
非法行跳过并提示；重复代码去重；**单只失败不影响其他基金**。

### 65.2 查询状态

| 状态 | 含义 |
| --- | --- |
| `found` | 命中且属于场外研究池 |
| `not_found` | 数据库中不存在 |
| `invalid_code` | 非 6 位数字 |
| `excluded_product` | 场内 ETF / QDII 等排除 |
| `terminated` | 库内标记已终止 |
| `no_nav_data` | 有基金信息但无净值 |

**没有任何状态把「没数据」伪装成「净值为 0」。**

### 65.3 数据覆盖摘要

每个份额都输出 `coverage`：净值记录数、起止日期、空值数、非正净值数、
货币收益行数、费率规则数、有生效日的费率数、支付宝状态（恒 `unknown`）。

### 65.4 实测

| 代码 | 状态 | 份额 |
| --- | --- | ---: |
| `110022` | found | 1 |
| `161725` | found | 2 |
| `012414` | found | 2（同 161725 本体） |
| `000007` | terminated | 1 |
| `000198` | found（货币） | 1 |
| `999999` | not_found | 0 |

12 份额 / 9 本体回归不变。

### 65.5 产物

| 项 | 路径 |
| --- | --- |
| 查询模块 | `app/fund/research/lookup.py` |
| 报告 | `reports/phase3B5_2_code_lookup_report.md` |
| 报告 JSON | `reports/phase3B5_2_code_lookup_report.json` |
| 专项测试 | `tests/test_3b5_2_code_lookup.py`（32 项） |

## 66. 阶段3B-5.3 自选基金受控接入 V1.0

### 66.1 查询与采集分离

| 命令 | 是否写库 |
| --- | --- |
| `python -m app.fund.research --code` | **否**（永远只读） |
| `python -m app.fund.ingest_user_funds --code` | **是**（唯一写入入口） |

### 66.2 用法

```bash
python -m app.fund.ingest_user_funds --code 012346
python -m app.fund.ingest_user_funds --codes-file my_funds.txt
python -m app.fund.ingest_user_funds --codes-file f.txt --json out.json
python -m app.fund.ingest_user_funds --code 012346 --dry-run
```

### 66.3 接入状态

| 状态 | 含义 |
| --- | --- |
| `ingested` | 接入成功 |
| `already_present` | 已存在，不重复写 |
| `not_found` | 接口无该代码 |
| `invalid_code` | 非 6 位数字 |
| `excluded_product` | 场内 ETF / QDII 拒绝 |
| `failed` | 失败，**不留半成品** |
| `timeout` | 接口超时 |

### 66.4 写入安全

| 措施 | 实现 |
| --- | --- |
| 接入前备份 | `data/backups/fund_agent_before_3b5_3_*.db` |
| 前后指纹 | `fingerprint_before` / `fingerprint_after` |
| 幂等 | 已存在返回 `already_present` |
| 不留半成品 | 先全取到内存，再由**同一 SQLite 事务**写入，失败整体 ROLLBACK |
| 无 Schema 变更 | 复用现有列 |
| 不删历史 | 只追加质量警告 |

### 66.5 实测

| 代码 | 名称 | 分类 | 净值行 |
| --- | --- | --- | ---: |
| `000961` | 天弘沪深300ETF联接 | `etf_linked` | 2882 |
| `012344`/`012345` | 嘉实领先优势混合 A/C | `active_equity` | 1277 |
| `012346`/`012347` | 易方达港股通成长混合 A/C | `active_equity` | 1230 |

5 份额 / 3 本体；A/C 正确归入同一本体。

### 66.6 产物

| 项 | 路径 |
| --- | --- |
| 接入包 | `app/fund/ingest_user_funds/` |
| 报告 | `reports/phase3B5_3_user_ingest_report.md` |
| 报告 JSON | `reports/phase3B5_3_user_ingest_report.json` |
| 专项测试 | `tests/test_3b5_3_user_ingest.py`（27 项） |

### 66.7 修正轮 3B-5.3.1：事务原子性与内容指纹

### 真正的原子事务

原实现 5 个仓储各自开连接、各自 commit，某步失败会留下已提交的部分写入。

修正：

```python
# app/fund/repo_base.py
@contextmanager
def use_conn(db_path=None, conn=None):
    if conn is not None:
        yield conn          # 复用外部连接，不 commit/rollback
        return
    with get_connection(db_path) as own:
        yield own
```

5 个写入方法（`upsert_master` / `upsert_share_class` / `upsert_nav_batch` /
`upsert_dividend_batch` / `record`）增加可选 `conn` 参数。
接入器自己 `BEGIN IMMEDIATE` → 全部成功才 `COMMIT` → 任一异常 `ROLLBACK`。

**不传 `conn` 时行为完全不变**，其他模块事务语义未受影响。

### 真实内容指纹

旧实现只算「行数 + 字段长度之和」，同长度修改会漏检。
新实现逐行逐列稳定序列化后算 SHA256：

| 值 | 序列化 |
| --- | --- |
| `None` | `@NULL` |
| `1` | `int:1` |
| `1.0` | `float:1.0` |
| `"1"` | `str:1` |

覆盖全部 10 张 `fund_*` 表；排除 `ingested_at` 等采集时间列。
**行数不变、字段长度不变、只改一个值**，指纹也会变。

### A/C 归组收紧

| 场景 | 结果 |
| --- | --- |
| 同名 + 同公司 | 合并 |
| 同名 + 不同公司 | **不合并** |
| 同名 + 一方公司为空 | **不合并**，标「需人工核验」 |

### 修复前后数据一致

| 时点 | 内容指纹 |
| --- | --- |
| 修复前 | `0c867be4…b9658` |
| 修复后 | `0c867be4…b9658` |
| 备份库 | `0c867be4…b9658` |

**三者完全一致** → 代码修复未触碰任何正式数据。

### 66.8 修正轮 3B-5.3.2：外键约束与序列化

### 事务连接启用外键

`_open_tx()` 现在在 `BEGIN IMMEDIATE` **之前**执行：

```python
conn.execute("PRAGMA foreign_keys = ON")
enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
if int(enabled) != 1:
    conn.close()
    raise RuntimeError("未能启用外键约束，拒绝继续接入")
conn.execute("BEGIN IMMEDIATE")
```

**只改本连接**，全局 `get_connection()` 仍为 SQLite 默认（OFF），有测试断言。

验证：插入不存在的 `fund_id` 对应份额 → **`sqlite3.IntegrityError`**，
且整只基金回滚。

### 指纹序列化无歧义

旧实现用 `|` 拼接，字段值含 `|` 会撞库：

```
("a|b", "c")  →  str:a|b|str:c
("a", "b|c")  →  str:a|str:b|c
```

新实现改为 JSON 数组 + 类型标签，由 JSON 负责转义：

```python
json.dumps([list(_stable_value(v)) for v in values],
           ensure_ascii=False, separators=(",", ":"))
```

| 值 | 序列化 |
| --- | --- |
| `None` | `["null",null]` |
| `1` | `["int",1]` |
| `1.0` | `["float","1.0"]` |
| `"1"` | `["str","1"]` |
| `b"1"` | `["bytes","31"]` |

`("a|b","c")` 与 `("a","b|c")` 现在**必然产生不同字节串**。

### 指纹值变化说明

算法从 `|` 拼接改为 JSON 数组后，指纹值本身会变：

| 时点 | 指纹 |
| --- | --- |
| 3B-5.3.1 算法 | `0c867be4…b9658` |
| 3B-5.3.2 算法（当前库） | `f71c36f9…d635b` |
| 3B-5.3.2 算法（备份库） | `f71c36f9…d635b` |

**同一算法下当前库与备份库完全一致** → 数据未变，只是算法换了。

## 67. 阶段3B-5.4 多类型场外基金真实接入 V1.0

### 67.1 覆盖范围

| 类型 | 真实样本 | 分类 | 净值行 |
| --- | --- | --- | ---: |
| 普通指数基金 | `050002` 博时裕富沪深300指数A | `ordinary_index` | 5644 |
| ETF 联接基金 | `001052` 华夏中证500ETF联接 | `etf_linked` | 2802 |
| ETF 联接 A/C | `001548`/`001549` 天弘上证50ETF联接 | `etf_linked` | 2764 |
| 主动权益基金 | `001938` 中欧时代先锋 | `active_equity` | 2678 |
| 混合型基金 | `519066` 汇添富蓝筹稳健混合 | `active_equity` | 4461 |
| 债券 A/C | `000032`/`000033` 易方达信用债 | `bond_pure` | 3288 |
| 货币基金 | `000509` 广发钱袋子货币 | `money_market` | 4676 |

9 份额 / 7 本体；六类全部真实接入；两组真实 A/C 配对。

### 67.2 关键口径

| 检查 | 结果 |
| --- | --- |
| 货币基金是否混用净值口径 | **否**，`uses_unit_nav=False`，净值指标 `not_applicable` |
| A/C 是否算成两只基金 | **否**，按 `fund_id` 去重 |
| 数据不足是否硬算 Sharpe | **否**，`not_available`，不把 0 当无风险利率 |
| 有缺口是否硬算年化 | **否**，`insufficient_data` |
| 是否伪造支付宝状态 | **否**，恒 `unknown` |

### 67.3 数据库

| 项 | 值 |
| --- | --- |
| 备份 | `data/backups/fund_agent_before_3b5_4_before_20261123_132335.db` |
| `integrity_check` | ok |
| `foreign_key_check` | 0 违规 |
| 清盘 41 / 事件 49 / 费率 90 / 经理 21 / 规模 683 | **全部不变** |

### 67.4 产物

| 文档 | 路径 |
| --- | --- |
| 候选审计 | `reports/phase3B5_4_candidate_audit.md` |
| 接入报告 | `reports/phase3B5_4_ingestion_report.md` |
| 研究验证 | `reports/phase3B5_4_research_validation_report.md` |
| 测试报告 | `reports/phase3B5_4_test_report.md` |
| 审计脚本 | `scripts/audit_3b5_4_candidates.py` |
| 专项测试 | `tests/test_3b5_4_multi_type.py`（35 项） |

### 67.5 顺带修复

`compute_money_indicators()` 原未接收 `db_path`，导致分析临时库时
货币统计回落到正式库（临时库货币统计恒为空）。
已补 `db_path` 透传，并新增 2 项隔离回归测试。

### 67.6 收益口径（重要）

净值型基金的**收益、年化收益、最大回撤、波动率**全部使用
**`acc_nav`（累计净值）**，不使用 `unit_nav`。

| 项 | 实际取值 |
| --- | --- |
| `return_field` | **`acc_nav`** |
| `unit_nav` 角色 | **独立对照**，位于 `indicators_unit_nav`，标注「不是总回报」 |
| 分红修复 | **未使用**（`dividend_repair_used=false`），累计净值用原始数据 |
| 货币基金 | **独立口径**：`per_10k_yield` / `seven_day_annual`，不使用任何净值口径 |

依据：`engine.py` `compute_nav_indicators(series, field_name="acc_nav")`，
`unit_nav` 单独再算一遍放在 `indicators_unit_nav` 供对照。

实测差异（`050002` 近1年）：`acc_nav` = -4.0993%，`unit_nav` = -8.9623%，
两者相差 4.8630 个百分点 —— 代码确实是各走各的，未混用。

## 68. 阶段3B-5.5 数据质量分级与指标可信度 V1.0

### 68.1 三条铁律

| # | 规则 |
| ---: | --- |
| 1 | 质量等级**只看数据**，绝不看收益（函数不接收收益率参数） |
| 2 | 指标级评级**独立**于基金级（13 项各自评级） |
| 3 | 算不出来就标 D / `not_available`，**绝不填 0** |

### 68.2 四级定义

| 级别 | 含义 |
| --- | --- |
| A | 数据质量较好，可支持常规描述性研究 |
| B | 有条件可用，存在明确限制 |
| C | 证据不足，只能展示有限描述性信息 |
| D | 数据不合格，不应生成相关研究结论 |
| `not_applicable` | 产品类型上不适用（如货币基金 × 净值型指标），**不等于 D** |

### 68.3 三个概念必须分开

| 概念 | 体现位置 |
| --- | --- |
| 基金本身表现差 | 只在 `7_return_risk` 数值，**不影响任何等级** |
| 基金数据质量差 | `4_data_quality_level` |
| 指标计算条件不足 | `5_indicator_grades` 各指标的 D / `not_available` |

### 68.4 13 项指标

`ret_1m` / `ret_3m` / `ret_6m` / `ret_12m` / `ret_36m` /
`annualized_return` / `max_drawdown` / `daily_volatility` /
`annualized_volatility` / `sharpe` / `excess_return` /
`peer_comparison` / `share_cost_comparison`

每项输出 `value` / `status` / `quality_level` / `evidence` / `limitation` / `reason`。

### 68.5 关键约束

| 约束 | 实现 |
| --- | --- |
| 分段回撤不冒充全区间回撤 | `degraded=true` + `complete_interval=false`，评 **B** 并注明可能低估 |
| 日波动取 `daily_vol` | 不能用 `value`（可能是年化值） |
| Sharpe 无利率则拒算 | 恒 `D` / `not_available`，`value=null` |
| 超额收益无基准则拒算 | 恒 `D` / `not_computed` |
| 同类样本不足则拒比 | 本体 < 2 → `D`；2~4 → `C`；**永远不到 A** |
| 分组依据不可验证则拒比 | `verifiable_group=False` → **`D`**，样本再多也不放行 |
| 基准族 unknown 则拒比 | `bond_pure|unknown` / `active_equity|unknown` → **`D`** |
| 货币基金免基准检查 | `money_market` 按产品类型分组，但**永不与净值型混组** |
| 年化证据必须有真实区间 | 节点无日期时用质量报告 `date_min/date_max` 补充；无日期 → `D` |
| A/C 成本不给结论 | 费率不全 → `D`；齐全也只能 `C`；`buy_sell_conclusion=null` |
| 货币基金独立 | 12 项 `not_applicable`，`money_market` 独立分组 |

### 68.6 真实样本结果

| 代码 | 类型 | 数据质量 | 可算 | 不适用 | 算不出 |
| --- | --- | --- | ---: | ---: | ---: |
| `050002` | 普通指数 | **B** | 7 | 1 | 5 |
| `001052` | ETF联接 | **B** | 9 | 1 | 3 |
| `001938` | 主动权益 | **B** | 10 | 1 | 2 |
| `000032` | 债券 | **B** | 10 | 0 | 3 |
| `000509` | 货币 | **B** | 1 | 12 | 0 |
| `001548` | ETF联接A | **B** | 9 | 0 | 4 |
| `001549` | ETF联接C | **B** | 9 | 0 | 4 |

### 68.7 产物

| 文档 | 路径 |
| --- | --- |
| 质量框架 | `reports/phase3B5_5_quality_framework.md` |
| 指标可信度 | `reports/phase3B5_5_indicator_quality.md` |
| 同类比较 | `reports/phase3B5_5_peer_comparison.md` |
| 报告示例 | `reports/phase3B5_5_practical_report_examples.md` |
| 测试报告 | `reports/phase3B5_5_test_report.md` |
| 分级模块 | `app/fund/research/quality.py` |
| 报告组装 | `app/fund/research/practical_report.py` |
| 专项测试 | `tests/test_3b5_5_quality_framework.py`（60 项） |

### 68.8 修正轮 3B-5.5.1

修正验收发现的两个问题，只动评级层，不动计算。

**问题1：同类分组可验证性漏洞（阻断）**

`grade_peer_comparison()` 读了 `verifiable_group` 却没用；组键只判是否以
`unknown` 开头，导致 `bond_pure|unknown` 被当有效分组（评 C）。

修正后判定顺序：

```
① money_market → 产品类型独立分组，跳过基准检查
② verifiable_group is False → D（样本再多也不放行）
③ 组键缺失 → D
④ 基准/指数族 unknown（含 bond_pure|unknown / active_equity|unknown）→ D
⑤ 依据通过后才看样本量：1→D，2~4→C，≥5→B
```

| 样本 | 修复前 | 修复后 |
| --- | --- | --- |
| `000032`（`bond_pure|unknown`） | C | **D** `no_verifiable_group` |
| `active_equity|unknown` | 可能被当有效 | **D** |
| `money_market` | 与其他指标同路径 | C（<5）/ B（≥5），免基准检查 |

**问题2：年化收益证据日期缺失**

`001052` 年化状态 ok、等级 A，但证据写的是 `起始 None，结束 None`。

原因：`_annualized()` 只返回 `span_days/years/method`，不返回 `start_date/end_date`。

修正：

| 情况 | 处理 |
| --- | --- |
| 节点有日期 | 优先用节点 |
| 节点无日期 | 用质量报告 `date_min/date_max` 补充 |
| 无任何可验证日期 | **D** `insufficient_evidence`，不编造 |
| `status=ok` 但 `value=None` | **D** `invalid_result`，不给 A |

**为什么可用质量报告日期**：`_annualized()` 取 `points[0].nav_date` 与
`points[-1].nav_date`，而 `QualityReport.date_min/date_max` 正是这两个值，
属于等价替换，不是编造。

修复后 `001052`：

```
成立以来年化 -0.025595，按实际自然日间隔复合年化；
计算区间 2015-05-05 → 2026-11-20，跨度 4217 天
（计算区间取自净值序列首尾，与质量报告一致）
```

## 69. 阶段3B-6.0.1 业绩比较基准与指数数据源审计

### 69.1 四类证据严格区分（核心规则）

| 类型 | 含义 | 强度 | 库内数量 |
| --- | --- | --- | ---: |
| `contract_benchmark` | 合同约定的业绩比较基准 | 强 | **0** |
| `contract_tracking_index` | 合同约定的跟踪指数 | 强 | **0**（字段全 NULL） |
| `platform_benchmark_text` | 第三方平台展示文字 | 中 | **18** |
| `inferred_from_name` | 仅凭名称推测 | 弱，**禁止当可验证基准** | **0** |

库内 `benchmark` 来源是 `akshare.fund_individual_basic_info_xq`（第三方聚合），
**未经合同原文核对**，因此统一标为平台转述。

### 69.2 全量审计结果

| 项 | 数值 |
| --- | ---: |
| 扫描本体 | **60**（含 41 清盘，全量非抽样） |
| 扫描份额 | **89** |
| 有 benchmark 文字 | 18 |
| 有 tracking_index | **0** |
| 指数代码可验证 | 12 |
| 复合基准 | **15** |
| 无任何基准 | 42 |

### 69.3 复合基准绝不退化成单指数

判定为复合的任一条件：

1. 按 `+` 拆出 ≥2 项；
2. 识别出 ≥2 个成分；
3. 存在无法识别的成分。

复合时 `single_index_family` 恒为 `None`。

例：`161005` =「沪深300×70% + 中债综合全价×25% + 同业存款×5%」，
只取沪深300 等于抹掉 30% 的其他成分，属口径伪造。

### 69.4 指数数据源实测结论

| 数据源 | 结论 |
| --- | --- |
| 中证官网 `stock_zh_index_hist_csindex` | ✅ **主源**，含 OHLC，2004 至今 |
| 新浪 `stock_zh_index_daily` | ⚠️ 交叉校验（沪深300 可追到 2002） |
| 东财 `index_zh_a_hist` | ❌ 实测 `Push2RateLimitError`，不用 |
| 中债 `bond_new_composite_index_cbond` | ✅ 但只有收盘值 |
| 恒生 `stock_hk_index_daily_sina` | ⚠️ **只有 2013-08-20 起** |

### 69.5 无风险利率（只审计，不改 Sharpe）

| 源 | 期限 | 结论 |
| --- | --- | --- |
| `bond_china_yield` | 3M~30Y | ✅ 期限最完整，**首选** |
| `bond_zh_us_rate` | 2/5/10/30Y | ✅ 但无 1 年期 |
| `macro_china_shibor_all` | O/N~1Y | ⚠️ 货币市场利率，非严格无风险 |

**期限必须匹配**：2026-11-20 实测 10年-2年 利差 **0.3473 个百分点**，
足以让 Sharpe 相差 10%+。禁止统一用 10 年期、禁止用 0 代替。

Sharpe 仍保持 `not_available`，本轮不动。

### 69.6 同类研究池现状

| 项 | 数值 |
| --- | ---: |
| 研究池本体 / 份额 | **19 / 26** |
| 同类组 | 13 |
| **≥5 本体的组** | **0** |
| 最大组 | 3（`etf_linked|broad|沪深300`）|
| 库内基准收益序列 | **0** |

A/C 5 组全部正确归并（26 份额 → 19 本体）。

### 69.7 产物

| 文档 | 路径 |
| --- | --- |
| 基准覆盖度 | `reports/phase3B6_0_1_benchmark_coverage.md` |
| 指数数据源 | `reports/phase3B6_0_1_index_data_source_audit.md` |
| 无风险利率 | `reports/phase3B6_0_1_risk_free_rate_audit.md` |
| 研究池现状 | `reports/phase3B6_0_1_peer_universe_audit.md` |
| 测试报告 | `reports/phase3B6_0_1_test_report.md` |
| 审计模块 | `app/fund/research/benchmark_audit.py` |
| 数据源脚本 | `scripts/audit_3b6_0_1_index_sources.py` |
| 专项测试 | `tests/test_3b6_0_1_benchmark_audit.py`（33 项） |

### 69.8 修正轮 3B-6.0.1.1

修正验收发现的两个证据准确性问题。

**问题1：指数验证范围失真**

原报告登记 10 个指数代码，但只对其中 6 个执行过历史调用，其余靠「代码已登记」推断。

修正后**全部 10 个逐一实调**，并严格区分三层状态：

| 状态 | 含义 | 结果 |
| --- | --- | --- |
| `code_mapping_verified` | 代码 ↔ 名称映射已核实 | **10/10** |
| `history_api_verified` | 历史接口实际调用成功 | **10/10** |
| `history_quality_verified` | 通过日期/重复/空值/数值检查 | **10/10** |
| **整条基金基准可复现** | 所有成分序列齐全 | **0 只** |

**指数验证 ≠ 基准可复现**：15 只复合基准里，债券成分无代码、现金序列未接入，一只都拼不出。

**问题2：中债历史覆盖结论夸大**

原结论基于 `2020-01-02 ~ 2020-01-10` 的 21 行，却写成「可取」。

分段实测 9 个窗口后：

| 项 | 结果 |
| --- | --- |
| 单次 11 年请求 | ❌ 返回 **0 行** |
| 2005 整年 | ❌ 返回 0 行 |
| 按年分段（2006~2026） | ✅ 可覆盖 |
| **`history_coverage_verified`** | **false** |

仍保留为候选数据源，但不宣称长期覆盖已验证。

**新发现：基线占位行**

中证官网接口无论 `start_date` 填什么，首行常是 `2004-01-01` 基线值，
而指数真实成立日可能晚得多（如 `399997` **价格序列**实际 2009-01-05 才有数据；
其**全收益序列** `H20539` 起点为 2008-12-31，见 77.12）。

判定规则：首行与第二行间隔 ≥365 天 **或** 首行不在交易日历。

不排除基线行的话，`399997` 会被误报为「缺 1214 个交易日」——实际上那段时间指数还没发布。

**质量检查分级**：

| 类别 | 项 | 失败后果 |
| --- | --- | --- |
| **硬性** | 日期解析/升序/重复/空日期/收盘空值/数值/起止/基线行 | 不能标 `quality_verified` |
| **警告** | OHLC 部分空值、缺口 | 如实记录，不阻断 |

OHLC 缺失只算警告的理由：指数基准只用于**收盘收益**，收盘完整即可。

**缺口处理**：优先用项目 `trade_calendar` 表作日历代理，`is_real_missing` **恒为 `null`**，
不填充、不插值、不当 0 收益。港股通指数因交易日与 A 股不同，缺口可能只是日历不匹配。

## 70. 阶段3B-6.0.2 指数与基准数据层

### 70.1 新增 6 张独立表

| 表 | 用途 |
| --- | --- |
| `index_master` | 指数基础信息（含收益口径） |
| `index_ingest_runs` | 采集审计 |
| `index_daily` | 指数历史行情 |
| `index_quality_checks` | 质量检查记录 |
| `benchmark_composite` | 复合基准 |
| `benchmark_composite_component` | 复合基准成分 |

**指数历史与基金净值物理隔离**：`index_daily` 与 `fund_nav_daily` 无任何关系，
也没有 `nav` / `accumulated_nav` 列。

### 70.2 接入 10 个中证指数

> 📌 **本节是 2026-11-20 的数据库入库快照（3B-6.0.2 时点），不是当前审计结论。**
> 当前权威结论见 **77.10 节**（探测至 2026-11-23）。
> 两者行数/截止日期不同属正常：数据库尚未重灌，审计用的是实时接口。

| 代码 | 名称 | 行数 | 有效起 | 有效止 | 质量 |
| --- | --- | ---: | --- | --- | --- |
| `000300` | 沪深300指数 | 5,558 | 2004-01-02 | 2026-11-20 | B |
| `000905` | 中证小盘500指数 | 5,317 | 2004-12-31 | 2026-11-20 | B |
| `000906` | 中证800指数 | 5,317 | 2004-12-31 | 2026-11-20 | B |
| `000016` | 上证50指数 | 5,559 | 2004-01-02 | 2026-11-20 | B |
| `399997` | 中证白酒指数 | 4,345 | 2009-01-05 | 2026-11-20 | B |
| `H30184` | 中证全指半导体产品与设备指数 | 5,316 | 2005-01-04 | 2026-11-20 | B |
| `000942` | 中证内地消费主题指数 | 5,317 | 2004-12-31 | 2026-11-20 | B |
| `000012` | 上证国债指数 | 5,558 | 2004-01-02 | 2026-11-20 | B |
| `000922` | 中证红利指数 | 5,317 | 2004-12-31 | 2026-11-20 | B |
| `930930` | 中证港股通综合指数 | 2,999 | 2014-11-14 | 2026-11-20 | B |

合计 **50,603 行**（数据库快照，2026-11-20）。

**与 77.10 的差异说明**：

| 项 | 70.2（数据库快照） | 77.10（当前审计） |
| --- | --- | --- |
| 数据截止 | 2026-11-20 | **2026-11-23** |
| `399997` 序列 | 价格指数 `399997` | **全收益 `H20539`** |
| `399997` 行数 | 4,345 | **4,347** |
| `399997` 真实起点 | 2009-01-05 | **2008-12-31** |

**两者不是矛盾，是不同时点 + 不同序列。引用时须说明来源。**

### 70.3 收益口径全部 unknown

| 口径 | 指数数 |
| --- | ---: |
| `price_return` | 0 |
| `total_return` | 0 |
| `net_total_return` | 0 |
| **`unknown`** | **10** |

来源只提供指数**点位**，不声明是否全收益口径；
沪深300 等同时存在价格版与全收益版，接口无字段区分。
按「不得仅凭名称或代码推断全收益口径」，一律标 `unknown`。

**后果：这 10 个指数只能用于价格走势展示，不能用于正式总收益超额比较。**

### 70.4 质量规则

| 类别 | 项 | 失败后果 |
| --- | --- | --- |
| **硬性** | 日期解析/升序/重复/空日期/收盘空值/数值/起止/基线行 | 拒绝入库 |
| **警告** | OHLC 部分空值、疑似缺口 | 入库但降级 |

全部 10 个指数**收盘价 100% 完整**，OHLC 早期大面积为空 → 等级 B。

缺口 `gap_is_real_missing` **恒为 NULL**，不填充、不插值、不当 0 收益。
`930930` 港股通 56 处疑似缺口可能只是港股与 A 股交易日不同。

### 70.5 复合基准：0 条可复现

| 项 | 数值 |
| --- | ---: |
| 复合基准记录 | 15 |
| 完整 | **0** |
| 可复现 | **0** |

原因：债券指数、现金利率序列、恒生指数都不在本轮接入范围。
权重来自库内基准文字（证据等级 `platform`），**未编造任何历史权重**。

校验规则含「只有 1 个成分不构成复合基准」，防止只接一个成分就宣称可复现。

### 70.6 重要发现：中证接口忽略日期参数

实测 `index-perf` 接口**忽略 `startDate` / `endDate`**，
2004 / 2020 / 全区间三种请求返回完全相同的全量数据。

因此 3B-6.0.1.1 提出的「按年分段」在本接口无效，改为**单次请求 + 重试**：

| 项 | 值 |
| --- | --- |
| 单次请求 | 是 |
| 重试 | 6 次 × 45 秒 |
| 指数间隔 | 6 秒 |
| 反爬 | 403，冷却约 6 分钟恢复 |

### 70.7 基线占位行

接口首行常为 `2004-01-01` 基线值。入库时标 `quality_status='suspect'`，
**保留可追溯但不计入有效区间**：

| 代码 | 真实有效起点（价格序列） |
| --- | --- |
| `399997` | **2009-01-05**（不是 2004-01-01） |
| `930930` | **2014-11-14** |
| `H30184` | **2005-01-04** |

> 📌 **本表是数据库内价格序列的快照（2026-11-20）**。
> 全收益序列的起点不同（`H20539`=2008-12-31、`H20930`=2014-11-14、`H20184`=2005-01-04），
> 当前权威结论见 **77.12 节**。

### 70.8 数据库安全

| 项 | 值 |
| --- | --- |
| 建表前备份 | 是（`data/fund_agent.backup_3b6_0_2_*.db`） |
| 修改既有表 | **0** |
| 基金表行数变化 | **0** |
| 内容指纹 | `11c56eba…` 未变 |
| 外键 | 指数层连接显式启用，全局连接行为不变 |
| 事务 | `BEGIN IMMEDIATE`，异常整体回滚 |

### 70.9 产物

| 文档 | 路径 |
| --- | --- |
| 数据层 | `reports/phase3B6_0_2_index_data_layer.md` |
| 数据质量 | `reports/phase3B6_0_2_data_quality.md` |
| 复合基准 | `reports/phase3B6_0_2_composite_benchmark.md` |
| 测试报告 | `reports/phase3B6_0_2_test_report.md` |

### 70.10 修正轮 3B-6.0.2.1

修复两个验收阻断。

**阻断一：原始数据质量检查被预处理绕过**

旧流程 `去重 → 排序 → 质检` 让两类问题永远查不出来：

| 问题 | 旧行为 | 后果 |
| --- | --- | --- |
| 重复日期 | 字典按日期覆盖 | `no_duplicate_dates` 永远 ok |
| 日期倒序 | `sorted()` 先排好 | `date_ascending` 永远 ok |

修正后：

```
原始 rows（保持顺序、保留重复）→ check_history_quality
  → 硬性失败 → 拒绝入库（index_daily 0 行，审计与质量记录保留）
  → 硬性通过 → 去重 → 排序 → 入库
```

**阻断二：复合基准不校验收益口径**

`add_component()` 只查有无行情，`evaluate_composite()` 只看 `data_available`。
口径 unknown 的指数只要有历史点位就能通过——不允许。

修正后两处都强制校验 `index_master.return_basis`：

| 口径 | 可用于总收益 | `data_available` |
| --- | --- | --- |
| `total_return` | 是 | 1 |
| `net_total_return` | 是（保留独立标识） | 1 |
| `price_return` | 否（不含分红） | **0** |
| `unknown` | 否（口径未知） | **0** |

**「有历史行情数据」≠「有可用于总收益比较的历史序列」。**

**变异验证**：改回旧顺序 → 7 项测试失败；去除口径检查 → 各 2 项失败。

**现状态未变**：10 个指数仍全 `unknown`，15 条复合基准仍全不可复现，
50,603 行指数历史零改动，正式库零写入。

**一处既有测试收紧**：`test_duplicate_dates_in_payload_deduped`
改为 `..._rejected_at_ingest`，从「去重后入库 5 行」改为「拒绝入库 0 行」。
旧断言本身就是被修掉的绕过行为，**这是收紧不是放宽**。

### 70.11 修正轮 3B-6.0.2.2

上轮修好了收益口径，但行情可用性判定仍有漏洞：

```sql
SELECT COUNT(*) FROM index_daily WHERE index_code=?   -- 旧写法
```

只数**总行数**，不看 `quality_status`。只有 suspect 行或只有 1 条有效观测的指数，
会被错误标记为 `data_available=1`。

**修正后的有效行情判定**（四条同时满足）：

| # | 条件 |
| ---: | --- |
| 1 | 指数代码存在 |
| 2 | 收益口径为 `total_return` / `net_total_return` |
| 3 | `index_daily` 至少 **2 条** `quality_status='valid'` |
| 4 | 这些行 `close` 为正的有限数 |

| 状态 | 计入有效观测 |
| --- | --- |
| `valid` | ✅ |
| `suspect` | ❌ |
| `rejected` | ❌ |

**不得仅用总行数判断数据可用性。**

为什么是 2 条：一期收益至少需要两个时间点。

**`evaluate_composite()` 不再信任历史标记**：每次都重新统计有效行和读取口径，
历史组件曾标可用也无效，并把最新判定写回组件。

**变异验证**：

| 变异 | 失败测试数 |
| --- | ---: |
| 忽略 `quality_status` | **5** |
| `MIN_VALID_OBSERVATIONS = 1` | **4** |
| 信任历史 `data_available` | **4** |

**现状态未变**：10 个指数有效观测都远超 2 条但口径全 `unknown`，
15 条复合基准仍全不可复现，50,603 行指数行情零改动，正式库零写入。

**如实记录**：正式库 `benchmark_composite_component` 有 17 条 `data_available=1`，
是 3B-6.0.2 建表时按旧逻辑写入的历史遗留值。本轮不写库故不刷新，
但 `evaluate_composite()` 每次重算，不会让它泄漏成可复现。

### 70.12 修正轮 3B-6.0.2.3

`count_effective_observations()` 声称只统计正的**有限**收盘价，
但原实现用 `c != c or c <= 0`，**只能识别 NaN，漏掉 ±inf**。

修正为：

```python
return math.isfinite(c) and c > 0
```

| 值 | 修复前 | 修复后 |
| --- | --- | --- |
| 有限正数 | ✅ 计入 | ✅ 计入 |
| `+inf` | ❌ **错误计入** | ❌ 不计入 |
| `-inf` | ❌ **错误计入** | ❌ 不计入 |
| `NaN` / `0` / 负数 / `NULL` | 不计入 | 不计入 |

为什么必须用 `math.isfinite`：

- `NaN != NaN` 为真 → `v != v` 能抓 NaN
- `inf == inf` 为真 → `v != v` **抓不到 inf**
- `math.isfinite` 两者都能抓

**核心场景验证**（直接调 `assess_index_component()`）：构造 2 条记录，
1 条 `+inf` + 1 条正常正数 → 总行数 2，**有效仅 1**，`available=0`，
达不到 2 条门槛。

**变异验证**：退回旧判定 → **9 项测试失败**，覆盖 inf 全部路径。

**顺带发现 1 条真实数据问题**（如实记录，本轮不修）：

| 字段 | 值 |
| --- | --- |
| 指数 | `H30184` |
| 日期 | `2013-06-28` |
| `close` | **`0.0`** |
| `quality_status` | `valid` |

任务书禁止修改 50,603 条行情，故保留。**对结论无影响**：
该行修复前后都不被计入（旧 `c <= 0` 排除，新 `c > 0` 同样排除），
且该指数本就卡在 `return_basis='unknown'`。建议后续数据修补轮单独处理。

## 71. 阶段3B-6.0.3 研究池扩容

### 71.1 扩容结果

| 项 | 扩容前 | 扩容后 |
| --- | ---: | ---: |
| 库内本体 | 60 | **120** |
| 库内份额 | 89 | **149** |
| 研究池本体 | 19 | **79** |
| 研究池份额 | 26 | **86** |
| 同类组 | 13 | **26** |
| ≥5 本体的组 | **0** | **5** |
| 最大组 | 3 | **14** |
| 净值行数 | 80,083 | **245,656** |

### 71.2 六类场外基金覆盖

| 产品类型 | 扩容前 | 扩容后 |
| --- | ---: | ---: |
| 普通指数基金 | 2 | **16** |
| ETF联接基金 | 6 | **21** |
| 主动权益基金 | 5 | **16** |
| 纯债基金 | 2 | **14** |
| 混合债券基金 | 0 | **2** |
| 货币基金 | 2 | **7** |
| LOF 场外份额 | 2 | **3** |

### 71.3 入选规则（可复核）

| 规则 | 实现 |
| --- | --- |
| 只取场外 | `is_offmarket_pool()` 排除场内 ETF / QDII |
| 类别判定 | 复用 3B-5.0 `classify_fund()` |
| **主排序** | **按基金代码升序，不按业绩** |
| A/C 归并 | 候选阶段 `base_fund_name` 去重 + 接入阶段 `fund_id` 归并 |

明确没做：按收益率/规模/评级挑选、只选存续。

### 71.4 关键陷阱：数量达标 ≠ 可比较

纯债组有 **14 个本体**，但组键是 `bond_pure|unknown`，
因久期/信用/转债字段全 NULL，**按 3B-5.5.1 必须评 D**。

真正可验证且达标的组只有 **4 个**：

- `etf_linked|broad|沪深300`（5）
- `ordinary_index|broad|中证500`（5）
- `active_equity|中证800`（5）
- `money_market`（7，产品类型隔离）

### 71.5 数据质量问题（如实记录）

| 问题 | 影响 | 本轮是否修 |
| --- | --- | --- |
| 库内 `fund_type_l1` 与天天基金分类在 16/17 只债券基金上不一致 | 混合债券组只有 2 只 | **否** |
| 5 只 LOF 简称不含「(LOF)」但全称含 | LOF 组只有 3 只 | **否** |
| 41 个清盘本体全部 `fund_type_l1 IS NULL` | 无法分类 | **否** |

**不为凑数强行合并类别、不按份额重复计数、不改分类规则。**

### 71.6 未补充采集的辅助数据

| 数据 | 覆盖 | 为什么没补 |
| --- | ---: | --- |
| 规模 | 8 / 79 | 禁止回填历史时点规模 |
| 经理 | 9 / 79 | 禁止把当前快照伪装历史任职 |
| 费率 | 12 / 79 | 禁止第三方费率冒充支付宝费率 |

### 71.7 三个数据快照测试改造

扩容后 3 个测试因写死数字失效，改为**数据驱动断言**（更强）：

| 测试 | 旧 | 新 |
| --- | --- | --- |
| `test_summary_live_numbers` | `fund_count == 19` | 与直接查库结果一致 |
| `test_money_000509_not_d` | 货币为 `C` | 永不为 D，等级随组内数量 |
| `test_ac_pair_shares_same_peer_and_dedup` | `member_count == 1` | A/C 归并契约 + 去重标志 |

**未删除任何测试，断言反而更强。**

### 71.8 产物

| 文档 | 路径 |
| --- | --- |
| 扩容报告 | `reports/phase3B6_0_3_universe_expansion.md` |
| 数据质量 | `reports/phase3B6_0_3_data_quality.md` |
| 同类覆盖 | `reports/phase3B6_0_3_peer_coverage.md` |
| 测试报告 | `reports/phase3B6_0_3_test_report.md` |

## 72. 阶段3B-6.0.4 同类比较与超额收益验证

### 72.1 结论先行

| 项 | 数值 |
| --- | ---: |
| 同类组 | 26 |
| **可比较**（基准可验证 + ≥5 本体） | **4** |
| 仅描述性 | 12 |
| 排除（仅 1 本体） | 10 |
| **能算超额收益的组** | **0** |

### 72.2 四个可比较组

| 组键 | 本体数 |
| --- | ---: |
| `money_market`（独立口径） | 7 |
| `active_equity\|中证800`（有保留，见 72.5） | 5 |
| `etf_linked\|broad\|沪深300` | 5 |
| `ordinary_index\|broad\|中证500` | 5 |

### 72.3 超额收益：全线阻断

`excess_return_status = not_available`。三道闸门任一不通过即阻断：

| 闸门 | 当前 |
| --- | --- |
| 指数收益口径 | **10/10 unknown** |
| 复合基准完整 | **0/15 可复现**（债券/现金/固定利率成分全缺） |
| 基准收益序列 | **库内无此表** |

**同类相对表现 ≠ 超额收益，同类排名 ≠ Alpha。**

### 72.4 公平比较窗口

| 方式 | 说明 |
| --- | --- |
| 共同历史区间 | 取所有参与者交集，不拿成立以来直接比 |
| 滚动窗口 | 1Y / 3Y，步长 30 天，端点必须精确命中 |
| 市场阶段 | **不做**（事后选区间会制造有利结论） |

年化门槛：**不足 365 天不年化**，避免把短期涨幅外推。

### 72.5 LOF 分类问题（已披露未修）

7 只存续基金全称含「LOF」，但其中 **5 只简称不含**，
`classify_fund()` 按简称判定时漏识别：

若改按全称识别，`active_equity|中证800` 组从 **5 → 3**，
降为 `descriptive_only`，可比组将从 4 个减为 **3 个**。

**本轮不修**（属 3B-5.0 定稿规则，需单独立项），但已在报告中明确保留。

### 72.6 A/C 成本：只给框架不给建议

| 项 | 数值 |
| --- | ---: |
| 有费率本体 / 份额 / 规则 | 9 / 12 / 90 |
| 成本可算本体 | **7 / 9** |
| 真正 A/C 双份额本体 | **3** |
| 输出购买建议 | **0** |

不给结论的四条原因：第三方费率≠支付宝、有效期仅 11/90、
不得用当前费率倒推历史、不得仅凭名称判断。

### 72.7 数据质量

| 维度 | 等级 |
| --- | --- |
| 净值覆盖 / 重复 / acc_nav | **A** |
| 净值连续性（3 只有大缺口） | B |
| 分红（acc_nav 已含分红，无需修补） | B |
| 基准证据 / 复合基准 / 规模时点 / 费率有效期 | **D** |

**没有 A 级组**——基准证据全 D，同类比较缺可验证基准这一环。

### 72.8 新增模块与测试

| 模块 | 用途 |
| --- | --- |
| `peer_comparison.py` | 区间收益 / 共同窗口 / 滚动 / 稳定性 |
| `excess_return.py` | 超额收益阻断判定 |
| `share_cost.py` | A/C 成本框架 |
| `peer_engine.py` | 组级编排 |

新增测试 **50 项**（32 + 18），既有测试零修改。
全量 **1864 passed**（1814 → 1864）。

### 72.9 正式数据库只读

| 项 | 值 |
| --- | --- |
| 内容指纹（前后） | `115ac91e…387dd4`（**未变**） |
| ETF 指纹 | `d54727c0…bbcac49`（未变） |
| `integrity_check` | ok |
| 外键违规 | 0 |

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |

### 72.10 产物（10 对）

| 文档 | 路径 |
| --- | --- |
| 研究设计 | `reports/phase3B6_0_4_00_design.md` |
| 数据审计 | `reports/phase3B6_0_4_01_data_audit.md` |
| 同类规则 | `reports/phase3B6_0_4_02_peer_rules.md` |
| 指标口径 | `reports/phase3B6_0_4_03_metric_definitions.md` |
| 基准与超额边界 | `reports/phase3B6_0_4_04_benchmark_and_excess.md` |
| 同类比较结果 | `reports/phase3B6_0_4_05_peer_comparison.md` |
| A/C 成本 | `reports/phase3B6_0_4_06_share_cost.md` |
| 稳定性 | `reports/phase3B6_0_4_07_stability.md` |
| 测试 | `reports/phase3B6_0_4_08_tests.md` |
| 数据质量 | `reports/phase3B6_0_4_09_data_quality.md` |

## 73. 阶段3B-6.0.4.1 LOF 分类与同类质量评级窄修正

### 73.1 修正的两个阻断问题

| # | 问题 | 修正 |
| ---: | --- | --- |
| 1 | LOF 只按简称识别，5 只漏识别 | 综合 `fund_full_name` 判定 |
| 2 | `bond_pure\|unknown` 错标 C | 改 D，接权威评级函数 |

### 73.2 问题1：LOF 分类

库内 **5 只**基金简称被截断，全称才含 LOF：

| 代码 | 简称 | 修正前 | 修正后 |
| --- | --- | --- | --- |
| `001883` | 中欧新动力混合 | active_equity | **lof** |
| `001886` | 中欧成长 | active_equity | **lof** |
| `001888` | 中欧盛世成长 | active_equity | **lof** |
| `001889` | 中欧增强回报债券 | bond_pure | **lof** |
| `002592` | 中欧纯债 | bond_pure | **lof** |

**关键发现**：只改 `classify_fund()` 无效——`load_universe()` 的 SELECT
根本没取 `fund_full_name`，全称传不到分类器。数据通路一并修正。

| 文件 | 修正 |
| --- | --- |
| `classification.py` | 新增 `detect_lof()`，简称/全称任一含 LOF 即识别 |
| `data_access.py` | `load_universe()` SELECT +`fund_full_name` |
| `lookup.py` | `_SELECT` +`fund_full_name` |
| `ingest_user_funds/_impl.py` | 幂等查询与分类调用带全称 |

### 73.3 分类变化

| 产品类型 | 修正前 | 修正后 |
| --- | ---: | ---: |
| LOF | 3 | **8** |
| active_equity | 16 | **13** |
| bond_pure | 14 | **12** |
| 其余不变 | — | — |
| **合计** | **79** | **79** |

### 73.4 问题2：质量评级

**根因**：3B-6.0.4 报告生成时自建映射表 `{comparable:B, descriptive_only:C, excluded:D}`，
绕过了 `quality.grade_peer_comparison()`。`bond_pure|unknown` 状态是
`descriptive_only`，被无差别映射成 C。

**修正**：新增 `peer_engine.group_quality_grade()`，只做参数组装，
判定**完全委托**权威函数。`quality.py` 一行未改。

| 组键 | 修正前 | 修正后 |
| --- | --- | --- |
| `bond_pure\|unknown`（12 本体） | C | **D** |
| `bond_mixed\|unknown` | C | **D** |
| `active_equity\|unknown` | C | **D** |
| `money_market`（7） | B | **B**（特例保持） |

### 73.5 重新分组结果（真实计算）

| 项 | 3B-6.0.4 | 本版 |
| --- | ---: | ---: |
| 同类组 | 26 | **28** |
| **可比较** | 4 | **3** |
| 仅描述性 | 12 | **15** |
| 排除 | 10 | **10** |
| B 级 | 4 | **3** |
| C 级 | 20 | **10** |
| D 级 | 2 | **15** |

**三个可比较组**：`money_market`（7）、`etf_linked|broad|沪深300`（5）、
`ordinary_index|broad|中证500`（5）。

### 73.6 `active_equity|中证800` 降级

| 项 | 3B-6.0.4 | 本版 |
| --- | ---: | ---: |
| 本体数 | 5 | **3** |
| 状态 | `comparable` | **`descriptive_only`** |
| 等级 | B | **C** |

**没有为了保住 5 个样本而合并其他基金。**

### 73.7 未变项

| 项 | 状态 |
| --- | --- |
| 超额收益 | 仍 `not_available` |
| 数据质量规则 | `quality.py` 未改 |
| 数据指纹 | `115ac91e…387dd4` **未变** |
| 门禁 | 三值不变 |

### 73.8 测试

新增 **38 项**（`tests/test_3b6_0_4_1_lof_and_grade.py`）。
全量 **1902 passed**（1864 → 1902），既有测试零删除零弱化。

## 74. 阶段3B-6.1.0 官方基准与无风险利率数据源可行性审计

### 74.1 结论先行

| 问题 | 答案 |
| --- | --- |
| 10 个指数能否取得全收益序列 | ~~**6 个可以，3 个不行**~~ → **已修正：10 个全收益代码均存在（见 77.10）** |
| 15 条复合基准能否复现 | **0 条** |
| 无风险利率能否接入 | **可以**（中债国债曲线，2006-03 起） |
| 是否升级任何口径 | **否**（审计阶段不接入） |

### 74.2 指数口径：三档结论

> ⚠️ **本节是 3B-6.1.0 的历史结论，其中「无全收益」判定已被 3B-6.1.0.1 推翻。**
> 当时按「H + 后 5 位」惯例猜代码，全部返回空，据此误判。
> **当前权威结论见 77.10 节。本节仅作历史记录保留。**

| 指数 | 价格 | 全收益 | 净收益 | 结论（已被推翻） |
| --- | --- | --- | --- | --- |
| `000300` 沪深300 | ✅ | ✅ H00300 | ✅ N00300 | 三套齐全 |
| `000905` 中证500 | ✅ | ✅ H00905 | ✅ N00905 | 三套齐全 |
| `000906` 中证800 | ✅ | ✅ H00906 | ✅ N00906 | 三套齐全 |
| `000016` 上证50 | ✅ | ✅ H00016 | ✅ N00016 | 三套齐全 |
| `000942` 内地消费 | ✅ | ✅ H00942 | ❌ | 缺净收益 |
| `000922` 中证红利 | ✅ | ✅ H00922 | ❌ | 缺净收益 |
| `000012` 上证国债 | ✅ | ⚠️ 特殊 | ⚠️ 特殊 | **命名陷阱** |
| `399997` 中证白酒 | ✅ | ~~❌~~ | ~~❌~~ | ~~**无全收益**~~ → **已推翻** |
| `H30184` 半导体 | ✅ | ~~❌~~ | ~~❌~~ | ~~**无全收益**~~ → **已推翻** |
| `930930` 港股通 | ✅ | ~~❌~~ | ~~❌~~ | ~~**无全收益**~~ → **已推翻** |

### 74.3 ⚠️ 致命命名陷阱：上证国债指数

| 代码 | 名称 | 2024-01-02 收盘 |
| --- | --- | ---: |
| `000012` | 上证国债指数 | 206.07（全价） |
| `H00012` | 上证国债指数(**净价**) | 104.65 |
| `N00012` | 上证国债指数(利息及再投资) | 145.71 |

**`H` 前缀在股票指数代表全收益，在债券指数里却代表净价。**
按前缀惯例映射会把净价指数当全收益用——这是严重错误。

### 74.4 价格 ≠ 全收益（实测）

2024-01-02 沪深300：价格 `000300` = **3,386.35**，全收益 `H00300` = **4,709.92**，
相差 **1,323.57 点（+39.1%）**。绝不可互换。

### 74.5 官方证据

已实际下载并解析 **沪深300 编制方案 PDF**（16 页，1,184,619 字节）：

> 中证指数有限公司同时计算沪深300全收益指数和净收益指数的日收盘值…
> 计算中考虑了样本税前、税后现金红利的再投资收益

**证明了「这类指数存在」，但没证明「其余 9 个指数也都有」**，
也没证明「接口的 H00300 就是官方那条序列」。

### 74.6 复合基准：0 条可复现

| 缺口层 | 影响基准数 |
| --- | ---: |
| 现金成分无序列 | **10** |
| 债券指数成分无序列 | **5** |
| 指数成分无全收益 | 3 |
| **历史权重证据缺失** | **15 / 15** |

**最致命的是历史权重**：即使全部成分都能取到数据，
「用当前权重回填历史」被明令禁止，仍然不可复现。

### 74.7 无风险利率候选

| 候选 | 可用 | 定位 |
| --- | --- | --- |
| 中债国债收益率曲线 | ✅ 2006-03 起日频 | **首选无风险利率代理** |
| Shibor | ⚠️ 仅 2015 起 | 货币市场利率参考 |
| 中美国债（东财） | ⚠️ 无短端 | 仅参考 |
| 上证国债指数 | ❌ | **是指数不是利率** |

**「活期存款利率」是合同基准，不是市场无风险利率，不可混用。**

### 74.8 关键判断：接入指数全收益不解决问题

| 场景 | 可算超额收益的基金数 |
| --- | ---: |
| 当前 | **0** |
| 仅接入指数全收益 | **0** |
| 再加无风险利率 | **0** |
| 再加债券指数 | **0** |
| 再加历史权重 | 可能 >0 |

**单纯接入指数全收益，不会让任何基金的超额收益变为可用。**

### 74.9 交叉验证的诚实结论

中证 `3386.35` vs 新浪 `3386.352`，差 0.002 点 —— 数值一致，
但**两个来源底层都来自交易所收盘价**，**不构成独立交叉验证**。

### 74.10 只读保证

| 项 | 值 |
| --- | --- |
| 内容指纹（前后） | `115ac91e…387dd4`（**未变**） |
| `index_daily` | 50,603 行（**未变**） |
| `index_master` | 10 行（未变） |
| `benchmark_composite` | 15 条（未变） |
| 成分 | 34 条（未变） |
| `integrity_check` | ok |
| 外键违规 | 0 |

全量测试 **1919 passed**（1902 → 1919）。

## 75. 阶段3B-6.1.0.1 指数口径与复合基准审计语义修正

### 75.1 修正的 4 类问题

| # | 问题 | 性质 |
| ---: | --- | --- |
| 1 | `H00012`（净价）被填入 `net_total_return_index_code` | **语义错误** |
| 2 | `000051` 的 1% 年收益率被当成 1% 资产权重 | **语义错误** |
| 3 | 其余 9 个指数缺官方编制方案 | 证据不足 |
| 4 | 3 项测试依赖本地 `.tmp610` 缓存 | 可复现性缺陷 |

### 75.2 问题1：上证国债指数语义分离

| 代码 | 语义 | 2024-01-02 收盘 |
| --- | --- | ---: |
| `000012` | 全价 | 206.07 |
| `H00012` | **净价（不是净收益）** | 104.65 |
| `N00012` | 利息及再投资 | 145.71 |

修正：`net_total_return_index_code = null`，新增 `clean_price_index_code = H00012`。

**`H` 前缀在股票指数代表全收益，在债券指数却代表净价。**

### 75.3 问题2：000051 固定年收益率

原始文本：`沪深300指数收益率×95%＋1%（指年收益率，评价时应按期间折算）`

| 项 | 修正前 | 修正后 |
| --- | --- | --- |
| 成分类型 | `fixed_rate` | **`fixed_annual_return`** |
| `weight` | 0.01（错） | **`null`** |
| `annual_rate` | 无 | **0.01** |
| 资产权重合计 | 0.96（错） | **0.95** |

**1% 是年化收益率，不是 1% 资产权重。** 期间折算方法标 `unknown`。

### 75.4 顺带发现更严重错误：3 个指数被误判「无全收益」

3B-6.1.0 按「H + 后 5 位」的股票指数惯例猜代码，全部返回空，据此误判。

| 指数 | 3B-6.1.0 猜测 | **官方真实代码** | 实测 |
| --- | --- | --- | --- |
| `399997` 白酒 | `H39997` ❌ | **`H20539`**（全收益）/ `399997CNY02`（净收益） | ✅ |
| `H30184` 半导体 | — | **`H20184`**（全收益） | ✅ |
| `930930` 港股通 | `H930930` ❌ | **`H20930`**（全收益） | ✅ |
| `000922` 红利（净收益） | `N00922` ❌ | **`000922CNY020`** | ✅ |

**真实代码来自中证官方 factsheet 的「衍生指数」栏。**

**教训：不得按代码前缀惯例推断官方衍生指数代码。**

### 75.5 官方证据补齐：8/9 编制方案 + 10/10 factsheet

| 项 | 数量 |
| --- | ---: |
| 编制方案（真实下载解析） | **8** |
| factsheet | **10** |
| 未取得的编制方案 | 2（`000012` / `930930`，csindex 直链 404） |

**未取得的如实标记，不用无关文件凑数。**

注意：L2「有官方文件」**不等于**「口径已核实」——方案正文多数未提全收益定义，
代码映射来自 factsheet。因此 `return_basis` **仍全部保持 `unknown`**。

### 75.6 问题4：测试可复现性

新增仓库级证据附件 `reports/evidence/phase3B6_1_0_index_probe_evidence.json`，
3 项测试改为读它而不再依赖 `.tmp610`：

| 项 | 修正前 | 修正后 |
| --- | --- | --- |
| `test_3b6_1_0_audit.py` | 14 passed, **3 skipped** | **17 passed, 0 skipped** |

**已通过临时改名 `.tmp610` 验证不依赖缓存。**

### 75.7 复合基准状态修正

| 状态 | 条数 |
| --- | ---: |
| `reproducible` | **0** |
| `partially_reproducible` | **14** |
| `not_reproducible` | **1**（`012344`，含恒生指数无代码） |

**指数全收益缺口已清零**（10/10 取得），剩余缺口：
现金 10 条、债券 5 条、固定收益率折算 1 条、**历史权重 15/15**。

### 75.8 只读与门禁

| 项 | 值 |
| --- | --- |
| 内容指纹（前后） | `115ac91e…387dd4`（**未变**） |
| `index_daily` | 50,603（未变） |
| `index_master` | 10（未变） |
| `benchmark_composite` | 15（未变） |
| 成分 | 34（未变） |
| `integrity_check` | ok |
| 外键违规 | 0 |

全量测试 **1945 passed / 0 skipped**（1919 → 1945）。

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |

## 76. 阶段3B-6.1.0.2 指数证据统计与基准语义一致性修正

### 76.1 修正的 4 处不一致

| # | 问题 | 类型 |
| ---: | --- | --- |
| 1 | `summary` 数量(5/2)与 `detail` 数组(6/3)不符 | 统计不一致 |
| 2 | `official_factsheet` 全 `null`，证据却记 10/10 已下载 | 证据不一致 |
| 3 | 短窗口成功被当完整历史可用 | 口径混淆 |
| 4 | `000051` 推断剩余 5% 的资产配置 | 过度解释 |

### 76.2 三层口径（核心定义）

| 层 | 判定依据 | 结果 |
| --- | --- | ---: |
| ① `code_identified` | 有官方衍生指数代码记录 | 10 / 10 |
| ② `short_probe_ok` | 2024-01-02~01-10 探测窗口有数据 | 10 / 10 |
| ③ ~~`full_history_verified`~~ | **已废弃（3B-6.1.0.2 旧口径）** | ~~10/10~~ |
|
> ⚠️ **`full_history_verified=10/10` 是 3B-6.1.0.2 的旧口径，已废弃，不得作为当前状态引用。**
> 自 3B-6.1.0.3 起改为五态判定；普通股票指数实际覆盖达标 **7/9**。

**铁律：不得把 ① 或 ② 直接计为 ③。**

> 旧三层中的 ③ 已不存在，不可再引用。
> 当前状态请见第 77 节（五态判定）。

### 76.3 按完整历史覆盖的互斥分类

| 分类 | 指数数 | 指数 |
| --- | ---: | --- |
| `A_full_three_series_history` | **6** | 000300/000905/000906/000016/399997/000922 |
| `B_price_and_total_history` | **3** | H30184/000942/930930 |
| `special_bond_index` | **1** | 000012 |

**校验**：6 + 3 + 1 = **10** ✅

### 76.4 factsheet 证据回填（10/10）

| 指数 | 字节 | 页数 | 披露代码 |
| --- | ---: | ---: | --- |
| `000300` | 451,156 | 2 | H00300, N00300 |
| `000905` | 445,394 | 2 | H00905, N00905 |
| `000906` | 448,091 | 2 | H00906, N00906 |
| `000016` | 447,776 | 2 | H00016, N00016 |
| `399997` | 431,023 | 2 | H20539, 399997CNY02 |
| `H30184` | 431,782 | 2 | H20184 |
| `000942` | 442,911 | 2 | H00942 |
| `000012` | 421,962 | 2 | H00012, N00012 |
| `000922` | 449,780 | 2 | H00922, 000922CNY020 |
| `930930` | 446,156 | 2 | H20930 |

**重要区分**：factsheet 只提供代码列表，**不保证列顺序可读，多数不解释经济含义**。
全收益/净收益的语义归属一律以**接口返回的指数中文全称**为准。

`000012` 的「H00012=净价 / N00012=利息及再投资」结论来自接口名称（L3），
**不是官方文件证明**。

### 76.5 000051 修正后的准确解释

原始文本：`沪深300指数收益率×95%＋1%（指年收益率，评价时应按期间折算）`

**能直接断言**：

- 沪深300指数收益率的系数为 **95%**
- 另有 **1% 年化固定收益率**加项
- 该 1% **不是资产权重**
- 原文要求「评价时应按期间折算」

**不能断言**：

- 其余 **5% 的资产配置方式**（原文未说明是现金、债券还是任何资产）
- 折算公式（单利/复利）
- 天数基准（365/360/实际天数）
- 折算起止点

**统一严谨描述**：

> 基准公式包含沪深300指数收益率×95%，另加按期间折算的1%年化固定收益率。
> 该1%不是资产权重。原始文本未明确说明其余5%的资产配置方式，因此不推断其配置含义。

**禁止表述**：「95% 配沪深300，剩余 5% 按 1% 年化固定收益计」。

字段保持：`weight=null`、`annual_rate=0.01`、`period_conversion_method=unknown`、
`weight_sum_of_asset_components=0.95`、`status=not_reproducible`。

### 76.6 复合基准状态

| 状态 | 条数 |
| --- | ---: |
| `reproducible` | **0** |
| `partially_reproducible` | **13** |
| `not_reproducible` | **2**（`000051`、`012344`） |

### 76.7 完整历史证据入库

`reports/evidence/phase3B6_1_0_index_probe_evidence.json` 新增 `full_history_probe` 段，
记录 **30 个代码**的完整历史覆盖元数据（行数/起止/缺口/异常值），
**第三层因此可仓库级复现**，不依赖本地缓存。

### 76.8 只读与门禁

| 项 | 值 |
| --- | --- |
| 内容指纹（前后） | `115ac91e…387dd4`（**未变**） |
| `index_daily` | 50,603（未变） |
| `index_master` | 10（未变） |
| `benchmark_composite` | 15（未变） |
| 成分 | 34（未变） |
| `integrity_check` | ok |
| 外键违规 | 0 |

全量测试 **1979 passed / 0 skipped**（1945 → 1979）。

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |

## 77. 阶段3B-6.1.0.3 历史数据获取与连续覆盖质量分离

### 77.1 核心修正：一个状态拆成五个

3B-6.1.0.2 的 `full_history_verified` 是**一个 true 掩盖四种不同事实**。

| 状态 | 判定依据 |
| --- | --- |
| `history_retrieved` | 接口返回非空（rows > 0） |
| `history_range_verified` | 首末日期与行数已核实 |
| `history_coverage_adequate` | 真实起点覆盖率 **≥ 95%** |
| `history_quality_adequate` | 重复=0、空值=0、非正=0、内部缺口 **≤ 20 天** |
| `backtest_usable` | 前四项 + **收益口径已确认** → 本轮恒 false |

**不得因为前一项为 true 就自动把后一项设为 true。**

### 77.2 四项比率的明确区分（核心交付）

| 比率 | 普通股票指数（9 个） |
| --- | ---: |
| **数据获取成功率** | **9/9** |
| **历史区间核实率** | **9/9** |
| **覆盖达标率** | **7/9** |
| **质量达标率** | **8/9** |
| **回测可用率** | **0/9** |

**五项逐级递减，说明「取到」与「能用」之间隔着三道关。**

### 77.3 按经济语义分开统计

| 类别 | 数量 | 序列 |
| --- | ---: | --- |
| 普通股票指数 | 9 | 各自的全收益代码 |
| 特殊债券指数 | 1 | `N00012`（利息及再投资） |

**`N00012` 不计入普通股票指数全收益覆盖率。**

### 77.4 基线占位行已识别（不是数据缺失）

| 缺口类型 | 实际含义 | 是否缺失 |
| --- | --- | --- |
| 365~369 天 | **基线占位行**（首行 2004-01-01 为基点值） | **否** |
| 11~13 天 | 春节/国庆法定长假 | **否** |
| 1,826~3,970 天 | 指数真实发布起点晚 | 是（起点晚，非缺失） |

**剔除占位后，全部序列内部缺口最大仅 11~13 天。**

`000300`/`000016`/`H00016` **无占位行**（次行紧接首行）。

### 77.5 覆盖未达标的 2 个指数

| 指数 | **全收益代码** | 真实起点 | 覆盖率 | 行数 | 原因 |
| --- | --- | --- | ---: | ---: | --- |
| `399997` | `H20539` | **2008-12-31** | **78.2%** | **4,347** | 中证白酒指数发布晚 |
| `930930` | `H20930` | **2014-11-14** | **52.5%** | **3,000** | 港股通综合指数发布晚 |

**数据截止均为 2026-11-23**（探测日）。

**无法通过换数据源解决**——指数本身发布晚。

### 77.6 质量未达标的 1 个指数

| 指数 | 问题 | 处理 |
| --- | --- | --- |
| `H30184` | 1 个非正收盘（2013-06-28 `close=0.0`） | **保留并记录，未删除未插值** |

### 77.7 为什么全部 backtest_usable=false

| 阻断项 | 影响 |
| --- | --- |
| **收益口径未确认（`return_basis=unknown`）** | **全部 10 个** |
| 历史起点晚（覆盖率 < 95%） | `399997`、`930930`、`000012` |
| 非正值异常 | `H30184` |
| 特殊债券收益语义 | `000012` |

**仅口径一项就让全部指数不可回测。不得为凑数放宽门槛。**

### 77.8 阈值声明

| 阈值 | 值 | 依据 |
| --- | ---: | --- |
| 覆盖率达标 | **95%** | 真实起点到最新日期的天数 / 请求区间天数 |
| 内部缺口容忍 | **20 天** | 实测法定长假 11~13 天，20 天可容纳长假并排除真缺失 |

**这是审计口径，不是回测准入门槛**。回测门槛需另行立项。

### 77.9 只读与门禁

| 项 | 值 |
| --- | --- |
| 内容指纹（前后） | `115ac91e…387dd4`（**未变**） |
| `index_daily` | 50,603（未变） |
| `index_master` | 10（未变） |
| `benchmark_composite` | 15（未变） |
| 成分 | 34（未变） |
| `integrity_check` | ok |
| 外键违规 | 0 |

全量测试 **2001 passed / 0 skipped**（1979 → 2001）。

| 门禁 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |


### 77.10 逐指数真实历史覆盖（不套用统一行数）


> ⚠️ **旧版「2004年至今、5,318 行/序列」是笼统结论，不适用于所有指数。**


| 指数 | 全收益代码 | 实际行数 | 真实起点 | 覆盖率 | 覆盖达标 |
| --- | --- | ---: | --- | ---: | --- |
| `000300` | `H00300` | 5,318 | 2004-12-31 | 95.6% | ✅ |
| `000905` | `H00905` | 5,318 | 2004-12-31 | 95.6% | ✅ |
| `000906` | `H00906` | 5,318 | 2004-12-31 | 95.6% | ✅ |
| `000016` | `H00016` | 5,560 | 2004-01-01 | 100.0% | ✅ |
| `399997` | `H20539` | 4,347 | 2008-12-31 | 78.2% | ❌ |
| `H30184` | `H20184` | 5,317 | 2005-01-04 | 95.6% | ✅ |
| `000942` | `H00942` | 5,318 | 2004-12-31 | 95.6% | ✅ |
| `000012` | `N00012` | 3,373 | 2012-12-31 | 60.7% | ❌ |
| `000922` | `H00922` | 5,318 | 2004-12-31 | 95.6% | ✅ |
| `930930` | `H20930` | 3,000 | 2014-11-14 | 52.5% | ❌ |


**行数跨 3,000 ~ 5,560，覆盖率跨 52.5% ~ 100%，不得用单一数字概括。**


### 77.11 非正值异常按三层序列分别说明


> ⚠️ 旧版只列「4 个异常序列」，会让读者误以为其余变体均无异常。实际 **5 处**。


| 代码 | 所属层 | 异常日期 | 影响主分析？ |
| --- | --- | --- | --- |
| `H30184` | **价格** | 2013-06-28 | 它本身是价格指数 |
| `H20184` | **全收益** | 2013-06-28 | **是**（`H30184` 的全收益质量不达标） |
| `N00905` | **净收益** | 2013-01-25 | 否（主分析用 `H00905`） |
| `N00906` | **净收益** | 2013-01-25 | 否（主分析用 `H00906`） |
| `N00016` | **净收益** | 2013-01-25 | 否（主分析用 `H00016`） |


**「不影响主分析」≠「可以忽略」**——净收益序列异常仍存在。
**全部保留原始值，未删除、未插值。**


### 77.12 当前权威结论（唯一可引用的口径）


> 📌 **本表是当前唯一权威结论，数据来自 3B-6.1.0.3 实测探测，截止 2026-11-23。**
> 与 `reports/phase3B6_1_0_01_index_return_basis.json` 完全一致。


| 指数 | 价格代码 | 价格行数 | 全收益代码 | 全收益行数 | 全收益真实起点 | 覆盖率 | 截止 |
| --- | --- | ---: | --- | ---: | --- | ---: | --- |
| `000300` | `000300` | 5,559 | `H00300` | 5,318 | 2004-12-31 | 95.6% | 2026-11-23 |
| `000905` | `000905` | 5,318 | `H00905` | 5,318 | 2004-12-31 | 95.6% | 2026-11-23 |
| `000906` | `000906` | 5,318 | `H00906` | 5,318 | 2004-12-31 | 95.6% | 2026-11-23 |
| `000016` | `000016` | 5,560 | `H00016` | 5,560 | 2004-01-01 | 100.0% | 2026-11-23 |
| `399997` | `399997` | 4,346 | `H20539` | 4,347 | 2008-12-31 | 78.2% | 2026-11-23 |
| `H30184` | `H30184` | 5,317 | `H20184` | 5,317 | 2005-01-04 | 95.6% | 2026-11-23 |
| `000942` | `000942` | 5,318 | `H00942` | 5,318 | 2004-12-31 | 95.6% | 2026-11-23 |
| `000012` | `000012` | 5,559 | `N00012` | 3,373 | 2012-12-31 | 60.7% | 2026-11-23 |
| `000922` | `000922` | 5,318 | `H00922` | 5,318 | 2004-12-31 | 95.6% | 2026-11-23 |
| `930930` | `930930` | 3,000 | `H20930` | 3,000 | 2014-11-14 | 52.5% | 2026-11-23 |


**`399997` 当前口径**：全收益 `H20539`，**4,347 行**，真实起点 **2008-12-31**，
截止 **2026-11-23**，覆盖率 **78.2%**（**不达标**，不可用于长周期回测）。


**`930930` 当前口径**：全收益 `H20930`，**3,000 行**，真实起点 **2014-11-14**，
截止 **2026-11-23**，覆盖率 **52.5%**（**不达标**，不可用于长周期回测）。


**历史快照索引**（不得作为当前结论引用）：


| 快照 | 章节 | 日期 | 说明 |
| --- | --- | --- | --- |
| 数据库入库快照 | 70.2 / 70.7 | 2026-11-20 | 价格序列，4,345 行 |
| 代码猜测期结论 | 74.2 | 3B-6.1.0 | 「无全收益」判定，**已被推翻** |

## 78. 阶段3B-6.1.1 中债国债收益率数据源深化审计

### 78.1 结论先行

| 问题 | 结论 |
| --- | --- |
| 能否稳定获取 | **能**，42 段全部成功 |
| 历史起点 | **2006-03-01**；2002~2005 实测 0 行 |
| 数据质量 | 8 个期限完全相同：**5,185 行**，最大缺口 **11 天**，**0 异常值** |
| **2 年期** | **不存在**（接口无此列） |
| 发布时间 | **未取得官方证据** |
| 时点可用性 | **无法证明，建议 T+1** |
| 修订风险 | **未排除** |
| 证据等级 | **L3 第三方聚合** |

### 78.2 接口实测约束（本轮新发现）

| 约束 | 实测 |
| --- | --- |
| 日期格式 | 必须 `YYYYMMDD`，传 `YYYY-MM-DD` 会 `No tables found` |
| 单次跨度 | **约 1 年**（跨 2 年静默返回 0 行） |
| 0 行的含义 | **可能是跨度过大导致的静默失败，不等于无数据** |

**因此本轮改为按半年分段请求，42 段全部成功。**

### 78.3 逐期限覆盖与质量

| 期限 | 有效行 | 起 | 止 | 覆盖率 | 最大缺口 | 异常值 |
| --- | ---: | --- | --- | ---: | ---: | ---: |
| `3月` | 5,185 | 2006-03-01 | 2026-11-24 | 99.5% | 11 | 0 |
| `6月` | 5,185 | 2006-03-01 | 2026-11-24 | 99.5% | 11 | 0 |
| `1年` | 5,185 | 2006-03-01 | 2026-11-24 | 99.5% | 11 | 0 |
| `3年` | 5,185 | 2006-03-01 | 2026-11-24 | 99.5% | 11 | 0 |
| `5年` | 5,185 | 2006-03-01 | 2026-11-24 | 99.5% | 11 | 0 |
| `7年` | 5,185 | 2006-03-01 | 2026-11-24 | 99.5% | 11 | 0 |
| `10年` | 5,185 | 2006-03-01 | 2026-11-24 | 99.5% | 11 | 0 |
| `30年` | 5,185 | 2006-03-01 | 2026-11-24 | 99.5% | 11 | 0 |

**8 个期限的日期索引完全一致**——来自同一次曲线计算，不存在某期限独立缺失。

### 78.4 缺口阈值：为什么是 15 天

| 缺口天数 | 性质 | 是否缺失 |
| ---: | --- | --- |
| 1~3 天 | 周末 | **否** |
| 4~11 天 | 法定长假 | **否** |

**实测最大缺口 11 天**（2020-01-23 → 2020-02-03，春节 + 疫情延长）。

若用 10 天阈值会**误判为数据缺失**，故设为 **15 天**。
**这是审计口径，不是回测准入门槛。**

### 78.5 时点可用性（本轮最重要的未解决问题）

| 概念 | 本轮状态 |
| --- | --- |
| `observation_date` | 接口「日期」字段，语义未获官方说明 |
| `publication_date` | **未取得官方时刻证据** |
| `available_date` | **无法证明** |

**建议滞后方案**：

| 方案 | 代价 |
| --- | --- |
| **T+1**（建议默认） | 损失 1 个交易日 |
| T+2 | 损失 2 个交易日 |
| T+5（最保守） | 样本损失较大 |

**修订风险**：同区间两次调用 sha256 完全相同、跨区间同日重叠 61 天数值差异 0，
**但这只说明短周期未观察到修订，不能排除长期修订**。

### 78.6 日度化公式对比

| 期限 | A 日均 | B 日均 | 日均差 | 相对差 |
| --- | ---: | ---: | ---: | ---: |
| `1年` | 0.0000657865 | 0.0000649366 | -8.499e-07 | -1.2919% |
| `3年` | 0.0000742285 | 0.0000731737 | -1.055e-06 | -1.4210% |

**B 恒小于 A**（复利折现），差异量级 **1e-6**。

**Sharpe 敏感性未实算**——本轮禁止修改 Sharpe 公式。
仅给出量级估计：对日波动率约 1% 的基金，Sharpe 影响 **< 0.001**。

### 78.7 不同基金类别适用性（候选，非正式口径）

| 类别 | 候选 | 限制 |
| --- | --- | --- |
| 股票指数 / ETF联接 | 1 年期国债 | 需 T+1 滞后 |
| 主动权益 | 1 年期国债 | 同上 |
| 纯债 / 混合债券 | 1 年期**或** 3 年期（待定） | **两者结论不同，不可随意选** |
| 货币基金 | Shibor 或 1 年期国债 | **Shibor 仅 2015 起，覆盖不足** |

**四种利率不可混用**：无风险利率 ≠ 合同基准；国债收益率 ≠ 债券指数收益率；
Shibor ≠ 活期存款利率；**上证国债指数是指数不是利率**。

### 78.8 本轮明确不做的事

| 项 | 状态 |
| --- | --- |
| 写入正式数据库 | **否** |
| 确定正式无风险利率 | **否** |
| 确定日度化公式 | **否** |
| 确定滞后天数 | **否**（仅建议 T+1） |
| 计算任何 Sharpe | **否** |

### 78.9 未解决问题

| # | 问题 | 严重程度 |
| ---: | --- | --- |
| 1 | **官方发布时刻未取得** | **高** |
| 2 | **历史修订风险未排除** | **高** |
| 3 | 2 年期不存在 | 中 |
| 4 | 2002~2005 无法获取 | 中 |
| 5 | 证据等级只到 L3 | 中 |
| 6 | 未下载中债登官方编制说明 | 中 |
| 7 | 日度化公式未定 | 中 |
| 8 | 各基金类别代理未定 | 中 |

### 78.10 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |

## 79. 阶段3B-6.1.1.1 原始 CSV 重复记录与异常行独立校验

### 79.1 原测试的缺陷

**缺陷一：重复记录检测失效**

原测试用字典解析：

```python
series[(date, tenor)] = value
```

字典赋值会**覆盖**同键的前一条记录，重复行在检查之前就消失了。
后续 `len(dates) - len(set(dates))` 必然等于 0——
**这不是「没有重复」，而是「重复被吞掉了」。**

**反证**：构造 2 条完全相同的行，字典法只得到 8 条记录（查重 0），
逐行扫描得到 16 条（发现 8 对重复）。

**缺陷二：异常行被静默跳过**

原解析器用 `except ValueError: continue` 和 `pass` 吞掉三类问题：
坏日期、空值/NaN、非数值。
**从统计上无法区分「数据干净」与「数据有问题但被跳过」。**

### 79.2 修正：先计数，后判断

新增 `scripts/scan_3b6_1_1_1_raw_csv.py`：

```
逐行读取 → 记录原始行 → 检查日期 → 逐期限检查单元格 → 汇总
         （不去重，不去异常，全部计数）
```

### 79.3 真实数据扫描结果（42 份 CSV）

| 项 | 数量 |
| --- | ---: |
| 扫描文件数 | **42** |
| 原始数据行数 | **5,185** |
| 日期可解析行 | **5,185** |
| 日期不可解析行 | **0** |
| 有效记录 | **41,480** |
| 唯一 `(日期,期限)` | **41,480** |
| 空值单元格 | **0** |
| 非数值单元格 | **0** |
| NaN / Inf | **0 / 0** |
| 超范围 | **0** |
| **重复对数** | **0** |
| **数值冲突** | **0** |

**唯一组合数 = 有效记录数（41,480），说明零重复。**
若存在重复，唯一数会小于有效记录数。

### 79.4 各期限记录数独立复算

| 期限 | 逐行扫描 | coverage_quality.json | 一致 |
| --- | ---: | ---: | --- |
| `3月` | 5,185 | 5,185 | ✅ |
| `6月` | 5,185 | 5,185 | ✅ |
| `1年` | 5,185 | 5,185 | ✅ |
| `3年` | 5,185 | 5,185 | ✅ |
| `5年` | 5,185 | 5,185 | ✅ |
| `7年` | 5,185 | 5,185 | ✅ |
| `10年` | 5,185 | 5,185 | ✅ |
| `30年` | 5,185 | 5,185 | ✅ |

### 79.5 交叉复算确认

| 项 | 逐行扫描 | 现有报告 | 一致 |
| --- | ---: | ---: | --- |
| 有效记录总数 | 41,480 | 41,480 | ✅ |
| 原始行数 / 独立日期 | 5,185 | 5,185 | ✅ |
| 各期限记录数 | 5,185 | 5,185 | ✅ |

**现有审计统计全部经独立复算确认无误。**

### 79.6 新增测试（25 项）

| 类别 | 数量 | 关键测试 |
| --- | ---: | --- |
| 反证字典法失效 | 1 | `test_dict_parsing_hides_duplicates` |
| 真实数据校验 | 8 | `test_no_duplicate_pairs_in_real_data` 等 |
| 构造用例（发现问题） | 9 | 同值重复、异值冲突、空值、非数值、坏日期、NaN、超范围 |
| 构造用例（不误判） | 2 | `test_normal_records_not_flagged`、`test_non_curve_rows_ignored` |
| 证据与只读 | 5 | 指纹、行数、恒真断言检查 |

**`test_normal_records_not_flagged` 是反向验证的关键**——
只证明「能发现问题」不够，还必须证明「不会把正常数据判成问题」。

### 79.7 结论

| 项 | 结论 |
| --- | --- |
| 真实数据是否有异常 | **无**（全部缺陷计数为 0） |
| 现有统计是否需修正 | **否**（独立复算全部一致） |
| 原测试证明力 | **不足**（结论恰好正确，但推理不可靠） |
| 本轮改进 | 把「无重复」重建在**可验证的基础上** |

### 79.8 门禁

| 项 | 值 |
| --- | --- |
| `ready_for_research_analysis` | **True** |
| `ready_for_backtest` | **False** |
| `ready_for_formal_ranking` | **False** |

