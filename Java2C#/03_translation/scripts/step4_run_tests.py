"""
Step 4: Compile & Run — compile each C# test with mcs, run with mono, record results.
"""
import subprocess, csv, os, sys, time, tempfile, re
from pathlib import Path
import multiprocessing as mp

PIPELINE = Path(__file__).parent
INPUT_DIR = PIPELINE / "03_CsAPI_test_cases"
OUTPUT_DIR = PIPELINE / "04_test_results"
OUTPUT_CSV = OUTPUT_DIR / "cs_test_results.csv"
LOG_PATH = OUTPUT_DIR / "run_details.log"

COMPILE_TIMEOUT = 30  # seconds
RUN_TIMEOUT = 10      # seconds
MCS_REFS = "-r:System.dll -r:System.Core.dll -r:System.Drawing.dll -r:System.Numerics.dll"


def find_test_method(cs_code: str) -> str:
    """Find the test method name in a C# file.
    Returns the method name, or empty string if not found."""
    # Look for "public void methodName_test_N()"
    m = re.search(r'public\s+void\s+(\w+_test_\d+)\s*\(\s*\)', cs_code)
    if m:
        return m.group(1)
    # Also try without "public"
    m = re.search(r'void\s+(\w+_test_\d+)\s*\(\s*\)', cs_code)
    if m:
        return m.group(1)
    return ""


def find_test_container_class(cs_code: str) -> str:
    """Find the class name that contains the test method."""
    # Find the namespace/class structure
    # The test method is inside a class — find which class contains it
    # Look for "public class Xxx" before the test method
    m = re.search(r'class\s+(\w+)\s*[{:]', cs_code)
    if m:
        return m.group(1)
    return ""


def compile_and_run(args: tuple) -> dict:
    """Compile and run one C# test file."""
    cls, filename, filepath = args
    result = {"class": cls, "filename": filename, "compile_status": "", "run_status": "", "error_message": ""}

    tmpdir = tempfile.mkdtemp(prefix="cs_test_")

    try:
        cs_code = filepath.read_text(encoding="utf-8")

        # Step 1: Syntax-only compile check
        r = subprocess.run(
            ["mcs", "-target:library"] + MCS_REFS.split() + ["-out:/dev/null", str(filepath)],
            capture_output=True, text=True, timeout=COMPILE_TIMEOUT
        )
        if r.returncode != 0:
            result["compile_status"] = "COMPILE_ERROR"
            result["run_status"] = "SKIPPED"
            errors = re.findall(r'CS\d{4}[^)]*\)', r.stderr)
            result["error_message"] = ("; ".join(errors[:5]) if errors else r.stderr[:500]).replace("\n", " | ").replace(",", ";")
            return result

        result["compile_status"] = "PASS"

        # Step 2: Find test method and container class
        test_method = find_test_method(cs_code)
        if not test_method:
            result["compile_status"] = "NO_TEST_METHOD"
            result["run_status"] = "SKIPPED"
            result["error_message"] = "Could not find test method in file"
            return result

        # Find the test method position
        test_pos = cs_code.find(f"void {test_method}")

        # Find the namespace that CONTAINS the test method (last namespace before test_pos)
        namespace = "Generated.Test"
        for nm in re.finditer(r'namespace\s+(\S+)', cs_code):
            if nm.start() < test_pos:
                namespace = nm.group(1)

        # Find the class containing the test method (last class before test_pos)
        container_class = "Program"
        for cm in re.finditer(r'class\s+(\w+)', cs_code):
            if cm.start() < test_pos:
                container_class = cm.group(1)

        # Step 3: Create wrapper with Main() that calls the test
        wrapper_path = Path(tmpdir) / "test_runner.cs"
        wrapper_code = f"""using System;
using {namespace};

public class TestRunner {{
    public static int Main() {{
        try {{
            var instance = new {container_class}();
            instance.{test_method}();
            return 0;
        }} catch (Exception ex) {{
            Console.Error.WriteLine("TEST FAILED: " + ex.Message);
            return 1;
        }}
    }}
}}
"""
        wrapper_path.write_text(wrapper_code, encoding="utf-8")

        # Step 4: Compile with wrapper
        exe_path = Path(tmpdir) / "test.exe"
        r = subprocess.run(
            ["mcs", "-target:exe", "-out:" + str(exe_path)] + MCS_REFS.split() +
            [str(filepath), str(wrapper_path)],
            capture_output=True, text=True, timeout=COMPILE_TIMEOUT
        )
        if r.returncode != 0:
            result["compile_status"] = "LINK_ERROR"
            result["run_status"] = "SKIPPED"
            errors = re.findall(r'CS\d{4}[^)]*\)', r.stderr)
            result["error_message"] = ("; ".join(errors[:5]) if errors else r.stderr[:500]).replace("\n", " | ").replace(",", ";")
            return result

        # Step 5: Run with mono
        r = subprocess.run(
            ["mono", str(exe_path)],
            capture_output=True, text=True, timeout=RUN_TIMEOUT
        )
        if r.returncode == 0:
            result["run_status"] = "PASS"
            result["error_message"] = ""
        else:
            result["run_status"] = "FAIL"
            err = (r.stderr + r.stdout)[:500].replace("\n", " | ").replace(",", ";")
            result["error_message"] = err

    except subprocess.TimeoutExpired:
        if result["compile_status"] == "":
            result["compile_status"] = "TIMEOUT"
        result["run_status"] = "TIMEOUT"
        result["error_message"] = "TIMEOUT"
    except Exception as e:
        result["compile_status"] = "ERROR"
        result["run_status"] = "SKIPPED"
        result["error_message"] = str(e)[:200]
    finally:
        import shutil
        try:
            shutil.rmtree(tmpdir)
        except Exception:
            pass

    return result


