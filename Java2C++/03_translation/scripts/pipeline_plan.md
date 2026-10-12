# C++ Translation Pipeline

Java → C++ 测试代码翻译流水线。将 306 个 Java 类（1754 个方法）的 Randoop 测试翻译为可编译运行的 C++ 测试。

## 目录结构

```
pipeline/
├── README.md                          # 本文件
├── step1_translate_class.py           # Step 1: 整类翻译 + 方法完整性验证
├── step1_retry_v3.py                  # Step 1 补充: 换模型重试剩余类
├── step1_retry_large.py               # Step 1 补充: 大类的分块翻译
├── step2_split_methods.py             # Step 2: 机械拆分
├── step2.5_compile_check.py           # Step 2.5: 编译检查
├── step3_translate_bodies.py          # Step 3: 测试体翻译
├── step3_retry_compile.py             # Step 3 补充: 编译反馈重翻译
├── step4_run_tests.py                 # Step 4: 编译+运行验证
├── 01_CppJavadoc_API_by_class/        # Step 1 输出 (306 个类级 C++ 文件)
├── 01_translate.log                   # Step 1 日志 (JSONL)
├── 02_CppJavadoc_splitted_method/     # Step 2 输出 (1754 个方法级 C++ 文件)
├── 02_split.log                       # Step 2 日志 (JSONL)
├── 02.5_compile_check.csv             # Step 2.5 结果
├── 02.5_compile_check.log             # Step 2.5 日志
├── 03_CppJavadoc_test_cases/          # Step 3 输出 (990 个最终 C++ 测试)
├── 03_translate_bodies.log            # Step 3 日志 (JSONL)
├── 03_retry_compile.log              # Step 3 重翻译日志 (JSONL)
├── 04_test_results/                   # Step 4 输出
│   └── cpp_test_results.csv           # 最终测试结果
└── *.log                              # 各 worker 运行日志
```

## 外部依赖（只读）

| 路径 | 说明 |
|---|---|
| `new_Java_method_tests/{Class}.java` | 306 个类级 Java 测试 (JUnit 5, @Test 骨架) |
| `new_Java_test_cases/{Class}/{method}_test_{N}.java` | 1754 个方法级 Randoop Java 测试 (JUnit 4, 含断言) |
| `Javadoc_randoop_list_1754.csv` | 映射表: 测试编号, 类全名, 包名, 类名, 方法名, 文件名 |
| `.env` | DeepSeek API 配置 |

## 流水线步骤

### Step 1: 整类翻译 + 方法完整性验证

**脚本**: `step1_translate_class.py`

**输入**: `new_Java_method_tests/{Class}.java` (306 类)

**输出**: `01_CppJavadoc_API_by_class/{Class}.cpp` (306 文件)

**流程**:
1. 从 CSV 解析每个类应有的方法列表
2. 整个 Java 文件发给 DeepSeek → 翻译为完整 C++（类实现 + 测试函数）
3. 验证 C++ 输出中包含所有预期方法名
4. 缺失方法 → 提示 LLM 重翻译（最多 3 次）
5. 记录每类的重试次数、方法覆盖率

**Prompt A** (System):
```
You are a professional Java and C++ developer.
Below is a Java test file. Each @Test method creates an instance of a Java class
and exercises one of its API methods.
Your task:
1. Translate every Java @Test method into exactly one C++ test function with the
SAME name (e.g., equals_test_6446 -> void equals_test_6446()).
2. For each Java class used in the tests, implement a C++ equivalent class whose
API behaves identically to the original Java API.
Output only the complete C++ code. No markdown fences, no explanations.
```

**模型**: `deepseek-chat` (temperature=0.1, max_tokens=16384)

**结果**: 306/306 类完成，1754/1754 方法覆盖

---

### Step 2: 机械拆分

**脚本**: `step2_split_methods.py`

**输入**: `01_CppJavadoc_API_by_class/*.cpp` + CSV

**输出**: `02_CppJavadoc_splitted_method/{Class}/{method}_test_{N}.cpp` (1754 文件)

**流程**:
1. 读取每个 C++ 文件，提取 header（#include + 类定义，即第一个测试函数之前的部分）
2. 用正则匹配所有测试函数: `void\s+(\w+_test_\d+)\s*\(`
3. 对 CSV 中每个方法，找到对应函数体，组装为 header + 函数体的独立文件

**边缘情况**:
- 函数缩进不一致 → 正则 `\n\s*void` 兼容
- 嵌套括号在参数中 → fallback 用字符串查找 + 括号匹配

**结果**: 1754/1754 拆分完成

---

### Step 2.5: 编译检查

**脚本**: `step2.5_compile_check.py`

**输入**: `02_CppJavadoc_splitted_method/*/*.cpp`

**输出**: `02.5_compile_check.csv`

**流程**:
1. 对每个方法文件执行 `g++ -std=c++17 -fsyntax-only -w`
2. 记录 PASS/FAIL 及错误信息
3. 8 进程并行 (multiprocessing.Pool)

**结果**: 991 PASS (56.5%), 763 FAIL (43.5%)

---

### Step 3: 测试体翻译

**脚本**: `step3_translate_bodies.py`

**输入**:
- C++ 骨架: `02_CppJavadoc_splitted_method/{Class}/{method}_test_{N}.cpp` (仅 Step 2.5 编译通过的)
- Java 测试: `new_Java_test_cases/{Class}/{method}_test_{N}.java`

**输出**: `03_CppJavadoc_test_cases/{Class}/{method}_test_{N}.cpp` (990 文件)

