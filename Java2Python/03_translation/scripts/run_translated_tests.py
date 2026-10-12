#!/usr/bin/env python3
"""Run translated Python tests and report behavioral consistency.

Usage:
  python run_translated_tests.py [--new-only] [--limit N] [--csv RESULTS.csv]
"""

import sys, os, csv, traceback, importlib.util, inspect, argparse, json
from pathlib import Path
from collections import defaultdict

PY_DIR = Path("/root/autodl-tmp/Java2Python/PythonAPI_splitted_method")
CSV_PATH = Path("/root/autodl-tmp/Java2Python/Java_test_cases4python/_generation_record.csv")

results = {"pass": 0, "fail": 0, "error": 0, "total": 0}
details = []  # per-test results

def load_targets(new_only: bool = False):
    """Load test targets from the _generation_record.csv."""
    raw_text = CSV_PATH.read_bytes().decode("utf-8").replace("\r", "")
    lines = [l for l in raw_text.split("\n") if l]
    reader = csv.DictReader(lines)

    targets = []
    for row in reader:
        py_file = row.get("python_file", "").strip()
        cls = row["class"]
        number = row["number"]
        method = row["method"]

        if py_file and py_file not in ("no_test", "missing"):
            if new_only:
                # Only the 126 newly translated files
                # These are the ones whose python_file was "missing" before
                # But we already updated the CSV, so we can't tell from CSV alone
                # Alternative: check file modification time (today)
                py_path = PY_DIR / cls / py_file
                if py_path.exists():
                    import os
                    mtime = os.path.getmtime(str(py_path))
                    # Files modified today (July 19)
                    if mtime > 1721347200:  # July 19 00:00 UTC approx
                        targets.append((cls, py_file, number, method, "new"))
                    else:
                        targets.append((cls, py_file, number, method, "old"))
                # Don't skip old files either - just mark them
            else:
                py_path = PY_DIR / cls / py_file
                if py_path.exists():
                    targets.append((cls, py_file, number, method))

    return targets


def run_one_test(cls_name: str, py_file: str) -> tuple[str, str]:
    """Run a single Python test file. Returns (result, detail_msg)."""
    py_path = PY_DIR / cls_name / py_file
    if not py_path.exists():
        return ("error", "File not found")

    mod_name = py_path.stem
    try:
        spec = importlib.util.spec_from_file_location(
            f"test_{cls_name}_{mod_name}", py_path
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except BaseException as e:
        return ("error", f"Import/exec error: {type(e).__name__}: {e}")

    # Find test function
    func = None
    # Strategy 1: function starting with 'test_' followed by method name pattern
    for name in sorted(dir(mod)):
        if name.startswith("test_") and ("_test_" in name or name[-4:].isdigit()):
            f = getattr(mod, name, None)
            if callable(f) and not name.startswith("_"):
                func = f
                break

    if func is None:
        # Strategy 2: any function with _test_NNNN
        for name in dir(mod):
            if "_test_" in name:
                f = getattr(mod, name, None)
                if callable(f) and not name.startswith("_"):
                    func = f
                    break

    if func is None:
        return ("error", "No test function found")

    try:
        sig = inspect.signature(func)
        kwargs = {}
        for pname, param in sig.parameters.items():
            if param.default is not inspect.Parameter.empty:
                kwargs[pname] = param.default
            else:
                ann = param.annotation
                if ann is inspect.Parameter.empty:
                    kwargs[pname] = None
                elif ann in (int, "int"):
                    kwargs[pname] = 0
                elif ann in (str, "str"):
                    kwargs[pname] = ""
                elif ann in (bool, "bool"):
                    kwargs[pname] = False
                elif ann in (bytes, "bytes"):
                    kwargs[pname] = b""
                elif ann in (float, "float"):
                    kwargs[pname] = 0.0
                else:
                    kwargs[pname] = None
        func(**kwargs)
        return ("pass", "")
    except AssertionError:
        return ("fail", "AssertionError")
    except BaseException as e:
        return ("error", f"{type(e).__name__}: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--new-only", action="store_true",
                    help="Only run the 126 newly translated tests")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--csv", type=str, help="Export results to CSV")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    targets = load_targets(new_only=args.new_only)

    if args.limit:
        targets = targets[:args.limit]

    print(f"Running {len(targets)} tests...")
    if args.new_only:
        new_count = sum(1 for t in targets if len(t) > 4 and t[4] == "new")
        print(f"  (of which {new_count} are newly translated)")

    # Progress tracking
    last_report = 0
    for i, t in enumerate(targets):
        cls, py_file = t[0], t[1]
        number = t[2]
        method = t[3]
        tag = t[4] if len(t) > 4 else ""

        result, detail = run_one_test(cls, py_file)
        results[result] += 1
        results["total"] += 1
        details.append({
            "class": cls, "file": py_file, "number": number,
            "method": method, "result": result, "detail": detail, "tag": tag
        })

        if result == "fail" and args.verbose:
            print(f"  FAIL [{i+1}] {cls}/{py_file}")
        elif result == "error" and args.verbose:
            if results["error"] <= 10:
                print(f"  ERR  [{i+1}] {cls}/{py_file}  {detail[:80]}")

        # Progress every 500
        if i - last_report >= 500:
            print(f"  [{i+1}/{len(targets)}] pass={results['pass']} fail={results['fail']} "
                  f"error={results['error']}")
            last_report = i

    # Final report
    total = results["total"]
    print(f"\n{'='*60}")
    print(f"Results: total={total} pass={results['pass']} fail={results['fail']} error={results['error']}")
    if total > 0:
        print(f"Pass rate: {results['pass']/total*100:.1f}%")
        if results['pass'] + results['fail'] > 0:
            executable = results['pass'] + results['fail']
            print(f"Of executable tests (pass+fail): {results['pass']/executable*100:.1f}% pass")

    # Breakdown by error type
    if results['error'] > 0:
        error_types = defaultdict(int)
        for d in details:
            if d['result'] == 'error':
                # Extract first meaningful part of error
                err_msg = d['detail'].split(':')[0] if ':' in d['detail'] else d['detail']
                error_types[err_msg] += 1
        print(f"\nTop error types:")
        for err, count in sorted(error_types.items(), key=lambda x: -x[1])[:10]:
            print(f"  {count:5d}  {err}")

    # New-only breakdown
    if args.new_only:
        new_results = defaultdict(int)
        for d in details:
            if d.get('tag') == 'new':
                new_results[d['result']] += 1
        print(f"\nNew translations only:")
        n_total = sum(new_results.values())
        if n_total > 0:
            print(f"  total={n_total} pass={new_results['pass']} fail={new_results['fail']} "
                  f"error={new_results['error']}")

    # Export CSV if requested
    if args.csv:
        with open(args.csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['class', 'method', 'number', 'file', 'result', 'detail', 'tag'])
            writer.writeheader()
            writer.writerows(details)
        print(f"\nResults exported to {args.csv}")


if __name__ == "__main__":
    main()
