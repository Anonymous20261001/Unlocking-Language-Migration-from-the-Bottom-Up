"""
Step 3: Test Body Translation — translate Java Randoop test bodies to C#.

Only processes methods whose skeleton PASSED Step 2.5 compile check.
"""
import time, requests, re, csv, json, os, sys
from pathlib import Path

BASE = Path(__file__).parent.parent
PIPELINE = Path(__file__).parent
SKELETON_DIR = PIPELINE / "02_CsAPI_splitted_nofw"
COMPILE_CSV = PIPELINE / "02.5_compile_check.csv"
OUTPUT_DIR = PIPELINE / "03_CsAPI_test_cases"
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

SYSTEM_PROMPT = """You translate Java test code to C#.

Given C# class definitions and a Java test method body, output ONLY the C# function body (lines between { and }).

Mapping rules:
- Assert.assertTrue(msg, cond) -> System.Diagnostics.Debug.Assert(cond);
- Assert.assertFalse(msg, cond) -> System.Diagnostics.Debug.Assert(!cond);
- Assert.assertEquals(msg, expected, actual) -> if (!object.Equals(expected, actual)) throw new Exception("Expected " + expected + " but got " + actual);
- Assert.assertNull(msg, obj) -> System.Diagnostics.Debug.Assert(obj == null);
- Assert.assertNotNull(msg, obj) -> // removed (null check not needed in C#)
- Assert.fail(msg) -> throw new Exception(msg);
- Assert.assertArrayEquals(msg, a, b) -> // collection comparison, use manual check
- Assert.assertSame(msg, a, b) -> System.Diagnostics.Debug.Assert(ReferenceEquals(a, b));
- Assert.assertNotSame(msg, a, b) -> System.Diagnostics.Debug.Assert(!ReferenceEquals(a, b));
- try { ... } catch (SomeException e) { } -> try { ... } catch (Exception) { }
- new Type(args) -> new Type(args)
- null -> null
- boolean -> bool
- String -> string
- Integer/long/double/float literals stay as-is
- Use the EXACT types and method names from the class definitions provided

Important: Do NOT modify the wrapper class unless it has a compile error.
Only the test body should be translated.

Output ONLY the function body lines. No explanation, no markdown fences, no using, no namespace, no class definitions, no function signature."""


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


def extract_header(cs_code: str) -> str:
    """Extract class definitions (everything before first test method)."""
    # Strip markdown fences
    code = cs_code.strip()
    code = re.sub(r'^```\w*\s*\n?', '', code)
    code = re.sub(r'\n?```\s*$', '', code)
    # Find first test method
    m = re.search(r'\n\s*(?:public\s+)?void\s+(\w+_test_\d+)', code)
    if m:
        header = code[:m.start()].strip()
    else:
        header = code.strip()
    return header


def query_deepseek(system_prompt: str, user_content: str, max_tokens: int = 4096) -> str:
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
    body = re.sub(r'^(?:public\s+)?void\s+\w+_test_\d+\s*\(\s*\)\s*\{?\s*', '', body)
    # Remove leading opening brace
    body = re.sub(r'^\s*\{\s*\n?', '', body)
    # Remove trailing closing brace(s)
    body = re.sub(r'\}\s*$', '', body)
    body = body.strip()
    body = body.encode('utf-8', errors='replace').decode('utf-8')
    return body


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load methods to process (only Step 2.5 PASS)
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

    for idx, row in enumerate(passed):
        cls = row["class"]
        filename = row["filename"]
        # Parse test_num and method_name from filename like "getInstance_test_144.cs"
        name_match = re.match(r'(.+)_test_(\d+)\.cs', filename)
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
            if (idx + 1) % 50 == 0:
                print(f"  [{idx+1}/{total}] ok:{ok} skip:{skip} fail:{fail}")
            continue

        try:
            # Read C# skeleton
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
            user_prompt = f"""=== C# Class Definitions (DO NOT MODIFY THESE) ===
{class_defs}

=== Java Test Case ===
{java_code}

Output ONLY the C# function body for {func_name}. Use the EXACT C# types from the class definitions above."""

            # Translate
            body = query_deepseek(SYSTEM_PROMPT, user_prompt, max_tokens=4096)
            body = clean_body(body)

            # Assemble output: header + test method + close class + close namespace
            out_code = class_defs
            # Ensure System.Diagnostics is available if Debug.Assert is used
            if "Debug.Assert" in body and "using System.Diagnostics" not in out_code:
                out_code = "using System.Diagnostics;\n" + out_code
            out_code += f"\n\npublic void {func_name}() {{\n{body}\n}}\n    }}\n}}"

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

        if (idx + 1) % 20 == 0:
            print(f"  [{idx+1}/{total}] ok:{ok} skip:{skip} fail:{fail}")
        time.sleep(0.05)

    print(f"\n{'='*60}")
    print(f"Step 3 complete: ok={ok}, skip={skip}, fail={fail}")
    print(f"Log: {LOG_PATH}")


if __name__ == "__main__":
    main()
