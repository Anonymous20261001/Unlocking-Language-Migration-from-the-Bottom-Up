# 数据一致性声明

本文件声明三语言数据包之间的一致性关系、支撑数据与论文数字的对应关系，
以及从原始实验目录到本支撑材料文件夹的全部规范化改动。

## 1. 核心一致性：8,895 个样本三元组逐行一致

三个语言包的 `04_results/all_samples_results.csv` 均含 8,895 行，且
`(class, method, number)` 三元组**逐行完全一致**（三方交集 = 并集 = 8,895）：

```
C#  : 8,895 行（Java_benchmark 7,141 + Javadoc_new 1,754）
C++ : 8,895 行（Java_benchmark 7,141 + Javadoc_new 1,754）
Py  : 8,895 行（Java_benchmark 7,141 + Javadoc_new 1,754）
C# vs C++ vs Py 三元组差集：均为空
```

即三个方向的实验对**同一组 Java API 方法**进行翻译评估——这是论文可比性
结论（Table 2/4/5）的数据基础。复验命令：

```bash
python3 - <<'EOF'
import csv
def load(p):
    with open(p, encoding='utf-8-sig') as f:
        return {(x['class'],x['method'],x['number']) for x in csv.DictReader(f)}
cs  = load('Java2C#/04_results/all_samples_results.csv')
cpp = load('Java2C++/04_results/all_samples_results.csv')
py  = load('Java2Python/04_results/all_samples_results.csv')
assert len(cs)==len(cpp)==len(py)==8895
assert cs==cpp==py
print('OK: 8,895 triplets identical across C#/C++/Python')
EOF
```

## 2. 源数据一致性：01_source 三语言字节相同

三语言包 `01_source/` 的文件集与内容完全一致（MD5 相同）：

| 文件 | MD5 | 内容 |
|---|---|---|
| JavaAPI_splitted_method.zip | `74d018dea598b2086261f8bc37ee1490` | 按方法拆分的 API 源（1,053 类 / 10,954 方法） |
| JavaAPI_by_class.zip | `e198ac2ada7f9e7a5173b3bfe7c6f911` | 按类组织的 API 源（1,053 类） |
| Java_benchmark.zip | `647c041bbf760a31b5e70c917335289d` | 第一批 Randoop 测试（7,141 个） |
| javadoc_method_tests.zip | `6f00839cb19cc643323653fe7450c5a6` | 第二批 519 类 JUnit5 测试骨架 |
| javadoc_randoop_tests.zip | `9935af71bc67dbef076fa08fe860fdd0` | 第二批逐方法 Randoop 测试（1,754 个 .java + 生成记录） |
| benchmark_method_list.csv | `bde393e250e506034dbbca1ef76c4216` | 第一批方法清单（7,141 行） |
| javadoc_method_list.csv | `2bf98e968f1e2463f82448e5fd684f8c` | 第二批候选方法清单（3,367 行） |

三语言包 `02_randoop/method_master_list.csv`（10,508 行，含 domain 列）、
`coverage_summary.txt`、`benchmark_randoop_success.csv`（7,141 行）、
`javadoc_randoop_success.csv`（1,754 行）同样逐字节相同。

各语言包 `03_translation/` 覆盖该方向流水线的**全部阶段**（目标语言不同，
故内容各异）：

| 方向 | 阶段产物 |
|---|---|
| Java2C# | benchmark：类级 1,053 + 拆分无框架版 7,141 + 拆分框架保留版 7,141 + 测试体 4,477；javadoc：工作区全量 3,077 .cs + 步骤 CSV/日志 |
| Java2C++ | benchmark：类级 1,053 + 骨架 7,146 + 测试体 5,872；javadoc：类级 306 + 骨架 1,756 + 测试体 1,309 + 工作区 |
| Java2Python | benchmark：方法级 7,141 .py；javadoc：类级 306 + 骨架 1,754 + 测试体 1,750 |

另有各语言包 `04_results/raw/`（原始结果 CSV 与分析文档）、顶层
`tools/randoop-all-4.3.4.jar`（测试生成工具）。

## 3. 支撑数据与论文数字的对应关系

论文所有核心数字均可从本文件夹复算：

