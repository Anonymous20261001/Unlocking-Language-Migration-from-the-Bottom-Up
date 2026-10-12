"""
Run all 1,754 Python Javadoc test cases and report behavioral consistency.
Categories:
  PASS  - test passed (behavior matches Java)
  FAIL  - assertion failed (behavior differs from Java)
  ERROR - crash/exception (translation/import bug)
"""

import csv, subprocess, sys, re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

BASE = Path("/root/autodl-tmp/Java2Python")
TEST_DIR = BASE / "PythonJavadoc_test_cases"
OUTPUT_CSV = BASE / "python_test_results.csv"

_print_lock = Lock()


def run_one_test(py_file: Path) -> dict:
    """Run a single Python test with pytest. Returns result dict."""
    try:
        proc = subprocess.run(
            ["python3", str(py_file.absolute())],
            capture_output=True, text=True, timeout=15,
            env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"}
        )
        combined = proc.stdout + "\n" + proc.stderr
        rc = proc.returncode

        cls_name = py_file.parent.name
        func_name = py_file.stem

        if rc == 0 and ("OK" in combined or "ok" in combined.lower()):
            return {"class": cls_name, "file": func_name, "status": "PASS",
                    "error_type": "", "error_msg": ""}

        # Extract error info
        error_type = "Unknown"
        error_msg = ""
        for line in combined.split("\n"):
            line_s = line.strip()
            # unittest assertion failure: "AssertionError: ..."
            if "AssertionError" in line_s and ":" in line_s:
                parts = line_s.split("AssertionError:", 1)
                error_type = "AssertionError"
                error_msg = parts[1].strip()[:200]
                break
            # Other errors: "TypeError: ...", "NameError: ...", etc.
            m = re.search(r"(TypeError|NameError|AttributeError|ImportError|ValueError|KeyError|IndexError|OSError|RuntimeError|SyntaxError):\s*(.*)", line_s)
            if m:
                error_type = m.group(1)
                error_msg = m.group(2)[:200]
                break

        # Detect if it's assertion failure vs general error
        if error_type == "AssertionError":
            status = "FAIL"
        else:
            status = "ERROR"

        return {"class": cls_name, "file": func_name, "status": status,
                "error_type": error_type, "error_msg": error_msg}
    except subprocess.TimeoutExpired:
        return {"class": str(py_file.parent.name), "file": py_file.stem,
                "status": "TIMEOUT", "error_type": "Timeout", "error_msg": ""}
    except Exception as e:
        return {"class": str(py_file.parent.name), "file": py_file.stem,
                "status": "ERROR", "error_type": type(e).__name__, "error_msg": str(e)[:200]}


def main():
    py_files = sorted(TEST_DIR.glob("*/*.py"))
    total = len(py_files)
    print(f"Running {total} tests with 8 workers...")

    results = []
    workers = 8
    done = 0

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_one_test, f): f for f in py_files}
        for fut in as_completed(futs):
            done += 1
            try:
                r = fut.result()
                results.append(r)
            except Exception as e:
                f = futs[fut]
                results.append({"class": f.parent.name, "file": f.stem,
                                "status": "ERROR", "error_type": type(e).__name__,
                                "error_msg": str(e)[:200]})
            if done % 200 == 0:
                p = sum(1 for r in results if r["status"] == "PASS")
                f = sum(1 for r in results if r["status"] == "FAIL")
                e = sum(1 for r in results if r["status"] == "ERROR")
                print(f"  [{done}/{total}] pass={p} fail={f} error={e}")

    results.sort(key=lambda r: (r["class"], r["file"]))

    # Write CSV
    with open(OUTPUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["class", "file", "status", "error_type", "error_msg"])
        w.writeheader()
        w.writerows(results)

    # Summary
    statuses = {}
    for r in results:
        s = r["status"]
        statuses[s] = statuses.get(s, 0) + 1

    print(f"\n{'='*60}")
    for s in ["PASS", "FAIL", "ERROR", "TIMEOUT"]:
        if s in statuses:
            print(f"  {s}: {statuses[s]} ({statuses[s]/total*100:.1f}%)")
    print(f"\n结果: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
