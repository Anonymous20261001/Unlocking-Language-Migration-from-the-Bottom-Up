#!/usr/bin/env python3
"""Run translated Python tests and report behavioral consistency with Java."""

import sys, os, csv, traceback, importlib.util
from pathlib import Path

BASE = Path("/root/autodl-tmp/api_translation")
PY_DIR = BASE / "PythonAPI_splitted_method"
MAPPING = BASE / "migration_mapping.csv"

results = {"pass": 0, "fail": 0, "error": 0, "total": 0}


def run_one_test(cls_name: str, py_file: str) -> str:
    """Run a single Python test file. Returns 'pass', 'fail', or 'error'."""
    py_path = PY_DIR / cls_name / py_file
    if not py_path.exists():
        return "error"

    # Import the module
    mod_name = py_path.stem
    try:
        spec = importlib.util.spec_from_file_location(mod_name, py_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
    except BaseException:
        return "error"

    # Find and run the test function
    func = None
    for name in dir(mod):
        if name.endswith(f"_{mod_name.split('_')[-1]}") or \
           name == mod_name or \
           name == f"test_{mod_name}" or \
           (name.startswith("test_") and mod_name.replace("test_", "") in name):
            func = getattr(mod, name, None)
            if callable(func) and not name.startswith("_"):
                break

    if func is None:
        # fallback: find any function ending in _test_NNNN
        for name in dir(mod):
            if "_test_" in name or (name.endswith(mod_name[-4:]) and name[0].islower()):
                f = getattr(mod, name, None)
                if callable(f) and not name.startswith("_"):
                    func = f
                    break

    if func is None:
        return "error"

    try:
        # Try to call with no args first, then with default args
        import inspect
        sig = inspect.signature(func)
        kwargs = {}
        for pname, param in sig.parameters.items():
            if param.default is not inspect.Parameter.empty:
                kwargs[pname] = param.default
            else:
                # Provide a dummy value based on type annotation
                ann = param.annotation
                if ann == inspect.Parameter.empty:
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
        return "pass"
    except AssertionError:
        return "fail"
    except BaseException:
        # includes pytest.Failed / SystemExit from corrupted stub files —
        # a broken stub must surface as "error", not kill the whole run
        return "error"


def main():
    if len(sys.argv) > 1:
        limit = int(sys.argv[1])
    else:
        limit = 50

    with open(MAPPING, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["status"] == "migrate"]

    if limit:
        rows = rows[:limit]

    print(f"Running {len(rows)} tests...")

    for i, row in enumerate(rows):
        result = run_one_test(row["class_name"], row["python_file"])
        results[result] += 1
        results["total"] += 1

        if result == "fail":
            print(f"  FAIL [{results['total']}] {row['class_name']}/{row['python_file']}")
        elif result == "error":
            # Only report first few errors
            if results["error"] <= 5:
                print(f"  ERR  [{results['total']}] {row['class_name']}/{row['python_file']}")

    print(f"\nResults: total={results['total']} pass={results['pass']} "
          f"fail={results['fail']} error={results['error']}")
    if results["total"] > 0:
        print(f"Pass rate: {results['pass']/results['total']*100:.1f}%")


if __name__ == "__main__":
    main()
