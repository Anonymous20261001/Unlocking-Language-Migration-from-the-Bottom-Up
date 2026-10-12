# Unlocking Language Migration from the Bottom Up — Supporting Materials

This repository contains the experimental supporting materials for the paper
**"Unlocking Language Migration from the Bottom Up: A Large-Scale Study on the
Java Standard Library"**, covering all three translation directions (Java→C#,
Java→C++, Java→Python): source data, Randoop test-generation records, LLM
translation artifacts, and compilation and behavioral evaluation results.

## Research Overview

Language migration in real projects stalls at API call sites: the API surface
is huge and cross-language semantic differences are subtle. The paper proposes
a **bottom-up strategy** — the standard library is the common foundation of all
applications and dependencies; if an LLM can migrate standard-library APIs,
application migration becomes feasible. To this end, the paper:

1. generates wrappers for the public API methods of the Java standard library
   (Java SE 25) (construct an instance + invoke a single API method), isolating
   translation difficulty strictly to API mapping itself;
2. uses Randoop to generate tests for 8,895 API methods (covering 14 functional
   domains) as behavioral oracles;
3. judges correctness with a two-level oracle: **compilation** (Phase 1,
   RQ1–RQ2) and **differential testing** (Phase 2, RQ3–RQ4).

## Dataset Overview (paper Table 1)

| Domain | Classes | Methods | Randoop coverage | Representative packages |
|---|---:|---:|---:|---|
| Core Language | 132 | 1,667 | 1,118 | java.lang, java.text, java.beans, java.math |
| Data Containers | 106 | 1,392 | 1,176 | java.util |
| Concurrency | 63 | 1,095 | 499 | java.util.concurrent, jdk.incubator.vector |
| IO | 61 | 228 | 199 | java.io, java.nio |
| Date & Time | 32 | 259 | 248 | java.time |
| Security | 160 | 572 | 347 | java.security, javax.crypto, javax.net.ssl |
| AWT (Graphics 2D) | 189 | 2,063 | 858 | java.awt, java.awt.image |
| Swing (GUI) | 447 | 4,740 | 3,193 | javax.swing |
| Networking | 73 | 334 | 258 | java.net, java.rmi, javax.naming |
| Database | 41 | 233 | 202 | javax.xml, java.sql |
| Monitoring & Managing | 95 | 478 | 295 | javax.management, jdk.jfr, jdk.jshell |
| Media | 102 | 499 | 407 | javax.sound, javax.print, javax.imageio |
| Dynamic Languages | 21 | 144 | 77 | javax.script, jdk.dynalink |
| Dev Tools | 12 | 44 | 18 | javax.tools |
| **Total** | **1,534** | **13,748** | **8,895** | — |

> The paper is the authoritative source for the dataset (final Java SE 25
> inventory, excluding com.sun.\* / netscape.\* / bridge and synthetic methods).
> The master list `02_randoop/method_master_list.csv` is the experiment-period
> inventory (10,508 candidates = 7,141 benchmark + 3,367 javadoc) and has a
> `domain` column, so the Randoop column of paper Table 1 can be re-checked per
> functional domain (Concurrency 499, Date & Time 248, Media 407, Dynamic
> Languages 77, etc. match exactly; per-domain deviations of ±1–2% stem from
> final inventory adjustments in the paper environment).

## Core Results (paper Table 2 / Table 4)

| Target | CSR (compile/execution equivalence) | Behaviorally consistent | BSR | Overall reliability |
|---|---:|---:|---:|---:|
| C# (.NET 8.0) | 5,320 / 8,895 = **59.8%** | 4,771 | **89.7%** | 53.6% |
| C++ (g++ 11.4.0) | 7,176 / 8,895 = **80.7%** | 6,668 | **92.9%** | 75.0% |
| Python (execution equivalence) | 5,591 / 8,895 = **62.9%** | 3,804 | **68.1%** | 42.8% |

All numbers can be recomputed exactly from each language package's
`04_results/all_samples_results.csv` (CSR denominator = non-compile-failure
samples; BSR = PASS / CSR denominator).


## Folder Structure

```
Unlocking_Language_Migration_Supporting_Materials/
├── README.md                  # this file
├── analysis/                  # leaf-level error classifications and per-domain summaries (evidence behind Fig.2/3 and Table 3/4)
├── Java2C#/                   # Java→C# data package (README + 01_source ~ 04_results)
├── Java2C++/                  # Java→C++ data package
└── Java2Python/               # Java→Python data package
```

Each language package:

```
{lang}/
├── README.md              # dataset description and metrics for this direction
├── 01_source/             # Java source data (method-list CSVs + Java source archives)
├── 02_randoop/            # Randoop generation and coverage records (method_master_list.csv master list, 10,508 rows)
├── 03_translation/        # target-language translation artifacts of the pipeline stages
└── 04_results/            # experiment results (all_samples_results.csv, 8,895 rows) + supporting reports
```

### `analysis/`

Leaf-level classification outputs computed in the paper environment for
Fig.2/Fig.3 and Tables 3/4: per-method error classifications
(`csharp_classified.csv`, `cpp_classified.csv`, `python_classified.csv`,
`rq4_classified.csv`), per-domain summaries (`domain_csr.csv`,
`domain_leaf_stacks.csv`, `domain_leaf_top.csv`), behavior statistics
(`behavior_stats.csv`), the CS error-code→leaf mapping
(`csharp_code_mapping.csv`), the class→domain override table
(`class_package_override.csv`), and the three merged raw result tables
(`C#_merged_8895.csv`, `C++_merged_results_8895.csv`, `Python_mergerd_8895.csv`).


## Data Availability

The paper's data-availability statement:
https://github.com/Anonymous20261001/Unlocking-Language-Migration-from-the-Bottom-Up
