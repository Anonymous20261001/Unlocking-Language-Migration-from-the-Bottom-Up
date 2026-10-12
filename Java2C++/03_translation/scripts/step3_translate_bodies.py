"""
Step 3: Test Body Translation — translate Java Randoop test bodies to C++.

Only processes methods whose skeleton PASSED Step 2.5 compile check.
Uses Prompt B (from translate_benchmark.py) with the wrapper-class rule.
"""
import time, requests, re, csv, json, os, sys
from pathlib import Path
from tqdm import tqdm

BASE = Path(__file__).parent.parent
PIPELINE = Path(__file__).parent
SKELETON_DIR = PIPELINE / "02_CppJavadoc_splitted_method"
COMPILE_CSV = PIPELINE / "02.5_compile_check.csv"
OUTPUT_DIR = PIPELINE / "03_CppJavadoc_test_cases"
LOG_PATH = PIPELINE / "03_translate_bodies.log"
JAVA_TEST_DIR = BASE / "new_Java_test_cases"

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

SYSTEM_PROMPT = """You translate Java test code to C++.

Given C++ class definitions and a Java test method body, output ONLY the C++ function body (lines between { and }).

Mapping rules:
- Assert.assertTrue(msg, cond) -> assert(cond);
- Assert.assertFalse(msg, cond) -> assert(!cond);
- Assert.assertEquals(msg, expected, actual) -> assert(expected == actual);
- Assert.assertEquals(msg, a, b) -> assert(a == b);
- Assert.assertNull(msg, obj) -> assert(obj == nullptr);
- Assert.assertNotNull(msg, obj) -> // removed (null check not needed in C++)
- Assert.fail(msg) inside try { ... } catch: remove it (Java expects exception, C++ may not throw)
- Assert.fail(msg) NOT in try-catch: assert(false);
- Assert.assertArrayEquals(msg, a, b) -> assert(memcmp(a, b, size) == 0);
- Assert.assertSame(msg, a, b) -> assert(&a == &b);
- Assert.assertNotSame(msg, a, b) -> assert(&a != &b);
- try { ... } catch (SomeException e) { } -> try { ... } catch (...) { }
- new Type(args) -> Type(args)
- null -> nullptr
- String literals stay as-is (use std::string)
- Integer literals stay as-is
- Boolean literals: true -> true, false -> false
- Use the EXACT types and method names from the class definitions provided

重要规则: 如果不是编译问题，不要为了通过测试而改动wrapper类。只有在wrapper类本身有编译错误时才修改它。

Output ONLY the function body lines. No explanation, no markdown fences, no #include, no class definitions, no function signature."""


