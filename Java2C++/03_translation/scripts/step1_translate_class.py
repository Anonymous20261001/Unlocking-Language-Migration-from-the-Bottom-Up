"""
Step 1: Class-level Java → C++ Translation with Method Completeness Verification.

Reads Java test files from new_Java_method_tests/, translates to C++ via DeepSeek,
verifies ALL expected test functions are present in output, retries if missing.
"""
import time, requests, re, csv, json, os, sys
from pathlib import Path
from tqdm import tqdm

# ── Paths ───────────────────────────────────────────────────────────
BASE = Path(__file__).parent.parent  # /root/autodl-tmp/Java2C++/
PIPELINE = Path(__file__).parent     # /root/autodl-tmp/Java2C++/pipeline/
JAVA_SOURCE_DIR = BASE / "new_Java_method_tests"
OUTPUT_DIR = PIPELINE / "01_CppJavadoc_API_by_class"
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
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

MAX_RETRIES = 3

SYSTEM_PROMPT = """You are a professional Java and C++ developer.

Below is a Java test file. Each @Test method creates an instance of a Java class
and exercises one of its API methods.

Your task:
1. Translate every Java @Test method into exactly one C++ test function with the
SAME name (e.g., equals_test_6446 -> void equals_test_6446()).
2. For each Java class used in the tests, implement a C++ equivalent class whose
API behaves identically to the original Java API.

Important:
- Keep the EXACT same function naming: {method}_test_{number}
- Every @Test method in the Java file MUST have a corresponding C++ function
- Output only the complete C++ code. No explanation, no markdown fences."""


# ── Helpers ──────────────────────────────────────────────────────────
def parse_csv(csv_path: Path) -> dict:
    """Build {class_stem: [(test_num, method_name), ...]} from CSV."""
    class_map = {}
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            stem = Path(row["﻿文件名"] if "﻿文件名" in row else row["文件名"]).stem
            test_num = int(row["测试编号"])
            method_name = row["方法名"]
            class_map.setdefault(stem, []).append((test_num, method_name))
    return class_map


def load_log() -> dict:
    """Read existing log, return {class_stem: last_record} for resume."""
    completed = {}
    if LOG_PATH.exists():
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("status") == "ok":
                        completed[rec["class"]] = rec
                except json.JSONDecodeError:
                    continue
    return completed


def append_log(record: dict):
    """Append one JSON record to log file."""
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def verify_methods(cpp_code: str, expected: list) -> tuple:
    """Check which expected method names are found in C++ output.
    expected: [(test_num, method_name), ...]
    Returns: (missing_list, found_count)
    """
    missing = []
    found = 0
    for test_num, method_name in expected:
        func_name = f"{method_name}_test_{test_num}"
        # Match "void func_name(" or "void func_name (..."
        if re.search(rf'\bvoid\s+{re.escape(func_name)}\s*\(', cpp_code):
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
        "temperature": 0.2,
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


# ── Main ────────────────────────────────────────────────────────────
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load CSV mapping
    class_map = parse_csv(CSV_PATH)
    print(f"CSV: {len(class_map)} unique classes, {sum(len(v) for v in class_map.values())} total methods")

    # Resume state: skip only if file exists, non-empty, and status is ok
    completed = load_log()
    # Also check for empty files — these need re-translation
    for stem in list(completed.keys()):
        output_path = OUTPUT_DIR / f"{stem}.cpp"
        if output_path.exists() and output_path.stat().st_size == 0:
            del completed[stem]
            print(f"  [resume] redoing empty file: {stem}")
    print(f"Resume: {len(completed)} classes already completed")

    # Collect class stems
    all_stems = sorted(class_map.keys())

    # Sharding
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
    pbar = tqdm(stems, desc="Step 1", unit="class")

    for stem in pbar:
        expected = class_map[stem]
        output_path = OUTPUT_DIR / f"{stem}.cpp"

        # Resume: skip if already ok
        if stem in completed and output_path.exists():
            skip += 1
            pbar.set_postfix({"ok": ok, "skip": skip, "fail": fail})
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
        cpp_code = ""
        for retry in range(MAX_RETRIES + 1):
            try:
                if retry == 0:
                    user_prompt = java_code
                else:
                    # Retry: tell LLM what's missing
                    missing_str = ", ".join(missing)
                    user_prompt = (
                        f"{java_code}\n\n"
                        f"=== IMPORTANT: MISSING FUNCTIONS ===\n"
                        f"The following test functions were NOT found in your previous output:\n"
                        f"  {missing_str}\n\n"
                        f"Please translate the ENTIRE Java file again, making sure ALL @Test methods "
                        f"(including those listed above) are translated to C++ test functions "
                        f"with the EXACT same names."
                    )

                cpp_code = query_deepseek(SYSTEM_PROMPT, user_prompt)
                missing, found = verify_methods(cpp_code, expected)

                if len(missing) == 0:
                    # All methods present - success
                    output_path.write_text(cpp_code, encoding="utf-8")
                    append_log({"class": stem, "retries": retry, "expected": len(expected),
                                "found": found, "missing": [], "status": "ok"})
                    ok += 1
                    break
                elif retry < MAX_RETRIES:
                    print(f"\n  [{stem}] retry {retry+1}: {len(missing)}/{len(expected)} missing: {missing[:5]}...")
                    time.sleep(0.5)
                else:
                    # Max retries exhausted
                    if cpp_code and cpp_code.strip():
                        output_path.write_text(cpp_code, encoding="utf-8")
                        status = "incomplete"
                    else:
                        status = "empty_response"
                    append_log({"class": stem, "retries": retry, "expected": len(expected),
                                "found": found, "missing": missing, "status": status})
                    fail += 1
                    print(f"\n  [{stem}] FAILED after {MAX_RETRIES} retries: {len(missing)} still missing: {missing[:10]}")

            except Exception as e:
                if retry < MAX_RETRIES:
                    print(f"\n  [{stem}] error (retry {retry+1}): {e}")
                    time.sleep(2)
                else:
                    append_log({"class": stem, "retries": retry, "expected": len(expected),
                                "found": 0, "missing": [], "status": "api_error", "error": str(e)[:200]})
                    fail += 1

        pbar.set_postfix({"ok": ok, "skip": skip, "fail": fail})
        time.sleep(0.05)

    print(f"\n{'='*60}")
    print(f"Step 1 complete: ok={ok} skip={skip} fail={fail}")
    print(f"Log: {LOG_PATH}")


if __name__ == "__main__":
    main()
