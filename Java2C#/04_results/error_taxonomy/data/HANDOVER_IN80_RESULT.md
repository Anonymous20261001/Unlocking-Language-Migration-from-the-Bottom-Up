# IN-80 重跑交接结果

> 日期: 2026-08-29
> 交付: error_taxonomy/data/csharp_in80_supplement.csv (80 行)

## 1. 执行方式

- 按交接文档协议重跑 80 个 IN 行:
  - IN-compile (42) / IN-empty (36): 用 deepseek-chat 重新翻译测试体
    (C# 类定义 + Java 测试体 → 无参数 void 测试方法),
    编译失败时带编译器错误反馈重试, 最多 4 轮;
    库级编译通过后注入 Main() 运行取结果
  - IN-timeout (2): 仅重新执行确认
- 16 个并行 worker, 每行独立处理, 结果按 row_key 对齐

## 2. 结果汇总

| status | 数量 | new_outcome 分布 |
|---|---|---|
| fixed | 31 | PASS ×10, 断言失败 ×21 |
| still_fails | 49 | 编译错误 ×43, no_test_method ×4, timeout ×2 |

### fixed (31) — 可由作者重新归类

- **PASS ×10**: 重翻译后可编译可执行且行为一致, 建议移出失败集或归入通过
- **断言失败 ×21**: 翻译产物可执行, 产生了真实运行时结果
  (如 `TEST FAILED: Expected exception of type NullReferenceException...`),
  可按断言内容归入 RV/EX

### still_fails (49) — 保留 IN, 按 failure_content 细分

- 编译错误 ×43: 测试体翻译后仍编译失败 (含 1 条 CS0029 void→bool)
- no_test_method ×4: 重翻译后仍无参数化测试方法
  (MultiProgressBarUIAutoTest ×3, FixedHeightLayoutCacheAutoTest ×1)
- timeout ×2: RandomAutoTest.nextgaussian, ReentrantLockAutoTest.lock 稳定超时

## 3. 自检

- [x] 80 行逐行有 status; fixed 有 new_outcome, still_fails 有 failure_content
- [x] row_key 与清单一一对应 (80 唯一键, 无缺失无重复)
- [x] 未改动 merged_8895.csv 与 csharp_in80_checklist.csv

## 4. 备注

- 重翻译产物已写回 CsAPI_benchmark_translated/ (按管线输出惯例覆盖)
- 4 个 new_pipeline 行 (IN-compile) 已按其实际路径处理
  (Java 源在 new_Java_test_cases/, 骨架在 pipeline_cs/02_CsAPI_splitted_nofw/)
- API 认证: 脚本优先读 .env 的 DEEPSEEK_API_KEY (bashrc 中导出的旧 key 会覆盖 .env, 已规避)
