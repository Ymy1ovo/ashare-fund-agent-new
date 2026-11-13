# 变更日志

## 2026-11-13 — 阶段3A.3.2.1 公司行为账本关键缺陷整改

- **修复现金分红入账时点**：上一阶段把分红和拆分套用同一条「次一交易日」规则，
  导致除息日价格已跌、现金次一日才到，制造虚假日亏损（`510300` 2021-01-19
  当日收益 −1.343%，修复后 −0.054%），且除息日收盘后的订单会动用不存在的现金。
  本阶段改为**除息日确认应收、发放日转入可用现金**两段式，
  新增 `dividend_receivable` 字段与 `dividend_receivables` 表，
  总资产恒等式变为 `cash + market_value + receivable`。
- **权益登记日锁定份额**：分红金额按登记日收盘持仓计算，不再用除息日持仓，
  避免登记日与除息日之间的买卖算错金额。
- **拆分/合并继续按官方 `effective_date`**，没有套用分红规则。
- **证据等级整改**：上一阶段把 166 条事件全部标 `confirmed` 属于过度声称。
  本阶段新增 `evidence_status`（`official_confirmed` / `secondary_confirmed` /
  `unverified` / `rejected`），逐条抓取基金管理人公告原文（34 只标的 343 条公告），
  核对除息日、比例、金额、发放日：
  **144 条 official + 12 条 secondary + 10 条 unverified**。
  `unverified` 事件引擎完全不应用；回测区间内 81 条 100% 为 official。
- **事件数量全量对账**：`scripts/reconcile_events.py` 输出 14 项校验全部通过。
  澄清上一阶段的 80/166/1,071 三个数字的口径差异：区间内 81（按 `effective_date`）、
  全量 166、应用行数 2,788（不是事件数）。
- **事件数据指纹**：`compute_event_fingerprint` 覆盖 11 个字段，
  `compute_events_digest` 按稳定顺序聚合，同时纳入回测层与验证层的 `input_hash`。
  即使版本号不变，事件内容变化必然改变输入指纹。
- **事件版本管理**：`save_action()` 不再静默覆盖，改用
  `corporate_actions`（当前）+ `corporate_action_versions`（历史快照）双表，
  记录 `change_reason`；本阶段 166 条事件全部产生 version 2，共 338 个版本。
- **份额调整批次守恒**：`apply_corporate_action()` 改用最大余数法分配舍入误差，
  保证 `sum(lot.quantity) == position.quantity == new_quantity`，
  已用 3~13 批次、8 种比例验证；可卖日期不前移，T+1 保持。
- **历史记录口径标记**：11 条 backtest + 39 条 validation 标记为
  `legacy_corporate_action_accounting`，禁止作为新口径评价依据。
- **新增测试 13 项**（分红应收/到账、证据等级、指纹、版本、多批次），
  全量 412 → **425 项**，全部通过。
- **重放结果**（新记录 `6e310be0193643c1`，事件指纹已纳入 `input_hash`）：
  - 样本外总收益 +20.24% → **+20.11%**，Sharpe 0.7290 → **0.7208**，
    回撤 −18.11% → **−18.29%**
  - 样本内总收益 +10.87% → **+13.68%**，Sharpe 0.1776 → **0.2522**
  - MA250 vs 等权持有：收益 +0.80 pp（优势不显著）、波动率与回撤略优、
    成本仍高 **13.6 倍**
- 新增七份报告：event_reconciliation / dividend_accounting_fix /
  evidence_quality / fingerprint_version / backtest_replay / test / data_snapshot。
- 数据库：新增 2 张表、7 个列，迁移幂等，历史记录一条未删；行情指纹未变。

## 2026-11-12 — 阶段3A.3.2 价格口径与基金份额变动处理

- **先核查后修复**：从数据库重新提取全部价格异常（8% 阈值命中 342 处，
  回测区间内 22 处），逐条匹配官方公告，分类为 19 拆分 + 2 合并 + 1 现金分红，
  **全部有官方来源，0 处 unverified**。未从价格跳变反推任何比例。
- **发现回测期内共有 80 个公司行为**（23 拆分 + 57 分红，涉及 26 只 ETF），
  远超 8% 阈值能捕获的 22 处 —— 小额分红不会造成大幅跳变，此前被完全忽略。
