"""
Step 1: Class-level Java → C# Translation with Method Completeness Verification.

Reads Java test files from new_Java_class_tests/, translates to C# via DeepSeek,
verifies ALL expected test methods are present in output, retries if missing.
"""
import time, requests, re, csv, json, os, sys
from pathlib import Path

# ── Paths ───────────────────────────────────────────────────────────
BASE = Path(__file__).parent.parent  # /root/autodl-tmp/Java2C#/
PIPELINE = Path(__file__).parent     # /root/autodl-tmp/Java2C#/pipeline_cs/
JAVA_SOURCE_DIR = BASE / "new_Java_class_tests"
OUTPUT_DIR = PIPELINE / "01_CsAPI_by_class"
LOG_PATH = PIPELINE / "01_translate.log"
CSV_PATH = BASE / "Javadoc_randoop_list_1754.csv"

# ── API Config ──────────────────────────────────────────────────────
_env_path = BASE / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").strip().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ[_k.strip()] = _v.strip()

API_URL = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
if not API_URL.endswith("/chat/completions"):
    API_URL = API_URL.rstrip("/") + "/v1/chat/completions"
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

MAX_RETRIES = 3

SYSTEM_PROMPT = """You are a professional Java and C# developer.

Below is a Java test file. Each @Test method creates an instance of a Java class
and exercises one of its API methods.

Your task:
1. Translate every Java @Test method into exactly one C# test method with the
SAME name (e.g., equals_test_6446 -> public void equals_test_6446()).
2. For each Java class used in the tests, implement a C# equivalent class whose
API behaves identically to the original Java API.

Important:
- Keep the EXACT same method naming: {method}_test_{number}
- Every @Test method in the Java file MUST have a corresponding C# test method
- Use namespace Generated.Test
- Do NOT use NUnit/XUnit/MSTest attributes — test methods are plain void methods
- Java String -> C# string, boolean -> bool, Object -> object
- The code must compile with: mcs -target:library
- Output only the complete C# code. No explanation, no markdown fences."""


# ── Helpers ──────────────────────────────────────────────────────────
def parse_csv(csv_path: Path) -> dict:
    """Build {class_stem: [(test_num, method_name), ...]} from CSV.
    Handles BOM and Windows CRLF."""
    class_map = {}
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        raw = f.read()
    # Normalize line endings
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    reader = csv.DictReader(raw.splitlines())
    for row in reader:
        # Handle possible BOM in first column name
        filename_key = "文件名"
        if filename_key not in row:
            # Try keys with BOM
            for k in row.keys():
                if "文件名" in k:
                    filename_key = k
                    break
        stem = Path(row[filename_key]).stem
        test_num = int(row["测试编号"])
        method_name = row["方法名"]
        class_map.setdefault(stem, []).append((test_num, method_name))
    return class_map


def load_log() -> dict:
    """Read existing log, return {class_stem: last_record} for resume.
    Includes ALL processed classes (ok, incomplete, empty_response, etc.)
    so we don't reprocess already-attempted classes."""
    completed = {}
    if LOG_PATH.exists():
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    # Keep all processed classes, not just ok ones
                    completed[rec["class"]] = rec
                except json.JSONDecodeError:
                    continue
    return completed


def append_log(record: dict):
    """Append one JSON record to log file."""
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def verify_methods(cs_code: str, expected: list) -> tuple:
    """Check which expected method names are found in C# output.
    expected: [(test_num, method_name), ...]
    Returns: (missing_list, found_count)
    """
    missing = []
    found = 0
    for test_num, method_name in expected:
        func_name = f"{method_name}_test_{test_num}"
        # Match C# method: "void func_name()" or "void func_name ()"
        if re.search(rf'\bvoid\s+{re.escape(func_name)}\s*\(', cs_code):
            found += 1
        else:
            missing.append(func_name)
    return missing, found


