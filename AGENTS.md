# 项目规则：D:\ymy\jj-agent（A股基金量化分析 Agent）

本文件只写本项目专属约束；通用聊天人格与全局偏好见上级 `D:\ymy\AGENTS.md`。

## 一、写文件方式（硬约束）

1. 超过约 1.5KB 的代码/文档，一律用 `ops_bash` + heredoc 写入，不用 `write` 工具：
   ```bash
   cat > app/backtest/costs.py <<'PYEOF'
   ...内容...
   PYEOF
   ```
2. 少用 `write` 一次写大文件——`content` 内含真实换行会导致 JSON 解析失败、整次调用作废。
3. 每个文件写完立即 `python -m compileall -q <path>` 验证语法，不留半截文件。
4. 所有 Python 命令加 `PYTHONUTF8=1`，路径用 `/`。

## 二、项目事实（不要再探查一遍）

- 解释器：`.venv/Scripts/python.exe`，Python 3.11.2。
- 数据库：`data/fund_agent.db`（约 231MB），**不得重建或覆盖**。
- 主要表：`etf_pool`(46)、`etf_daily_prices`(116,609)、`trade_calendar`(8,797)、`etf_adjustment_snapshots`(139，其中当前 46)、`indicator_runs`、`etf_indicator_daily`(3 个版本 × 116,764)。
- 指标版本：`v1.0.0-30b821a1af15`、`v1.0.1-30b821a1af15`、`v1.0.2-30b821a1af15`（当前）。
- 已有模块：`app/quant/`（价格口径、收益、趋势、动量、波动、风险、引擎）、`app/database/`、`app/main.py`、`dashboard/`、`scripts/`。
- 已有测试 96 项通过；运行：`PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest -q`。
- 打包：`python scripts/package_project.py --mode source-only|data-snapshot|full-release`。

## 三、开发纪律

1. 不修改阶段1/2 已验收逻辑（`app/quant/*`、`app/data/*`），除非发现明确 bug 并先说明。
2. 不删除旧指标版本、不填充缺失行情、不伪造分红/成交数据。
3. 新增表必须单独写 `migrations/*.sql`，且 `init_db` 用 `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE ADD COLUMN` 幂等迁移。
4. 测试只用临时 SQLite（`tests/conftest.py` 的 `temp_db`），不污染正式库。
5. 阶段推进以用户明确指令为准，做完就停，不自行进入下一阶段。

## 四、常用命令

```bash
cd /d/ymy/jj-agent
PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest -q
PYTHONUTF8=1 .venv/Scripts/python.exe -m compileall -q app scripts dashboard tests
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/package_project.py --mode source-only
```

## 五、退出码纪律（对 ops_bash 强制，防止任务流中断）

`ops_bash` 最外层退出码非 0 即返回 `[COMMAND_FAILED; effects: unknown; retry: never]`，
该命令被禁止重试。非 git 目录跑 `git status`(128)、`ls` 不存在文件(2)、
`grep` 无匹配(1) 都会误触发。因此：

1. 探测类命令（git/ls/cat/grep/find/head）一律带兜底，结尾 `|| echo STEP_FAILED`。
2. 多步命令末尾加 `; echo DONE_OK` 保证 0。
3. 不用 `&&` 串长链路，一条命令只做一件事。
4. 只有 pytest / 打包 / 迁移这类需要真实成败的命令保留原生退出码，且单独一条跑。
