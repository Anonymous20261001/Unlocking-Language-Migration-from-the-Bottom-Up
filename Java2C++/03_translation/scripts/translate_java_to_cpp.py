"""
Java → C++ API Translation via DeepSeek
==========================================
Reads Java source files from JavaAPI_by_class, sends each to DeepSeek
for zero-shot translation to C++, and saves the results.

API: SJTU HPC internal endpoint (data stays on-campus)
Model: deepseek-v4-flash
"""

import time
import requests
from pathlib import Path
import os
import sys
from tqdm import tqdm

# ── Config ──────────────────────────────────────────────────────────
# Load .env file if present
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").strip().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.__setitem__(_k.strip(), _v.strip())

_raw_url = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
# Auto-append path if user only provides base URL
if not _raw_url.endswith("/chat/completions"):
    _raw_url = _raw_url.rstrip("/") + "/v1/chat/completions"
API_URL = _raw_url
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

JAVA_SOURCE_DIR = Path("/root/autodl-tmp/Java2C++/JavaAPI_by_class")
OUTPUT_DIR = Path("/root/autodl-tmp/Java2C++/CppAPI_by_class")

# Prompt: same structure as Java→Python, only target language changed
SYSTEM_PROMPT = (
    "You are a professional Java and C++ developer.\n\n"
    "Below is a Java test file. Each @Test method creates an instance of a Java class "
    "and exercises one of its API methods.\n\n"
    "Your task:\n"
    "1. Translate every Java @Test method into exactly one C++ test function with the "
    "SAME name (e.g., equals_test_6446 → void equals_test_6446(...)).\n"
    "2. For each Java class used in the tests, implement a C++ equivalent class whose "
    "API behaves identically to the original Java API.\n\n"
    "Output only the complete C++ code.\n"
)


# ── API Call ────────────────────────────────────────────────────────
def query_deepseek(messages: str, max_tokens: int = 4096) -> str:
    """Send a translation request to DeepSeek with retry logic."""
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

    # Parallel sharding: OFFSET (0-based) and STRIDE (e.g. 8 workers)
    offset = int(os.environ.get("OFFSET", "0"))
    stride = int(os.environ.get("STRIDE", "1"))
    java_files = [f for i, f in enumerate(java_files) if i % stride == offset]

    limit = int(os.environ.get("LIMIT", "0"))
    if limit > 0:
        java_files = java_files[:limit]
    total = len(java_files)
    print(f"[worker {offset}/{stride}] 找到 {total} 个 Java 文件")
    print(f"输出目录: {OUTPUT_DIR}")
    print(f"{'='*60}")

    success_count = 0
    skip_count = 0
    fail_count = 0

    pbar = tqdm(java_files, desc="Translating", unit="file")
    for java_path in pbar:
        stem = java_path.stem
        output_path = OUTPUT_DIR / f"{stem}.cpp"

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
            cpp_code = query_deepseek(prompt)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(cpp_code)
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