- **新增公司行为事件表** `corporate_actions`（166 条，全部 confirmed）
  与 `corporate_action_applications`（记录每次回测用了哪些事件）：
  按 `(code, action_type, ex_date)` 幂等，`status` 严格区分 confirmed / unverified，
  未确认事件**不得应用**。
- **修复账本口径**：拆分/合并调整**持仓数量**（成本基准按比例反比守恒），
  现金分红增加**现金**；成交与估值继续用**原始价格**，不用前复权价。
  事件在开盘撮合之前应用，避免用新价格配旧数量。
- **`input_hash` 纳入 `corporate_action_version`**：口径变化必须改变哈希，
  否则修复前后结果无法区分。
- **修正 3A.3.1 的污染估算公式**：`implied_ratio - 1` 乘前一日市值不成立，
  改为 `r_raw - r_adj` 口径，并明确标注为「近似」，不得作为正式绩效；
  正式结果由完整回测重放给出。
- **新增 25 项专项测试** `tests/test_corporate_actions.py`：覆盖 10:1 拆分、
  1:2 合并、非整数比例、现金分红、同日拆分+分红、重复导入、事件顺序错误、
  非交易日、无持仓、部分成交、零碎股、现金不足、市值/总资产连续性、
  收益率正确性、缺失行情、未确认不应用、重复应用保护。全部走完整
  Engine + Broker + Portfolio + 估值链路。全量 387 → **412 项**，全部通过。
- **历史记录全部保留**：37 条旧验证记录、11 条回测记录、29,248 条订单、
  26,093 条成交、116,609 行行情**一条未删、一条未改**，指纹一致。
- **重放结果**（新记录 `c46fa37b932944c2`，旧记录 `32aead3291734f91` 保留）：
  - 样本内总收益 **-16.33% → +10.87%**，最大回撤 **-32.81% → -13.73%**
  - 样本外总收益 **+32.21% → +20.24%**，波动率 **24.27% → 16.94%**，
    最大回撤 **-24.54% → -18.11%**
  - 结论等级仍为「有条件通过」，但支撑数字全部更新
- **推翻 3A.3.1 的部分结论**：修复后 MA250 的波动率与回撤**反而优于**等权持有
  （16.94% vs 17.16%、-18.11% vs -19.03%），
  「风险控制未实现」的结论建立在被污染数据之上。3A.3.1 报告保留不改，
  新结论以 `phase3A3_2_backtest_replay_report.md` 为准。
- 新增六份报告：corporate_action_audit / accounting_design / repair_report /
  backtest_replay_report / data_snapshot / test_report。
- 数据库未修改行情数据；新增两张表，备份于
  `data/backups/fund_agent_pre_3a3_2_20261112.db`。

## 2026-11-12 — 阶段3A.3.1 MA 趋势策略失效归因（只读研究）

- **新增只读研究模块** `app/research/attribution.py`：净值变动分解（持有收益 /
  交易执行价差 / 交易费用）、成本四段拆分、交易行为统计、收益贡献排名、
  回撤剖面、下跌日分布、持仓集中度、市场环境归因、价格口径断点检测与污染估计。
  全部为纯计算，不访问数据库、不写文件、不改历史记录。
- **新增研究脚本** `scripts/research_3a3_1.py`：从验证记录 `32aead3291734f91`
  读取样本外区间与 41 只 ETF，用当前代码重跑 MA250 与等权买入持有，
  运行前后各取一次 `market-fingerprint-v3` 校验数据未被修改。
  实测耗时 49.6 秒，指纹一致。
- **新增 14 项专项测试** `tests/test_research_3a3_1.py`：分解恒等式（含同日买卖）、
  成本四段不重复计入、行为统计、回撤恢复判定、价格断点检测、污染估计、
  环境分组、集中度。全量 373 → **387 项**，全部通过。
- **核心发现**：
  - MA250 与等权买入持有几乎打平（31.79% vs 31.97%），交易笔数 425 vs 41；
  - 成本 10,639.52 元 vs 697.70 元（15.2 倍），抹平了 MA250 的 8,181 元毛利优势；
  - MA250 波动率 24.13% > 20.83%、最大回撤 -25.12% < -18.58%（更深），
    Sharpe 0.7818 < 0.8805，Calmar 0.6719 < 0.9130，**风险控制未实现**；
  - 447 个交易日只有 1 天完全空仓，平均暴露度 97.70%，**组合从未真正降仓**；
  - 震荡市 97 天交易 184 笔（占全部 43.3%），收益反低于买入持有；
  - **发现数据缺陷**：原始收盘价存在 22 处份额折算断点（样本外 6 + 样本内 16），
    引擎按不复权收盘估值、持仓数量未同步，样本外虚增约 7.34% / 7.04%。
