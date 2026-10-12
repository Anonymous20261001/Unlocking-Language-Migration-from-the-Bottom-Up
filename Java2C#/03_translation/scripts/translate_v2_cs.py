"""
Java benchmark → C# translation via LLM.
Translates Java JUnit test method bodies into C# test method bodies,
keeping C# wrapper class definitions unchanged.

Usage:
  python translate_v2_cs.py --test      # translate first 5, show output + compile status
  python translate_v2_cs.py              # translate all pass-compiling entries
"""

import time, requests, re, csv, os, sys, subprocess, multiprocessing as mp
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────
API_URL = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
if not API_URL.endswith("/chat/completions"):
    API_URL = API_URL.rstrip("/") + "/v1/chat/completions"
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

BENCHMARK_DIR  = Path("/root/autodl-tmp/Java2C#/Java_benchmark")
SKELETON_DIR   = Path("/root/autodl-tmp/Java2C#/CsAPI_splitted_nofw")
COMPILE_CSV    = Path("/root/autodl-tmp/Java2C#/compile_nofw_results.csv")
OUTPUT_DIR     = Path("/root/autodl-tmp/Java2C#/CsAPI_benchmark_translated")

# Mono compiler flags for syntax check
MCS_REFS = "-r:System.dll -r:System.Core.dll -r:System.Drawing.dll -r:System.Numerics.dll"

SYSTEM_PROMPT = """You translate Java JUnit tests to C#. You will receive a C# file (wrapper class definitions + a skeleton test method) and a Java test file.

Rules:
1. Translate the Java test method body into C#. The test method MUST have no parameters: void MethodName().
2. Move all needed values into local variables inside the function body.
3. Preserve the test semantics: same assertions, same expected behavior.
4. Keep C# wrapper class definitions unchanged.
5. You may modify the wrapper class ONLY when it prevents the test from compiling (e.g. missing method, wrong signature).
6. Do NOT use NUnit/XUnit/MSTest attributes. The test method is a plain void method.
7. Use System.Diagnostics.Debug.Assert() or simple if-throw for assertions.
8. Do NOT add a Main() function. Output only the class definitions and the test method.

Output the complete C# file. No markdown fences, no explanation."""

USER_MESSAGE_TEMPLATE = """=== C# File ===
{cs_code}

=== Java Test ===
{java_code}

Translate the test function body. The wrapper classes must compile with mcs -target:library.
Keep wrapper class definitions exactly as-is. Fill in the test method body only.
Output the complete C# file."""


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
    """Strip markdown fences."""
    text = raw.strip()
    text = re.sub(r'^```\w*\s*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text)
    return text.strip()


def compile_check(filepath: Path) -> bool:
    """Syntax-check a C# file with mcs."""
    try:
        r = subprocess.run(
            ["mcs", "-target:library"] + MCS_REFS.split() + ["-out:/dev/null", str(filepath)],
            capture_output=True, text=True, timeout=60)
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def translate_one(entry: dict) -> dict:
    cls = entry["class"]
    num = entry["number"]
    filename = entry["filename"]
    result = {"cls": cls, "num": num, "filename": filename}

    java_path = BENCHMARK_DIR / cls / filename
    cs_filename = filename.replace('.java', '.cs')
    skel_path = SKELETON_DIR / cls / cs_filename

    if not java_path.exists():
        result["ok"] = False; result["error"] = "java file missing"
        return result
    if not skel_path.exists():
        result["ok"] = False; result["error"] = "skeleton file missing"
        return result

    # Resume: skip if output already exists and compiles
    fn_match_pre = re.search(r'void\s+(\w+_test_\d+)', skel_path.read_text(encoding="utf-8"))
    func_name = fn_match_pre.group(1) if fn_match_pre else f"test_{num}"
    out_dir = OUTPUT_DIR / cls
    out_path_pre = out_dir / f"{func_name}.cs"
    if out_path_pre.exists() and compile_check(out_path_pre):
        result["ok"] = True
        result["compiles"] = True
        result["out_path"] = str(out_path_pre)
        result["skipped"] = True
        return result

    try:
        java_code = java_path.read_text(encoding="utf-8")
        cs_code = skel_path.read_text(encoding="utf-8")

        prompt = USER_MESSAGE_TEMPLATE.format(cs_code=cs_code, java_code=java_code)
        llm_output = query_llm(prompt, max_tokens=4096)
        output = clean_output(llm_output)

        out_dir.mkdir(parents=True, exist_ok=True)
        fn_match = re.search(r'void\s+(\w+_test_\d+)', cs_code)
        func_name = fn_match.group(1) if fn_match else f"test_{num}"
        out_path = out_dir / f"{func_name}.cs"
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
    """Load entries from compile_nofw_results.csv where passed == True."""
    entries = []
    with open(COMPILE_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("passed", "").strip() == "True":
                entries.append({
                    "class": row["class"].strip(),
                    "number": row["number"].strip(),
                    "filename": row["java_test_name"].strip() + ".java",
                })
    return entries


def main(test_mode: bool = False, retry_mode: bool = False):
    entries = load_entries()
    print(f"Loaded {len(entries)} entries with passed=True")

    if test_mode:
        entries = entries[:5]
        workers = 1
    else:
        workers = 32

    round_num = 0
    max_rounds = 10

    while True:
        round_num += 1
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        ok = fail = compile_ok = compile_fail = skipped = 0
        with mp.Pool(workers) as pool:
            for i, r in enumerate(pool.imap_unordered(translate_one, entries, chunksize=5)):
                if r["ok"]:
                    ok += 1
                    if r.get("skipped"):
                        skipped += 1
                    elif r.get("compiles", False):
                        compile_ok += 1
                    else:
                        compile_fail += 1
                else:
                    fail += 1

                if (i + 1) % 100 == 0 or test_mode:
                    print(f"  [round{round_num}][{i+1}/{len(entries)}] "
                          f"ok:{ok} fail:{fail} compile_ok:{compile_ok} compile_fail:{compile_fail} skip:{skipped}")

        print(f"\nRound {round_num} done! ok:{ok} fail:{fail} compile_ok:{compile_ok} "
              f"compile_fail:{compile_fail} skip:{skipped}")

        if test_mode:
            print("\n" + "=" * 60)
            for f in sorted(OUTPUT_DIR.glob("*/*.cs")):
                compiles = compile_check(f)
                status = "PASS" if compiles else "FAIL"
                print(f"\n--- {f.parent.name}/{f.name} [{status}] ---")
                print(f.read_text()[:1200])
            break

        if compile_fail == 0 and fail == 0:
            print(f"\nALL {len(entries)} entries compile successfully!")
            break

        if round_num >= max_rounds:
            print(f"\nMax rounds ({max_rounds}) reached. {compile_fail} still failing.")
            break

        if not retry_mode:
            break

        print(f"\nRetrying {compile_fail + fail} failed entries...\n")


if __name__ == "__main__":
    main(test_mode="--test" in sys.argv, retry_mode="--retry" in sys.argv)
