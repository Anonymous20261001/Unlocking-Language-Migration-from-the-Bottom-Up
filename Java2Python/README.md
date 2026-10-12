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

Python has no compile phase, so the paper uses "execution-equivalence checking"
to surface the runtime errors corresponding to compile errors: if a translated
program errors out before invoking the target API (import failures, undefined
names, etc.), it counts as a compile-equivalent failure. This check is more
lenient than static compilation (it absorbs type/signature mismatches), so
Python's CSR should not be compared directly with other languages; it is a
baseline for import/parsing correctness.

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

### Result Distribution (aligned with paper Fig.2 n=3,304 / Fig.3 n=1,787)

| error_location | Count | Meaning |
|---|---|---|
| none (PASS) | 3,804 (42.8%) | behaviorally consistent |
| behavior_diff | 1,787 (20.1%) | API invoked successfully, behavior differs from Java (paper Fig.3: RV 97% / EX 3%) |
| call_error | 2,532 (28.4%) | name/signature mismatch (paper Fig.2: T4 32.2% + T1 24.9%) |
| import_error | 540 (6.1%) | missing dependency (paper Fig.2: R2 16.3%, mostly ported java/javax imports) |
| syntax_error | 232 (2.6%) | Python file cannot be parsed (paper Fig.2: S family 7.0%) |

### Key Takeaways (Python side of paper Finding 5)

- 62.9% of samples pass the execution-equivalence check (compile-correct),
  indicating that Java→Python API translation itself is of high quality
- but BSR is only 68.1%: Python's check is lenient, and behavioral differences
  (RV2 representation differences, 55.5%) become the largest failure class
- for 4 Javadoc_new samples (LocalDate.ofInstant/ofEpochDay/ofYearDay,
  ByteBuffer.allocateDirect) the Java test files are missing (corrupted Randoop
  records); per the paper's convention they count as execution-equivalence
  failures

## Directory Structure

```
Java2Python/
├── README.md                  # this file
├── DIRECTORY_SPEC.md          # directory specification (common across languages)
├── 01_source/                 # source data (zip + csv, byte-identical across the three languages; javadoc_method_by_method.zip is this direction's appendix)
├── 02_randoop/                # Randoop coverage analysis
│   ├── method_master_list.csv # candidate-method master list (10,508 rows, identical across the three languages)
│   ├── method_master_list_full_api_13664.csv  # full API inventory appendix (13,664 rows)
│   ├── coverage_summary.txt   # coverage overview (identical across the three languages)
│   ├── coverage_summary_full_api.txt          # full-API coverage appendix
│   └── *_randoop_success.csv  # per-batch success lists
├── 03_translation/            # Python translation artifacts (all stages, complete)
│   ├── benchmark_python_7141.zip   # benchmark batch: method-level translations, 7,141 .py files (with compilation caches)
│   ├── javadoc_class_translated.zip # javadoc batch: class-level translations (306 .py files + mapping table)
│   ├── javadoc_skeletons.zip       # javadoc batch: method-level skeletons (1,754 .py files)
│   ├── javadoc_python_1750.zip     # javadoc batch: test-body translations, 1,750 .py files (4 samples lack Java sources, see above)
│   └── scripts/               # pipeline scripts
└── 04_results/                # experiment results
    ├── all_samples_results.csv # complete results for 8,895 samples (core)
    ├── result_summary.txt
    ├── benchmark_result_7141.csv
    ├── javadoc_result_1754.csv # 1,754 rows (including ERROR records for the 4 missing-source samples)
    ├── behavior_report.csv
    ├── translation_audit_150.csv
    └── raw/                   # raw results and documents (Java2PythonResult.csv and 6 others)
```

## CSV Column Reference

**method_master_list.csv**: `class, method, number, fqcn, domain, source, randoop_status, failure_category, failure_reason`

**all_samples_results.csv**: `class, method, number, dataset, result, error_type, error_msg, error_location`

## Translation Consistency Audit (150-sample audit, calibration of the paper §3.3.1 agent-based audit)

| Metric | Value |
|---|---|
| Audited samples | 150 (120 benchmark + 30 javadoc, random seed 42) |
| Criterion | whether assertions and expected-exception checks are preserved (lenient: ignoring exception granularity, message wording, variable naming) |
| CONSISTENT | 149 (99%) |
| INCONSISTENT | 0 |
| SKIP | 1 |

Conclusion: assertion/expected-exception translation fidelity is 99%; the main
failure modes are wrapper behavior (behavior_diff) and call signatures
(call_error). Audit records: `04_results/translation_audit_150.csv`; audit
script: `03_translation/scripts/audit_translation.py`.
