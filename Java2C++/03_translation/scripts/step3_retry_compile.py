"""
Step 3 Retry: Re-translate methods that failed Step 4 compile check,
with compile-error feedback loop until they compile or max retries exhausted.
"""
import time, requests, re, csv, json, os, sys, subprocess, tempfile
from pathlib import Path
from tqdm import tqdm

BASE = Path(__file__).parent.parent
PIPELINE = Path(__file__).parent
SKELETON_DIR = PIPELINE / "02_CppJavadoc_splitted_method"
STEP4_CSV = PIPELINE / "04_test_results" / "cpp_test_results.csv"
S25_CSV = PIPELINE / "02.5_compile_check.csv"
OUTPUT_DIR = PIPELINE / "03_CppJavadoc_test_cases"
LOG_PATH = PIPELINE / "03_retry_compile.log"
JAVA_TEST_DIR = BASE / "new_Java_test_cases"

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
MODEL = "deepseek-chat"
MAX_RETRIES = 3

SYSTEM_PROMPT = """You translate Java test code to C++.

Given C++ class definitions and a Java test method body, output ONLY the C++ function body (lines between { and }).

Mapping rules:
- Assert.assertTrue(msg, cond) -> assert(cond);
- Assert.assertFalse(msg, cond) -> assert(!cond);
- Assert.assertEquals(msg, expected, actual) -> assert(expected == actual);
- Assert.assertNull(msg, obj) -> assert(obj == nullptr);
- Assert.assertNotNull(msg, obj) -> // removed
- Assert.fail(msg) -> assert(false);
- try { ... } catch (SomeException e) { } -> try { ... } catch (...) { }
- new Type(args) -> Type(args)
- null -> nullptr
- Use the EXACT types and method names from the class definitions provided
- Use std::string (NOT just 'string'), std::vector, etc.
- Add #include <typeinfo> if you use typeid()
- Do NOT add your own opening { or closing } — the wrapper adds those

重要: 如果不是编译问题，不要为了通过测试而改动wrapper类。只有wrapper类本身有编译错误时才修改它。

Output ONLY the function body lines. No explanation, no markdown, no #include, no class definitions, no function signature."""


def get_failed_methods():
    """Get methods that passed Step 2.5 but failed Step 4 compile."""
    if not STEP4_CSV.exists():
        print("Step 4 CSV not found, using all Step 2.5 PASS methods")
        s25 = set()
        with open(S25_CSV) as f:
            for row in csv.DictReader(f):
                if row['compile_status'] == 'PASS':
                    s25.add((row['class'], row['filename']))
        return list(s25)

    failed = []
    with open(STEP4_CSV) as f:
        for row in csv.DictReader(f):
            if row['compile_status'] != 'PASS':
                failed.append(row)
    print(f"Step 4 compile failures: {len(failed)}")
    return failed


def load_done():
    """Load already-fixed methods from retry log."""
    done = set()
    if LOG_PATH.exists():
        with open(LOG_PATH) as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    r = json.loads(line)
                    if r.get('status') == 'fixed':
                        done.add(r.get('rel_path', ''))
                except: pass
    return done


def append_log(record):
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def extract_header(cpp_code):
    m = re.search(r'\n\s*void\s+(\w+_test_\d+)', cpp_code)
    if m:
        header = cpp_code[:m.start()].strip()
        header = re.sub(r'^```\w*\s*', '', header)
        header = re.sub(r'\s*```\s*$', '', header)
        return header
    return cpp_code.strip()


