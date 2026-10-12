# 交接文档:C# 翻译产物中"Java 残留"证据采集

**日期**:2026-09-15
**委托方**:论文《Do LLMs Already Possess API Mapping Knowledge?》(RQ2 同名陷阱论证)
**执行方式**:由另一 agent 在翻译产物所在环境执行,结论以 Markdown 返回。

## 背景

论文 RQ2 提出"同名陷阱"(same-name trap)解释:因为 Java 与 C# 表面相似,
LLM 把 Java 语法与类型名**照搬**进 C#,而不是做真正的映射,导致 C# 的编译
失败集中在 S1(无效 token)与 T4(声明错误)——CS1525(无效表达式项)与
CS0103(当前上下文不存在该名字)是其中最高频的错误码(各约 500 次,居
C# 全部错误码前 3)。

该机制目前只有**间接证据**(错误码性质 + Core Language 域最差)。
需要**直接证据**:在编译失败的 C# 翻译文件中,找到错误位置确为 Java
语法/类型名残留的实例,并给出统计。

## 任务

### 1. 定位翻译产物

找到 Java→C# 翻译生成的 `.cs` 文件。已知线索:
- 论文目录 `/Users/jeff/Desktop/博一/API mapping Draft` 下**没有**这些文件,
  请在其他位置查找(实验服务器、原始实验工作目录、按项目名
  api-translation / j2cs / translation 相关路径);
- 翻译单位:每个 Java API 类一个 wrapper 文件(类名形如
  `java_util_ArraysAutoTest`),编译前按**方法拆分**为每方法一个编译单元
  (含 import 与类骨架);
- 同时找到 `C#_merged_8895.csv` 对应的原始翻译输出目录(该 CSV 有
  dataset/class/method 列,可用于对齐文件)。

### 2. 采集失败单元的 Java 残留证据

对**编译失败**(stage1 或 final 编译报错)的 `.cs` 单元,检查报错行
(错误码 CS1525 / CS0103 / CS0246 / CS1514 等)是否出现以下 Java 残留模式:

| 模式 | 说明 |
|---|---|
| `Integer` / `Character` / `Boolean` / `Short` / `Long` / `Float` / `Double` | Java 包装类名(C# 无) |
| `java\.` / `javax\.` / `jdk\.` | Java 包全限定名被原样搬入 |
| `String[]` / `int[]` 形式的数组声明 | Java 数组语法(C# 用 `string[]`) |
| `@Test` / `@Override` / `@Deprecated` 等注解 | Java 注解语法残留 |
| `System\.out` / `System\.err` | Java 标准输出调用 |
| `boolean` / `final ` / `implements` | Java 关键字(C# 用 bool/readonly/:) |
| `new String(...)` / `equals(` 等明显的 Java API 用法 | Java API 直接调用 |

### 3. 产出结论(严格按此格式)

1. **翻译产物位置与规模**:路径、文件总数、失败单元数;
2. **定性实例**:抽样至少 10 个失败文件,逐个给出
   `文件名 | 报错行号 | 错误码 | 报错内容(原文) | Java 残留片段(原文)`;
3. **统计(如可行)**:按错误码分组(CS1525/CS0103/CS0246),统计含
   Java 残留模式的单元数/比例;
4. **对照组(如可行)**:随机抽 50 个**编译成功**的单元,统计其中
   Java 残留模式出现率,与失败单元对比;
5. **一句话结论**:Java 残留与 CS1525/CS0103 失败是否存在直接关联。

### 4. 注意事项

- 只报告**可定位到行**的证据,不要推测;
- 若找不到翻译产物,直接报告"未找到",并列出搜索过的路径;
- 不要修改任何文件,只读分析。
