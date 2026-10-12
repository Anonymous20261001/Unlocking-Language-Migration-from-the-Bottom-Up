#!/usr/bin/env python3
"""Split new_method_tests/*.java into per-method files under new_method_by_method/"""

import os
import re
import sys

SRC_DIR = "/root/autodl-tmp/Java2Python/new_method_tests"
DST_DIR = "/root/autodl-tmp/Java2Python/new_method_by_method"


def parse_java_file(content):
    """Parse a Java test file and return (package, imports, class_name, methods).

    Each method is a dict with: annotation, signature_lines, body_lines
    """
    lines = content.split("\n")

    # Extract package
    pkg = "package generated.test;"
    for line in lines:
        if line.strip().startswith("package "):
            pkg = line.strip()
            break

    # Extract imports (all non-empty lines between package and class)
    imports = []
    in_imports = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("package "):
            in_imports = True
            continue
        if in_imports:
            if stripped.startswith("import "):
                imports.append(stripped)
            elif stripped.startswith("public class ") or stripped.startswith("class "):
                break

    # Extract class name
    class_name = None
    for line in lines:
        m = re.match(r'public\s+class\s+(\w+)', line.strip())
        if m:
            class_name = m.group(1)
            break
    if not class_name:
        m = re.match(r'class\s+(\w+)', line.strip())
        if m:
            class_name = m.group(1)

    # Find all @Test methods
    methods = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped == "@Test" or stripped.startswith("@Test"):
            # Found a test method
            annotation = lines[i].rstrip()
            i += 1
            # Collect method signature lines (until we find the opening brace)
            sig_lines = []
            while i < len(lines) and "{" not in lines[i]:
                sig_lines.append(lines[i])
                i += 1
            # The line with "{"
            if i < len(lines):
                sig_lines.append(lines[i])
                i += 1
            else:
                break

            # Now collect method body until matching close brace
            body_lines = []
            brace_depth = 1  # we've seen one "{"
            while i < len(lines) and brace_depth > 0:
                line = lines[i]
                # Count braces in this line (but not in strings/comments)
                for ch in line:
                    if ch == "{":
                        brace_depth += 1
                    elif ch == "}":
                        brace_depth -= 1
                body_lines.append(line)
                i += 1

            methods.append({
                "annotation": annotation,
                "signature": sig_lines,
                "body": body_lines,
            })
        else:
            i += 1

    return pkg, imports, class_name, methods


def method_name_from_sig(sig_lines):
    """Extract method name from signature lines."""
    for line in sig_lines:
        m = re.match(r'public\s+\w+\s+(\w+)\s*\(', line.strip())
        if m:
            return m.group(1)
    return "unknown"


def main():
    os.makedirs(DST_DIR, exist_ok=True)

    java_files = sorted(
        f for f in os.listdir(SRC_DIR) if f.endswith(".java")
    )

    total_methods = 0
    total_dirs = 0

    for filename in java_files:
        filepath = os.path.join(SRC_DIR, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        pkg, imports, class_name, methods = parse_java_file(content)

        if not methods:
            print(f"  [WARN] No @Test methods found in {filename}")
            continue

        # Class name without the trailing "AutoTest" (it's already in the filename pattern)
        # The directory name should match the class name
        dir_name = class_name  # e.g. "java_awt_geom_QuadCurve2DAutoTest"
        dir_path = os.path.join(DST_DIR, dir_name)
        os.makedirs(dir_path, exist_ok=True)
        total_dirs += 1

        for method in methods:
            mname = method_name_from_sig(method["signature"])
            if mname == "unknown":
                continue

            # Build the individual test file
            out_lines = []
            out_lines.append(pkg)
            out_lines.append("")
            for imp in imports:
                out_lines.append(imp)
            out_lines.append("")
            out_lines.append(f"public class {class_name} {{")
            out_lines.append(f"  {method['annotation']}")
            for sig_line in method["signature"]:
                out_lines.append(f"  {sig_line.rstrip()}")
            for body_line in method["body"]:
                out_lines.append(f"  {body_line.rstrip()}")
            out_lines.append("}")

            out_content = "\n".join(out_lines) + "\n"

            out_filename = f"{mname}.java"
            out_path = os.path.join(dir_path, out_filename)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(out_content)
            total_methods += 1

        if total_dirs % 100 == 0:
            print(f"  Processed {total_dirs} classes, {total_methods} methods...")

    print(f"\nDone! Created {total_dirs} directories with {total_methods} method files.")
    print(f"Output: {DST_DIR}")


if __name__ == "__main__":
    main()
