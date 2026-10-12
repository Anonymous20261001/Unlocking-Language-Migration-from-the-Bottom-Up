"""
Re-translate the 78 IN-compile/IN-empty rows (excluding 2 IN-timeout) with LLM.
Phase-2 protocol: C# class defs + Java test body -> parameterless void C# test method.
Compile with error feedback, then run with mono for outcome.
"""
import csv, glob, json, os, re, subprocess, sys, tempfile, shutil
import requests

BASE = "/root/autodl-tmp/Java2C#"
CHECKLIST = f"{BASE}/Missing/csharp_in80_checklist.csv"
OUTPUT = f"{BASE}/error_taxonomy/data/csharp_in80_supplement.csv"
JAVA_DIR = f"{BASE}/Java_benchmark"
SKELETON_DIR = f"{BASE}/CsAPI_splitted_nofw"
TRANSLATED_DIR = f"{BASE}/CsAPI_benchmark_translated"

API_URL = "https://api.deepseek.com/v1/chat/completions"
# .env wins over stale env vars (bashrc may export an outdated key)
API_KEY = ""
_env = f"{BASE}/.env"
if os.path.exists(_env):
    for line in open(_env):
        line = line.strip()
        if line.startswith("DEEPSEEK_API_KEY="):
            API_KEY = line.split("=", 1)[1]
if not API_KEY:
    API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = "deepseek-chat"
MAX_RETRIES = 4
MCS_REFS = "-r:System.dll -r:System.Core.dll -r:System.Drawing.dll -r:System.Numerics.dll"

SYSTEM_PROMPT = """You translate Java JUnit tests to C#. You will receive a C# file (wrapper class definitions + a skeleton test method) and a Java test file.

Rules:
1. Translate the Java test method body into C#. The test method MUST have no parameters: public void MethodName().
2. Move all needed values into local variables inside the function body.
3. Preserve the test semantics: same assertions, same expected behavior.
4. Keep C# wrapper class definitions unchanged.
5. You may modify the wrapper class ONLY when it prevents the test from compiling (e.g. missing method, wrong signature).
6. Do NOT use NUnit/XUnit/MSTest attributes. The test method is a plain void method.
7. Use System.Diagnostics.Debug.Assert() or simple if-throw for assertions.
8. Do NOT add a Main() function.
TOP PRIORITY: make the code COMPILE successfully.

Output the complete C# file. No markdown fences, no explanation."""


def query_llm(prompt, max_tokens=4096):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}
    payload = {"model": MODEL,
               "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": prompt}],
               "stream": False, "temperature": 0.1, "max_tokens": max_tokens}
    for attempt in range(1, 5):
        try:
            r = requests.post(API_URL, headers=headers, json=payload, timeout=(30, 180))
        except requests.RequestException:
            import time; time.sleep(2); continue
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
        if 400 <= r.status_code < 500 and r.status_code != 429:
            break
        import time; time.sleep(2)
    raise RuntimeError(f"API error HTTP {r.status_code}")


def clean_output(raw):
    t = raw.strip()
    t = re.sub(r'^```\w*\s*\n?', '', t)
    t = re.sub(r'\n?```\s*$', '', t)
    return t.strip()


def compile_check(path):
    try:
        r = subprocess.run(["mcs", "-target:library"] + MCS_REFS.split() + ["-out:/dev/null", path],
                           capture_output=True, text=True, timeout=60)
        return (r.returncode == 0), r.stderr
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"


def find_test_method(code):
    m = re.search(r'public\s+void\s+(\w+[Tt]est[_\w]*\d+)\s*\(\s*\)', code)
    return m.group(1) if m else None


