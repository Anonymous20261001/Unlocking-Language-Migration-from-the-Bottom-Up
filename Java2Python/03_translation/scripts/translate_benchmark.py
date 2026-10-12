"""
LLM-based Java benchmark → C++ translation.
Expands C++ skeleton test functions with real test behavior from Java benchmark.
"""
import time, requests, re, csv
from pathlib import Path
import os, sys, json, multiprocessing as mp

# ── Config ──────────────────────────────────────────────────────────
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8").strip().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

API_URL = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
if not API_URL.endswith("/chat/completions"):
    API_URL = API_URL.rstrip("/") + "/v1/chat/completions"
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

BENCHMARK_DIR = Path("/root/autodl-tmp/Java2C++/tmp_benchmark/Java_benchmark")
SKELETON_DIR = Path("/root/autodl-tmp/Java2C++/CppAPI_splitted_method")
MAPPING_CSV = Path("/root/autodl-tmp/Java2C++/mapping.csv")
OUTPUT_DIR = Path("/root/autodl-tmp/Java2C++/Cpp_benchmark_translated")

SYSTEM_PROMPT = """You translate Java test code to C++.

Given C++ class definitions and a Java test method body, output ONLY the C++ function body (lines between { and }).

Mapping rules:
- Assert.assertTrue(msg, cond) → assert(cond);
- Assert.assertEquals(msg, a, b) → assert(a == b);
- Assert.assertFalse(msg, cond) → assert(!cond);
- Assert.assertNull/assertNotNull → // removed
- Assert.fail(msg) → assert(false);
- try { ... } catch (SomeException e) { } → try { ... } catch (...) { }
- new Type(args) → Type(args)
- null → nullptr
- Use the EXACT types and method names from the class definitions provided

Output ONLY the function body lines. No explanation, no markdown, no #include, no class definitions."""


def query_deepseek(prompt: str, max_tokens: int = 4096) -> str:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "temperature": 0.2,
        "max_tokens": max_tokens,
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
    raise RuntimeError(f"HTTP {resp.status_code}")


def translate_one(entry) -> dict:
    cls, num, filename = entry
    java_path = BENCHMARK_DIR / cls / filename
    skel_dir = SKELETON_DIR / cls
    if not java_path.exists() or not skel_dir.exists():
        return {"cls": cls, "num": num, "ok": False, "error": "missing files"}

    try:
        java_code = java_path.read_text(encoding="utf-8")

        # Read ANY skeleton file from this class to get class definitions
        skel_files = list(skel_dir.glob("*.cpp"))
        if not skel_files:
            return {"cls": cls, "num": num, "ok": False, "error": "no skeleton"}

        skel_code = skel_files[0].read_text(encoding="utf-8")

        # Extract class definitions (everything before the first test function)
        func_match = re.search(r'\nvoid\s+(\w+_test_\d+)', skel_code)
        class_code = skel_code[:func_match.start()].strip() if func_match else skel_code
        class_code = re.sub(r'^```\w*\s*', '', class_code)
        class_code = re.sub(r'\s*```\s*$', '', class_code)

        # Build prompt: class defs + Java test
        prompt = f"""=== C++ Class Definitions (DO NOT MODIFY THESE) ===
{class_code}

=== Java Test Case ===
{java_code}

Output ONLY the C++ function body for the test function. The function name must be {func_match.group(1) if func_match else 'test_'+str(num)}.
Use the EXACT C++ types from the class definitions above.
Output raw C++ body lines (statements between {{ and }}). No explanation."""

        result = query_deepseek(prompt, max_tokens=2048)

        # Clean output
        body = result.strip()
        body = re.sub(r'^```\w*\s*\n?', '', body)
        body = re.sub(r'\n?```\s*$', '', body)
        # Remove any "void test_xxx() {" wrapper if present
        body = re.sub(r'^void\s+\w+_test_\d+\s*\(\s*\)\s*\{?\s*', '', body)
        body = re.sub(r'\}\s*$', '', body)
        body = body.strip()
        body = body.encode('utf-8', errors='replace').decode('utf-8')

        # Get the correct function name from the specific skeleton file
        specific_skel = skel_dir / f"{filename}"
        if specific_skel.exists():
            specific_code = specific_skel.read_text(encoding="utf-8")
            fn_match = re.search(r'void\s+(\w+_test_\d+)', specific_code)
            func_name = fn_match.group(1) if fn_match else f"test_{num}"
        else:
            func_name = func_match.group(1) if func_match else f"test_{num}"

        # Assemble output
        if '#include <cassert>' not in class_code:
            class_code = '#include <cassert>\n' + class_code
        full_code = class_code + f"\n\nvoid {func_name}() {{\n{body}\n}}\n"

        out_dir = OUTPUT_DIR / cls
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{func_name}.cpp").write_text(full_code, encoding="utf-8")

        return {"cls": cls, "num": num, "ok": True}
    except Exception as e:
        return {"cls": cls, "num": num, "ok": False, "error": str(e)[:100]}


def main(test_mode=False):
    entries = []
    with open(MAPPING_CSV) as f:
        for row in csv.DictReader(f):
            if row["compile_status"] == "pass":
                entries.append((row["class"], int(row["number"]), row["filename"]))

    if test_mode:
        entries = entries[:5]
        workers = 1
    else:
        workers = min(mp.cpu_count(), 8)

    print(f"Translating {len(entries)} files (LLM)")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    ok = fail = 0
    with mp.Pool(workers) as pool:
        for i, r in enumerate(pool.imap_unordered(translate_one, entries, chunksize=5)):
            if r["ok"]: ok += 1
            else: fail += 1
            if (i + 1) % 100 == 0 or test_mode:
                print(f"  {i+1}/{len(entries)} ok:{ok} fail:{fail}")

    print(f"\nDone! ok:{ok} fail:{fail}")

    if test_mode:
        # Show results
        import subprocess
        for f in sorted(OUTPUT_DIR.glob("*/*.cpp")):
            name = f"{f.parent.name}/{f.name}"
            r = subprocess.run(["g++", "-std=c++17", "-fsyntax-only", "-w", str(f)],
                              capture_output=True, text=True, timeout=10)
            status = "PASS" if r.returncode == 0 else f"FAIL: {r.stderr.split(chr(10))[-2] if r.stderr else ''}"
            print(f"\n=== {name} [{status}] ===")
            print(f.read_text()[:800])

    if not test_mode:
        # Quick compile check
        import subprocess, random
        fs = list(OUTPUT_DIR.glob("*/*.cpp"))
        random.shuffle(fs)
        sample = fs[:200]
        p = sum(1 for f in sample if subprocess.run(
            ["g++", "-std=c++17", "-fsyntax-only", "-w", str(f)],
            capture_output=True, timeout=10).returncode == 0)
        print(f"Compile({len(sample)}): {p}/{len(sample)} ({p*100//len(sample)}%)")


if __name__ == "__main__":
    main(test_mode="--test" in sys.argv)
