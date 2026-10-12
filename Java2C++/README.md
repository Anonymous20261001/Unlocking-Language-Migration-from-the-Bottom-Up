# Java→C++ Translation Experiment Data Package

Supporting materials for the Java→C++ direction of the paper *Unlocking Language
Migration from the Bottom Up: A Large-Scale Study on the Java Standard Library*.

## Dataset and Setup

| Item | Value |
|---|---|
| Study population | 8,895 method-level translation units (Randoop-covered Java standard-library API methods) |
| Batch composition | `Java_benchmark` 7,141 + `Javadoc_new` 1,754 (the two batches have zero overlap) |
| Target language | C++ (g++ 11.4.0, C++17, x86_64-linux-gnu) |
| Translation model | DeepSeek-V4 (deepseek-chat / deepseek-v4-flash), zero-shot, single-pass translation |
| Two-phase evaluation | Phase 1 compilation correctness (RQ1–RQ2) → Phase 2 behavioral correctness (RQ3–RQ4) |

## Pipeline (five steps for the second batch; the first batch used an early one-shot + retry)

1. **Class-level translation**: Java class-level test skeleton → LLM-generated
   C++ wrapper class + test skeleton
2. **Method splitting**: split into per-method .cpp compilation units
3. **Skeleton compilation gate**: g++ compile check (one error per method,
   1,719 in total)
4. **Test-body translation**: Java Randoop test bodies → LLM-translated C++
   test bodies
5. **Compile + run**: compare behavioral consistency against the Java oracle

## Key Metrics (aligned with paper Table 2 / Table 4)

| Metric | This package | Paper |
|---|---|---|
| Compilation success rate (CSR) | 7,176 / 8,895 = **80.7%** | 80.7% |
| Behaviorally consistent | **6,668** | 6,668 |
| Behavioral success rate (BSR) | 6,668 / 7,176 = **92.9%** | 92.9% |
| Overall reliability | 6,668 / 8,895 = **75.0%** | 75.0% |

Failure distribution (out of 8,895; aligned with paper Fig.2 n=1,719 /
Fig.3 n=508):

| Category | Count | Share |
|---|---|---|
| Compilation failures (paper Fig.2 n=1,719, one error per method) | 1,719 | 19.3% |
| Behavioral failures (paper Fig.3 n=508 = 415 + 77 + 16) | 508 | 5.7% |
| ├ assertion/value/representation/exception mismatches (behavior_diff) | 415 | 4.7% |
| ├ runtime crashes (call_error, CR family) | 77 | 0.9% |
| └ linker failures (IN1, the 16 not_processed rows) | 16 | 0.2% |

## Directory Structure

- `01_source/`: Java source data — method-list CSVs and source archives
  (JavaAPI_by_class.zip, JavaAPI_splitted_method.zip, Java_benchmark.zip, the
  two javadoc-batch test archives)
- `02_randoop/`: Randoop generation records and coverage
  (method_master_list.csv is the master list)
- `03_translation/`: C++ translation artifacts of the pipeline stages
- `04_results/`: experiment results (all_samples_results.csv is the master
  table, 8,895 rows) + per-batch and audit reports

### 03_translation artifacts

| File | Contents |
|---|---|
| `benchmark_translated.zip` | benchmark batch: test-body translations (5,872 .cpp files, = Cpp_benchmark_translated) |
| `benchmark_class_translated.zip` | benchmark batch: class-level wrappers (1,053 .cpp files, = CppAPI_by_class) |
| `benchmark_skeletons.zip` | benchmark batch: method-level skeletons (7,146 .cpp files, = CppAPI_splitted_method) |
| `javadoc_class_translated.zip` | javadoc batch: class-level translations (306 classes) |
| `javadoc_skeletons.zip` | javadoc batch: method-level skeletons (1,756 .cpp files) |
| `javadoc_test_cases.zip` | javadoc batch: final tests (1,309 .cpp files) |

## Data-File Reference

| File | Rows | Contents |
|---|---|---|
| 02_randoop/method_master_list.csv | 10,508 | method master list (class, method, number, fqcn, domain, source, status) |
| 04_results/all_samples_results.csv | 8,895 | per-sample result (result, error_type, error_msg, error_location) |
| 04_results/benchmark_result.csv | 7,141 | first-batch raw results |
| 04_results/javadoc_result.csv | 1,754 | second-batch pipeline summary |
| 04_results/audit_150_samples.csv | 150 | translation-consistency audit (agent-based audit calibration) |


