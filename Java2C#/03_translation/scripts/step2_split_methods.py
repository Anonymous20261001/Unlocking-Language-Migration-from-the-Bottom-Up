"""
Step 2: Mechanical Split — split class-level C# files into per-method files.

Reads each C# file from Step 1 output, extracts the header (using + namespace + class defs),
and splits out individual test method files.
"""
import re, csv, json, os
from pathlib import Path
from collections import OrderedDict

BASE = Path(__file__).parent.parent
PIPELINE = Path(__file__).parent
INPUT_DIR = PIPELINE / "01_CsAPI_by_class"
OUTPUT_DIR = PIPELINE / "02_CsAPI_splitted_nofw"
LOG_PATH = PIPELINE / "02_split.log"
CSV_PATH = BASE / "Javadoc_randoop_list_1754.csv"


def parse_csv(csv_path: Path) -> dict:
    """Build {class_stem: [(test_num, method_name), ...]} from CSV."""
    class_map = OrderedDict()
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        raw = f.read()
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    reader = csv.DictReader(raw.splitlines())
    for row in reader:
        filename_key = "文件名"
        if filename_key not in row:
            for k in row.keys():
                if "文件名" in k:
                    filename_key = k
                    break
        stem = Path(row[filename_key]).stem
        test_num = int(row["测试编号"])
        method_name = row["方法名"]
        class_map.setdefault(stem, []).append((test_num, method_name))
    return class_map


def append_log(record: dict):
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def extract_header_and_functions(cs_code: str) -> tuple:
    """Split C# code into header (before first test method) and dict of {method_name: full_code}."""
    # Strip markdown fences if present
    code = cs_code.strip()
    code = re.sub(r'^```\w*\s*\n?', '', code)
    code = re.sub(r'\n?```\s*$', '', code)

    # Find the header boundary: first test method
    # C# test pattern: "public void methodName_test_N()" or just "void methodName_test_N()"
    header_match = re.search(r'\n\s*(?:public\s+)?void\s+(\w+_test_\d+)\s*\(', code)
    if not header_match:
        return code.strip(), {}

    header = code[:header_match.start()].strip()

    # Find all test methods with their bodies
    functions = OrderedDict()
    # Match "public void func_name()" or "void func_name(params)"
    pattern = re.compile(r'(?:public\s+)?void\s+(\w+_test_\d+)\s*\([^)]*\)\s*\{')

    for m in pattern.finditer(code):
        func_name = m.group(1)
        start = m.start()

        # Brace matching to find method end
        brace_pos = m.end() - 1  # position of opening {
        depth = 0
        end_pos = brace_pos
        for i in range(brace_pos, len(code)):
            if code[i] == '{':
                depth += 1
            elif code[i] == '}':
                depth -= 1
                if depth == 0:
                    end_pos = i + 1
                    break

        func_code = code[start:end_pos].strip()
        functions[func_name] = func_code

    return header, functions


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    class_map = parse_csv(CSV_PATH)
    print(f"CSV: {len(class_map)} classes, {sum(len(v) for v in class_map.values())} methods")

    # Resume: load already-done entries from log
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
                        done.add(rec["filename"])
                except json.JSONDecodeError:
                    continue
    print(f"Resume: {len(done)} already split")

    total = ok = skip = missing = err = 0

    for stem in class_map:
        input_path = INPUT_DIR / f"{stem}.cs"
        if not input_path.exists():
            print(f"  [SKIP] missing input: {stem}.cs")
            continue

        cs_code = input_path.read_text(encoding="utf-8")
        header, functions = extract_header_and_functions(cs_code)

        if not functions:
            append_log({"class": stem, "method": "", "test_num": 0,
                        "filename": "", "status": "no_test_methods"})
            err += 1
            continue

        # Create class subdirectory
        class_dir = OUTPUT_DIR / stem
        class_dir.mkdir(parents=True, exist_ok=True)

        for test_num, method_name in class_map[stem]:
            func_name = f"{method_name}_test_{test_num}"
            filename = f"{func_name}.cs"
            total += 1

            if filename in done:
                skip += 1
                continue

            if func_name in functions:
                out_path = class_dir / filename
                # Header includes: using ... namespace Generated.Test { ... class definitions ... class TestClass {
                # The test method is inside the test class. We need to close the class and namespace.
                out_content = header + "\n\n" + functions[func_name] + "\n    }\n}\n"
                out_path.write_text(out_content, encoding="utf-8")

                append_log({"class": stem, "method": method_name, "test_num": test_num,
                            "filename": filename, "status": "ok"})
                ok += 1
            else:
                append_log({"class": stem, "method": method_name, "test_num": test_num,
                            "filename": filename, "status": "missing_method"})
                missing += 1

        if total % 100 == 0:
            print(f"  progress: {total} total, ok={ok}, skip={skip}, missing={missing}")

    print(f"\n{'='*60}")
    print(f"Step 2 complete: total={total}, ok={ok}, skip={skip}, missing={missing}, err={err}")
    print(f"Log: {LOG_PATH}")


if __name__ == "__main__":
    main()
