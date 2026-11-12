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
