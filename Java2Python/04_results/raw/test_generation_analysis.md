# 测试生成机制分析：骨架参数 vs Randoop 硬编码输入

生成日期：2026-07-18
关联报告：translation_fix_report.md

---

## 缘起

疑问：Python 测试函数签名有 `p0: Point2D` 这样的参数，但函数体里却是
`point2D2 = None` 硬编码赋值，参数完全没被使用。这个生成逻辑是什么？
Java 侧测试时会给骨架参数传值吗？

结论：**不会。骨架参数在 Java 和 Python 两侧都不参与实际测试。**

---

## 一、语料库中的三种文件角色

### 1. 骨架模板（JavaAPI_splitted_method/，10,954 个）—— 不可运行

```java
@Test
public void contains_test_988(Point2D p0) {   // 带参数的 @Test
    Area instance = new Area();
    instance.contains(p0);
}
```

- 带参数的 @Test 方法 JUnit 无法运行（JUnit 4 直接报错；
  JUnit 5 无 ParameterResolver 时抛 ParameterResolutionException）
- 作用仅是声明"要测哪个 API、参数是什么类型"，供 Randoop 生成使用

### 2. Randoop 具体测试（Java_test_cases4python/，7,059 个）—— Java 侧真正跑的

```java
@Test
public void contains_test_988() throws Throwable {   // 无参数
    Area area0 = new Area();
    Point2D point2D2 = null;      // Randoop 探索时决定的输入，硬编码
    try {
        area0.contains(point2D2);
        fail("Expected NullPointerException");
    } catch (NullPointerException e) { }
}
```

- Randoop 自动探索调用序列，把所有输入硬编码进方法体
- 是回归测试：断言/期望异常记录的是生成时的实际观察行为，
  因此在 Java 侧全部通过（构造保证）
- 骨架参数在这个世界里不存在

### 3. Python 测试（PythonAPI_splitted_method/，10,929 个）—— 两阶段拼合

```python
def contains_test_988(p0: Point2D):   # 签名：LLM 按骨架生成（遗迹，未删）
    area0 = Area()                     # 函数体：translate_ast.py 直译 Randoop
    point2D2 = None                    # Java `null` → Python `None`
    _raised = False
    try:
        area0.contains(point2D2)
    except Exception:
        _raised = True
    assert _raised, 'Expected exception'
```

| 元素 | 来源 |
|---|---|
| 函数签名（p0 等参数） | LLM 按骨架生成，翻译器不动签名 |
| mock 类（Point2D、Rectangle2D…） | LLM 生成，翻译器不动 |
| 函数体（硬编码值 + 断言） | translate_ast.py 直译 Randoop 具体测试 |

签名参数与函数体是两条平行线：`p0` 来自骨架声明，`point2D2 = None`
来自 Randoop 就地赋值，互不相干。runner 给 p0 传占位值只是为了避免
缺参 TypeError，值本身无意义。

---

## 二、三种测试范式对比

| 范式 | 输入来源 | Java 侧是否运行过 | 验证内容 |
|---|---|---|---|
| 骨架直接跑 | 外部参数（无人提供） | 否（JUnit 跑不了） | — |
| Randoop 测试 | 方法体内硬编码 | 是，全部通过 | 具体值行为 + 期望异常 |
| 预实验（Python） | 外部按类型喂最简单值 | Java 无对应 | 仅"调用不崩" |
| 本次翻译后（Python） | 方法体内硬编码（同 Randoop） | 与 Randoop 对齐 | 具体值行为 + 期望异常 |

预实验"8999 个没问题"与本次"2501 个 error"的差异来源见
translation_fix_report.md：判定标准不同（不崩 = OK vs 行为全匹配），
且 error 根因是 mock 缺类/缺构造重载/缺常量，与输入值无关。

---

## 三、重要推论：3,753 个骨架-only Python 文件没有 ground truth

Randoop 未能覆盖全部骨架（full_run.out：3,947 个方法 uncovered），
因此有 3,753 个 Python 文件只有骨架对应、没有 Randoop 具体测试：

- 它们函数体里的硬编码值和断言是当初 LLM 自行编造的
- 在 Java 侧从未运行过，没有"全部通过"的保证
- 其断言期望值无 ground truth，语义正确性无法用 Java 行为验证
- 本次 translate_ast.py 重新生成只覆盖 7,003 个 migrate 行，
  不包括这批文件

如需为这批文件建立 ground truth，需先让 Randoop 覆盖对应方法
（或人工确认期望值），再走翻译管线。
