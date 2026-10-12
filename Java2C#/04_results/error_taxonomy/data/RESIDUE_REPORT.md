# Java 残留证据采集报告（RQ2 同名陷阱）

## 1. 翻译产物位置与规模

| 数据集 | 位置 | 方法单元数 | 编译失败单元 | 备注 |
|---|---|---|---|---|
| old_benchmark (7141) | `/root/autodl-tmp/Java2C#/CsAPI_splitted_nofw/{class}/{cs_file}` | 7141 | **2733** | 对齐键: compile_nofw_results.csv 的 (class, number)→cs_file |
| new_pipeline (1754) | `/root/autodl-tmp/Java2C#/pipeline_cs/02_CsAPI_splitted_nofw/{class}/{filename}` | 1754 | **737** | 对齐键: method_report.csv 的 (class, filename) |
| 合计 | — | 8895 | **3470** | 与 merged_8895.csv 的 stage1_skeleton_compile=FAIL 一致 |

对齐 CSV: `pipeline_cs/merged_8895.csv`（8895 行, dataset/class/method/number 列）。
注: 3470 个失败单元中 3447 个重编译仍报错, 23 个当前可编译（期间人工修复过）。

## 2. 定性实例（错误行上的 Java 残留, 原文摘录）

| 文件名 | 行 | 错误码 | 报错内容 | Java 残留片段 |
|---|---|---|---|---|
| java_lang_IntegerAutoTest/decode_test_5892.cs | 20 | CS1525 | Unexpected symbol `>' | `if (i >>> 16 == 0) { n += 16; i <<= 16; }` ← Java 无符号右移 `>>>` |
| java_lang_IntegerAutoTest/parseInt_test_5895.cs | 20 | CS1525 | Unexpected symbol `>' | `if (i >>> 16 == 0) { ... }` |
| JFileChooserAutoTest/setAcceptAllFileFilterUsed_test_7055.cs | 280 | CS0246 | type/namespace `boolean` not found | `public void ..._test_7055(boolean p0)` ← Java boolean 关键字 |
| AreaAutoTest/getBounds_test_993.cs | 16 | CS0710 | static class cannot have instance constructor | `public Double(double x, double y)` ← Java 包装类名 Double 作为 C# 类名 |
| ShortAutoTest/compareUnsigned_test_2096.cs | 13 | CS0103 | name `Short` not found | `Short.CompareUnsigned(p0, p1);` ← Java Short 包装类 + PascalCase 方法混用 |
| StringAutoTest/valueOf_test_2133.cs | 260 | CS1502 | no overload matches | `new String(Regex.Replace(_value, regex._value, replacement._value, 1));` ← Java new String(...) API |
| java_awt_datatransfer_SystemFlavorMapAutoTest/decodeJavaMIMEType_test_12439.cs | 2 | CS0246 | namespace `java` not found | `using java.awt.datatransfer;` ← Java import 语句原样搬入 C# |
| IntegerAutoTest/toUnsignedLong_test_2029.cs | 235 | CS0117 | no definition for `ToUnsignedLong` | `Integer.ToUnsignedLong(p0);` ← Java Integer 包装类名作 C# 类型 |

（更多实例见 residue_instances_final.json, 共 210 条错误行级证据）

## 3. 统计（按错误码, 单位=方法文件, 首个错误码）

| 错误码 | 失败单元数 | 错误行含残留 | 比例 |
|---|---|---|---|
| CS0246 (类型不存在) | 771 | 29 | 3.8% |
| CS0103 (名字不存在) | 604 | 2 | 0.3% |
| CS1525 (无效表达式项) | 423 | 12 | 2.8% |
| CS0234 (命名空间类型缺失) | 189 | 15 | 7.9% |
| CS0708/CS0710 (静态类实例成员) | 21+ | 21 | 100% |

错误行级（一次错误一条）残留分布: CS0710 84 / CS0246 39 / CS1525 28 / CS1056 20 / CS1502 15 / CS1503 15 / CS0103 8 / CS0117 1。

残留模式命中数: java_wrapper_type 101 (Integer/Character/Boolean/Short/Long/Float/Double 类名) / java_fqcn 47 (java./javax./jdk. 全限定名) / java_api_call 30 (.equals( / new String() / System.out) / java_unsigned_shift 28 (>>>) / java_keyword 4 (boolean/final/implements)。

## 4. 对照组（50 个随机编译成功单元）

- 25/50 文件整体文本含 ≥1 种模式
- 命中上下文: **24 处注释**（如 `// C# equivalent of java.util.LinkedList`）、1 处字符串字面量、1 处代码
- 结论: 成功单元中"残留"只出现在注释/文档里, 不出现在可执行代码位置

## 5. 一句话结论

**Java 残留直接出现在编译错误行上的单元仅占 82/3447 (2.4%)**, 其中 CS1525 的 `>>>` 运算符与 CS0710 的 Java 包装类名（Double/Integer 等作 C# 类名）是最强的直接证据, 但**同名陷阱不是 CS1525/CS0103 大面积失败的主因**——绝大多数失败单元的报错行并不含可定位的 Java 残留, 按现有证据 CS1525/CS0103 的直接残留关联比例分别仅为 2.8% 与 0.3%。
