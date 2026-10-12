"""
Step 1 Retry V3: Process remaining classes with deepseek-chat model + higher max_tokens.
"""
import time, requests, re, csv, json, os, sys
from pathlib import Path
from tqdm import tqdm

BASE = Path(__file__).parent.parent
PIPELINE = Path(__file__).parent
JAVA_SOURCE_DIR = BASE / "new_Java_method_tests"
OUTPUT_DIR = PIPELINE / "01_CppJavadoc_API_by_class"
LOG_PATH = PIPELINE / "01_translate.log"
CSV_PATH = BASE / "Javadoc_randoop_list_1754.csv"

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
# Try deepseek-chat for larger output capacity
MODEL = "deepseek-chat"

MAX_RETRIES = 2

SYSTEM_PROMPT = """You are a professional Java and C++ developer.

Below is a Java test file with @Test methods. Your task:
1. Translate EVERY single @Test method into a C++ test function with the EXACT same name.
2. Implement C++ equivalent classes for ALL Java classes used, with identical API behavior.

CRITICAL: Every @Test method MUST have a corresponding C++ function. Do not skip any.

Output ONLY the complete C++ code. No markdown, no explanations."""


def get_ok_classes():
    ok = set()
    if LOG_PATH.exists():
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    r = json.loads(line)
                    if r.get("status") == "ok": ok.add(r["class"])
                except: pass
    return ok


def get_remaining():
    ok = get_ok_classes()
    class_map = {}
    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            stem = row["文件名"].replace(".java", "")
            if stem not in ok:
                class_map.setdefault(stem, []).append((int(row["测试编号"]), row["方法名"]))
    return class_map


def append_log(record):
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def verify_methods(cpp_code, expected):
    missing = []; found = 0
    for test_num, method_name in expected:
        func_name = f"{method_name}_test_{test_num}"
        if re.search(rf'\bvoid\s+{re.escape(func_name)}\s*\(', cpp_code):
            found += 1
        else:
            missing.append(func_name)
    return missing, found


def query_api(system_prompt, user_content, max_tokens=16384):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "stream": False, "temperature": 0.1, "max_tokens": max_tokens,
    }
    for attempt in range(1, 5):
        try:
            resp = requests.post(API_URL, headers=headers, json=payload, timeout=(30, 300))
        except requests.RequestException as e:
            time.sleep(2); continue
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"].strip()
            return content
        print(f"  HTTP {resp.status_code}: {resp.text[:200]}")
        if 400 <= resp.status_code < 500 and resp.status_code != 429:
            break
        time.sleep(2)
    raise RuntimeError(f"API error")


def translate_one(stem, expected):
    java_path = JAVA_SOURCE_DIR / f"{stem}.java"
    java_code = java_path.read_text(encoding="utf-8")
    n = len(expected)

    for retry in range(MAX_RETRIES + 1):
        try:
            if retry == 0:
                user_prompt = java_code
            else:
                user_prompt = f"{java_code}\n\n=== MISSING FUNCTIONS ===\n{', '.join(missing)}\n\nTranslate ALL methods including those listed above."

            cpp_code = query_api(SYSTEM_PROMPT, user_prompt, max_tokens=16384)
            if not cpp_code:
                time.sleep(2)
                continue

            missing, found = verify_methods(cpp_code, expected)
            if len(missing) == 0:
                (OUTPUT_DIR / f"{stem}.cpp").write_text(cpp_code, encoding="utf-8")
                append_log({"class": stem, "retries": retry, "expected": n,
                            "found": found, "missing": [], "status": "ok"})
                return True
            elif retry < MAX_RETRIES:
                time.sleep(0.5)
            else:
                if cpp_code:
                    (OUTPUT_DIR / f"{stem}.cpp").write_text(cpp_code, encoding="utf-8")
                append_log({"class": stem, "retries": retry, "expected": n,
                            "found": found, "missing": missing,
                            "status": "incomplete" if cpp_code else "empty_response"})
                return False
        except Exception as e:
            if retry >= MAX_RETRIES:
                append_log({"class": stem, "retries": retry, "expected": n,
                            "found": 0, "missing": [], "status": "api_error", "error": str(e)[:200]})
                return False
            time.sleep(2)
    return False


def main():
    remaining = get_remaining()
    if not remaining:
        print("All classes done!")
        return

    # Sort by method count
    remaining = dict(sorted(remaining.items(), key=lambda x: len(x[1])))
    print(f"Remaining: {len(remaining)} classes, {sum(len(v) for v in remaining.values())} methods")
    print(f"Model: {MODEL}")
    print(f"{'='*60}")

    # Sharding
    offset = int(os.environ.get("OFFSET", "0"))
    stride = int(os.environ.get("STRIDE", "1"))
    stems = list(remaining.keys())
    stems = [s for i, s in enumerate(stems) if i % stride == offset]
    print(f"[worker {offset}/{stride}] {len(stems)} classes")

    ok = fail = 0
    for stem in tqdm(stems, desc="Retry V3", unit="class"):
        expected = remaining[stem]
        n = len(expected)
        if translate_one(stem, expected):
            ok += 1
        else:
            fail += 1
            print(f"\n  [{stem}] FAILED ({n} methods)")
        time.sleep(0.1)

    print(f"\nDone: ok={ok} fail={fail}")


if __name__ == "__main__":
    main()
