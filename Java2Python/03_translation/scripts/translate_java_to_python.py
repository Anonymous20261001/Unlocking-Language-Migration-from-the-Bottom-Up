"""
Java → Python API Translation via DeepSeek
==========================================
Reads Java source files from JavaAPI_by_class, sends each to DeepSeek V3.2
for zero-shot translation to Python, and saves the results.

API: SJTU HPC internal endpoint (data stays on-campus)
Model: deepseek-v3.2
"""

import time
import requests
from pathlib import Path
import os
import sys
from tqdm import tqdm

# ── Config ──────────────────────────────────────────────────────────
_raw_url = os.environ.get("DEEPSEEK_API_URL", "https://models.sjtu.edu.cn/api/v1/chat/completions")
# Auto-append path if user only provides base URL
if not _raw_url.endswith("/chat/completions"):
    _raw_url = _raw_url.rstrip("/") + "/v1/chat/completions"
API_URL = _raw_url
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

JAVA_SOURCE_DIR = Path("/Users/jeff/PycharmProjects/JavaData/JavaAPI_by_class")
OUTPUT_DIR = Path("/Users/jeff/PycharmProjects/pythonData/PythonAPI_by_class")

# Prompt: same structure as Java→C#, only target language changed
SYSTEM_PROMPT = (
    "You are a professional Java and Python developer. "
    "Below is a Java source file containing test wrapper methods — each @Test method creates an instance of a class "
    "and calls one of its API methods. Translate it to Python following these rules:\n"
    "1. FIRST, write all test functions using unittest. Every Java @Test method MUST become exactly one Python "
    "test function with the SAME name (e.g., remove_test_3315 def remove_test_3315). Each test function is 3-5 lines.\n"
    "2. AFTER all test functions, write a minimal wrapper class containing ONLY the methods actually called by the tests. "
    "Keep each method to 1-3 lines. Do NOT implement full logic — these are stubs for compilation only.\n"
    "Do not reply with any additional text beyond the runnable Python code.\n"
)


# ── API Call ────────────────────────────────────────────────────────
def query_deepseek(messages: str, max_tokens: int = 4096) -> str:
    """Send a translation request to DeepSeek V3.2 with retry logic."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": messages}],
        "stream": False,
        "temperature": 0.7,
        "max_tokens": max_tokens,
    }

    for attempt in range(1, 6):
        try:
            resp = requests.post(API_URL, headers=headers, json=payload,
                                 timeout=(30, 120))
        except requests.RequestException as e:
            print(f"  请求异常 (第{attempt}次): {e}")
            time.sleep(2)
            continue

        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()

        print(f"  HTTP {resp.status_code} (第{attempt}次): {resp.text[:300]}")
        if 400 <= resp.status_code < 500 and resp.status_code != 429:
            break
        time.sleep(2)

    raise RuntimeError("请求失败，见上方 HTTP 输出")


# ── Main Translation Loop ───────────────────────────────────────────
def main():
    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Collect all Java files
    java_files = sorted(JAVA_SOURCE_DIR.glob("*.java"))
    total = len(java_files)
    print(f"找到 {total} 个 Java 文件")
    print(f"输出目录: {OUTPUT_DIR}")
    print(f"{'='*60}")

    success_count = 0
    skip_count = 0
    fail_count = 0

    pbar = tqdm(java_files, desc="Translating", unit="file")
    for java_path in pbar:
        stem = java_path.stem
        output_path = OUTPUT_DIR / f"{stem}.py"

        # Resume: skip already-processed files
        if output_path.exists():
            skip_count += 1
            pbar.set_postfix({"ok": success_count, "skip": skip_count, "fail": fail_count})
            continue

        pbar.set_postfix({"ok": success_count, "skip": skip_count, "fail": fail_count, "cur": stem[:20]})

        try:
            with open(java_path, "r", encoding="utf-8") as f:
                java_code = f.read()
            prompt = SYSTEM_PROMPT + java_code
            python_code = query_deepseek(prompt)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(python_code)
            success_count += 1
        except Exception as e:
            fail_count += 1
            error_path = OUTPUT_DIR / f"{stem}.error"
            with open(error_path, "w", encoding="utf-8") as f:
                f.write(str(e))

        time.sleep(0.05)

    print(f"\n{'='*60}")
    print(f"完成!  成功: {success_count}  跳过: {skip_count}  失败: {fail_count}")
    print(f"输出目录: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
