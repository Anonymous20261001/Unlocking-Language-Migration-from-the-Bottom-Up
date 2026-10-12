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

## Directory Structure

- `01_source/`: Java source data — method-list CSVs and source archives
  (JavaAPI_by_class.zip, JavaAPI_splitted_method.zip, the first-batch Randoop
  tests `Java_benchmark.zip`, the two javadoc-batch test archives)
- `02_randoop/`: Randoop generation records and coverage
  (method_master_list.csv is the master list, 10,508 rows)
- `03_translation/`: translation artifacts of the pipeline stages
- `04_results/`: experiment results (all_samples_results.csv is the master
  table, 8,895 rows) + per-stage and per-batch reports


## Coarse error_location Classification

| Value | Meaning |
|---|---|
| none | compiles and runs |
| syntax_error | compilation failure (CS1525/CS1056/CS1519/CS0111/CS0525/CS0708 and other syntax/declaration errors) |
| import_error | missing type/namespace (CS0246/CS0234) |
| call_error | name/signature mismatch (CS0103/CS1061/CS0117/CS1501) or runtime exception |
| behavior_diff | compiles and invokes successfully but behavior differs (paper RV/EX/IN families) |