| 论文数字 | 复算来源 | 结果 |
|---|---|---|
| CSR C# 59.8%（5,320） | Java2C# CSV：非 ERROR 行 = PASS+FAIL | 4,771+549 = 5,320 ✓ |
| BSR C# 89.7%（4,771） | Java2C# CSV：PASS / (PASS+FAIL) | 4,771/5,320 = 89.7% ✓ |
| CSR C++ 80.7%（7,176） | Java2C++ CSV：8,895 − 编译失败 1,719（= ERROR 1,812 − 行为阶段 93） | 7,176 ✓ |
| BSR C++ 92.9%（6,668） | Java2C++ CSV：PASS / 7,176 | 6,668/7,176 = 92.9% ✓ |
| CSR Python 62.9%（5,591） | Java2Python CSV：PASS+FAIL | 3,804+1,787 = 5,591 ✓ |
| BSR Python 68.1%（3,804） | Java2Python CSV：PASS / 5,591 | 3,804/5,591 = 68.04%（论文四舍五入为 68.1%） |
| Fig.2 C++ n=1,719 | Java2C++ CSV syntax_error 计数 | 1,719 ✓ |
| Fig.2 Python n=3,304 | Java2Python CSV ERROR 计数 | 3,304 ✓ |
| Fig.3 C++ n=508 | Java2C++ CSV：FAIL 415 + CRASH 77（call_error）+ not_processed 16 | 508 ✓ |
| Fig.3 Python n=1,787 | Java2Python CSV FAIL 计数 | 1,787 ✓ |
| Fig.3 C# n=549 | Java2C# CSV FAIL 计数 | 549 ✓ |
| Table 1 合计 8,895 | 主清单 generated 计数 | 8,895 ✓ |

### 3.1 C# 终版分类的还原（IN-80 重跑）

C# 原始结果表早于论文终版分析。论文在结果定稿前对 80 个工具类失败（IN）
样本做了重跑（`Java2C#/04_results/error_taxonomy/csharp_in80_supplement.csv`，
含逐行 row_key 与新结果）。本文件夹已按该补充表逐行还原论文终版分类，
对账如下：

```
原始 CSV:            PASS 4,761 / FAIL 555 / ERROR 3,579
IN-80 重跑:          10 行 → PASS（重翻译后可编译可执行且行为一致）
                    21 行 → 行为失败（EX1/RV 叶，error_type 已按失败内容标注）
                     4 行 → IN2（无测试方法，ERROR→FAIL）
                     2 行 → IN3（超时）
还原后（=论文）:      PASS 4,771 / FAIL 549 / ERROR 3,575  ✓
```

### 3.2 C++ 16 行 not_processed

原始 C++ 结果表有 16 行"未达运行阶段"（not_processed）。论文将其计入行为
阶段失败（Fig.3 C++ n=508 中的 IN1 链接失败）。`all_samples_results.csv` 中
这 93 行行为阶段记录按原始标记保留：16 行 `result=ERROR`、`error_type=
not_processed`；77 行崩溃 `result=ERROR`、`error_location=call_error`
（`error_type=CRASH`）；加 `result=FAIL` 415 = 508 ✓，与论文 Fig.3 C++ n=508
一致。

### 3.3 论文 Table 1（13,748 方法 / 1,534 类）与仓库库存的差异

论文 Table 1 为数据集权威口径（Java SE 25 最终整理）。本仓库主清单
`method_master_list.csv` 为实验期库存：10,508 候选 = 7,141 benchmark +
3,367 javadoc（全 API 库存见 `Java2Python/02_randoop/method_master_list_full_api_13664.csv`，
13,664 方法 / 1,521 类，与论文 13,748/1,534 差 84 方法/13 类，系论文环境
最终整理时并入的少量补充）。两者共享的 8,895 个生成样本完全一致；主清单
`domain` 列可复现论文 Table 1 的 Randoop 列（多数域精确吻合，见总 README）。

### 3.4 Fig.2 / Fig.3 叶级分布

论文 Fig.2/Fig.3 的叶级分布由论文环境按分类法规则归类（C#：50 个错误码；
C++：g++ 诊断模式；Python：运行时错误模式）。本文件夹每行样本保留原始
`error_type` 与完整 `error_msg`（错误码/诊断原文），分类法定义与操作化说明
见 `TAXONOMY.md`，可独立复核。论文环境的叶级归类输出（Fig.2/Fig.3 与
Table 3/4 的底层分类、分域汇总文件）见 `05_analysis/`，与论文图表的对应
关系见 `ANALYSIS_DATA.md`。

## 4. 从原始实验目录到本文件夹的规范化改动记录

