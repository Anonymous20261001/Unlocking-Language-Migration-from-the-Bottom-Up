# Java → Python 测试翻译语义修复报告

生成日期：2026-07-18
翻译脚本：translate_ast.py

---

## 一、文件覆盖

| 项目 | 数量 |
|---|---|
| Python 测试文件总数 | 11,055 |
| 有具体 Java 测试对应可逐句比对 | 7,059 |
| 仅对应参数化骨架（无期望值可查） | 3,996 |
| Java 有但 Python 缺失 | 0 |
| benchmark 空文件已清理 | 577 |

---

## 二、翻译器修复 & 复检

修复前后对比（translate_ast.py 共 8 处改动）：

| 问题 | 根因位置 | 修复前 | 修复后 |
|---|---|---|---|
| 异常测试被吞（永不 fail） | _trans_try 无条件输出 except Exception | 1,462 | 0 |
| 负号丢失（-1→1） | Literal.prefix_operators 被忽略 + javalang 括号负数 bug | 392 | 0 |
| char 强转错为字符串 | (int)'a' 输出字符串而非 ord 值 | 321 | 0 |
| 浮点后缀语法错误 | 正则不匹配科学计数法 2.14E9f | | |
| 关键字方法名撞车 | .not()/.and()/.or() 非法 Python | 102 | 0 |
| f-string 内 quotes/braces 错误 | _fstr 裸按 + 切分 | | |
| getClass()→__class__() | __class__() 会建新实例，应为 type() | | |
| FileDescriptor.in→in_ | static field 名撞关键字 | | |

---

## 三、7,059 个测试运行结果（2026-07-19 重跑）

### 总览

| 结果 | 数量 | 占比 | 含义 |
|---|---|---|---|
| pass | 2,516 | 35.6% | 行为一致 |
| fail | 2,002 | 28.4% | 真实行为不一致 |
| error | 2,541 | 36.0% | 没跑到断言（mock 缺零件） |

可执行测试通过率 (pass / pass+fail): **55.7%** (2,516 / 4,518)

### fail 细分（2,002）

| 根因 | 数量 |
|---|---|
| mock 该抛异常但没抛（空 pass 桩） | ~974 |
| mock 返回值与 Java 不符 | ~1,028 |

### error 细分（2,541）

| 根因 | 数量 | 谁该修 |
|---|---|---|
| import 阶段即缺类/缺成员 | ~156 | mock |
| import 成功但执行中途因 mock 缺陷崩溃 | ~2,385 | mock |
| 翻译器遗留 | 0 | — |

---

## 四、本次范围外的已知问题

| 问题 | 数量 |
|---|---|
| mock 代码损坏/缺零件致 error | ~2,541 |
| mock 行为偏差致 fail | 2,002 |
| 0 个 Java 测试无 Python 对应 | 0 |
| 骨架类 113 个测试未真正调用被测 API | 113 |

## 五、2026-07-19 更新记录

- 翻译 126 个缺失 Java→Python 测试（94 test4python + 32 benchmark）
- 删除 577 个 benchmark 空文件（Randoop 未生成）
- 全量重跑 7,059 个测试，结果记录至 `_generation_record.csv` 的 `test_result` 列
- 逐类报告: `test_behavior_report.csv`
