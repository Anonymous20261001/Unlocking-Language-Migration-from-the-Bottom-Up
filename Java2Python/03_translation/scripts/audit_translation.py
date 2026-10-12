"""
Random audit of 150 translated test cases for Java-Python semantic consistency.
Uses DeepSeek to judge each Java test + Python translation pair.
Output: For_Paper/04_results/translation_audit_150.csv
"""

import csv, os, random, re, time, requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

API_URL = "https://api.deepseek.com/anthropic/v1/messages"
API_KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
MODEL = "deepseek-v4-flash"
WORKERS = 8

BASE = Path("/root/autodl-tmp/Java2Python")
BENCH_JAVA = Path("/tmp/bench_extract/Java_benchmark")
BENCH_PY = BASE / "PythonAPI_splitted_method"
NEW_JAVA = BASE / "new_Java_test_cases"
NEW_PY = BASE / "PythonJavadoc_test_cases"
OUT_CSV = BASE / "For_Paper/04_results/translation_audit_150.csv"

JUDGE_PROMPT = (
    "You are auditing a Java-to-Python test translation.\n"
    "Below are ONLY the test function/method bodies (already extracted;\n"
    "wrapper classes omitted by design — do NOT call this truncation).\n"
    "Compare the Java test and the Python translation.\n"
    "\n"
    "FOCUS ONLY on whether the translation preserves the ERROR-CHECKING\n"
    "semantics of the Java test:\n"
    "1. Assertions: does the Python version check the same things?\n"
    "   (null/non-null, value equality, true/false — same expected values)\n"
    "2. Expected exceptions: if Java expects an exception (try/catch with\n"
    "   Assert.fail), does Python assert that an exception is raised?\n"
    "\n"
    "Ignore everything else: API method name mapping, variable naming,\n"
    "exception type granularity (NPE vs Exception), message wording,\n"
    "extra non-assert setup statements.\n"
    "\n"
    "CONSISTENT = assertions/expected-exceptions are preserved.\n"
    "INCONSISTENT = assertion missing, different expected value, or\n"
    "expected exception not checked.\n"
    "\n"
    "Answer with EXACTLY one word on the first line: CONSISTENT or INCONSISTENT.\n"
    "On the second line, give a brief reason (max 80 chars).\n"
)

_print_lock = Lock()

def log(msg):
    with _print_lock:
        print(msg, flush=True)


def query_judge(prompt: str) -> str:
    headers = {"Content-Type": "application/json", "x-api-key": API_KEY,
               "anthropic-version": "2023-06-01"}
    payload = {"model": MODEL, "max_tokens": 200, "temperature": 0.0,
               "thinking": {"type": "disabled"},
               "messages": [{"role": "user", "content": prompt}]}
    for attempt in range(4):
        try:
            resp = requests.post(API_URL, headers=headers, json=payload, timeout=(30, 120))
        except requests.RequestException:
            time.sleep(2); continue
        if resp.status_code == 200:
            for block in resp.json()["content"]:
                if block["type"] == "text":
                    return block["text"].strip()
            return "NO_TEXT"
        time.sleep(2)
    return "HTTP_ERROR"


def locate_files(row) -> tuple:
    """Return (java_code, py_code, java_path, py_path) for a sample row."""
    dataset = row["dataset"]
    cls, method, number = row["class"], row["method"], row["number"]

    if dataset == "Java_benchmark":
        # Java: use inventory filename
        java_dir = BENCH_JAVA / cls
        java_path = None
        if java_dir.is_dir():
            for f in java_dir.glob(f"*_test_{number}.java"):
                java_path = f; break
        py_dir = BENCH_PY / cls
        py_path = None
        if py_dir.is_dir():
            for f in py_dir.glob(f"*_test_{number}.py"):
                py_path = f; break
    else:  # Javadoc_new
        java_path = NEW_JAVA / cls / f"{method}_test_{number}.java"
        py_path = NEW_PY / cls / f"{method}_test_{number}.py"
        if not java_path.exists(): java_path = None
        if not py_path.exists(): py_path = None

    if java_path is None or py_path is None:
        return None, None, str(java_path), str(py_path)

    try:
        java_code = java_path.read_text(encoding="utf-8", errors="replace")
        py_code = py_path.read_text(encoding="utf-8", errors="replace")
        return java_code, py_code, str(java_path), str(py_path)
    except Exception:
        return None, None, str(java_path), str(py_path)


