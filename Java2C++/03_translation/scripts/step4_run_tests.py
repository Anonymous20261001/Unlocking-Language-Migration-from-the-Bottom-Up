"""
Step 4: Compile & Run — compile each C++ test, run it, record results.
"""
import subprocess, csv, os, sys, time, json, tempfile
from pathlib import Path
import multiprocessing as mp

PIPELINE = Path(__file__).parent
INPUT_DIR = PIPELINE / "03_CppJavadoc_test_cases"
OUTPUT_DIR = PIPELINE / "04_test_results"
OUTPUT_CSV = OUTPUT_DIR / "cpp_test_results.csv"
LOG_PATH = OUTPUT_DIR / "run_details.log"

COMPILE_TIMEOUT = 30  # seconds
RUN_TIMEOUT = 10      # seconds


def compile_and_run(args: tuple) -> dict:
    """Compile and run one C++ test file."""
    cls, filename, filepath = args
    result = {"class": cls, "filename": filename, "compile_status": "", "run_status": "", "error_message": ""}

    # Extract function name from filename: "getInstance_test_144.cpp" -> "getInstance_test_144"
    import re as _re
    fn_match = _re.match(r'(.+)\.cpp$', filename)
    func_name = fn_match.group(1) if fn_match else "test_func"

    # Use a temp dir
    tmpdir = tempfile.mkdtemp(prefix="cpp_test_")
    binary = Path(tmpdir) / "test.out"

    try:
        # Step 1: Syntax-only compile check
        r = subprocess.run(
            ["g++", "-std=c++17", "-fsyntax-only", "-w", str(filepath)],
            capture_output=True, text=True, timeout=COMPILE_TIMEOUT
        )
        if r.returncode != 0:
            result["compile_status"] = "COMPILE_ERROR"
            result["run_status"] = "SKIPPED"
            result["error_message"] = r.stderr[:500].replace("\n", " | ").replace(",", ";")
            return result

        result["compile_status"] = "PASS"

        # Step 2: Create wrapper with main() and compile + link + run
        wrapper_path = Path(tmpdir) / "test_wrapper.cpp"
        wrapper_code = (
            f'#include <cassert>\n'
            f'void {func_name}();\n'
            f'int main() {{ {func_name}(); return 0; }}\n'
        )
        wrapper_path.write_text(wrapper_code, encoding="utf-8")

        r = subprocess.run(
            ["g++", "-std=c++17", "-O0", "-o", str(binary), str(filepath), str(wrapper_path)],
            capture_output=True, text=True, timeout=COMPILE_TIMEOUT
        )
        if r.returncode != 0:
            result["compile_status"] = "LINK_ERROR"
            result["run_status"] = "SKIPPED"
            result["error_message"] = r.stderr[:500].replace("\n", " | ").replace(",", ";")
            return result

        # Step 3: Run
        r = subprocess.run(
            [str(binary)],
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
        # Cleanup temp files
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

    # Collect all .cpp files
    tasks = []
    for class_dir in sorted(INPUT_DIR.iterdir()):
        if not class_dir.is_dir():
            continue
        cls = class_dir.name
        for cpp_file in sorted(class_dir.glob("*.cpp")):
            tasks.append((cls, cpp_file.name, cpp_file))

    print(f"Found {len(tasks)} .cpp files")

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
                append_log(f"[{i+1}/{len(tasks)}] compile_ok={compile_ok} run_ok={run_ok}")

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