- **本阶段只记录不修复**：价格口径修复需改数据层与引擎层，建议单独立项 3A.3.2。
- 新增三份报告：research_design / attribution_report / research_recommendations。
- 数据库未修改：37 条验证记录、11 条回测记录、116,609 行行情全部未变，指纹一致。

## 2026-11-12 — 阶段3A.2.1.2.3 临时库嵌套加锁缺陷修复

- **嵌套加锁死锁**：`concurrency._make_single_task()` 临时库分支写成
  `run_with_write_lock(run_validation, cfg, lock_dir=lock_dir)`，而
  `run_validation()` 自 3A.2.1.2.2 起自身也加锁。同一线程两次获取不可重入的
  `threading.Lock`，第二次永久阻塞——任务无声挂死，不报错、不超时、不释放。
  两层的锁目标还不同（外层临时目录、内层数据库目录），跨进程互斥不成立。
  现把加锁点收敛到**公开入口一处**：`_make_single_task()` 只调
  `run_validation(cfg, db_path=…, lock_dir=…)`。未使用 `RLock` 掩盖问题，
  `_run_validation_unlocked()` 仍是内部函数。
- **持锁标记置位时机**：`_LOCK_DEPTH` 原本在拿锁**之前**置位，等待锁期间会被
  误判为「已持锁」而绕过排队。现下沉到 `_locked()` 闭包内（真正拿到锁之后），
  `finally` 复位。
- **进程内锁无限等待**：`run_with_write_lock()` 由 `with _WRITE_LOCK` 改为
  `acquire(timeout=…)`，超时抛 `ConcurrencyError`；同一线程重复获取立刻报错。
  修复前等价路径实测 20 秒仍在阻塞，修复后 0.0 秒即抛出明确错误。
- **`input_hash` 读错库**：临时库场景调用 `get_validation(vid)` 未传 `db_path`，
  读到正式库必然为空，`input_hash=None` 让 `_check_hash_consistency()` 跳过空值，
  一致性检查退化为恒真。现传 `db_path`。真实运行验证：修复前 `null`，
  修复后 `dc5137ab80c92d71` 且与临时库记录一致。
- **测试改为行为验证**：原 4 项入口锁测试依赖 `inspect.getsource()` 字符串匹配，
  改实现不改行为也能通过。现全部改为行为断言（执行期间持锁且他人拿不到锁、
  超时抛错且流程未执行、异常后锁被释放、嵌套加锁快速失败），净增 4 项。
- **真实运行证据**：单临时库任务 253.2s `success`，执行期间外部探测拿不到锁，
  结束后持锁标记 `false`，锁文件落在临时库目录；两临时库任务并发调度 579.1s
  完成（273.6s + 577.7s，严格串行），`hash_consistency=true`，ids 唯一。
- 全量测试 369 → **373 项**，全部通过，0 failed / 0 skipped。
- 六份报告重新校准（删除过期结论而非追加）：数量统一为 373，
  「多进程未执行」「351/351」等过期表述已删除。
- 行情完整指纹 `market-fingerprint-v3:d54727c0...ac49` 前后一致，
  历史 13 条 validation 记录完整保留，`integrity_check` ok。

## 2026-11-12 — 阶段3A.2.1.2.2 统一入口锁与报告校准

- **统一入口锁**：`runner.py` 拆为 `_run_validation_unlocked()`（不加锁内部实现）
  与 `run_validation()`（**公开入口，自动加锁**）。所有正式库调用无需自己加锁。
  重入保护用 `contextvars.ContextVar` 记录持锁深度，不使用全局布尔变量。
  `concurrency.run_concurrent_tasks()` 改为直接调用公开入口，不重复加锁。
- **入口级实测**：两线程直接调 `run_validation()` 484.5 秒串行完成；
  两独立进程直调 496.7 秒串行完成，exitcode 均 0，结束后持锁标记均 False。