def extract_test_method(java_code: str) -> str:
    """Extract the @Test method from a Java test file."""
    m = re.search(r'(@Test\s*\n\s*public\s+void\s+\w+\(\)[^{]*\{)', java_code)
    if not m:
        return java_code[:2000]
    start = m.start()
    brace = m.end() - 1
    depth = 1
    i = brace
    while i < len(java_code) and depth > 0:
        if java_code[i] == '{': depth += 1
        elif java_code[i] == '}': depth -= 1
        i += 1
    return java_code[start:i]


def extract_test_func(py_code: str) -> str:
    """Extract the test function from a Python test file (skip wrapper classes)."""
    # Find def test_xxx (the unittest test function)
    for m in re.finditer(r'(def\s+test_\w+)', py_code):
        start = py_code.rfind('\n', 0, m.start())
        if start < 0: start = 0
        # Function body extends until next top-level def/class, or EOF
        nxt = re.search(r'\n(?:def|class)\s+', py_code[m.end():])
        end = m.end() + nxt.start() if nxt else len(py_code)
        return py_code[start:end].strip()
    # Fallback: if no test_ prefix, find def xxx_test_NNN
    for m in re.finditer(r'(def\s+\w+_test_\d+)', py_code):
        start = py_code.rfind('\n', 0, m.start())
        if start < 0: start = 0
        nxt = re.search(r'\n(?:def|class)\s+', py_code[m.end():])
        end = m.end() + nxt.start() if nxt else len(py_code)
        return py_code[start:end].strip()
    return py_code[:2000]


def audit_one(row) -> dict:
    java_code, py_code, jp, pp = locate_files(row)
    if java_code is None:
        return {**row, "verdict": "SKIP", "reason": f"file missing: {jp} / {pp}"}

    java_test = extract_test_method(java_code)
    py_test = extract_test_func(py_code)

    prompt = (JUDGE_PROMPT
              + f"=== Java Test ({row['class']}/{row['method']}_test_{row['number']}) ===\n"
              + java_test + "\n\n"
              + "=== Python Translation ===\n"
              + py_test)

    resp = query_judge(prompt)
    lines = [l.strip() for l in resp.split("\n") if l.strip()]
    verdict = lines[0] if lines else "NO_ANSWER"
    reason = lines[1][:100] if len(lines) > 1 else ""
    if verdict not in ("CONSISTENT", "INCONSISTENT"):
        reason = (verdict + " " + reason)[:100]
        verdict = "NO_ANSWER"
    return {**row, "verdict": verdict, "reason": reason,
            "java_file": Path(jp).name, "py_file": Path(pp).name}


def main():
    random.seed(42)
    rows = list(csv.DictReader(open(BASE / "For_Paper/04_results/all_samples_results.csv")))
    print(f"Total samples: {len(rows)}")

    # Stratified sample: proportional to dataset sizes
    bench_rows = [r for r in rows if r["dataset"] == "Java_benchmark"]
    new_rows = [r for r in rows if r["dataset"] == "Javadoc_new"]
    n_bench = round(150 * len(bench_rows) / len(rows))
    n_new = 150 - n_bench
    sample = random.sample(bench_rows, n_bench) + random.sample(new_rows, n_new)
    random.shuffle(sample)
    print(f"Sampled: {n_bench} benchmark + {n_new} javadoc = {len(sample)}")

    results = []
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(audit_one, r): r for r in sample}
        for fut in as_completed(futs):
            done += 1
            try:
                results.append(fut.result())
            except Exception as e:
                r = futs[fut]
                results.append({**r, "verdict": "ERROR", "reason": str(e)[:100]})
            if done % 25 == 0:
                c = sum(1 for r in results if r["verdict"] == "CONSISTENT")
                i = sum(1 for r in results if r["verdict"] == "INCONSISTENT")
                log(f"  [{done}/150] consistent={c} inconsistent={i}")

    # Write audit CSV — keep only essential columns
    keep = ["class", "method", "number", "dataset", "verdict", "reason"]
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keep, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)

    from collections import Counter
    v = Counter(r["verdict"] for r in results)
    print(f"\n{'='*60}")
    print(f"Audit complete: {len(results)} samples")
    for k, n in v.most_common():
        print(f"  {k}: {n} ({n*100//len(results)}%)")
    print(f"Output: {OUT_CSV}")


if __name__ == "__main__":
    main()
