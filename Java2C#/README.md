# Java→C# Translation Experiment Data Package

Supporting materials for the Java→C# direction of the paper *Unlocking Language
Migration from the Bottom Up: A Large-Scale Study on the Java Standard Library*.

## Dataset and Setup

| Item | Value |
|---|---|
| Study population | 8,895 method-level translation units (Randoop-covered Java standard-library API methods) |
| Batch composition | `Java_benchmark` 7,141 + `Javadoc_new` 1,754 (the two batches have zero overlap) |
| Target language | C# (.NET 8.0 SDK, compiled with mono-mcs / mcs) |
| Translation model | DeepSeek-V4, zero-shot, temperature=0, single-pass translation, no compile feedback |
| Two-phase evaluation | Phase 1 compilation correctness (RQ1–RQ2) → Phase 2 behavioral correctness (RQ3–RQ4) |

## Pipeline (one compilation unit per method)

1. **Class-level translation**: Java class-level test skeleton → LLM-generated
   C# wrapper class + test skeleton
2. **Method splitting**: split into per-method .cs compilation units (imports +
   a single test method)
3. **Skeleton compilation**: syntax check with `mcs -target:library`
4. **Test-body translation**: Java Randoop test bodies → LLM-translated C# test
   bodies (only for skeletons that compile)
5. **Compile + run**: inject `Main()`, compile, run (10 s timeout), compare
   against the Java oracle

## Key Metrics (aligned with paper Table 2 / Table 4)

| Metric | This package | Paper |
|---|---|---|
| Compilation success rate (CSR) | 5,320 / 8,895 = **59.8%** | 59.8% |
| Behaviorally consistent | **4,771** | 4,771 |
| Behavioral success rate (BSR) | 4,771 / 5,320 = **89.7%** | 89.7% |
| Overall reliability | 4,771 / 8,895 = **53.6%** | 53.6% |

Failure distribution (out of 8,895):

| Category | Count | Share |
|---|---|---|
| Compilation failures (ERROR) | 3,575 | 40.2% |
| Behavioral failures (FAIL, paper Fig.3 n=549) | 549 | 6.2% |
| └ of which tool-class failures IN (49 rows after the IN-80 rerun) | 49 | 0.6% |

C# has the lowest CSR of the three targets: the "same-name trap" analysis of
paper RQ2 shows that the surface similarity between Java and C# makes the LLM
copy Java syntax/type names verbatim (S1 invalid tokens and T4 declaration
errors) instead of truly mapping them.

## Directory Structure

- `01_source/`: Java source data — method-list CSVs and source archives
  (JavaAPI_by_class.zip, JavaAPI_splitted_method.zip, the first-batch Randoop
  tests `Java_benchmark 00.21.39.zip`, the two javadoc-batch test archives)
- `02_randoop/`: Randoop generation records and coverage
  (method_master_list.csv is the master list, 10,508 rows)
- `03_translation/`: translation artifacts of the pipeline stages
- `04_results/`: experiment results (all_samples_results.csv is the master
  table, 8,895 rows) + per-stage and per-batch reports

### 03_translation artifacts

| File | Contents |
|---|---|
| `benchmark_translated.zip` | benchmark batch: class-level wrappers (1,053) + framework-free splits (7,141) + test bodies (4,477) |
| `benchmark_splitted_method.zip` | benchmark batch: framework-preserving splits (7,141 .cs files, the intermediate stage with NUnit references not stripped) |
| `javadoc_translated.zip` | javadoc batch: all .cs files in the pipeline workspace (3,077, including class-level / skeletons / test bodies) |

## Data-File Reference

| File | Rows | Contents |
|---|---|---|
| 02_randoop/method_master_list.csv | 10,508 | method master list (class, method, number, fqcn, domain, source, status) |
| 04_results/all_samples_results.csv | 8,895 | per-sample result (result, error_type, error_msg, error_location) |
| 04_results/benchmark_skeleton_compile.csv | 7,141 | benchmark-batch skeleton compile check |
| 04_results/benchmark_translated_compile.csv | 4,408 | benchmark-batch test-body compile check |
| 04_results/benchmark_behavior.csv | 4,303 | benchmark-batch run/behavior records |
| 04_results/javadoc_method_report.csv | 1,754 | javadoc-batch per-method pipeline report |
| 04_results/javadoc_skeleton_compile.csv | 1,754 | javadoc-batch skeleton compile check |
| 04_results/behavior_report.csv | 1,117 | per-class behavioral aggregation |
| 04_results/translation_audit_150.csv | 150 | translation-consistency audit (agent-based audit calibration) |
| 02_randoop/javadoc_uncovered_1613.csv | 1,613 | javadoc-uncovered appendix |

## Coarse error_location Classification

| Value | Meaning |
|---|---|
| none | compiles and runs |
| syntax_error | compilation failure (CS1525/CS1056/CS1519/CS0111/CS0525/CS0708 and other syntax/declaration errors) |
| import_error | missing type/namespace (CS0246/CS0234) |
| call_error | name/signature mismatch (CS0103/CS1061/CS0117/CS1501) or runtime exception |
| behavior_diff | compiles and invokes successfully but behavior differs (paper RV/EX/IN families) |

Note: the leaf-level distribution of paper Fig.2 (n=4,492 compilation errors;
the C# compiler can report several errors for one method) was classified in the
paper environment against the 50 C# error codes; the CSV keeps the primary
error code and message per row for re-checking. The corresponding classification
outputs are in the top-level `analysis/` folder.
