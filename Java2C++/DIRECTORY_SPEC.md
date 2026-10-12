# For_Paper 目录规范（语言无关，跨 Java→C# / Java→C++ / Java→Python 复用）

本规范与论文 *Unlocking Language Migration from the Bottom Up:
A Large-Scale Study on the Java Standard Library* 的术语与数字对齐。

## 顶级结构

```
For_Paper/
├── README.md                    # 数据集总说明（规模、来源、流水线、复现方法）
├── 01_source/                   # 源数据（Java 方法清单 + Randoop 测试输入）
├── 02_randoop/                  # Randoop 测试生成与覆盖分析
├── 03_translation/              # 目标语言翻译产物与流水线脚本
└── 04_results/                  # 实验结果（CSR / BSR 两阶段）
```

## 01_source/ — 源数据（三语言字节相同）

| 文件 | 内容 |
|---|---|
| `JavaAPI_splitted_method.zip` | 按方法拆分的 Java API 源方法文件（1,053 类 / 10,954 方法） |
| `JavaAPI_by_class.zip` | 按类组织的 Java API 源文件（1,053 类） |
| `Java_benchmark.zip` | 第一批 Randoop 测试（7,141 个，含回归注释，可提取 FQCN） |
| `javadoc_method_tests.zip` | 第二批 519 类 JUnit5 测试骨架（new_Java_class_tests） |
| `javadoc_randoop_tests.zip` | 第二批逐方法 Randoop 测试（1,754 个 .java + 生成记录） |
| `benchmark_method_list.csv` | 第一批方法清单（7,141 行） |
| `javadoc_method_list.csv` | 第二批候选方法清单（3,367 行，Javadoc 提取） |

## 02_randoop/ — Randoop 生成与覆盖

| 文件 | 内容 |
|---|---|
| `method_master_list.csv` | **全部候选方法主清单（10,508 行）**：含覆盖状态与未覆盖根因 |
| `coverage_summary.txt` | 覆盖总览（候选/生成/未覆盖 + 按来源 + 按 14 功能域） |
| `benchmark_randoop_success.csv` | 第一批生成成功清单（7,141 行） |
| `javadoc_randoop_success.csv` | 第二批生成成功清单（1,754 行） |
| `javadoc_uncovered_1613.csv` | 第二批未覆盖附录（仅 Java2C# 目录保留） |
| `method_master_list_full_api_13664.csv` | 全 API 库存附录（仅 Java2Python 目录保留，13,664 行） |

`method_master_list.csv` 列规范：
```
class, method, number, fqcn, domain, source, randoop_status, failure_category, failure_reason
```
- `method`: 方法名；`fqcn`: 类全名（benchmark 批从 Randoop 回归注释提取，100% 覆盖）
- `domain`: 论文 Table 1 的 14 个功能域之一（OTHER 表示域外包）
- `source`: `benchmark` / `javadoc`；`randoop_status`: `generated` / `uncovered`

## 03_translation/ — 翻译产物（各语言不同）

| 文件/目录 | 内容 |
|---|---|
| `{batch}_translated.zip` 等 | 各批次翻译的测试代码（按类/方法组织） |
| `scripts/` | 全部流水线脚本归档（生成、翻译、运行） |

## 04_results/ — 实验结果

| 文件 | 内容 |
|---|---|
| `all_samples_results.csv` | **全部样本结果（8,895 行，最重要）**：与论文 Table 2/4 对齐 |
| `result_summary.txt` | CSR / BSR 两阶段总览 |
| `{batch}_result.csv` 等 | 各批次原始结果（保留未合并的原始记录） |
| `behavior_report.csv` | 按类聚合的行为报告（可选） |
| `translation_audit_150.csv` | 150 条翻译一致性审计（agent-based audit 校准） |
| `error_taxonomy/` | 错误分类证据（IN-80 重跑补充、残留证据、交接文档） |

`all_samples_results.csv` 列规范：
```
class, method, number, dataset, result, error_type, error_msg, error_location
```
- `dataset`: `Java_benchmark` / `Javadoc_new`
- `result`: `PASS`（行为一致）/ `FAIL`（行为失败，进入 Phase 2）/ `ERROR`（编译/执行等价检查失败）
- `error_location`（DIRECTORY_SPEC 粗粒度桶）:
  - `none` — 通过
  - `syntax_error` — 文件无法编译（论文 S 家族 + 部分 T/C 叶）
  - `import_error` — 依赖缺失（论文 R3/E1 叶）
  - `call_error` — 名称/签名不匹配或运行时异常（论文 R2/T1/T4 编译叶 + CR 崩溃叶）
  - `behavior_diff` — API 调用成功，行为不一致（论文 RV/EX/IN 叶）

## 论文关键指标（README 必须包含）

1. 编译成功率 **CSR** = 编译通过（或 Python 执行等价检查通过）样本数 / 8,895
2. 行为成功率 **BSR** = 行为一致样本数 / CSR 分母
3. 总体可靠率 = 行为一致样本数 / 8,895
4. 编译错误分类（5 家族 15 叶子）与行为失败分类（4 家族 11 叶子）见 TAXONOMY.md