**流程**:
1. 读取骨架，提取类定义 header
2. 读取对应 Java Randoop 测试
3. 组合 prompt：类定义 + Java 测试 → LLM 输出纯 C++ 函数体
4. 清理 LLM 输出（去 markdown、去多余括号、去函数签名包装）
5. 组装: header + 翻译后的函数体

**Prompt B** (System):
```
You translate Java test code to C++.
Given C++ class definitions and a Java test method body,
output ONLY the C++ function body (lines between { and }).

Mapping rules:
- Assert.assertTrue(msg, cond) -> assert(cond);
- Assert.assertFalse(msg, cond) -> assert(!cond);
- Assert.assertEquals(msg, expected, actual) -> assert(expected == actual);
- Assert.assertNull(msg, obj) -> assert(obj == nullptr);
- Assert.assertNotNull(msg, obj) -> // removed
- Assert.fail(msg) -> assert(false);
- try { ... } catch (SomeException e) { } -> try { ... } catch (...) { }
- new Type(args) -> Type(args)
- null -> nullptr
- Use the EXACT types and method names from the class definitions provided

重要规则: 如果不是编译问题，不要为了通过测试而改动wrapper类。
只有在wrapper类本身有编译错误时才修改它。

Output ONLY the function body lines. No explanation, no markdown,
no #include, no class definitions, no function signature.
```

**模型**: `deepseek-chat` (temperature=0.1, max_tokens=2048-4096)

**结果**: 990/990 翻译完成

**补充脚本**: `step3_retry_compile.py` — 对编译失败的方法进行 4 轮编译反馈重翻译，每轮将编译错误喂给 LLM 重新翻译。

---

### Step 4: 编译 + 运行验证

**脚本**: `step4_run_tests.py`

**输入**: `03_CppJavadoc_test_cases/*/*.cpp`

**输出**: `04_test_results/cpp_test_results.csv`

**流程**:
1. `-fsyntax-only` 语法检查
2. 创建 wrapper (注入 `main()` 调用测试函数)
3. `g++ -std=c++17 -O0` 编译 + 链接
4. 运行可执行文件（10 秒超时）
5. 记录 COMPILE_ERROR / PASS / FAIL

**结果**: 962 编译通过 (97.1%), 667 运行通过 (67.4%)

---

## 最终结果

### 全流水线统计 (1754 目标方法)

| 步骤 | 通过 | 失败 | 通过率 |
|---|---|---|---|
| Step 1 类翻译 | 306/306 类 | 0 | 100% |
| Step 2 方法拆分 | 1754 | 0 | 100% |
| Step 2.5 骨架编译 | 991 | 763 | 56.5% |
| Step 3 测试体翻译 | 990 | 0 | 100% |
| Step 4 编译通过 | 962 | 28 (链接) | 97.1% |
| **Step 4 运行通过** | **667** | 295 | **67.4%** |

### 总通过率

```
1754 目标方法
├── 991 骨架编译通过 → 进入 Step 3
│   ├── 962 编译+链接通过 (97.1%)
│   └──  667 运行通过 (67.4%)  ← 最终可用
└── 763 骨架编译失败 → 未进入翻译
```

**最终运行通过: 667/1754 (38.0%)**

### 瓶颈分析

1. **Step 1 骨架质量 (最大瓶颈)**: 763 方法 (43.5%) 骨架编译失败，无法进入后续
   - 原因: LLM 翻译的 C++ 类实现有语法错误或缺失依赖
   - 改进方向: 增强 Prompt A 要求编译验证、使用更强的模型

2. **Step 3 测试体质量**: 295 方法运行失败（骨架编译通过但测试逻辑错）
   - 原因: LLM 对 C++ 类型系统理解不准，API 幻觉
   - 改进方向: 编译反馈循环（已部分改善）

3. **Step 4 链接失败**: 28 方法骨架方法体缺失
   - 原因: LLM 翻译的类声明了方法但未实现

## 使用方法

### 运行单个步骤

```bash
# Step 1: 多 worker 并行
for i in 0 1 2 3; do
    STRIDE=4 OFFSET=$i nohup python3 pipeline/step1_translate_class.py \
        > pipeline/worker${i}.log 2>&1 &
done

# Step 2
python3 pipeline/step2_split_methods.py

# Step 2.5
python3 pipeline/step2.5_compile_check.py

# Step 3: 多 worker
for i in 0 1 2 3; do
    STRIDE=4 OFFSET=$i nohup python3 pipeline/step3_translate_bodies.py \
        > pipeline/step3_w${i}.log 2>&1 &
done

# Step 4
python3 pipeline/step4_run_tests.py
```

### 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `DEEPSEEK_API_KEY` | API 密钥 | 从 `.env` 读取 |
| `DEEPSEEK_API_URL` | API 地址 | `https://api.deepseek.com/v1/chat/completions` |
| `DEEPSEEK_MODEL` | 模型名 | `deepseek-chat` |
| `OFFSET` | Worker 编号 (0-based) | 0 |
| `STRIDE` | Worker 总数 | 1 |
| `LIMIT` | 限制处理数量 | 0 (不限制) |

## 技术要点

### 模型选择

- `deepseek-v4-flash`: 快速但输出容量有限，容易出现空响应
- `deepseek-chat`: 更大的输出容量和更好的代码质量，推荐使用

### C++ 编译

- 标准: C++17 (`-std=c++17`)
- 语法检查: `-fsyntax-only -w` (仅检查语法，不链接)
- 完整编译: `-O0` 生成可执行文件

### 已知问题

1. LLM 输出的 `string`/`vector` 缺少 `std::` 前缀
2. LLM 输出的函数体可能包含多余或缺失的 `{` `}`
3. LLM 对骨架中的 C++ API 可能产生幻觉（调用不存在的方法）
4. 部分骨架类声明了方法但缺少实现体（导致链接失败）
