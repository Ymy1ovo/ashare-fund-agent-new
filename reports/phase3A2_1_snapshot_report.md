# 阶段3A.2.1 数据库快照交付报告

- 生成时间：2026-11-11T16:49:16
- 生成方式：`scripts/package_project.py --mode data-snapshot`（SQLite `backup()` API）
- 变更说明：阶段3A.2.1 **无数据库结构变更**，无迁移文件。
  快照仅因 `validation_*` 四张表新增了整改后的验证记录而定。

## 一、快照文件

| 项目 | 内容 |
| --- | --- |
| ZIP 路径 | `D:\ymy\jj-agent\dist\Ashare-Fund-Agent_data-snapshot_20261111_164916.zip` |
| ZIP 大小 | 103,791,970 字节（98.98 MiB） |
| **ZIP SHA256** | `6d2524f5e2388136a41154dd2e9553fe9e07c1d3f9145a28b1008bb92dbbb83f` |
| manifest | `..._164916.zip.manifest.json` |
| 校验文件 | `..._164916.zip.sha256` |
| 包内数据库 | `data/fund_agent.db`，268,685,312 字节 |
| **包内数据库 SHA256** | `1e106f701900efefdce625a976ef787e6e226664a3e09d2a3282ad75dfed5b5f` |
| ZIP 内容 | 数据库 + 3 个迁移文件 + `manifest.json` |

## 二、完整性检查

| 检查项 | 结果 |
| --- | --- |
| 源库 `PRAGMA integrity_check` | **ok** |
| 快照 `PRAGMA integrity_check` | **ok**（解压后独立验证） |
| ZIP `testzip()` | None（无损坏） |
| 解压后数据库 SHA256 vs manifest | **一致** |
| 源库打包前后 SHA256 | 一致（未修改原库） |

## 三、各表记录数量（快照实测）

| 表 | 记录数 |
| --- | ---: |
| `etf_pool` | 46 |
| `etf_daily_prices` | 116,609 |
| `etf_indicator_daily` | 350,292 |
| `etf_adjustment_snapshots` | 139（当前 46） |
| `trade_calendar` | 8,797 |
| `backtest_runs` | 11（未变） |
| `validation_runs` | 10 |
| `validation_windows` | 64 |
| `validation_grid` | 64 |
| `validation_stress` | 56 |

## 四、历史验证记录保留情况

快照中 10 条验证记录全部保留：

| validation_id | 状态 | 结论 | 说明 |
| --- | --- | --- | --- |
| `c99a2a75b7e646c5` | failed | - | 阶段3A.2 早期失败 |
| `03bf88593cd54841` | failed | - | 阶段3A.2 早期失败 |
| `f9898c695b394808` | success | 不通过 | 阶段3A.2 代表性池 |
| `5ec77faf42d64162` | success | 不通过 | 阶段3A.2 代表性池（正式） |
| `e725034e46ff47e5` | success | 有条件通过 | 阶段3A.2 全池 |
| `7d884a1a03d94915` | success | 不通过 | 3A.2.1 调试运行（预热报错） |
| `e1e11a114ff74326` | success | 不通过 | 3A.2.1 调试运行（数据场景失败） |
| `9ecdd5ec67594110` | success | 不通过 | 3A.2.1 调试运行 |
| `f07b281c296841a4` | success | 不通过 | **3A.2.1 代表性池（正式）** |
| `b6e1155d19ba4b6a` | success | 不通过 | **3A.2.1 全池（正式）** |

未删除、未覆盖任何旧记录。

## 五、新增或修改的数据说明

| 内容 | 变化 |
| --- | --- |
| 行情 `etf_daily_prices` | 无变化（116,609 行） |
| 指标 `etf_indicator_daily` | 无变化（350,292 行） |
| 复权快照 | 无变化（139 行） |
| 历史回测 | 无变化（11 run） |
| 验证记录 | **新增 3 条正式记录**（`f07b281c296841a4`、`b6e1155d19ba4b6a` 等） |
| 数据库结构 | **无变更** |

## 六、数据指纹

```
算法：market-fingerprint-v2
全库 SHA256：394024221c09d310f520e3e39cdd83faca944b7f5f89e3eec0a2c0835b92084a
行数：116,609
```

## 七、Git 提交说明

数据库与快照包均未提交到 Gitee / GitHub。
`.gitignore` 已排除 `dist/`、`*.zip`、`data/*.db`，快照通过文件路径单独交付。
