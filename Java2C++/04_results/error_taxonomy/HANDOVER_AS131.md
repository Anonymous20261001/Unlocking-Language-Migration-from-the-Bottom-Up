# 交接文档:C++ 行为失败内容补录(AS-131)

> 交付对象:管线 agent
> 日期:2026-08-29
> 联系人:论文作者

## 1. 背景

在 LLM API 翻译研究中,C++ javadoc 子集的 131 个方法**行为评估失败**(测试断言未通过,
`run_status = FAIL`),但数据管线当时只把失败原因存成了 `test.out` 文件的**路径**,没有保存
断言失败的实际内容(预期值 vs 实际值、异常文本等)。

因此这 131 条目前只能标记为 AS(assertion failure with unrecorded content),
无法归入论文 RQ4 的失败子类(RV-value / RV-repr / RV-null / EX-missing / EX-unexpected /
CR-signal / CR-silent)。本任务的目的:**补录这 131 条测试的失败内容**,使它们可以完成分类。

## 2. 输入数据

| 文件 | 说明 |
|---|---|
| `error_taxonomy/data/cpp_as131_checklist.csv` | **本任务的清单**,131 行,每行包含定位信息 |
| `结果/C++_merged_results_8895.csv` | 原始数据(第 2 版修复后),`run_status == 'FAIL'` 的 131 行即任务对象 |

清单列含义:

| 列 | 含义 |
|---|---|
| `dataset` | 固定为 `javadoc` |
| `class` / `fqcn` / `package` | 包装类名 / 完整类名 / 所属 Java 包 |
| `method` | 被测 Java API 方法名 |
| `test_num` | Randoop 测试编号(全局唯一,建议作为主键) |
| `cpp_function` | 翻译后的 C++ 测试函数名 |
| `final_reason` | 目前仅有 `test.out: <路径>`(即内容缺失之处) |
| `row_key` | `class|method|test_num`,回填时用它对行 |

## 3. 任务

对清单中**每一行**,获取该测试失败时的**完整断言输出**,来源优先级:

1. **原始 `test.out` 文件**:按 `final_reason` 中的路径读取文件内容(文件仍在服务器上时首选;
   通常形如 `/root/autodl-tmp/Java2C++/pipeline/03_CppJavadoc_test*/.../test.out`)
2. **重跑该测试**:用 `cpp_function`(或按 `class`/`method`/`test_num` 定位)重新执行该 C++
   测试,捕获其失败输出(stderr + stdout)

要求:
- 失败内容必须是**断言失败时的原始文本**(如 `expected ... got ...`、异常堆栈等),
  不要做任何分类或改写
- 若测试当前**已通过**(环境修复/数据变更导致),请标记 `status = now_passes`,不要给成功输出
- 若无法定位(文件丢失且无法重跑),请标记 `status = not_found`

## 4. 为什么需要"完整断言内容"(分类规则,供参考)

回填后我们会按失败消息的直接含义分类,因此消息中需要能看出以下区别:

| 目标子类 | 判别特征 |
|---|---|
| RV-value | 数值/对象不相等,如 `x != y`、`expected 3, got 4` |
| RV-repr | 字符串表示不同,如 `expected "abc", got "def"`(toString/打印格式差异) |
| RV-null | `nullptr` vs 非空(`null_check_failed`) |
| EX-missing | 期望抛异常但未抛(如 `expected_exception_not_thrown`) |
| CR-* | 进程崩溃 / 无输出 |

如果 test.out 内容里这些信息齐全,分类即可完成;若只有 "FAILED" 之类摘要则不够,请尽量取完整输出。

## 5. 交付格式

请将结果写成 **UTF-8 CSV** 文件,放到:

```
error_taxonomy/data/cpp_as131_supplement.csv
```

列定义:

```
row_key, class, method, test_num, status, failure_content
```

- `row_key` / `class` / `method` / `test_num`:与清单保持一致(用于对行)
- `status`:found / now_passes / not_found
- `failure_content`:断言失败的原始文本(found 时必填);允许包含换行,
  请按 CSV 规范加引号转义

**不要修改** `C++_merged_results_8895.csv` 或清单文件本身。

## 6. 完成后

通知作者(或直接把文件放好),作者会:
1. 把 131 条按第 4 节规则重新分类进 RV/EX/CR 各类
2. 更新论文 RQ4 表(C++ 的 AS 行将被真实子类取代)
3. 更新 `error_taxonomy/data/rq4_classified.csv` 与统计

## 7. 快速自检(交付前)

- [ ] 131 行逐行都有 status,且 found 行都有非空 failure_content
- [ ] row_key 与清单一一对应,无缺失、无重复
- [ ] failure_content 是原始失败文本,未做任何总结/翻译
- [ ] 未改动任何既有数据文件
