"""
Step 3 Retry: Re-translate methods that failed Step 4 compile check,
with compile-error feedback loop until they compile or max retries exhausted.
"""
import time, requests, re, csv, json, os, sys, subprocess, tempfile
from pathlib import Path

BASE = Path(__file__).parent.parent
PIPELINE = Path(__file__).parent
SKELETON_DIR = PIPELINE / "02_CsAPI_splitted_nofw"
STEP4_CSV = PIPELINE / "04_test_results" / "cs_test_results.csv"
S25_CSV = PIPELINE / "02.5_compile_check.csv"
OUTPUT_DIR = PIPELINE / "03_CsAPI_test_cases"
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
MAX_RETRIES = 4
MCS_REFS = "-r:System.dll -r:System.Core.dll -r:System.Drawing.dll -r:System.Numerics.dll"

SYSTEM_PROMPT = """You translate Java test code to C#.

Given C# class definitions and a Java test method body, output ONLY the C# function body (lines between { and }).

Mapping rules:
- Assert.assertTrue(msg, cond) -> System.Diagnostics.Debug.Assert(cond);
- Assert.assertFalse(msg, cond) -> System.Diagnostics.Debug.Assert(!cond);
- Assert.assertEquals(msg, expected, actual) -> if (!object.Equals(expected, actual)) throw new Exception(...);
- Assert.assertNull(msg, obj) -> System.Diagnostics.Debug.Assert(obj == null);
- Assert.assertNotNull(msg, obj) -> // removed
- Assert.fail(msg) -> throw new Exception(msg);
- try { ... } catch (SomeException e) { } -> try { ... } catch (Exception) { }
- new Type(args) -> new Type(args)
- null -> null, boolean -> bool, String -> string
- Use the EXACT types and method names from the class definitions provided

IMPORTANT: You may ADD or MODIFY wrapper class methods if needed to compile.
If the test calls a method that doesn't exist, ADD a stub for it.
TOP PRIORITY: make the code COMPILE successfully.

Output the COMPLETE C# file (wrapper + test + closing braces). No markdown, no explanation."""


def get_failed_methods():
    """Get methods that failed Step 4 compile."""
    if not STEP4_CSV.exists():
        print("Step 4 CSV not found, cannot determine failures")
        return []
    failed = []
    with open(STEP4_CSV, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("compile_status", "") != "PASS":
                failed.append(row)
    print(f"Step 4 compile failures: {len(failed)}")
    return failed


def load_done():
    """Load already-fixed methods from retry log."""
    done = set()
    if LOG_PATH.exists():
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    if r.get("status") == "fixed":
                        done.add(r.get("rel_path", ""))
                except json.JSONDecodeError:
                    pass
    return done


def append_log(record):
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def extract_header(cs_code):
    """Extract class definitions header from skeleton."""
    code = cs_code.strip()
    code = re.sub(r'^```\w*\s*\n?', '', code)
    code = re.sub(r'\n?```\s*$', '', code)
    m = re.search(r'\n\s*(?:public\s+)?void\s+(\w+_test_\d+)', code)
    if m:
        return code[:m.start()].strip()
    return code.strip()


def compile_check(code):
    """Check if C# code compiles with mcs. Returns (True, '') or (False, error_message)."""
    with tempfile.NamedTemporaryFile(suffix=".cs", mode="w", delete=False) as tmp:
        tmp.write(code)
        tmp_path = tmp.name
    try:
        r = subprocess.run(
            ["mcs", "-target:library"] + MCS_REFS.split() + ["-out:/dev/null", tmp_path],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode == 0:
            return True, ""
        else:
            errors = re.findall(r'CS\d{4}[^)]*\)', r.stderr)
            return False, ("; ".join(errors[:5]) if errors else r.stderr[:600]).replace("\n", " | ")
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
            time.sleep(2)
            continue
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
        if 400 <= resp.status_code < 500 and resp.status_code != 429:
            break
        time.sleep(2)
    raise RuntimeError(f"API error HTTP {resp.status_code}")


def clean_body(body):
    body = re.sub(r'^```\w*\s*\n?', '', body.strip())
    body = re.sub(r'\n?```\s*$', '', body)
    body = re.sub(r'^(?:public\s+)?void\s+\w+_test_\d+\s*\(\s*\)\s*\{?\s*', '', body)
    body = re.sub(r'^\s*\{\s*\n?', '', body)
    body = re.sub(r'\}\s*$', '', body)
    return body.strip().encode('utf-8', errors='replace').decode('utf-8')


def translate_one(row):
    """Translate one method, with compile-feedback retry loop."""
    cls = row["class"]
    filename = row["filename"]
    name_match = re.match(r'(.+)_test_(\d+)\.cs', filename)
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
            user_prompt = f"""=== C# Class Definitions ===
{class_defs}

=== Java Test Case ===
{java_code}

Output ONLY the C# function body for {func_name}. Use EXACT C# types from above."""
        else:
            user_prompt = f"""=== C# Class Definitions ===
{class_defs}

=== Java Test Case ===
{java_code}

=== Your Previous Translation Had This Compile Error ===
{current_error}

Fix the compile error and output ONLY the corrected C# function body for {func_name}.
Use EXACT C# types and member names from the class definitions."""

        try:
            body = query_api(SYSTEM_PROMPT, user_prompt, max_tokens=4096)
            body = clean_body(body)

            # Assemble
            out_code = class_defs
            if "Debug.Assert" in body and "using System.Diagnostics" not in out_code:
                out_code = "using System.Diagnostics;\n" + out_code
            out_code += f"\n\npublic void {func_name}() {{\n{body}\n}}\n    }}\n}}"

            # Compile check
            ok, err = compile_check(out_code)
            if ok:
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
    # Save last attempt anyway
    try:
        out_path = OUTPUT_DIR / cls / filename
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(out_code, encoding="utf-8")
    except Exception:
        pass
    return False


def main():
    failed = get_failed_methods()
    if not failed:
        print("No failures to retry.")
        return

    done = load_done()
    print(f"Failed: {len(failed)}, already fixed: {len(done)}")

    # Filter to only methods that passed Step 2.5
    s25_pass = set()
    if S25_CSV.exists():
        with open(S25_CSV, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["compile_status"] == "PASS":
                    s25_pass.add(row["filename"])

    pending = [r for r in failed if r["filename"] in s25_pass
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
    for idx, row in enumerate(pending):
        if translate_one(row):
            ok += 1
        else:
            fail += 1
        if (idx + 1) % 20 == 0:
            print(f"  [{idx+1}/{len(pending)}] fixed:{ok} still_failing:{fail}")
        time.sleep(0.05)

    print(f"\nDone: fixed={ok} still_failing={fail}")


if __name__ == "__main__":
    main()