def load_passed_methods() -> list:
    """Load methods that passed Step 2.5 compile check."""
    if not COMPILE_CSV.exists():
        print(f"WARNING: {COMPILE_CSV} not found, no methods to process")
        return []
    entries = []
    with open(COMPILE_CSV, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["compile_status"] == "PASS":
                entries.append(row)
    return entries


def load_completed() -> set:
    """Load set of already-completed output filenames."""
    done = set()
    if LOG_PATH.exists():
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("status") == "ok":
                        done.add(rec.get("rel_path", ""))
                except json.JSONDecodeError:
                    continue
    return done


def append_log(record: dict):
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def extract_header(cpp_code: str) -> str:
    """Extract class definitions (everything before first test function)."""
    m = re.search(r'\nvoid\s+(\w+_test_\d+)', cpp_code)
    if m:
        header = cpp_code[:m.start()].strip()
    else:
        header = cpp_code.strip()
    # Strip markdown fences
    header = re.sub(r'^```\w*\s*', '', header)
    header = re.sub(r'\s*```\s*$', '', header)
    return header


def query_deepseek(system_prompt: str, user_content: str, max_tokens: int = 2048) -> str:
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
    for attempt in range(1, 5):
        try:
            resp = requests.post(API_URL, headers=headers, json=payload,
                                 timeout=(30, 180))
        except requests.RequestException as e:
            time.sleep(2)
            continue
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
        if 400 <= resp.status_code < 500 and resp.status_code != 429:
            break
        time.sleep(2)
    raise RuntimeError(f"API error HTTP {resp.status_code}")


def clean_body(body: str) -> str:
    """Clean LLM output into raw function body lines."""
    body = body.strip()
    # Remove markdown fences
    body = re.sub(r'^```\w*\s*\n?', '', body)
    body = re.sub(r'\n?```\s*$', '', body)
    # Remove function wrapper if LLM added it
    body = re.sub(r'^void\s+\w+_test_\d+\s*\(\s*\)\s*\{?\s*', '', body)
    # Remove leading opening brace (LLM sometimes outputs { ... })
    body = re.sub(r'^\s*\{\s*\n?', '', body)
    # Remove trailing closing brace
    body = re.sub(r'\}\s*$', '', body)
    body = body.strip()
    body = body.encode('utf-8', errors='replace').decode('utf-8')
    return body


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load methods to process
    passed = load_passed_methods()
    print(f"Step 2.5 PASS methods: {len(passed)}")

    if not passed:
        print("No methods to translate. Run Step 2.5 first.")
        return

    # Resume state
    completed = load_completed()
    print(f"Resume: {len(completed)} already completed")

    # Sharding
    offset = int(os.environ.get("OFFSET", "0"))
    stride = int(os.environ.get("STRIDE", "1"))
    passed = [row for i, row in enumerate(passed) if i % stride == offset]

    limit = int(os.environ.get("LIMIT", "0"))
    if limit > 0:
        passed = passed[:limit]

    total = len(passed)
    print(f"[worker {offset}/{stride}] {total} methods to translate")
    print(f"{'='*60}")

    ok = skip = fail = 0
    pbar = tqdm(passed, desc="Step 3", unit="method")

    for row in pbar:
        cls = row["class"]
        filename = row["filename"]
        # Parse test_num and method_name from filename like "getInstance_test_144.cpp"
        name_match = re.match(r'(.+)_test_(\d+)\.cpp', filename)
        if not name_match:
            append_log({"class": cls, "filename": filename,
                        "rel_path": f"{cls}/{filename}", "status": "bad_filename"})
            fail += 1
            continue
        method_name = name_match.group(1)
        test_num = name_match.group(2)
        func_name = f"{method_name}_test_{test_num}"
        rel_path = f"{cls}/{filename}"

        out_path = OUTPUT_DIR / cls / filename
        if rel_path in completed and out_path.exists():
            skip += 1
            pbar.set_postfix({"ok": ok, "skip": skip, "fail": fail})
            continue

        pbar.set_postfix({"ok": ok, "skip": skip, "fail": fail, "cur": func_name[:15]})

        try:
            # Read C++ skeleton
            skel_path = SKELETON_DIR / cls / filename
            if not skel_path.exists():
                append_log({"class": cls, "filename": filename, "rel_path": rel_path,
                            "status": "no_skeleton"})
                fail += 1
                continue

            skel_code = skel_path.read_text(encoding="utf-8")
            class_defs = extract_header(skel_code)

            # Read Java test
            java_path = JAVA_TEST_DIR / cls / f"{func_name}.java"
            if not java_path.exists():
                append_log({"class": cls, "filename": filename, "rel_path": rel_path,
                            "status": "no_java_test"})
                fail += 1
                continue
            java_code = java_path.read_text(encoding="utf-8")

            # Build user prompt
            user_prompt = f"""=== C++ Class Definitions (DO NOT MODIFY THESE) ===
{class_defs}

=== Java Test Case ===
{java_code}

Output ONLY the C++ function body for {func_name}. Use the EXACT C++ types from the class definitions above."""

            # Translate
            body = query_deepseek(SYSTEM_PROMPT, user_prompt, max_tokens=2048)
            body = clean_body(body)

            # Assemble output
            out_code = class_defs
            if '#include <cassert>' not in out_code:
                out_code = '#include <cassert>\n' + out_code
            out_code += f"\n\nvoid {func_name}() {{\n{body}\n}}\n"

            # Save
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(out_code, encoding="utf-8")

            append_log({"class": cls, "method": method_name, "test_num": test_num,
                        "filename": filename, "rel_path": rel_path, "status": "ok"})
            ok += 1

        except Exception as e:
            append_log({"class": cls, "filename": filename, "rel_path": rel_path,
                        "status": "error", "error": str(e)[:200]})
            fail += 1

        time.sleep(0.05)

    print(f"\n{'='*60}")
    print(f"Step 3 complete: ok={ok}, skip={skip}, fail={fail}")
    print(f"Log: {LOG_PATH}")


if __name__ == "__main__":
    main()