- **报告校准**：
  - 删掉「回撤被系统性高估/低估」断言，改为「相对 0% 基准加深 1.45~2.45 pp」；
  - 74 笔按护栏分界为「护栏前 72 笔（分支不存在）+ 护栏后 2 笔（现金足够）」；
  - 并发报告统一为全流程串行，删除过时的「跨进程未实测」；
  - 测试数量统一为 337 → 351 → 365 → **369**。
- 新增 4 项入口锁测试，全量 365 → **369 项**，全部通过。
- 行情完整指纹前后一致，历史 13 条 validation 记录完整保留。

## 2026-11-12 — 阶段3A.2.1.2.1 最终验收缺陷修复

- **信号附近删除比例失效**：`delete_signal_adjacent()` 原忽略 `ratio`，
  1%/20% 得到相同结果。现按 `round(可删信号数 × ratio)` 抽样（至少 1 个），
  记录 signal_count / eligible / deleted / actual_ratio，无信号日记 skipped。
  六档实测：0 → 11 → 30 → 52 → 101 → 204 行，严格递增。
- **CLI 不可复现**：`run_sensitivity_scan.py` 未传 `holding_dates` / `signal_dates`，
  持仓期间与信号附近两种模式无法真实执行。现在先跑基准回测提取两组日期再传入，
  并输出 `deleted_rows_by_mode`。CLI 五模式实跑通过。
- **并发模型**：从「计算并行 + 写入串行」改为**全流程串行排队**
  （`execution_model=full-pipeline-serial`，`compute_parallel=False`）。
  锁文件固定在正式库同目录 `data/.validation_write.lock`。
  修复 Windows 空文件区域锁不可靠、多进程首建锁文件 PermissionError 两个缺陷。
  实测 2 线程 434s / 4 线程 1312s / 2 独立进程 557s，事件严格串行，exitcode 均 0。
- **源库指纹**：`source_fingerprint()` 从行数求和升级为复用 `market-fingerprint-v3`
  完整内容哈希；新增单测验证「改一行但行数不变」指纹必须变化。
- **报告措辞修正**：回撤改为「相对完整数据基准的变化」，不判定高估/低估；
  历史 74 笔按护栏分界为「护栏前 72 笔（分支不存在）+ 护栏后 2 笔（现金充足）」，
  修正原「均因现金充足」的错误归因；并发报告删除计算并行结论。
- 新增 `tests/test_final_acceptance.py` 14 项，全量 351 → **365 项**，全部通过。
- 行情指纹 `market-fingerprint-v3:d54727c0...ac49` 前后一致，历史记录完整。

## 2026-11-12 — 阶段3A.2.1.2 验证体系工程收尾

- 新增 `app/validation/sensitivity_scan.py`：6 删除比例 × 5 缺失模式的敏感性扫描，
  独立 SQLite 副本、固定随机种子、保护区间首尾估值日。
  实跑代表性池 30 场景 + 全池 12 场景，共 **42 场景**，负现金天数全部 0。
- 新增 `app/validation/concurrency.py`：进程内线程锁 + 跨进程文件锁串行写入，
  明确声明 SQLite 不支持多写并发。实测 2 任务 / 4 任务并发，
  validation_id 唯一、integrity ok、失败任务不影响其他任务。
  修复了 `input_hash` 误用数据指纹作为隔离判据的问题。
- 新增 `app/validation/sell_probe.py`：受控副本跑完整 Engine 流程验证
  `sell_proceeds_below_fee`。历史真实数据从未自然触发（74 笔「成交额<费用」
  均因现金充足未拒单），受控场景两档（现金不足/充足）+ 阈值扫描全部正确。
- 新增 `scripts/run_sensitivity_scan.py` 与 `tests/test_reliability.py` 14 项测试。
- 全量测试 337 → **351 项**，全部通过。
- 历史 13 条 validation 记录完整保留，新增 9 条；行情指纹前后一致。
- 新增 6 份报告：design / test / sparse_sensitivity / concurrency / sell_proceeds / validation。
- 真实券商交割单核验仍标记为 `deferred_external_evidence`。

## 2026-11-12 — 阶段3A.2.1.1.2.1.1 绩效总成本漏计税费修复