def query_deepseek(system_prompt: str, user_content: str, max_tokens: int = 16384) -> str:
    """Send chat completion request with system + user messages."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }
    for attempt in range(1, 6):
        try:
            resp = requests.post(API_URL, headers=headers, json=payload,
                                 timeout=(30, 300))
        except requests.RequestException as e:
            print(f"  [attempt {attempt}] request error: {e}")
            time.sleep(2)
            continue
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
        print(f"  [attempt {attempt}] HTTP {resp.status_code}: {resp.text[:300]}")
        if 400 <= resp.status_code < 500 and resp.status_code != 429:
            break
        time.sleep(2)
    raise RuntimeError(f"API request failed after {attempt} attempts")


# ── Per-class translation (called from multiprocessing) ──────────────
def process_one_class(args: tuple) -> dict:
    """Translate one class. Returns result dict for logging."""
    stem, expected, completed_set = args

    output_path = OUTPUT_DIR / f"{stem}.cs"

    # Skip if already done
    if stem in completed_set and output_path.exists() and output_path.stat().st_size > 0:
        return {"class": stem, "status": "skipped", "retries": 0, "expected": len(expected), "found": 0, "missing": []}

    # Read Java source
    java_path = JAVA_SOURCE_DIR / f"{stem}.java"
    if not java_path.exists():
        return {"class": stem, "retries": 0, "expected": len(expected), "found": 0, "missing": [], "status": "java_not_found"}

    java_code = java_path.read_text(encoding="utf-8")

    # Translate with retry loop
    cs_code = ""
    for retry in range(MAX_RETRIES + 1):
        try:
            if retry == 0:
                user_prompt = java_code
            else:
                missing_str = ", ".join(missing)
                user_prompt = (
                    f"{java_code}\n\n"
                    f"=== IMPORTANT: MISSING TEST METHODS ===\n"
                    f"The following test methods were NOT found in your previous output:\n"
                    f"  {missing_str}\n\n"
                    f"Please translate the ENTIRE Java file again, making sure ALL @Test methods "
                    f"(including those listed above) are translated to C# test methods "
                    f"with the EXACT same names (e.g., public void methodName_test_N())."
                )

            cs_code = query_deepseek(SYSTEM_PROMPT, user_prompt)
            missing, found = verify_methods(cs_code, expected)

            if len(missing) == 0:
                output_path.write_text(cs_code, encoding="utf-8")
                return {"class": stem, "retries": retry, "expected": len(expected), "found": found, "missing": [], "status": "ok"}
            elif retry < MAX_RETRIES:
                time.sleep(0.5)
            else:
                if cs_code and cs_code.strip():
                    output_path.write_text(cs_code, encoding="utf-8")
                    status = "incomplete"
                else:
                    status = "empty_response"
                return {"class": stem, "retries": retry, "expected": len(expected), "found": found, "missing": missing, "status": status}

        except Exception as e:
            if retry < MAX_RETRIES:
                time.sleep(2)
            else:
                return {"class": stem, "retries": retry, "expected": len(expected), "found": 0, "missing": [], "status": "api_error", "error": str(e)[:200]}

    return {"class": stem, "retries": MAX_RETRIES, "expected": len(expected), "found": 0, "missing": [], "status": "unknown_error"}


# ── Main ────────────────────────────────────────────────────────────
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load CSV mapping
    class_map = parse_csv(CSV_PATH)
    total_methods = sum(len(v) for v in class_map.values())
    print(f"CSV: {len(class_map)} unique classes, {total_methods} total methods")

    # Resume state
    completed = load_log()
    for stem in list(completed.keys()):
        output_path = OUTPUT_DIR / f"{stem}.cs"
        if output_path.exists() and output_path.stat().st_size == 0:
            del completed[stem]
            print(f"  [resume] redoing empty file: {stem}")
    print(f"Resume: {len(completed)} classes already completed")

    # Collect class stems from CSV
    all_stems = sorted(class_map.keys())

    # Sharding via STRIDE/OFFSET
    offset = int(os.environ.get("OFFSET", "0"))
    stride = int(os.environ.get("STRIDE", "1"))
    stems = [s for i, s in enumerate(all_stems) if i % stride == offset]

    limit = int(os.environ.get("LIMIT", "0"))
    if limit > 0:
        stems = stems[:limit]

    total = len(stems)
    print(f"[worker {offset}/{stride}] {total} classes to process")
    print(f"Output: {OUTPUT_DIR}")
    print(f"{'='*60}")

    ok = skip = fail = 0
    for idx, stem in enumerate(stems):
        expected = class_map[stem]
        output_path = OUTPUT_DIR / f"{stem}.cs"

        # Resume: skip if already processed (any status)
        if stem in completed:
            skip += 1
            if (idx + 1) % 10 == 0:
                print(f"  [{idx+1}/{total}] ok:{ok} skip:{skip} fail:{fail}")
            continue

        # Read Java source
        java_path = JAVA_SOURCE_DIR / f"{stem}.java"
        if not java_path.exists():
            append_log({"class": stem, "retries": 0, "expected": len(expected),
                        "found": 0, "missing": [], "status": "java_not_found"})
            fail += 1
            continue

        java_code = java_path.read_text(encoding="utf-8")

        # Translate with retry loop
        cs_code = ""
        for retry in range(MAX_RETRIES + 1):
            try:
                if retry == 0:
                    user_prompt = java_code
                else:
                    missing_str = ", ".join(missing)
                    user_prompt = (
                        f"{java_code}\n\n"
                        f"=== IMPORTANT: MISSING TEST METHODS ===\n"
                        f"The following test methods were NOT found in your previous output:\n"
                        f"  {missing_str}\n\n"
                        f"Please translate the ENTIRE Java file again, making sure ALL @Test methods "
                        f"(including those listed above) are translated to C# test methods "
                        f"with the EXACT same names (e.g., public void methodName_test_N())."
                    )

                cs_code = query_deepseek(SYSTEM_PROMPT, user_prompt)
                missing, found = verify_methods(cs_code, expected)

                if len(missing) == 0:
                    output_path.write_text(cs_code, encoding="utf-8")
                    append_log({"class": stem, "retries": retry, "expected": len(expected),
                                "found": found, "missing": [], "status": "ok"})
                    ok += 1
                    break
                elif retry < MAX_RETRIES:
                    print(f"  [{stem}] retry {retry+1}: {len(missing)}/{len(expected)} missing")
                    time.sleep(0.5)
                else:
                    if cs_code and cs_code.strip():
                        output_path.write_text(cs_code, encoding="utf-8")
                        status = "incomplete"
                    else:
                        status = "empty_response"
                    append_log({"class": stem, "retries": retry, "expected": len(expected),
                                "found": found, "missing": missing, "status": status})
                    fail += 1
                    print(f"  [{stem}] FAILED: {len(missing)}/{len(expected)} missing")

            except Exception as e:
                if retry < MAX_RETRIES:
                    print(f"  [{stem}] error retry {retry+1}: {e}")
                    time.sleep(2)
                else:
                    append_log({"class": stem, "retries": retry, "expected": len(expected),
                                "found": 0, "missing": [], "status": "api_error", "error": str(e)[:200]})
                    fail += 1

        if (idx + 1) % 10 == 0:
            print(f"  [{idx+1}/{total}] ok:{ok} skip:{skip} fail:{fail}")
        time.sleep(0.05)

    print(f"\n{'='*60}")
    print(f"Step 1 complete: ok={ok} skip={skip} fail={fail}")
    print(f"Log: {LOG_PATH}")


if __name__ == "__main__":
    main()