原始实验目录（`Java2C#/For Paper`、`Java2C++/For_Paper`、
`Java2Python/For_Paper`）**保持原样未动**；以下改动只落在本文件夹：

| # | 改动 | 原因 |
|---|---|---|
| 1 | 修复 C# `JavaAPI_splitted_method.zip`（原文件损坏，无法解析为 zip） | 用 C++/Python 的完好副本（MD5 `74d0…`）替换 |
| 2 | 统一 01_source 命名与文件集（C++ `api_methods.zip`→`JavaAPI_splitted_method.zip`、`benchmark_randoop.zip`→`Java_benchmark.zip` 等；Python 补 `benchmark_method_list.csv` 与 `javadoc_randoop_tests.zip`） | 三语言字节一致 |
| 3 | 重建 javadoc 两个 zip（剔除 `_progress.log`、`-checkpoint.java` 杂散文件） | 内容原为 1,754 个 .java 完全一致，仅打包杂质不同 |
| 4 | `javadoc_method_list.csv` 统一为 3,367 行候选清单（原 C#/C++ 为 1,754 行生成清单，生成子集已在 02_randoop） | 与 Python 及论文口径一致 |
| 5 | 主清单统一为 10,508 行并增加 `method`/`domain` 列、补全 benchmark FQCN（从 7,141 个测试文件的回归注释提取，100% 覆盖） | 与论文 Table 1 口径一致 |
| 6 | 成功清单统一列名 `class, method, number, fqcn, domain, source, randoop_status`（原 Python 为中文列名） | 跨语言可比较 |
| 7 | C# 结果表 dataset 标签 `old_benchmark/new_pipeline` → `Java_benchmark/Javadoc_new` | 与 C++/Python 及论文一致 |
| 8 | C# 结果表应用 IN-80 重跑还原（见 §3.1） | 与论文 Table 2/4 一致 |
| 9 | C++ 结果表 16 行 not_processed → FAIL/IN1（见 §3.2） | 与论文 Fig.3 一致 |
| 10 | Python 原始 javadoc 结果补 4 行 ERROR（Randoop 记录损坏样本：LocalDate.ofInstant/ofEpochDay/ofYearDay、ByteBuffer.allocateDirect），文件改名 `javadoc_result_1754.csv` | 原 1,750 行漏记 |
| 11 | Python `result_summary.txt` 重写（原为过期中间版本：PASS 3,716 → 实际 3,804） | 与 CSV 实际值及论文一致 |
| 12 | 三个语言包 README / DIRECTORY_SPEC 重写为论文术语（CSR/BSR/RQ/Fig） | 与论文对齐 |
| 13 | 剔除 `.ipynb_checkpoints`、`__pycache__` 等杂物 | 干净交付 |
| 14 | 补齐 C# `benchmark_splitted_method.zip`（7,141 个 .cs，框架保留版拆分，原目录 CsAPI_splitted_method） | 阶段完整性 |
| 15 | 补齐 C++ `benchmark_class_translated.zip`（1,053 个 .cpp，原目录 CppAPI_by_class） | 阶段完整性 |
| 16 | 补齐 Python `javadoc_class_translated.zip`（306 .py）与 `javadoc_skeletons.zip`（1,754 .py） | 阶段完整性 |
| 17 | 各语言包 `04_results/raw/`：归档原始结果 CSV 与分析文档（如 compile_nofw_results.csv、translation_result.csv、Java2PythonResult.csv 等 27 个文件） | 原始证据 |
| 18 | `tools/randoop-all-4.3.4.jar` + Python `01_source/javadoc_method_by_method.zip`（4,010 个逐方法 Java 测试）+ pipeline 工作区 zip（C#/C++） | 复现与中间产物 |
| 19 | error_taxonomy 补充 IN-80 清单（csharp_in80_checklist.csv、HANDOVER_IN80.md） | 分类证据 |

## 5. 原始实验目录 → 支撑材料完整映射