- **根因**：上一阶段把 `Trade.commission` 收窄为纯佣金后，
  `metrics.compute_performance()` 的 `total_cost = total_commission + total_slippage`
  未同步，漏掉印花税与过户费。实测 264 笔成交漏计 51,041.98 元（41.4%）。
- `total_cost` 改为 `total_trade_fees + total_slippage`。
- `Performance` 新增 `total_stamp_tax`、`total_transfer_fee`、`total_trade_fees`。
- 报告绩效表改为分项列示（佣金/印花税/过户费/费用合计/滑点/总成本）；
  交易明细表增加四列。
- 新增 `COST_SEMANTICS` 常量与 `cost_semantics_of()` / `describe_cost_semantics()`，
  新回测写入 `summary_json.cost_semantics`；历史记录标记为 `legacy`，
  **不补造历史税费、不重算历史结果**。
- 新增 `tests/test_cost_aggregation.py` 15 项，全量 322 → 337 项，全部通过。
- 数据库结构无变更，无需迁移与快照。

## 2026-11-12 — 阶段3A.2.1.1.2.1 佣金与交易税费累计混用修复

- **根因**：`broker.py` 把 `order.fee`（含印花税+过户费）当作「已收佣金」传给
  `incremental_commission()`，税费被当成佣金，导致后续部分成交少收佣金。
  实例：10000+10000 两笔成交，第二笔应补收 1.00 元佣金，实际收 0。
- 隐藏原因：11 次历史回测的 `stamp_duty_rate` 与 `transfer_fee_rate` 均为 0，
  `order.fee` 恰等于佣金，缺陷未暴露。
- `Order` 新增 `commission`、`stamp_tax`、`transfer_fee` 与 `total_fees` property。
- `Trade` 的 `commission` 语义收敛为**只含佣金**，新增 `stamp_tax`、`transfer_fee`、`total_fees`。
- `_max_affordable()` 佣金基数改用 `order.commission`，并把税费纳入现金约束。
- `reconcile()` 期末现金推演改用 `trade.total_fees`；真实回测差值 51,041.98 元问题消除。
- 新增迁移 `migrations/phase3a2_1_1_2_1_fee_split.sql`，加列不删列，历史订单
  `commission` 回填为 `fee`（前提：旧税率均为 0，已实测确认）。
- 新增 `tests/test_fee_split.py` 12 项（场景 A–H），全量 310 → 322 项，全部通过。
- 交付新 data-snapshot；行情指纹 `d54727c0...ac49` 前后一致，历史记录全部保留。

## 2026-11-12 — 阶段3A.2.1.1.2 佣金累计模型与零碎股清仓修复

- **最低佣金按订单累计**：新增 `CostConfig.min_commission_model`（默认 `per_order`）。
  同一订单多次部分成交共用一份最低佣金额度，增量 = max(累计金额×费率, 最低佣金) − 已收。
  实测 300+200 两次成交从 per_fill 的 10.00 元降为 per_order 的 5.00 元。
- `Order` 新增 `gross_amount`（累计成交金额）与 `liquidate`（清仓意图）。
- **零碎股完整清仓**：`sell_quantity()` 支持 `liquidate`，清仓时整手与零股合并成一笔申报。
  持仓 130,400、策略算出 130,399.7 时一次卖光，不再残留 1 份。
  部分减仓仍按整手，只有可卖不足一手时才整笔卖零股。
- `Broker._max_affordable()` 改为按订单累计佣金计算，避免重复最低佣金低估可买量。
- **统一收益样本统计口径**：新增 `metrics.return_sample_stats()`，输出可加总的五元
  （首日 / 持仓缺口 / 前日缺口 / 缺净值 / 有效），并附 `definition` 版本标签。
  `evaluate_sparse_result()` 强制校验加总，不成立判 failed。
  查明上一阶段 256 与 269 的差异来源是 MA250 与 MA60 参数不同，非口径冲突。
- 新增 `tests/test_validation_fix_3.py` 34 项测试，全量 276 → 310 项，全部通过。
- 两池 sparse_data 实跑：代表性池 802 订单 / 695 成交，全池 2,117 / 1,244，负现金均 0 天。
- 无数据库迁移；历史 validation 12 条、行情、指标、复权快照、历史回测全部保留。

## 2026-11-11 — 阶段3A.2.1.1 全池压力测试阻塞修复

