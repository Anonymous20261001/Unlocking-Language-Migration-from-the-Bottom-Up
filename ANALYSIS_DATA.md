# 分析数据说明（原支撑材料 README，2026-10-02 整理版）

本文件记录 `05_analysis/` 中分析结果文件与论文图表数字的对应关系与推导链，
原为支撑材料根目录 `README.md` 的一部分（2026-10-02 整理版），2026-10-12 并入
本支撑包，内容保持不变。权威一致性声明与全部规范化改动记录见
`DATA_CONSISTENCY.md`；两套分类法定义见 `TAXONOMY.md`。

## 1. 文件位置

```
05_analysis/       原始流水线记录与叶级分类结果
```

## 2. 论文表格 ↔ 数据文件 ↔ 统计口径

| 论文位置 | 数据文件（`05_analysis/`） | 口径 |
|---|---|---|
| 表 1（数据集构成） | 由 `C#_merged_8895.csv` 等方法数汇总 | 每方法一行（8,895 个方法级编译单元） |
| 表 2（分域 CSR） | `domain_csr.csv`（按域汇总） | 编译通过方法数 / 域内方法数 |
| 图 2（错误构成 donut）与表 3（分域错误构成） | `csharp_classified.csv` + `cpp_classified.csv` + `python_classified.csv`（经 `class_package_override.csv` 映射到域） | **叶子出现次数**：每个失败方法对每个叶子最多计 1 次。C++/Python 每失败方法恰好 1 个叶子（n = 失败方法数）；C# 一个失败方法可带多个叶子（n = 4,492 个方法-叶子对，失败方法数为 3,470）。图 2 与表 3 分母合计均为 9,515 = 4,492 + 1,719 + 3,304 |
| 表 4（行为一致性） | `behavior_stats.csv` + BSR 分域表 | 编译通过 → 行为一致 |
| 图 3 / RQ4（行为失败构成） | `rq4_classified.csv`（C# 549 行 + C++ 508 行）+ `python_classified.csv` 的 rq4 列（Python 1,787 行） | 每失败方法一个行为失败类别 |
| CS 错误码 → 叶子映射 | `csharp_code_mapping.csv` | 见附录表 tab:csharp-code-mapping |

## 3. 关键数字的推导链（供复算）

- C++ 编译通过 = 7,176 = 8,895 − 1,719（`cpp_classified.csv` 行数）
- Python 编译通过 = 5,591 = 8,895 − 3,304（`python_classified.csv` 有 rq2_leaf 的行数）
- C++ 行为失败 = 508 = 7,176 − 6,668；其中 492 条有行为分类记录，另有 16 条为
  链接阶段失败（14 个 SimpleScriptContext + Attribute + MultiTableUI），在 RQ4 中
  归类为 IN1（Uncompilable test bodies），见 `rq4_classified.csv` 的 `IN-compile` 行。
- 图 2 的 C++ n=1,719 与 8,895−7,176=1,719 完全一致。

## 4. 历史更新记录（2026-10-02）

1. 图 2 由"诊断条数"口径（C# n=7,617）统一为"叶子出现次数"口径（C# n=4,492），
   与表 3 完全自洽。
2. C++ 编译通过数 7,160 → 7,176（同步 CSR 80.7%、BSR 92.9%、各分域 CSR/BSR）。
3. 16 个链接失败的 C++ 方法从"编译失败"改计为"编译通过但行为失败（IN1）"：
   - `rq4_classified.csv` 追加 16 行 `IN-compile`（C++ 总数 492 → 508）；
   - 分域分配：Dynamic Languages +14（CSR 57.1→75.3，BSR 58 个中 44 个一致 = 75.9%），
     Swing +2（CSR 85.5→85.6，BSR 2,733 个中 2,592 个一致 = 94.8%）；`domain_csr.csv` 已同步。
4. `behavior_stats.csv` 重新生成，与论文表 4 完全一致（原文件为早期版本，勿再使用）。

## 5. 已知版本差异（诚实记录）

- C# 编译通过数：论文与 `behavior_stats.csv` 使用 **5,320**（59.8%）；而
  `C#_merged_8895.csv` 中 skeleton 编译通过为 5,425（61.0%）。差 105 个方法，
  与 old_benchmark 的"纯陷阱单元"（105 个）数量一致，系总数字冻结版本与
  修复后流水线记录之间的历史差异。论文正文采用 5,320；若审稿人对账请引用本说明。
- C++ 的 7,176 与 `C++_merged_results_8895.csv` 的行级记录一致（1,703 skeleton 失败
  + 16 链接失败 = 1,719 失败）。

## 6. 与 DATA_CONSISTENCY.md 的关系

- 本目录的三个 `*_8895.csv` 为 2026-10-02 时点的流水线记录；最终结果以各语言包
  `04_results/all_samples_results.csv` 为准（C# 已应用 IN-80 重跑还原，见
  `DATA_CONSISTENCY.md` §3.1；C++ 行为阶段 93 行的原始标记方式见 §3.2；
  `Python_mergerd_8895.csv` 与 Python 包的 PASS 3,804 / FAIL 1,787 / ERROR 3,304
  分布完全一致）。
- 叶级分类文件（`*_classified.csv`、`rq4_classified.csv`、`domain_csr.csv`、
  `domain_leaf_stacks.csv`、`domain_leaf_top.csv`、`csharp_code_mapping.csv` 等）
  为论文环境按 `TAXONOMY.md` 规则归类 Fig.2/Fig.3 的实际输出；包内逐行
  `error_type`/`error_msg` 可对照复核。