def compile_check(code):
    """Check if C++ code compiles. Returns (True, '') or (False, error_message)."""
    with tempfile.NamedTemporaryFile(suffix='.cpp', mode='w', delete=False) as tmp:
        tmp.write(code)
        tmp_path = tmp.name
    try:
        r = subprocess.run(
            ["g++", "-std=c++17", "-fsyntax-only", "-w", tmp_path],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0:
            return True, ""
        else:
            return False, r.stderr[:600].replace("\n", " | ")
    except Exception as e:
        return False, str(e)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def query_api(system_prompt, user_content, max_tokens=4096):
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
            resp = requests.post(API_URL, headers=headers, json=payload, timeout=(30, 180))
        except requests.RequestException as e:
            time.sleep(2); continue
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
        if 400 <= resp.status_code < 500 and resp.status_code != 429:
            break
        time.sleep(2)
    raise RuntimeError(f"API error HTTP {resp.status_code}")


def clean_body(body):
    body = re.sub(r'^```\w*\s*\n?', '', body.strip())
    body = re.sub(r'\n?```\s*$', '', body)
    body = re.sub(r'^void\s+\w+_test_\d+\s*\(\s*\)\s*\{?\s*', '', body)
    body = re.sub(r'^\s*\{\s*\n?', '', body)
    body = re.sub(r'\}\s*$', '', body)
    return body.strip().encode('utf-8', errors='replace').decode('utf-8')


def translate_one(row, round_num=0):
    """Translate one method, with compile-feedback retry loop."""
    cls = row['class']
    filename = row['filename']
    name_match = re.match(r'(.+)_test_(\d+)\.cpp', filename)
    if not name_match:
        return False
    method_name = name_match.group(1)
    test_num = name_match.group(2)
    func_name = f"{method_name}_test_{test_num}"
    rel_path = f"{cls}/{filename}"

    # Read skeleton
    skel_path = SKELETON_DIR / cls / filename
    if not skel_path.exists():
        return False
    skel_code = skel_path.read_text(encoding="utf-8")
    class_defs = extract_header(skel_code)

    # Read Java test
    java_path = JAVA_TEST_DIR / cls / f"{func_name}.java"
    if not java_path.exists():
        return False
    java_code = java_path.read_text(encoding="utf-8")

    # Try until compile passes
    current_error = ""
    for attempt in range(MAX_RETRIES + 1):
        if attempt == 0:
            user_prompt = f"""=== C++ Class Definitions ===
{class_defs}

=== Java Test Case ===
{java_code}

Output ONLY the C++ function body for {func_name}. Use EXACT C++ types from above."""
        else:
            user_prompt = f"""=== C++ Class Definitions ===
{class_defs}

=== Java Test Case ===
{java_code}

=== Your Previous Translation Had This Compile Error ===
{current_error}

Fix the compile error and output ONLY the corrected C++ function body for {func_name}.
Use EXACT C++ types and member names from the class definitions."""

        try:
            body = query_api(SYSTEM_PROMPT, user_prompt, max_tokens=4096)
            body = clean_body(body)

            # Assemble
            out_code = class_defs
            if '#include <cassert>' not in out_code:
                out_code = '#include <cassert>\n' + out_code
            out_code += f"\n\nvoid {func_name}() {{\n{body}\n}}\n"

            # Compile check
            ok, err = compile_check(out_code)
            if ok:
                # Save
                out_path = OUTPUT_DIR / cls / filename
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(out_code, encoding="utf-8")
                append_log({"class": cls, "method": method_name, "test_num": test_num,
                            "filename": filename, "rel_path": rel_path,
                            "attempts": attempt + 1, "status": "fixed"})
                return True
            else:
                current_error = err
                if attempt < MAX_RETRIES:
                    print(f"  [{func_name}] compile fail (attempt {attempt+1}), retrying...")
                    time.sleep(0.3)
        except Exception as e:
            if attempt < MAX_RETRIES:
                time.sleep(2)
            else:
                append_log({"class": cls, "method": method_name, "test_num": test_num,
                            "filename": filename, "rel_path": rel_path,
                            "attempts": attempt + 1, "status": "error", "error": str(e)[:200]})

    # All retries exhausted
    append_log({"class": cls, "method": method_name, "test_num": test_num,
                "filename": filename, "rel_path": rel_path,
                "attempts": MAX_RETRIES + 1, "status": "still_failing",
                "last_error": current_error[:300]})
    # Save the last attempt anyway
    out_path = OUTPUT_DIR / cls / filename
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if 'out_code' in dir():
        out_path.write_text(out_code, encoding="utf-8")
    return False


def main():
    failed = get_failed_methods()
    done = load_done()
    print(f"Failed: {len(failed)}, already fixed: {len(done)}")

    # Filter to only methods that passed Step 2.5
    s25_pass = set()
    if S25_CSV.exists():
        with open(S25_CSV) as f:
            for row in csv.DictReader(f):
                if row['compile_status'] == 'PASS':
                    s25_pass.add(row['filename'])

    pending = [r for r in failed if r['filename'] in s25_pass
               and f"{r['class']}/{r['filename']}" not in done]

    # Sharding
    offset = int(os.environ.get("OFFSET", "0"))
    stride = int(os.environ.get("STRIDE", "1"))
    pending = [r for i, r in enumerate(pending) if i % stride == offset]

    limit = int(os.environ.get("LIMIT", "0"))
    if limit > 0:
        pending = pending[:limit]

    print(f"[worker {offset}/{stride}] {len(pending)} methods to retry")
    print(f"{'='*60}")

    ok = fail = 0
    for row in tqdm(pending, desc="Retry compile", unit="method"):
        if translate_one(row):
            ok += 1
        else:
            fail += 1
        time.sleep(0.05)

    print(f"\nDone: fixed={ok} still_failing={fail}")


if __name__ == "__main__":
    main()