def run_test(filepath):
    """Run translated test with mono, return (passed, message)."""
    with open(filepath) as f:
        code = f.read()
    tm = find_test_method(code)
    if not tm:
        return False, "no_test_method"
    test_pos = code.find(f"void {tm}")
    ns = "Generated.Test"
    for nm in re.finditer(r'namespace\s+(\S+)', code):
        if nm.start() < test_pos:
            ns = nm.group(1)
    cls_name = "Program"
    for cm in re.finditer(r'class\s+(\w+)', code):
        if cm.start() < test_pos:
            cls_name = cm.group(1)
    tmpdir = tempfile.mkdtemp()
    try:
        wrapper = f"""using System;
using {ns};
public class TestRunner {{
    public static int Main() {{
        try {{
            new {cls_name}().{tm}();
            return 0;
        }} catch (Exception ex) {{
            Console.Error.WriteLine("TEST FAILED: " + ex.Message);
            return 1;
        }}
    }}
}}
"""
        wrapper_path = os.path.join(tmpdir, 'runner.cs')
        exe_path = os.path.join(tmpdir, 'test.exe')
        open(wrapper_path, 'w').write(wrapper)
        r = subprocess.run(["mcs", "-target:exe", "-out:" + exe_path] + MCS_REFS.split() + [filepath, wrapper_path],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return False, "COMPILE_ERR: " + r.stderr[:200].replace("\n", " | ")
        r2 = subprocess.run(["mono", exe_path], capture_output=True, text=True, timeout=10)
        if r2.returncode == 0:
            return True, ""
        return False, (r2.stderr + r2.stdout)[:300].replace("\n", " | ")
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def extract_header(skel_code):
    code = skel_code.strip()
    code = re.sub(r'^```\w*\s*\n?', '', code)
    code = re.sub(r'\n?```\s*$', '', code)
    m = re.search(r'\n\s*(?:public\s+)?void\s+(\w+_test_\d+)', code)
    if m:
        return code[:m.start()].strip()
    return code.strip()


def locate_files(cls, num, dataset):
    """Locate Java + skeleton files by test number, dataset-aware."""
    if dataset == "new_pipeline":
        java_dir = f"{BASE}/new_Java_test_cases"
        skel_dir = f"{BASE}/pipeline_cs/02_CsAPI_splitted_nofw"
    else:
        java_dir = JAVA_DIR
        skel_dir = SKELETON_DIR
    java_candidates = glob.glob(f"{java_dir}/{cls}/*_{num}.java")
    skel_candidates = glob.glob(f"{skel_dir}/{cls}/*_{num}.cs")
    if not java_candidates:
        return None, None
    java = java_candidates[0]
    skel = skel_candidates[0] if skel_candidates else None
    return java, skel


def retranslate_one(row):
    cls, num, dataset = row["class"], row["number"], row["dataset"]
    cls_name = row["cls"]

    # IN-timeout: just re-run existing translated file
    if cls_name == "IN-timeout":
        trans = glob.glob(f"{TRANSLATED_DIR}/{cls}/*{num}*.cs")
        if not trans:
            return {"status": "still_fails", "new_outcome": "", "failure_content": "translated file missing"}
        ok, msg = run_test(trans[0])
        if ok:
            return {"status": "fixed", "new_outcome": "PASS", "failure_content": ""}
        if msg == "TIMEOUT":
            return {"status": "still_fails", "new_outcome": "", "failure_content": "timeout"}
        return {"status": "still_fails", "new_outcome": "", "failure_content": msg}

    java_path, skel_path = locate_files(cls, num, dataset)
    if not java_path:
        return {"status": "still_fails", "new_outcome": "", "failure_content": "java file not found"}
    if not skel_path:
        return {"status": "still_fails", "new_outcome": "", "failure_content": "skeleton file not found"}

    with open(java_path) as f:
        java_code = f.read()
    with open(skel_path) as f:
        skel_code = f.read()
    class_defs = extract_header(skel_code)

    # Output filename: match translated dir convention
    method_name = os.path.basename(java_path).replace(f"_test_{num}.java", "")
    out_path = f"{TRANSLATED_DIR}/{cls}/{method_name}_test_{num}.cs"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    current_err = ""
    for attempt in range(MAX_RETRIES + 1):
        if attempt == 0:
            prompt = f"""=== C# File ===
{class_defs}

=== Java Test ===
{java_code}

Translate the test function body. The wrapper classes must compile with mcs -target:library.
Keep wrapper class definitions exactly as-is. Fill in the test method body only.
Output the complete C# file."""
        else:
            prompt = f"""=== C# File ===
{class_defs}

=== Java Test ===
{java_code}

=== Your Previous Translation Had This Compile Error ===
{current_err}

Fix the compile error and output the complete corrected C# file. Output only the complete C# code, no markdown."""
        try:
            out = clean_output(query_llm(prompt))
            with open(out_path, 'w') as f:
                f.write(out)
            ok, err = compile_check(out_path)
            if ok:
                passed, msg = run_test(out_path)
                if passed:
                    return {"status": "fixed", "new_outcome": "PASS", "failure_content": ""}
                if msg.startswith("COMPILE_ERR"):
                    # library compiled but runner wrapper failed -> still a compile failure
                    current_err = msg
                    continue
                if msg == "no_test_method":
                    current_err = "no_test_method"
                    continue
                # runs but assertion fails -> fixed with failure content as outcome
                return {"status": "fixed", "new_outcome": msg, "failure_content": ""}
            current_err = err[:600]
        except Exception as e:
            current_err = str(e)[:200]
    return {"status": "still_fails", "new_outcome": "", "failure_content": current_err[:300]}


def main():
    with open(CHECKLIST) as f:
        rows = list(csv.DictReader(f))

    offset = int(os.environ.get("OFFSET", "0"))
    stride = int(os.environ.get("STRIDE", "1"))
    rows = [r for i, r in enumerate(rows) if i % stride == offset]
    limit = int(os.environ.get("LIMIT", "0"))
    if limit > 0:
        rows = rows[:limit]

    print(f"[worker {offset}/{stride}] processing {len(rows)} rows")
    results = []
    for i, row in enumerate(rows):
        res = retranslate_one(row)
        res["row_key"] = row["row_key"]
        res["class"] = row["class"]
        res["method"] = row["method"]
        res["number"] = row["number"]
        results.append(res)
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(rows)} done")

    # Append to output CSV (per-worker shard file to avoid races)
    shard = f"{OUTPUT}.w{offset}.csv"
    fields = ["row_key", "class", "method", "number", "status", "new_outcome", "failure_content"]
    with open(shard, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(results)
    print(f"Shard written: {shard}")


if __name__ == "__main__":
    main()