| 原始位置（/root/autodl-tmp 下） | 支撑材料位置 | 状态 |
|---|---|---|
| Java2C#/Java_benchmark/（7,141 测试） | 三语言 01_source/Java_benchmark.zip | ✓ 字节相同 |
| Java2C#/JavaAPI_by_class/（1,053 类） | 三语言 01_source/JavaAPI_by_class.zip | ✓ |
| JavaAPI_splitted_method.zip（C++/Python 根目录） | 三语言 01_source/JavaAPI_splitted_method.zip | ✓（C# 根目录那份已损坏，见 §4-1） |
| new_Java_class_tests/（519 类，= new_Java_method_tests，内容相同） | 三语言 01_source/javadoc_method_tests.zip | ✓ |
| new_Java_test_cases/（1,754 测试 + 记录） | 三语言 01_source/javadoc_randoop_tests.zip | ✓（剔除 2 个杂散文件） |
| Java2Python/new_method_by_method/（4,010 个逐方法 Java 测试） | Java2Python/01_source/javadoc_method_by_method.zip | ✓ 附录 |
| Javadoc_method_list_3367.csv / Javadoc_randoop_list_1754.csv / java_benchmark_inventory.csv | 01_source 两个方法清单 + 04_results/raw/ | ✓ |
| Java2C#/CsAPI_by_class + CsAPI_splitted_nofw + CsAPI_benchmark_translated | Java2C#/03_translation/benchmark_translated.zip | ✓ |
| Java2C#/CsAPI_splitted_method（7,145，框架保留版） | Java2C#/03_translation/benchmark_splitted_method.zip | ✓ 补齐 |
| Java2C#/pipeline_cs/（javadoc 批工作区） | Java2C#/03_translation/javadoc_translated.zip + pipeline_workspace.zip | ✓ |
| Java2C++/CppAPI_by_class（1,053） | Java2C++/03_translation/benchmark_class_translated.zip | ✓ 补齐 |
| Java2C++/CppAPI_splitted_method（7,146） | Java2C++/03_translation/benchmark_skeletons.zip | ✓ |
| Java2C++/Cpp_benchmark_translated（5,872） | Java2C++/03_translation/benchmark_translated.zip | ✓ |
| Java2C++/pipeline/（javadoc 批工作区） | Java2C++/03_translation/{javadoc_*.zip ×3} + pipeline_workspace.zip + logs/ | ✓ |
| Java2Python/PythonAPI_splitted_method（7,141 .py） | Java2Python/03_translation/benchmark_python_7141.zip | ✓ |
| Java2Python/PythonJavaDoc_by_class（306） / PythonJavadoc_splitted_method（1,754） / PythonJavadoc_test_cases（1,750） | Java2Python/03_translation/javadoc_{class_translated, skeletons, python_1750}.zip | ✓ 补齐 |
| 各根目录原始结果 CSV（compile_*.csv、behavior_results.csv、translation_result.csv、merged_results_8895.csv、Java2PythonResult.csv、mapping.csv、method_mapping.csv、migration_mapping.csv、python_test_results.csv、test_behavior_report.csv 等） | 各语言包 04_results/raw/（27 个文件） | ✓ 补齐 |
| Missing/ 清单（IN-80 / AS131 checklist + 交接） | 各语言包 04_results/error_taxonomy/ | ✓ 补齐 |
| randoop-all-4.3.4.jar | tools/ | ✓ 补齐 |
| pipeline_cs/*.py / pipeline/*.py / 根目录 translate_*.py 等脚本 | 各语言包 03_translation/scripts/ | ✓ |
| 分析文档（analysis_for_paper.txt、pipeline_plan.md、test_generation_analysis.md 等） | 各语言包 04_results/raw/ | ✓ |
| Java2C++/tmp_benchmark/ | 剔除（Java_benchmark 的重复拷贝，内容已含） | — |
| Java2C++/For_Paper_supporting_materials.zip | 剔除（旧版打包，已被本文件夹取代） | — |
| __MACOSX/、__pycache__/、.ipynb_checkpoints/、Untitled.ipynb、空目录 ":" | 剔除（系统/缓存杂物） | — |

## 6. 完整性校验

```bash
# 每个语言包：CSV 行数与 zip 完整性
python3 - <<'EOF'
import csv, zipfile, os
for lang in ['Java2C#','Java2C++','Java2Python']:
    with open(f'{lang}/04_results/all_samples_results.csv', encoding='utf-8-sig') as f:
        n = sum(1 for _ in csv.DictReader(f))
    assert n == 8895, lang
    with open(f'{lang}/02_randoop/method_master_list.csv', encoding='utf-8-sig') as f:
        m = sum(1 for _ in csv.DictReader(f))
    assert m == 10508, lang
    for root,_,files in os.walk(lang):
        for fn in files:
            if fn.endswith('.zip'):
                p = os.path.join(root, fn)
                assert zipfile.ZipFile(p).testzip() is None, p
    print(lang, 'OK')
EOF
```