- **碎股卖出根因**：卖单数量使用 `round_lot(..., allow_odd=True)`，等价 `floor()`，
  持仓 130,400 股时申报 130,399，卖出后剩 1 股；后续卖出 1 股成交额 0.3738 元 < 最低佣金 5 元，
  现金转负触发账本异常。
- 新增 `sell_quantity()`：整手优先，只有可卖不足一手时才允许整笔清零股；
  engine 与 broker 统一调用。
- broker 新增卖出净收入不足防护：收入<费用且现金不够时拒单（`sell_proceeds_below_fee`），
  不制造负现金。
- 指纹升级 v3：新增 `adjustment_type`、`adjustment_coverage_start/end`；
  `LEGACY_FINGERPRINT_VERSIONS` 保留 v2 兼容；空值编码统一。
- `_load_regime_warmup()` 改为按**有效价格**计数：`db_rows` / `valid_prices` / `invalid_prices` 三量分离；
  预热状态按 `valid_prices >= 250` 判定 ok / partial / unavailable。
- 全池 sparse_data 实测通过：41 只、2,004 订单、1,235 成交、负现金 0 天、指纹前后一致。
- 新增 `tests/test_validation_fix_2.py` 27 项测试，全量 249 → 276 项，全部通过。
- 无数据库迁移；历史 validation、行情、指标、复权快照、历史回测全部保留。

## 2026-11-11 — 阶段3A.2.1 验证体系缺陷整改

- 修复市场环境分类缺少 OOS 前预热数据：额外加载 OOS 前全部历史交易日（实测 3,064 天）
  做 MA250 预热，预热数据不进入输出、不计入 OOS 绩效。OOS `unclassified` 从 246 天降到 0 天。
- 新增 `app/validation/fingerprint.py`：`market-fingerprint-v2`，覆盖
  code / trade_date / open / high / low / close / volume / amount / adjusted_close /
  adjustment_snapshot_id 十个字段，按 (code, trade_date) 排序后 SHA256，
  算法版本纳入 `input_hash`。
- 数据类压力测试落到实跑：
  - `sparse_data`：SQLite backup 生成独立副本，删除零散 4,047 行 + 连续缺失 32 行，
    源库零写入；447 天中 270 天有效日收益、176 天缺口，状态 success。
  - `insufficient`：截取 41 个交易日（低于 120 阈值），引擎算出的 Sharpe/CAGR 被隐藏，
    状态 insufficient，不再标记 skipped。
- `regime_stats()` 重写：输入改为保留 NaN 的原始交易日序列，逐环境统计
  total_days / valid_days / missing_days，不再有压缩跨缺口收益的空间。
- 新增 `tests/test_validation_fix.py` 40 项测试，全量 209 → 249 项，全部通过。
- 新增 `regime_ma_window`、`min_validation_days` 配置项。
- 无数据库迁移；历史 validation 记录、行情、指标、复权快照、历史回测全部保留。
- 新增报告：`phase3A2_1_design.md`、`phase3A2_1_test_report.md`、`phase3A2_1_validation_report.md`。

## 2026-11-11 — 阶段3A.2 策略可信度验证体系

- 新增 `app/validation/`：配置、切分、Walk-Forward、市场环境、参数敏感性、基准、压力、存储、报告、调度共 11 个模块。
- 新增 `migrations/phase3a2_validation.sql`：`validation_runs`、`validation_windows`、`validation_grid`、`validation_stress` 四张表，全部 `CREATE TABLE IF NOT EXISTS`。
- 新增 `scripts/run_validation.py`、`scripts/smoke_validation_api.py`。
- 新增 `dashboard/pages/4_策略验证.py` 看板页。
- 新增 `/api/validations`、`/api/validations/{id}` 两个接口。
- 新增 `tests/test_validation.py` 55 项测试，全量 154 → 209 项，全部通过。
- 实际运行代表性池（6 只）与全池（41 只）两次验证：
  - 代表性池 `5ec77faf42d64162`：结论「不通过」，样本内 0/7 组合正收益。
  - 全池 `e725034e46ff47e5`：结论「有条件通过」，样本外 Sharpe 0.7637、收益 30.71%。
- 关键发现：样本外等权买入持有（31.97%、Sharpe 0.8805）优于 MA250 趋势（30.71%、Sharpe 0.7637），
  趋势择时未创造超额收益。
