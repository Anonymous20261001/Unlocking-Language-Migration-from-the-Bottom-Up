"""
Java benchmark → C++ translation via LLM.
Translates Java JUnit test method bodies into C++ test function bodies,
keeping C++ class definitions (wrapper) unchanged.

Usage:
  python translate_v2.py --test      # translate first 5, show output + compile status
  python translate_v2.py              # translate all pass-compiling entries
"""

import time, requests, re, csv, os, sys, subprocess, multiprocessing as mp
from pathlib import Path

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
MAPPING_CSV  = Path("/root/autodl-tmp/Java2C++/mapping.csv")
OUTPUT_DIR   = Path("/root/autodl-tmp/Java2C++/Cpp_benchmark_translated")

SYSTEM_PROMPT = """You translate Java JUnit tests to C++. You will receive a C++ file (class definitions + a skeleton test function) and a Java test file.

Rules:
1. Translate the Java test method body into C++. The test function MUST have no parameters: void functionName().
2. Move all needed values into local variables inside the function body.
3. Preserve the test semantics: same assertions, same expected behavior.
4. Keep C++ class definitions unchanged when possible.
5. You may modify class definitions ONLY when they prevent the test from compiling (e.g. missing method, wrong signature).
6. The output must compile with g++ -std=c++17.
7. Do NOT add a main() function. Output only the class definitions and the test function.

Output the complete C++ file. No markdown fences, no explanation."""

USER_MESSAGE_TEMPLATE = """=== C++ File ===
{cpp_code}

=== Java Test ===
{java_code}

Translate the test function body. Keep class definitions exactly as-is.
Output the complete C++ file."""


def query_llm(prompt: str, max_tokens: int = 4096) -> str:
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {API_KEY}"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    last_err = ""
    for attempt in range(1, 6):
        try:
            resp = requests.post(API_URL, headers=headers, json=payload,
                                 timeout=(30, 180))
        except requests.RequestException as e:
            last_err = str(e)
            time.sleep(2)
            continue
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
        last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
        if 400 <= resp.status_code < 500 and resp.status_code != 429:
            break
        time.sleep(2)
    raise RuntimeError(last_err)


def clean_output(raw: str) -> str:
    """Strip markdown fences and any LLM-added main() function."""
    text = raw.strip()
    text = re.sub(r'^```\w*\s*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text)
    # Remove any int main() { ... } that LLM might add
    text = re.sub(r'\n*(//.*\n)*int\s+main\s*\(\s*\)\s*\{.*', '', text, flags=re.DOTALL)
    # Ensure <cassert> is included if assert() is used
    if re.search(r'\bassert\s*\(', text) and '#include <cassert>' not in text:
        text = '#include <cassert>\n' + text
    # Ensure <iostream> is included if std::cout/cerr is used
    if re.search(r'std::(cout|cerr)\b', text) and '#include <iostream>' not in text:
        text = '#include <iostream>\n' + text
    return text.strip()


def compile_check(filepath: Path) -> bool:
    r = subprocess.run(
        ["g++", "-std=c++17", "-fsyntax-only", "-w", str(filepath)],
        capture_output=True, text=True, timeout=30)
    return r.returncode == 0


def translate_one(entry: tuple) -> dict:
    cls, num, filename = entry
    result = {"cls": cls, "num": num, "filename": filename}

    java_path = BENCHMARK_DIR / cls / filename
    cpp_filename = filename.replace('.java', '.cpp')
    skel_path = SKELETON_DIR / cls / cpp_filename

    if not java_path.exists():
        result["ok"] = False; result["error"] = "java file missing"
        return result
    if not skel_path.exists():
        result["ok"] = False; result["error"] = "skeleton file missing"
        return result

    try:
        java_code = java_path.read_text(encoding="utf-8")
        cpp_code  = skel_path.read_text(encoding="utf-8")

        prompt = USER_MESSAGE_TEMPLATE.format(cpp_code=cpp_code, java_code=java_code)
        llm_output = query_llm(prompt, max_tokens=4096)
        output = clean_output(llm_output)

        out_dir = OUTPUT_DIR / cls
        out_dir.mkdir(parents=True, exist_ok=True)
        # derive function name from skeleton
        fn_match = re.search(r'void\s+(\w+_test_\d+)', cpp_code)
        func_name = fn_match.group(1) if fn_match else f"test_{num}"
        out_path = out_dir / f"{func_name}.cpp"
        out_path.write_text(output, encoding="utf-8")

        compiles = compile_check(out_path)
        result["ok"] = True
        result["compiles"] = compiles
        result["out_path"] = str(out_path)
    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)[:200]

    return result


def load_entries() -> list:
    """Load entries from mapping.csv where compile_status == 'pass'."""
    entries = []
    with open(MAPPING_CSV, encoding="utf-8") as f:
        raw = f.read()
    # strip Windows CR
    raw = raw.replace('\r\n', '\n').replace('\r', '\n')
    reader = csv.DictReader(raw.splitlines())
    for row in reader:
        if row.get("compile_status", "").strip() == "pass":
            entries.append((
                row["class"].strip(),
                int(row["number"].strip()),
                row["filename"].strip(),
            ))
    return entries


def main(test_mode: bool = False):
    entries = load_entries()
    print(f"Loaded {len(entries)} entries with compile_status=pass")

    if test_mode:
        entries = entries[:5]
        workers = 1
    else:
        workers = 32  # I/O bound (API calls), not CPU bound

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    ok = fail = compile_ok = compile_fail = 0
    with mp.Pool(workers) as pool:
        for i, r in enumerate(pool.imap_unordered(translate_one, entries, chunksize=5)):
            if r["ok"]:
                ok += 1
                compiles = r.get("compiles", False)
                if compiles:
                    compile_ok += 1
                else:
                    compile_fail += 1
            else:
                fail += 1

            if (i + 1) % 50 == 0 or test_mode:
                print(f"  [{i+1}/{len(entries)}] ok:{ok} fail:{fail} "
                      f"compile_ok:{compile_ok} compile_fail:{compile_fail}")

    print(f"\nDone! ok:{ok} fail:{fail} compile_ok:{compile_ok} compile_fail:{compile_fail}")

    if test_mode:
        print("\n" + "=" * 60)
        for f in sorted(OUTPUT_DIR.glob("*/*.cpp")):
            compiles = compile_check(f)
            status = "PASS" if compiles else "FAIL"
            print(f"\n--- {f.parent.name}/{f.name} [{status}] ---")
            print(f.read_text()[:1000])


if __name__ == "__main__":
    main(test_mode="--test" in sys.argv)