def append_log(msg: str):
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Collect all .cs files
    tasks = []
    for class_dir in sorted(INPUT_DIR.iterdir()):
        if not class_dir.is_dir():
            continue
        cls = class_dir.name
        for cs_file in sorted(class_dir.glob("*.cs")):
            tasks.append((cls, cs_file.name, cs_file))

    print(f"Found {len(tasks)} .cs files")

    if not tasks:
        print("No files to test. Run Step 3 first.")
        return

    # Resume: skip already-tested
    done = set()
    if OUTPUT_CSV.exists():
        with open(OUTPUT_CSV, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                done.add(row["filename"])
    print(f"Resume: {len(done)} already tested")

    tasks = [t for t in tasks if t[1] not in done]
    print(f"Pending: {len(tasks)}")

    if not tasks:
        print("All done.")
        return

    # Write CSV header if new
    fieldnames = ["class", "filename", "compile_status", "run_status", "error_message"]
    if not OUTPUT_CSV.exists():
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

    workers = min(mp.cpu_count(), 8)
    print(f"Using {workers} workers")

    compile_ok = compile_fail = run_ok = run_fail = 0
    start = time.time()

    with mp.Pool(workers) as pool:
        for i, result in enumerate(pool.imap_unordered(compile_and_run, tasks, chunksize=5)):
            with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writerow(result)

            if result["compile_status"] == "PASS":
                compile_ok += 1
                if result["run_status"] == "PASS":
                    run_ok += 1
                else:
                    run_fail += 1
            else:
                compile_fail += 1

            if (i + 1) % 50 == 0:
                elapsed = time.time() - start
                append_log(f"[{i+1}/{len(tasks)}] compile_ok={compile_ok} run_ok={run_ok} compile_fail={compile_fail}")

    elapsed = time.time() - start
    append_log(f"Done: compile_ok={compile_ok} compile_fail={compile_fail} "
               f"run_ok={run_ok} run_fail={run_fail} ({elapsed:.0f}s)")

    print(f"\n{'='*60}")
    print(f"Step 4 complete:")
    print(f"  Compile: PASS={compile_ok} FAIL={compile_fail}")
    print(f"  Run:     PASS={run_ok} FAIL={run_fail}")
    print(f"Results: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