- 新增报告：`phase3A2_design.md`、`phase3A2_report.md`、`phase3A2_test_report.md`。
- 未修改 `app/backtest/`、`app/quant/`、`app/data/`，历史行情/指标/快照/回测记录一行未动。

## 2026-11-11 — 阶段3A.1.1 部分成交状态专项修复

- 新增 `Order.sync_status()` 作为唯一状态收敛入口：有成交只能是 `filled` / `partial`，
  `rejected` / `expired` / `unfilled` / `cancelled` 只对零成交订单生效。
- 修复 Broker 已把剩余部分设为 `rejected` 后，Engine 因 `status not in ("rejected",)`
  跳过修正、导致「有成交却标 rejected」的问题。
- Broker 新增 `_defer()` / `_terminate()`，已完成订单在 `execute()` 入口直接拦截，
  不重复成交、不重复扣费。
- Engine 撮合后状态收敛统一走 `sync_status()`；缺失行情分支保留已有成交的 `partial`。
- 修正 2 个原有测试的错误断言，新增 10 项部分成交专项测试，`test_backtest_partial_fill.py` 由 8 项增至 18 项。
- 全量测试 144 → 154 项，全部通过。
- 新增专项报告 `reports/phase3A1_1_partial_fill_fix_report.md`。

## 2026-11-10 — 阶段3A.1 回测验收问题修复

- Sharpe/Sortino 改用日均超额收益年化，CAGR 独立计算。
- 缺失行情：缺口当日与次日日收益置 NaN，只统计持仓 ETF。
- 部分成交：保留 partial，新增 `remaining_quantity`，剩余续挂或明确取消。
- 新增迁移 `migrations/phase3a1_backtest_partial_fill.sql`。
- 新增测试 17 项，全量 144 passed。
- 新增报告：`phase3A1_report.md`、`phase3A1_test_report.md`、`phase3A1_risk_comparison.md`、`phase3A1_manual_case.md`。

## 2026-11-10 — 阶段3A 历史回测引擎 V1.0

- 新增 `app/backtest/` 完整回测架构：配置、模型、行情读取、成本、执行、撮合、账本、引擎、绩效、报告、持久化、策略。
- 严格 T+1：T 日收盘信号最早 T+1 开盘成交；停牌/零成交/涨跌停不虚构成交，延期或过期。
- 价格口径：成交与估值只用原始 OHLC；前复权价仅用于信号，不混用、不重复计分红。
- 账本：FIFO 批次、现金约束、每日总资产核对、期末现金独立推演。
- 成本：佣金（含最低佣金）、比例/固定滑点、可选印花税与过户费；ETF 规则按类别配置。
- 新增 5 张表：`backtest_runs`、`backtest_daily_nav`、`backtest_orders`、`backtest_trades`、`backtest_positions_daily`。
- 新增 API 6 个：`/api/backtests` 列表、详情、净值、成交、订单、持仓。
- 新增 `scripts/run_backtest.py` 与 Streamlit「回测结果」页面。
- 新增测试 31 项，全量 127 passed。
- 新增报告：`phase3A_design.md`、`phase3A_report.md`、`phase3A_test_report.md`、`phase3A_backtest_case.md`。

## 2026-11-09 — 阶段2.2 与交付打包规范

- 修复区间风险摘要缺失交易日压缩：
  - `summarize_range()` 在原始交易日索引上使用 `pct_change(fill_method=None)`。
  - 波动率、夏普、索提诺只使用真实相邻日收益。
  - 最大回撤使用有效价格观察序列，不填充缺失价格。
  - 摘要和 `compute_risk()` 共用 `daily_return_series()`。
- 指标引擎版本 `v1.0.2-30b821a1af15`；旧版本 v1.0.0/v1.0.1 保留。
- 46只ETF重新计算：26 success、20 partial、0 failed。
- 新增交付打包规范：
  - `source-only`：轻量源码包，不含数据库和日志。
  - `data-snapshot`：SQLite 一致性备份、完整性检查、独立快照包。
  - `full-release`：源码包 + 数据库快照包 + 测试/质量报告 + 变更说明。
- 新增 `scripts/package_project.py`，输出 ZIP SHA256 和 manifest。
