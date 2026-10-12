"""
Run behavior check: compile each translated C# file with a Main() wrapper,
execute with mono, record pass/fail (0=pass, non-zero=fail).
"""
import subprocess, re, csv, tempfile, os
from pathlib import Path
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed

COMPILE_CSV = Path("/root/autodl-tmp/Java2C#/compile_benchmark_results.csv")
TRANSLATED_DIR = Path("/root/autodl-tmp/Java2C#/CsAPI_benchmark_translated")
OUT_CSV = Path("/root/autodl-tmp/Java2C#/behavior_results.csv")
OUT_TXT = Path("/root/autodl-tmp/Java2C#/behavior_summary.txt")

MCS_REFS = "-r:System.dll -r:System.Core.dll -r:System.Drawing.dll -r:System.Numerics.dll"
TIMEOUT = 10
WORKERS = 8


def find_test_class_and_method(content):
    """Find the class containing the test method, and the method name."""
    classes = re.findall(r'(?:public\s+)?class\s+(\w+)\s*\{', content)
    for tc in classes:
        m = re.search(rf'class\s+{tc}\s*\{{', content)
        if not m:
            continue
        start = m.start()
        depth = 0
        end = start
        for j in range(start, len(content)):
            if content[j] == '{':
                depth += 1
            elif content[j] == '}':
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
        class_body = content[start:end]
        tm = re.findall(r'public void (\w+[Tt]est[_\w]*\d+)\(\)', class_body)
        if tm:
            return tc, tm[0], end
    return None, None, None


def check_one(row):
    cls = row['class']
    num = row['number']
    result = {"class": cls, "number": num, "java_method": row['java_method']}

    # Find the output file
    files = list((TRANSLATED_DIR / cls).glob(f"*{num}*"))
    if not files:
        result["run_pass"] = False
        result["error"] = "file_not_found"
        return result

    f = files[0]
    content = f.read_text(encoding="utf-8")

    tc, tm, closing_pos = find_test_class_and_method(content)
    if not tc:
        result["run_pass"] = False
        result["error"] = "no_test_method"
        return result

    # Inject Main() before class closing brace
    main_code = f"""
    public static void Main() {{
        try {{
            new {tc}().{tm}();
            System.Environment.Exit(0);
        }} catch (System.Exception) {{
            System.Environment.Exit(1);
        }}
    }}
"""
    modified = content[:closing_pos - 1] + main_code + '\n' + content[closing_pos - 1:]

    with tempfile.TemporaryDirectory() as tmpdir:
        src = os.path.join(tmpdir, "test.cs")
        exe = os.path.join(tmpdir, "test.exe")
        Path(src).write_text(modified, encoding="utf-8")

        # Compile
        r = subprocess.run(
            ["mcs", "-target:exe", f"-out:{exe}", "-nologo"] + MCS_REFS.split() + [src],
            capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            result["run_pass"] = False
            result["error"] = f"compile:{r.stderr[:100]}"
            return result

        # Run
        try:
            r2 = subprocess.run(["mono", exe], capture_output=True, text=True, timeout=TIMEOUT)
            result["run_pass"] = r2.returncode == 0
            result["exit_code"] = r2.returncode
        except subprocess.TimeoutExpired:
            result["run_pass"] = False
            result["error"] = "timeout"
        except Exception as e:
            result["run_pass"] = False
            result["error"] = str(e)[:100]

    return result


def main():
    with open(COMPILE_CSV) as f:
        rows = [r for r in csv.DictReader(f) if r['passed'] == 'True']

    print(f"Running behavior check on {len(rows)} files with {WORKERS} workers...")

    results = []
    passed = 0
    failed = 0

    with ProcessPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(check_one, r): r for r in rows}
        for i, fut in enumerate(as_completed(futures)):
            results.append(fut.result())
            if fut.result()["run_pass"]:
                passed += 1
            else:
                failed += 1
            if (i + 1) % 500 == 0:
                print(f"  [{i+1}/{len(rows)}] pass={passed} fail={failed} ({passed*100//(i+1)}%)")

    results.sort(key=lambda r: (r["class"], int(r["number"])))
    print(f"\nDone! Passed: {passed}/{len(rows)} ({passed*100//len(rows)}%)  Failed: {failed}")

    # Write results
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["class", "java_method", "number", "run_pass", "exit_code", "error"])
        for r in results:
            w.writerow([r["class"], r.get("java_method", ""), r["number"],
                         r["run_pass"], r.get("exit_code", ""), r.get("error", "")])

    with open(OUT_TXT, "w") as f:
        f.write(f"Behavior check: CsAPI_benchmark_translated\n")
        f.write(f"Total: {len(rows)}  Passed: {passed} ({passed*100//len(rows)}%)  Failed: {failed}\n")

    print(f"Results: {OUT_CSV}")


if __name__ == "__main__":
    main()
