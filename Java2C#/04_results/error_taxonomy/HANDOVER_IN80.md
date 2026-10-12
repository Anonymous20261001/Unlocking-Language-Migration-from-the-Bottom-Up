# 交接文档:C# 仪器故障行重跑(IN-80)

> 交付对象:管线 agent
> 日期:2026-08-29
> 联系人:论文作者

## 1. 背景

C# 目标有 **80 个方法**在行为评估(RQ4)中被归为 **IN(Instrumentation,仪器故障)**,
即"翻译后的**测试本身**没能运行起来",没有产生可与 Java oracle 对比的运行时结果:

| 子类 | 数量 | 含义 |
|---|---|---|
| IN-compile | 42 | 翻译后的**测试体**编译失败(38 条来自运行失败行 `error_message` 以 `COMPILE_ERR` 开头;4 条来自门径级 `final_compile = COMPILE_ERROR`) |
| IN-empty | 36 | 翻译结果中找不到可执行的测试方法(`error_message = no_test_method`) |
| IN-timeout | 2 | 测试运行超时(`error_message = timeout`) |

本任务目的:**重新跑这 80 个方法的测试体翻译/编译/执行**,确认它们是真实的仪器故障,
还是可修复后产生正常行为结果;若确实失败,补录完整失败内容。

## 2. 输入数据

| 文件 | 说明 |
|---|---|
| `error_taxonomy/data/csharp_in80_checklist.csv` | 本任务清单,80 行,含定位信息 |

清单列含义:

| 列 | 含义 |
|---|---|
| `dataset` | `old_benchmark`(7,141 子集)或 `new_pipeline`(1,754 子集) |
| `class` / `method` | 包装类 / 被测 Java API 方法(短类名或全名,取决于 dataset) |
| `number` | Randoop 测试编号(建议作为主键,与类内方法联合定位) |
| `cls` | 现有分类:`IN-compile` / `IN-empty` / `IN-timeout` |
| `error_message` | 现有失败消息(如 `COMPILE_ERR: ...`、`no_test_method`、`timeout`) |
| `run_pass` / `final_compile` | 原数据中的运行/编译标记 |
| `row_key` | `class|method|number`,回填时对行用 |

## 3. 任务

对清单中**每一行**,按 `cls` 分类处理:

### 3.1 IN-compile(42 行)

按 Phase-2 测试体翻译协议重新执行(与主线管线相同:提供 C# 类定义 + Java 测试体,
翻译为 C# 测试方法,编译失败时允许按编译器错误反馈重试,上限见主线设置)。

- 若最终编译通过并能执行 → `status = fixed`,在 `new_outcome` 填运行结果
  (`PASS` / 断言失败内容)
- 若仍编译失败 → `status = still_fails`,在 `failure_content` 填最终编译器错误全文

### 3.2 IN-empty(36 行)

检查翻译产物为何没有测试方法(翻译输出为空?方法名不匹配?)。

- 若重新翻译后得到可执行测试方法 → `status = fixed`,填 `new_outcome`
- 若反复翻译仍无测试方法 → `status = still_fails`,在 `failure_content` 简述现象
  (如"输出为空"/"方法名不匹配")

### 3.3 IN-timeout(2 行)

重新执行一次,确认是否稳定超时。

- 若通过/失败(非超时)→ `status = fixed`,填 `new_outcome`
- 若仍超时 → `status = still_fails`,填 `failure_content = timeout`

## 4. 交付格式

结果写成 **UTF-8 CSV**,放到:

```
error_taxonomy/data/csharp_in80_supplement.csv
```

列定义:

```
row_key, class, method, number, status, new_outcome, failure_content
```

- `row_key`/`class`/`method`/`number`:与清单一致(对行用)
- `status`:`fixed` / `still_fails`
- `new_outcome`:fixed 时的运行结果(`PASS`,或断言失败原文;编译失败填 `COMPILE_ERR`)
- `failure_content`:still_fails 时的失败原文(可为空,若 new_outcome 已说明)

**不要修改** `C#_merged_8895.csv` 或清单文件本身。

## 5. 完成后

作者会:
1. 将 `fixed` 行按 `new_outcome` 重新归类(改入 RV/EX,或移出失败集)
2. `still_fails` 行保留在 IN,并按补录内容细化(如区分"翻译输出为空"与"编译错误")
3. 更新 `rq4_classified.csv`、RQ4 表与三环图

## 6. 快速自检(交付前)

- [ ] 80 行逐行有 status,且 fixed 行有 new_outcome、still_fails 行有 failure_content
- [ ] row_key 与清单一一对应,无缺失、无重复
- [ ] 未改动任何既有数据文件
