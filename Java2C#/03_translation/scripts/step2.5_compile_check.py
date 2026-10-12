"""
Step 2.5: Compile Check — check each per-method C# file compiles with mcs.

Runs `mcs -target:library` on every file, records PASS/FAIL.
Uses multiprocessing for speed.
"""
import subprocess, csv, os, sys, time
from pathlib import Path
import multiprocessing as mp

PIPELINE = Path(__file__).parent
INPUT_DIR = PIPELINE / "02_CsAPI_splitted_nofw"
OUTPUT_CSV = PIPELINE / "02.5_compile_check.csv"
LOG_PATH = PIPELINE / "02.5_compile_check.log"

TIMEOUT = 30  # seconds per file
MCS_REFS = "-r:System.dll -r:System.Core.dll -r:System.Drawing.dll -r:System.Numerics.dll"


def compile_one(args: tuple) -> dict:
    """Compile a single .cs file with mcs, return result dict."""
    stem, filename, filepath = args
    try:
        r = subprocess.run(
            ["mcs", "-target:library"] + MCS_REFS.split() + ["-out:/dev/null", str(filepath)],
            capture_output=True, text=True, timeout=TIMEOUT
        )
        if r.returncode == 0:
            return {"class": stem, "filename": filename, "compile_status": "PASS",
                    "error_message": ""}
        else:
            # Extract CS error codes
            errors = re.findall(r'CS\d{4}', r.stderr)
            err_msg = ";".join(errors[:10]) if errors else r.stderr[:300].replace("\n", " | ").replace(",", ";")
            return {"class": stem, "filename": filename, "compile_status": "FAIL",
                    "error_message": err_msg}
    except subprocess.TimeoutExpired:
        return {"class": stem, "filename": filename, "compile_status": "FAIL",
                "error_message": "TIMEOUT"}
    except Exception as e:
        return {"class": stem, "filename": filename, "compile_status": "FAIL",
                "error_message": str(e)[:200]}


def append_log(msg: str):
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


import re  # needed for compile_one error extraction


def main():
    INPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Collect all .cs files
    tasks = []
    for class_dir in sorted(INPUT_DIR.iterdir()):
        if not class_dir.is_dir():
            continue
        stem = class_dir.name
        for cs_file in sorted(class_dir.glob("*.cs")):
            tasks.append((stem, cs_file.name, cs_file))

    print(f"Found {len(tasks)} .cs files to check")

    # Resume: read existing CSV to skip already-checked files
    done = set()
    if OUTPUT_CSV.exists():
        with open(OUTPUT_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                done.add(row["filename"])
    print(f"Resume: {len(done)} already checked")

    tasks = [t for t in tasks if t[1] not in done]
    print(f"Pending: {len(tasks)}")

    if not tasks:
        print("All done.")
        return

    # Write CSV header if new
    fieldnames = ["class", "filename", "compile_status", "error_message"]
    if not OUTPUT_CSV.exists():
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

    # Process with multiprocessing
    workers = min(mp.cpu_count(), 8)
    print(f"Using {workers} workers")

    ok = fail = 0
    start = time.time()

    with mp.Pool(workers) as pool:
        for i, result in enumerate(pool.imap_unordered(compile_one, tasks, chunksize=10)):
            # Append to CSV immediately
            with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writerow(result)

            if result["compile_status"] == "PASS":
                ok += 1
            else:
                fail += 1

            if (i + 1) % 200 == 0:
                elapsed = time.time() - start
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                append_log(f"[{i+1}/{len(tasks)}] ok={ok} fail={fail} rate={rate:.1f}/s")

    elapsed = time.time() - start
    append_log(f"Done: {len(tasks)} files in {elapsed:.0f}s, PASS={ok}, FAIL={fail}")
    print(f"\n{'='*60}")
    print(f"Step 2.5 complete: {len(tasks)} checked, PASS={ok}, FAIL={fail}")
    print(f"CSV: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
