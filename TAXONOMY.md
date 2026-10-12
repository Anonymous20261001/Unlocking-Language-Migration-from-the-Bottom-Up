# 错误分类法（论文 §3.2.2 / §3.4.2）

论文定义了两套语言无关的分类法：编译错误 5 家族 15 叶子（RQ2），行为失败
4 家族 11 叶子（RQ4）。每行样本按观察到的输出（而非推测原因）归类，优先级：
编译——按编译器诊断；行为——instrumentation > abnormal termination >
exception mismatch > value mismatch。

## 一、编译错误分类法（S/R/T/C/E，5 家族 15 叶子）

### S. Syntax — 词法与结构层错误

| 叶 | 名称 | 判定 | 示例 |
|---|---|---|---|
| S1 | Invalid tokens | 杂散字符、未知关键字、非代码文本 | 残留反引号 `int \`x = 1;` → g++ "error: stray \` in program" |
| S2 | Delimiters and structure | 缺失/多余花括号、分号、圆括号，成员嵌套在成员内 | |

### R. Resolution — 工具链无法解析的引用

| 叶 | 名称 | 判定 | 示例 |
|---|---|---|---|
| R1 | Unknown type or namespace | 引用的类型/命名空间在目标语言不存在 | 未 include `<vector>` 使用 `std::vector`；C# CS0246 |
| R2 | Unknown member or constructor | 可解析类型上不存在的成员/构造器 | `list.empty()` 保留 Java 成员名（应 `isEmpty`） |
| R3 | Missing dependency | 头文件/库/import 找不到 | |

### T. Typing — 目标类型系统违规

| 叶 | 名称 | 判定 | 示例 |
|---|---|---|---|
| T1 | Call or argument mismatch | 实参数量/种类与目标签名不符 | 实例方法当作静态方法调用 `Double::isNaN(d)` |
| T2 | Conversion and return mismatch | 赋值/返回/条件/操作数不能隐式转换 | void 函数里 `return v;` |
| T3 | Generics and inference | 类型实参无法推断、约束不满足、模板参数误用 | |
| T4 | Declaration and initialization | 名字先于声明/初始化使用（C# CS0103 为主） | |

### C. Contract — 声明契约违规

| 叶 | 名称 | 判定 | 示例 |
|---|---|---|---|
| C1 | Duplicate or conflicting definition | 成员/类型/重载重复定义或声明冲突 | |
| C2 | Contract violation | 继承/接口规则违反：缺 override、未实现接口、错误返回类型、继承 sealed/实例化抽象 | `override` 不匹配任何基类虚函数 |
| C3 | Usage-context misuse | 静态/实例混淆、访问保护违规、赋值给只读成员 | |
| C4 | Feature unavailable | 需要工具链不提供的语言特性/版本 | |

### E. Environment — 工具链失败（非翻译错误）

| 叶 | 名称 | 判定 |
|---|---|---|
| E1 | Missing third-party library | 外部库缺失（C++：BigInteger/BigDecimal wrapper 含 gmpxx.h） |
| E2 | Toolchain failure | 编译器崩溃、超时、输出写失败（不含翻译质量含义） |

### 论文 Fig.2 叶级分布（RQ2 结果）

| 叶 | C# (n=4,492 条错误) | C++ (n=1,719) | Python (n=3,304) |
|---|---:|---:|---:|
| S1 | 12.5% | 4% | 6% |
| S2 | 7% | 5% | 0.9% |
| R1 | 25.6% | 27% | 16% |
| R2 | 6% | 5% | 16% |
| R3 | — | — | 0.2% |
| T1 | 4% | 7% | 25% |
| T2 | 1.7% | 22% | 1.3% |
| T3 | 2% | — | — |
| T4 | 20.4% | 6% | 32% |
| C1 | 8% | 11% | — |
| C2 | 7% | 8% | — |
| C3 | 3% | 3% | — |
| C4 | 2% | 0.2% | — |
| E1 | — | 3% | 0.2% |
| E2 | 0.5% | — | 1.4% |
| 家族合计 | S 19% / R 32% / T 28% / C 20% / E 1% | S 9% / R 32% / T 35% / C 22% / E 3% | S 7% / R 33% / T 58% / E 2% |

