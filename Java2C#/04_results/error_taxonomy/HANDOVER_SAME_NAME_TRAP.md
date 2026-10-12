# 交接文档：C# 低编译通过率与"同名陷阱"分析

> 日期: 2026-09-15
> 交付人: pipeline agent
> 关联: HANDOVER_CS_RESIDUE.md（残留证据采集）+ RQ2 同名陷阱论证

## 1. 数据规模与定位

| 数据集 | 方法数 | 类数 | 编译单元位置 | 编译通过 |
|---|---|---|---|---|
| old_benchmark | 7141 | 811 | `CsAPI_splitted_nofw/{class}/{method}_test_{N}.cs` | 4408 (61.7%) |
| new_pipeline (Javadoc) | 1754 | 306 | `pipeline_cs/02_CsAPI_splitted_nofw/{class}/{method}_test_{N}.cs` | 1017 (58.0%) |
| **合计** | **8895** | — | 对齐: `pipeline_cs/merged_8895.csv` | **5425 (61.0%)** |

对照: C++ 同 1754 基准 = 1309/1738 (75.3%)（重试后）; 991/1754 (56.5%)（初始）。

## 2. 直接证据：Java 残留（详见 RESIDUE_REPORT.md）

- 3470 个失败单元重编译, 3447 报错
- 错误行直接含 Java 残留: 82 单元 (2.4%)
- 定性实例 8 条（含行号+原文）: `>>>` 运算符、`boolean` 关键字、
  `using java.awt.datatransfer;`（Java import 原样搬入）、
  `static class Double` + 实例构造、`Arrays.BinarySearch` 等
- 对照组: 50 个成功单元中"残留"25/50 出现, 但 24 处在注释/文档,
  1 处字符串, 仅 1 处在代码 → 成功单元无代码级残留

## 3. 陷阱的三种形态（比"逐字复制"更准确）

| 形态 | 定义 | 证据 | 量级 |
|---|---|---|---|
| **规则迁移** | Java 规则 + C# 语法（合法关键字、违规规则） | CS0525 接口常量 (539次, 抽样300/300确认: `const int ABORT=0x80;` 在 interface 内); CS0708/0710 静态类带实例成员 (21单元 100%) | ~8% 错误 |
| **名字沿用** | Java 类/方法名进入 C# 上下文 | CS0246 类型名 17% 为 Java 名; CS0103 名字 37% 为 Java 名（如 `Arrays.BinarySearch`、`FloatBuffer.allocate`、`Charset.availableCharsets`） | ~6% 错误 |
| **逐字复制** | Java 语法原样搬入 | `>>>` (28次)、`boolean`、`using java.`、`@Test` | 2.4% 单元 |

三种形态合计 ≈ 15-17% 错误出现次数。

## 4. 反事实分析：去掉陷阱后的通过率

| 数据集 | 失败单元 | 纯陷阱单元 | 陷阱修复后通过率 |
|---|---|---|---|
| new_pipeline (1754) | 731 | **384 (52%)** | 1017+384 = 1401/1754 = **79.9%** |
| old_benchmark (7141) | 2716 | 105 (4%) | 4408+105 = 4513/7141 = 63.2% |
| **合并 8895** | 3447 | 489 | 5914/8895 = **66.5%** |

纯陷阱单元定义: 该单元的全部编译错误均为陷阱类
（规则码 CS0525/CS0708/CS0710、Java 名词典命中的 CS0246/CS0103、错误行残留）。

**关键结论（仅 Javadoc 1754 子集有 C++ 对照）**:
- C# 实际 58.0% → 陷阱修复后 **79.9% > C++ 75.3%**
- 陷阱使 C# 损失约 22 个百分点, 大于 C# 与 C++ 的当前差距 (17.3pp)
- 即: 同名陷阱不只解释 C# 的劣势, 还使"最相似语言"从应然的第一名
  跌到实际最低

## 5. 新旧数据集陷阱率差异（prompt 效应证据）

| 数据集 | 失败中纯陷阱占比 | 管线差异 |
|---|---|---|
| new_pipeline | 52% | step1 prompt 未显式警告 Java/C# 差异; 用 v4-flash |
| old_benchmark | 4% | translate_v2_cs prompt 含明确 C# 规则（无 NUnit、Debug.Assert 等） |

13 倍的差异表明**陷阱可被 prompt 设计抑制**。

## 6. 结论层级（诚实版）

**有数据支撑**:
1. C# 错误集中在词法/语法/声明层, C++ 集中在语义层（错误码分布）
2. 陷阱三形态可量化解释 15-17% 错误次数、53%/4% 失败单元（分数据集）
3. Javadoc 子集反事实: 陷阱修复后 C# (79.9%) 反超 C++ (75.3%)

**推测性（未测量）**:
1. ~~"60% 错误可归因于按 Java 方式写 C#"~~ 已撤回, 无测量依据
2. ~~"逐字复制是主机制"~~ 已撤回, 实际主机制是规则迁移+名字沿用
3. 陷阱修复后的 79.9% 是反事实上界（假设纯陷阱单元修复即通过;
   混合单元 11/207 个未计入）

## 7. 交付物清单

| 文件 | 内容 |
|---|---|
| `error_taxonomy/data/RESIDUE_REPORT.md` | 残留直接证据（实例+统计+对照） |
| `error_taxonomy/data/WHY_CS_LOWEST.md` | 机制分析（v2 修正版） |
| `error_taxonomy/data/residue_cache.json` | 3470 失败单元编译错误缓存 |
| `error_taxonomy/data/residue_instances_final.json` | 210 条错误行级残留实例 |
| `error_taxonomy/data/residue_control.json` | 50 个成功单元对照组 |
| `error_taxonomy/data/collect_residue.py` | 残留采集脚本（可复跑） |
| `error_taxonomy/data/collect_control.py` | 对照组脚本 |

## 8. 复跑方式

```bash
cd /root/autodl-tmp/Java2C#
python3 error_taxonomy/data/collect_residue.py    # 有缓存直接复用; 删缓存则重编译(约10分钟)
python3 error_taxonomy/data/collect_control.py
```
