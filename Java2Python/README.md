# Java→Python Translation Experiment Data Package

Supporting materials for the Java→Python direction of the paper *Unlocking
Language Migration from the Bottom Up: A Large-Scale Study on the Java Standard
Library*.

## Dataset and Setup

| Item | Value |
|---|---|
| Study population | 8,895 method-level translation units (Randoop-covered Java standard-library API methods) |
| Batch composition | `Java_benchmark` 7,141 + `Javadoc_new` 1,754 (the two batches have zero overlap) |
| Target language | Python (no compile phase; execution-equivalence checking replaces compilation checking) |
| Translation model | DeepSeek-V4 Flash, zero-shot, single-pass translation |
| Two-phase evaluation | Phase 1 execution-equivalence checking (RQ1–RQ2) → Phase 2 behavioral correctness (RQ3–RQ4) |


## Dataset Size (full API inventory, appendix convention)

| Metric | Value |
|---|---|
| Total Java API methods (excluding Object methods ×11) | 13,664 (1,521 classes, experiment-period inventory; paper Table 1 reports 13,748 / 1,534 classes) |
| Randoop-generated tests (including 365 tests for Object methods) | 8,895 |
| Non-Object method coverage | 8,530 / 13,664 = 62% |
| Uncovered | 5,134 (38%; 55% are GUI classes due to headless restrictions) |

Excluded Object methods: toString, hashCode, equals, clone, finalize, getClass,
notify, notifyAll, wait (3 overloads)

## Key Metrics (aligned with paper Table 2 / Table 4)

| Metric | This package | Paper |
|---|---|---|
| Execution-equivalence pass rate (CSR) | 5,591 / 8,895 = **62.9%** | 62.9% |
| Behaviorally consistent | **3,804** | 3,804 |
| Behavioral success rate (BSR) | 3,804 / 5,591 = 68.0% | 68.1% (rounding difference) |
| Overall reliability | 3,804 / 8,895 = **42.8%** | 42.8% |


## Directory Structure

```
Java2Python/
├── README.md                  # this file
├── 01_source/                 # Java source data (zip + csv; javadoc_method_by_method.zip is this direction's appendix)
├── 02_randoop/                # Randoop coverage analysis
│   ├── method_master_list.csv # candidate-method master list (10,508 rows, identical across the three languages)
│   ├── method_master_list_full_api_13664.csv  # full API inventory appendix (13,664 rows)
│   └── *_randoop_success.csv  # per-batch success lists
├── 03_translation/            # Python translation artifacts
│   ├── benchmark_python_7141.zip   # benchmark batch: method-level translations, 7,141 .py files (with compilation caches)
│   ├── javadoc_class_translated.zip # javadoc batch: class-level translations (306 .py files + mapping table)
│   ├── javadoc_skeletons.zip       # javadoc batch: method-level skeletons (1,754 .py files)
│   └── javadoc_python_1750.zip     # javadoc batch: test-body translations, 1,750 .py files (4 samples lack Java sources, see above)
└── 04_results/                # experiment results
    ├── all_samples_results.csv # complete results for 8,895 samples (core)
    ├── benchmark_result_7141.csv
    ├── javadoc_result_1754.csv # 1,754 rows (including ERROR records for the 4 missing-source samples)
    ├── behavior_report.csv
    └── translation_audit_150.csv
```

