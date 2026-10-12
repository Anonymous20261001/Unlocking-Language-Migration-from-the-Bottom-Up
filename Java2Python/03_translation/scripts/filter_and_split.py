"""
Filter translated Python files -> per-method files in PythonJavadoc_splitted_method/
Output: PythonJavadoc_splitted_method/{ClassName}/{method}_test_{N}.py
Only keeps methods in Javadoc_randoop_list_1754.csv.
"""

import csv, re
from pathlib import Path

BASE = Path("/root/autodl-tmp/Java2Python")
SRC_DIR = BASE / "PythonJavaDoc_by_class"
DST_DIR = BASE / "PythonJavadoc_splitted_method"
CSV_PATH = BASE / "Javadoc_randoop_list_1754.csv"

def get_indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def split_python_file(src_path: Path, wanted_nums: set) -> dict:
    """Split a Python file into individual test functions + wrapper.
    Each output file = imports + all wrapper classes + single test function."""
    content = src_path.read_text(encoding="utf-8")
    lines = content.split("\n")

    # Find all test functions (with _test_NNN pattern)
    funcs = []  # [(name, num, start_line, end_line)]
    i = 0
    while i < len(lines):
        m = re.search(r"def\s+(?:test_)?(\w+_test_(\d+))\s*\(", lines[i])
        if m:
            name = m.group(1)
            num = m.group(2)
            start = i
            base_indent = get_indent(lines[i])
            i += 1
            while i < len(lines):
                stripped = lines[i].strip()
                cur_indent = get_indent(lines[i])
                if stripped == "":
                    i += 1
                elif cur_indent <= base_indent and (stripped.startswith("def ") or stripped.startswith("class ")):
                    break
                elif cur_indent <= base_indent and stripped != "":
                    break
                else:
                    i += 1
            funcs.append((name, num, start, i))
        else:
            i += 1

    if not funcs:
        return {}

    # Header: everything before the first line of code (imports + blank lines)
    first_line = funcs[0][2]
    # Also find any lines before first function that aren't blank — they might be imports at top
    header_end = first_line
    while header_end > 0 and lines[header_end - 1].strip() == "":
        header_end -= 1
    header = "\n".join(lines[:header_end]).rstrip()

    # Find all wrapper code: top-level class defs + their bodies
    # NOT inside test functions
    used_lines = set()
    for _, _, start, end in funcs:
        for j in range(start, end):
            used_lines.add(j)

    wrapper_lines = []
    for i, line in enumerate(lines):
        if i not in used_lines and i >= first_line:
            wrapper_lines.append(line)

    wrapper = "\n".join(wrapper_lines).strip()
    # Clean trailing if __name__ etc.
    wrapper = re.sub(r"\nif\s+__name__\s*==.*", "", wrapper)

    # Build per-method files
    results = {}
    for name, num, start, end in funcs:
        if num in wanted_nums:
            func_body = "\n".join(lines[start:end]).rstrip()
            parts = [header, "", func_body]
            if wrapper:
                parts.extend(["", wrapper])
            full = "\n".join(parts) + "\n"
            results[num] = (name, full)

    return results


def main():
    # Read wanted numbers
    wanted = {}  # class_name -> set of test_numbers
    with open(CSV_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            norm = {}
            for k, v in row.items():
                norm[k.strip().lstrip('﻿').strip()] = v.strip() if v else ''
            fn = norm.get('文件名', '')
            num = norm.get('测试编号', '')
            wanted.setdefault(fn.replace('.java', ''), set()).add(num)

    total_wanted = sum(len(v) for v in wanted.values())
    print(f"目标: {total_wanted} 个方法, {len(wanted)} 个类")
    print(f"输入: {SRC_DIR}")
    print(f"输出: {DST_DIR}")

    DST_DIR.mkdir(parents=True, exist_ok=True)

    total = 0
    missing = 0

    for py_file in sorted(SRC_DIR.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        cls_name = py_file.stem
        if cls_name not in wanted:
            continue

        wanted_nums = wanted[cls_name]
        results = split_python_file(py_file, wanted_nums)

        out_dir = DST_DIR / cls_name
        out_dir.mkdir(parents=True, exist_ok=True)

        for num, (func_name, code) in results.items():
            out_file = out_dir / f"{func_name}.py"
            out_file.write_text(code, encoding="utf-8")
            total += 1

        found_nums = set(results.keys())
        missed = wanted_nums - found_nums
        if missed:
            print(f"  MISSING {cls_name}: {sorted(missed)}")
            missing += len(missed)

    print(f"\n生成: {total} 个文件, 缺失: {missing}")
    print(f"输出: {DST_DIR}")


if __name__ == "__main__":
    main()