> 操作化：C# 经 50 个错误码映射（CS1525→S1、CS0103→T4、CS0246→R1、
> CS1061→R2 等）；C++ 经 g++ 诊断模式匹配；Python 以运行时错误对应
> （NameError→T4、TypeError→T1、ModuleNotFoundError→R2）。
> 各样本的首个错误码/消息保留在 `04_results/all_samples_results.csv`；
> C# 的"Java 残留"直接证据见 `Java2C#/04_results/error_taxonomy/HANDOVER_CS_RESIDUE.md`。

## 二、行为失败分类法（RV/EX/CR/IN，4 家族 11 叶子）

### RV. Failed assertions — 正常终止但与 oracle 不一致

| 叶 | 名称 | 判定 |
|---|---|---|
| RV1 | Wrong values | 返回值与期望不同 |
| RV2 | Wrong representations | 可观测渲染不同（底层值可能等价），如 ToString 输出分歧 |
| RV3 | Null values | 返回 null 而期望非 null，或反之（C++ 指针返回 nullptr） |
| RV4 | Other | 其余断言失败 |

### EX. Exception mismatch — 异常不一致

| 叶 | 名称 | 判定 |
|---|---|---|
| EX1 | Missing exceptions | oracle 抛异常而翻译不抛（如静默返回替代抛出） |
| EX2 | Unexpected exceptions | oracle 不抛而翻译抛出 |

### CR. Abnormal termination — 进程死亡而非正常结束

| 叶 | 名称 | 判定 |
|---|---|---|
| CR1 | Signal kills | 被信号杀死（如 CRASH(-11)） |
| CR2 | Silent deaths | 无输出死亡 |

### IN. Instrumentation — 评估工具失败（非翻译质量）

| 叶 | 名称 | 判定 |
|---|---|---|
| IN1 | Uncompilable test bodies | 翻译的测试体编译失败（C++ 含链接失败） |
| IN2 | Empty tests | 没有可执行测试方法 |
| IN3 | Timeouts | 超出时间限制 |

### 论文 Fig.3 分布（RQ4 结果）

| 家族 | C# (n=549) | C++ (n=508) | Python (n=1,787) |
|---|---:|---:|---:|
| RV 断言失败 | 58%（RV2 42% + RV1 16%） | 60%（RV1 41% + RV3 15% + RV2 4%） | 97%（RV2 55% + RV1 35% + RV4 6%） |
| EX 异常不匹配 | 34%（EX1 33%） | 15%（EX1） | 3%（EX1） |
| CR 异常终止 | — | 21%（CR1 10% + CR2 11%） | — |
| IN 工具失败 | 9%（IN1 43 + IN2 4 + IN3 2） | 3%（IN1 16，链接失败） | — |

> 要点：C# 行为失败集中于表示差异（RV2 41.9%）与缺失异常（EX1 32.8%）；
> C++ 唯一出现崩溃（109）与空值不匹配（76）；Python 行为失败几乎全部
> 是表示差异（RV2 55.5%），即最轻微的一类失败。

## 与 all_samples_results.csv 的对应关系

CSV 的 `error_location` 是粗粒度桶（none / syntax_error / import_error /
call_error / behavior_diff），细粒度叶级分类见：

| 语言 | 细粒度证据文件 |
|---|---|
| C# | `Java2C#/04_results/error_taxonomy/csharp_in80_supplement.csv`（IN-80 重跑 80 行，含 EX1/RV 判定） |
| C++ | `Java2C++/04_results/error_taxonomy/cpp_as131_supplement.csv`（AS131 断言失败补录） |
| 全部 | CSV 的 `error_type` / `error_msg` 保留每个样本的原始错误码与完整消息，可按上表规则复核 |
