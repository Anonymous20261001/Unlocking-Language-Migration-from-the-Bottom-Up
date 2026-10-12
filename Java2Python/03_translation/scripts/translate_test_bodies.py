"""
LLM translates Java Randoop test → complete Python unittest file.
Each Java test file → one Python test file via DeepSeek.
Output: PythonJavadoc_test_cases/{Class}/{method}_test_{N}.py
"""

import csv, os, re, time, requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

API_URL = "https://api.deepseek.com/anthropic/v1/messages"
API_KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
WORKERS = 8

BASE = Path("/root/autodl-tmp/Java2Python")
PY_SKEL_DIR = BASE / "PythonJavadoc_splitted_method"
JAVA_TEST_DIR = BASE / "new_Java_test_cases"
OUTPUT_DIR = BASE / "PythonJavadoc_test_cases"
CSV_PATH = BASE / "Javadoc_randoop_list_1754.csv"

SYSTEM_PROMPT = (
    "You are a Java-to-Python translator. "
    "Translate the given Java test file into a COMPLETE runnable Python unittest file.\n"
    "\n"
    "Rules:\n"
    "- Use self.assertTrue/assertEqual/assertIsNone/assertIsNotNone/fail/assertRaises\n"
    "- new Foo(args) → Foo(args); null → None; FQCN → short class name\n"
    "- String + non-string → wrap in str()\n"
    "- try { ... } catch (XxxException e) { } → with self.assertRaises(Exception): ...\n"
    "- Include ONLY a minimal wrapper class with the methods called by the test\n"
    "- Ensure valid Python syntax and semantic equivalence to the Java test\n"
    "\n"
    "Output ONLY the Python code. No explanation, no markdown.\n"
)

_print_lock = Lock()

def _extract_wrapper(py_code: str) -> str:
    """Extract non-Test wrapper classes from Python skeleton."""
    lines = py_code.split("\n")
    wrapper_start = None
    for i, line in enumerate(lines):
        m = re.match(r"^class\s+(\w+)", line)
        if m and "Test" not in m.group(1) and "unittest" not in line:
            wrapper_start = i
            break
    if wrapper_start is None:
        return "# No wrapper class found"
    return "\n".join(lines[wrapper_start:])


def log(msg):
    with _print_lock:
        print(msg, flush=True)


def query_deepseek(prompt: str, max_tokens: int = 4096) -> str:
    headers = {
        "Content-Type": "application/json",
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "thinking": {"type": "disabled"},
        "messages": [{"role": "user", "content": prompt}],
    }
    for attempt in range(1, 5):
        try:
            resp = requests.post(API_URL, headers=headers, json=payload, timeout=(30, 120))
        except requests.RequestException as e:
            if attempt < 4: time.sleep(2); continue
            raise
        if resp.status_code == 200:
            data = resp.json()
            for block in data["content"]:
                if block["type"] == "text":
                    content = block["text"].strip()
                    # Strip natural language preface before first ```python or first Python keyword
                    m = re.search(r"(?:^|\n)(?:```python|```|import |from |class |def |@|if __name__)", content)
                    if m:
                        content = content[m.start():].lstrip("\n")
                    # Strip markdown code fences (opening + closing)
                    content = re.sub(r"^```(?:python)?\s*\n?", "", content)
                    # Truncate at the LAST ``` — everything after is explanation, not code
                    last_fence = content.rfind("```")
                    if last_fence > 0:
                        # Only if preceded by code (not at the beginning)
                        before = content[:last_fence].strip()
                        if before:
                            content = before
                    return content
            raise RuntimeError("No text in response")
        if 400 <= resp.status_code < 500 and resp.status_code != 429:
            if attempt < 4: time.sleep(2); continue
            raise RuntimeError(f"HTTP {resp.status_code}")
        time.sleep(2)
    raise RuntimeError("请求失败")


def translate_one(py_file: Path, java_file: Path, idx: int, total: int) -> dict:
    cls = py_file.parent.name
    func_name = py_file.stem
    out_file = OUTPUT_DIR / cls / f"{func_name}.py"

    if out_file.exists():
        return {"class": cls, "func": func_name, "status": "skip"}

    try:
        py_skeleton = py_file.read_text(encoding="utf-8")
        java_code = java_file.read_text(encoding="utf-8")

        # Extract wrapper class code from skeleton
        wrapper = _extract_wrapper(py_skeleton)

        prompt = (
            f"=== Python Wrapper Class (use these exact methods) ===\n"
            f"{wrapper}\n\n"
            f"=== Java Test File ===\n"
            f"{java_code}\n\n"
            f"Translate to a COMPLETE Python unittest file for: {func_name}\n"
            f"Ensure valid Python syntax and semantic equivalence.\n"
        )

        python_code = query_deepseek(prompt)

        if not python_code or len(python_code.strip()) < 20:
            return {"class": cls, "func": func_name, "status": "error", "error": "empty"}

        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(python_code, encoding="utf-8")
        return {"class": cls, "func": func_name, "status": "ok"}
    except Exception as e:
        return {"class": cls, "func": func_name, "status": "error", "error": str(e)[:200]}


def main():
    wanted = {}
    with open(CSV_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            norm = {}
            for k, v in row.items():
                norm[k.strip().lstrip('﻿').strip()] = v.strip() if v else ''
            fn = norm.get('文件名', '')
            cls = fn.replace('.java', '')
            num = norm.get('测试编号', '')
            method = norm.get('方法名', '')
            wanted.setdefault(cls, []).append((num, method))

    total = sum(len(v) for v in wanted.values())
    print(f"目标: {total} methods, {len(wanted)} classes")
    print(f"模型: {MODEL}, 并行: {WORKERS}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    work = []
    for cls_name in sorted(wanted):
        for num, method in wanted[cls_name]:
            func_name = f"{method}_test_{num}"
            py_f = PY_SKEL_DIR / cls_name / f"{func_name}.py"
            java_f = JAVA_TEST_DIR / cls_name / f"{func_name}.java"
            if py_f.exists() and java_f.exists():
                work.append((py_f, java_f))
            else:
                work.append((None, None))  # placeholder

    work = [(p, j) for p, j in work if p is not None]
    print(f"待翻译: {len(work)}")

    records = []
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(translate_one, py_f, java_f, i, len(work)): py_f
                for i, (py_f, java_f) in enumerate(work)}
        for fut in as_completed(futs):
            done += 1
            try:
                r = fut.result()
                records.append(r)
                if r["status"] != "ok":
                    log(f"  [{done}] {r['status']}: {r['class']}/{r['func']} {r.get('error','')[:80]}")
            except Exception as e:
                log(f"  [{done}] crash: {e}")
            if done % 200 == 0:
                ok = sum(1 for r in records if r["status"] == "ok")
                log(f"  [{done}] ok={ok}")

    ok = sum(1 for r in records if r["status"] == "ok")
    err = sum(1 for r in records if r["status"] == "error")
    skip = sum(1 for r in records if r["status"] == "skip")
    print(f"\n{'='*60}")
    print(f"完成! ok={ok} err={err} skip={skip}")


if __name__ == "__main__":
    main()
