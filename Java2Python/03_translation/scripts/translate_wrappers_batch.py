"""
Translate new_method_tests Java files -> Python via DeepSeek (Anthropic API).
Output: PythonJavaDoc_by_class/{ClassName}.py
Records: PythonJavaDoc_by_class/_translation_record.csv
Multi-threaded (8 workers) for speed.
"""

import csv, os, re, sys, time, requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# ── Config ──────────────────────────────────────────────────────────
API_URL = "https://api.deepseek.com/anthropic/v1/messages"
API_KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
WORKERS = 8

BASE = Path("/root/autodl-tmp/Java2Python")
JAVA_DIR = BASE / "new_method_tests"
OUTPUT_DIR = BASE / "PythonJavaDoc_by_class"

SYSTEM_PROMPT = (
    "You are a professional Java and Python developer. "
    "Below is a Java source file containing test wrapper methods — each @Test method creates an instance of a class "
    "and calls one of its API methods. Translate it to Python following these rules:\n"
    "1. FIRST, write all test functions using unittest. Every Java @Test method MUST become exactly one Python "
    "test function with the SAME name (e.g., remove_test_3315 -> def remove_test_3315). Each test function is 3-5 lines.\n"
    "2. AFTER all test functions, write a wrapper class containing the methods called by the tests.\n"
    "Do not reply with any additional text beyond the runnable Python code.\n"
)

_print_lock = Lock()


def log(msg):
    with _print_lock:
        print(msg, flush=True)


def query_deepseek(prompt: str, max_tokens: int = 8192) -> str:
    headers = {
        "Content-Type": "application/json",
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "thinking": {"type": "disabled"},
        "messages": [{"role": "user", "content": prompt}],
    }
    for attempt in range(1, 6):
        try:
            resp = requests.post(API_URL, headers=headers, json=payload,
                                 timeout=(30, 180))
        except requests.RequestException as e:
            log(f"  请求异常 (第{attempt}次): {e}")
            time.sleep(2); continue
        if resp.status_code == 200:
            data = resp.json()
            for block in data["content"]:
                if block["type"] == "text":
                    content = block["text"].strip()
                    if content.startswith("```"):
                        content = re.sub(r"^```(?:python)?\s*\n?", "", content)
                        content = re.sub(r"\n?```\s*$", "", content)
                    return content
            raise RuntimeError("No text content in response")
        log(f"  HTTP {resp.status_code} (第{attempt}次): {resp.text[:200]}")
        if 400 <= resp.status_code < 500 and resp.status_code != 429: break
        time.sleep(2)
    raise RuntimeError("请求失败")


def check_missing(python_code: str, expected_nums: set) -> set:
    """Return set of test numbers in expected_nums but NOT in the Python output."""
    found = set(re.findall(r"def\s+\w+_test_(\d+)\s*\(", python_code))
    return expected_nums - found


def translate_one(jf: Path, idx: int, total: int, wanted_nums: set) -> dict:
    """Translate one Java file. Returns record dict."""
    cls_long = jf.stem
    out_file = OUTPUT_DIR / f"{cls_long}.py"

    if out_file.exists():
        return {"file": cls_long, "methods": len(wanted_nums), "status": "skip", "output": str(out_file)}

    try:
        java_code = jf.read_text(encoding="utf-8")
        n_wanted = len(wanted_nums)
        log(f"  [{idx}/{total}] {cls_long}: want {n_wanted} methods ({len(java_code)} chars) ...")

        prompt = SYSTEM_PROMPT + "\n" + java_code
        python_code = query_deepseek(prompt)

        # Verify all expected test numbers are present
        missing = check_missing(python_code, wanted_nums)
        if missing:
            log(f"  [{idx}/{total}] {cls_long}: MISSING {len(missing)} tests: {sorted(missing)[:10]}...")
            return {"file": cls_long, "methods": n_wanted,
                    "status": "missing", "missing": ",".join(sorted(missing)),
                    "output": str(out_file), "error": f"missing {len(missing)}"}

        out_file.write_text(python_code, encoding="utf-8")
        log(f"  [{idx}/{total}] {cls_long}: OK ({n_wanted} verified)")
        return {"file": cls_long, "methods": n_wanted, "status": "success", "output": str(out_file)}
    except Exception as e:
        log(f"  [{idx}/{total}] {cls_long}: FAIL {e}")
        (OUTPUT_DIR / f"{cls_long}.error").write_text(str(e))
        return {"file": cls_long, "methods": len(wanted_nums), "status": "fail", "error": str(e)}


def main():
    # ── Which classes to translate ──
    wanted = {}  # class_name -> set of test_numbers
    with open(BASE / "Javadoc_randoop_list_1754.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            norm = {}
            for k, v in row.items():
                norm[k.strip().lstrip('﻿').strip()] = v.strip() if v else ''
            fn = norm.get('文件名', '')
            num = norm.get('测试编号', '')
            wanted.setdefault(fn.replace('.java', ''), set()).add(num)

    java_files = sorted([f for f in JAVA_DIR.glob("*.java") if f.stem in wanted])

    total_methods = sum(len(wanted[cls]) for cls in wanted)
    print(f"待翻译: {len(java_files)} 个类, {total_methods} 个方法")
    print(f"输入: {JAVA_DIR}")
    print(f"输出: {OUTPUT_DIR}")
    print(f"并行: {WORKERS} workers")
    print(f"模型: {MODEL}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Parallel translation ──
    records = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(translate_one, jf, i + 1, len(java_files), wanted[jf.stem]): jf
                for i, jf in enumerate(java_files)}
        for fut in as_completed(futs):
            try:
                records.append(fut.result())
            except Exception as e:
                log(f"  Worker crashed: {e}")

    records.sort(key=lambda r: r["file"])

    # ── Write record CSV ──
    record_path = OUTPUT_DIR / "_translation_record.csv"
    with open(record_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "methods", "status", "output", "missing", "error"])
        w.writeheader()
        w.writerows(records)

    success = sum(1 for r in records if r["status"] == "success")
    skip = sum(1 for r in records if r["status"] == "skip")
    fail = sum(1 for r in records if r["status"] == "fail")
    print(f"\n{'='*60}")
    print(f"完成! 成功: {success}  跳过: {skip}  失败: {fail}")
    print(f"记录: {record_path}")
    print(f"输出: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
