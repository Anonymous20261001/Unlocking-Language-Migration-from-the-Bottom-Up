"""
Fill Python test stubs from PythonJavadoc_splitted_method with translated
Java Randoop test bodies from new_Java_test_cases.
Output: PythonJavadoc_test_cases/{Class}/{method}_test_{N}.py
"""

import csv, re, os
from pathlib import Path
from collections import defaultdict

# Try to use javalang; fall back to regex if not available
try:
    import javalang
    from javalang import tree as J
    HAS_JAVALANG = True
except ImportError:
    HAS_JAVALANG = False

BASE = Path("/root/autodl-tmp/Java2Python")
PY_SKEL_DIR = BASE / "PythonJavadoc_splitted_method"
JAVA_TEST_DIR = BASE / "new_Java_test_cases"
OUTPUT_DIR = BASE / "PythonJavadoc_test_cases"
CSV_PATH = BASE / "Javadoc_randoop_list_1754.csv"

# ── Method name mapping from Python wrapper ──────────────────────────

def build_method_map(py_src: str) -> dict:
    """Parse Python wrapper class -> {JavaName: python_name}."""
    mm = {}
    for m in re.finditer(r"^\s*def\s+(\w+)\s*\(", py_src, re.MULTILINE):
        py = m.group(1)
        if py.startswith("_") and not py.startswith("__"):
            continue
        mm[py] = py
        java = re.sub(r"_([a-z])", lambda x: x.group(1).upper(), py)
        if java != py:
            mm[java] = py
    # dunder bridges
    for dunder, java_name in [("__str__", "toString"), ("__eq__", "equals"),
                               ("__hash__", "hashCode"), ("__len__", "size")]:
        if f"def {dunder}" in py_src:
            mm[java_name] = dunder
    return mm

_STD = {"toString": "__str__", "hashCode": "__hash__", "equals": "__eq__",
        "getClass": "__class__", "size": "__len__", "finalize": "__del__"}
_ASSERT = {"assertTrue", "assertFalse", "assertEquals", "assertNotNull",
           "assertNull", "assertArrayEquals", "assertSame", "assertNotSame",
           "assertThat", "fail"}

def py_method(java_name: str, mmap: dict) -> str:
    if java_name in _ASSERT:
        return java_name
    if java_name in _STD:
        return _STD[java_name]
    if java_name in mmap:
        return mmap[java_name]
    # fallback: camelCase → snake_case
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", java_name).lower()
    if s in mmap.values():
        return s
    return s

# ── Regex-based Java → Python translation ───────────────────────────

def fqn_simple(s: str) -> str:
    return re.sub(r"<.*?>", "", s).split(".")[-1]

def translate_expr(expr: str, mmap: dict) -> str:
    """Translate a Java expression to Python."""
    expr = expr.strip()

    # Literals
    if expr == "null": return "None"
    if expr == "true": return "True"
    if expr == "false": return "False"
    if re.match(r"^-?\d+(\.\d+)?[dDfFLl]?$", expr):
        return re.sub(r"[dDfFLl]$", "", expr)
    if re.match(r"^(-?\d+\.?\d*[eE][+-]?\d+)[dDfF]?$", expr):
        return re.sub(r"[dDfF]$", "", expr)
    if re.match(r"^'.'$", expr):
        return f"ord({expr})" if len(expr) == 3 else expr
    if re.match(r'^".*"$', expr):
        return expr

    # Cast: (Type) expr
    m = re.match(r"^\((\w+)\)\s*(.+)$", expr)
    if m:
        cast_type, inner = m.group(1), m.group(2)
        if cast_type in ("int", "long", "short", "byte"):
            return f"int({translate_expr(inner, mmap)})"
        if cast_type in ("float", "double"):
            return f"float({translate_expr(inner, mmap)})"
        return translate_expr(inner, mmap)

    # new Type(args)
    m = re.match(r"^new\s+([\w.]+)\s*\(([^)]*)\)$", expr)
    if m:
        cls = fqn_simple(m.group(1))
        args = ", ".join(translate_expr(a.strip(), mmap) for a in m.group(2).split(",") if a.strip())
        return f"{cls}({args})"

    # new Type[] { ... } or new byte[] { ... }
    m = re.match(r"^new\s+(\w+)\s*\[\]\s*\{([^}]*)\}$", expr)
    if m:
        type_name, items = m.group(1), m.group(2)
        if type_name == "byte":
            vals = [translate_expr(v.strip(), mmap) for v in items.split(",") if v.strip()]
            return f"bytes([{', '.join(vals)}])"
        vals = [translate_expr(v.strip(), mmap) for v in items.split(",") if v.strip()]
        return f"[{', '.join(vals)}]"

    # new Type[size]
    m = re.match(r"^new\s+([\w.]+)\s*\[([^\]]+)\]$", expr)
    if m:
        return "[]"

    # Method call: obj.method(args) or Class.method(args)
    m = re.match(r"^([\w.]+)\.(\w+)\(([^)]*)\)$", expr)
    if m:
        qualifier, method, args_str = m.group(1), m.group(2), m.group(3)
        # FQCN static call: java.lang.Math.abs(...)
        if "." in qualifier and qualifier[0].islower():
            # It's a FQCN — just use the class name
            pass
        py_m = py_method(method, mmap)
        if py_m == "__class__":
            return f"type({translate_expr(qualifier, mmap)})"
        args = ", ".join(translate_expr(a.strip(), mmap) for a in args_str.split(",") if a.strip())
        recv = translate_expr(qualifier, mmap) if qualifier else ""
        if recv:
            return f"{recv}.{py_m}({args})"
        else:
            return f"{py_m}({args})"

    # Binary ops
    for op in ["==", "!=", "<=", ">=", "<", ">", "&&", "||", "+", "-", "*", "/", "%"]:
        parts = expr.split(f" {op} ")
        if len(parts) == 2:
            l, r = translate_expr(parts[0].strip(), mmap), translate_expr(parts[1].strip(), mmap)
            if op == "&&": return f"({l} and {r})"
            if op == "||": return f"({l} or {r})"
            return f"{l} {op} {r}"

    # Variable reference
    if re.match(r"^[a-zA-Z_]\w*$", expr):
        return expr

    return expr  # fallback


def translate_assert(stmt: str, mmap: dict) -> str:
    """Translate org.junit.Assert.xxx() → self.assertXxx()"""
    stmt = stmt.strip().rstrip(";")

    # Assert.assertTrue(msg, cond) or Assert.assertTrue(cond)
    m = re.search(r"Assert\.assertTrue\((.+)\)$", stmt)
    if m:
        args = _split_top_level(m.group(1))
        if len(args) >= 2:
            return f"self.assertTrue({translate_expr(args[1], mmap)}, {translate_expr(args[0], mmap)})"
        return f"self.assertTrue({translate_expr(args[0], mmap)})"

    m = re.search(r"Assert\.assertFalse\((.+)\)$", stmt)
    if m:
        args = _split_top_level(m.group(1))
        if len(args) >= 2:
            return f"self.assertFalse({translate_expr(args[1], mmap)}, {translate_expr(args[0], mmap)})"
        return f"self.assertFalse({translate_expr(args[0], mmap)})"

    m = re.search(r"Assert\.assertEquals\((.+)\)$", stmt)
    if m:
        args = _split_top_level(m.group(1))
        if len(args) == 2:
            return f"self.assertEqual({translate_expr(args[1], mmap)}, {translate_expr(args[0], mmap)})"
        if len(args) >= 3:
            return f"self.assertEqual({translate_expr(args[2], mmap)}, {translate_expr(args[1], mmap)}, {translate_expr(args[0], mmap)})"

    m = re.search(r"Assert\.assertNotNull\((.+)\)$", stmt)
    if m:
        return f"self.assertIsNotNone({translate_expr(m.group(1), mmap)})"

    m = re.search(r"Assert\.assertNull\((.+)\)$", stmt)
    if m:
        return f"self.assertIsNone({translate_expr(m.group(1), mmap)})"

    m = re.search(r"Assert\.assertArrayEquals\((.+)\)$", stmt)
    if m:
        args = _split_top_level(m.group(1))
        if len(args) == 2:
            return f"self.assertEqual(list({translate_expr(args[0], mmap)}), list({translate_expr(args[1], mmap)}))"
        if len(args) >= 3:
            return f"self.assertEqual(list({translate_expr(args[1], mmap)}), list({translate_expr(args[2], mmap)}), {translate_expr(args[0], mmap)})"

    m = re.search(r"Assert\.fail\((.+)\)$", stmt)
    if m:
        return f"self.fail({translate_expr(m.group(1), mmap)})"

    return f"# UNTRANSLATED: {stmt}"


def _split_top_level(s: str) -> list:
    """Split top-level comma-separated args."""
    parts, cur, depth = [], [], 0
    in_str, in_chr = False, False
    for ch in s:
        if in_str:
            cur.append(ch)
            if ch == '"' and (len(cur) < 2 or cur[-2] != '\\'):
                in_str = False
        elif in_chr:
            cur.append(ch)
            if ch == "'" and (len(cur) < 2 or cur[-2] != '\\'):
                in_chr = False
        elif ch == '"': cur.append(ch); in_str = True
        elif ch == "'": cur.append(ch); in_chr = True
        elif ch in '([<': depth += 1; cur.append(ch)
        elif ch in ')]>': depth -= 1; cur.append(ch)
        elif ch == ',' and depth == 0:
            parts.append(''.join(cur).strip()); cur = []
        else: cur.append(ch)
    if cur: parts.append(''.join(cur).strip())
    return parts


def translate_java_body(java_code: str, mmap: dict) -> list[str]:
    """Translate Java test method body → list of Python statement lines."""
    if HAS_JAVALANG:
        return _translate_with_javalang(java_code, mmap)
    return _translate_with_regex(java_code, mmap)


def _translate_with_javalang(java_code: str, mmap: dict) -> list[str]:
    """Use javalang AST for translation."""
    try:
        tree = javalang.parse.parse(java_code)
    except Exception:
        return _translate_with_regex(java_code, mmap)

    for _, node in tree:
        if isinstance(node, J.MethodDeclaration):
            method = node
            break
    else:
        return []

    lines = []
    for stmt in (method.body or []):
        lines.extend(_trans_stmt(stmt, mmap, 2))
    return lines


def _is_literal_str(node) -> bool:
    """Check if node is a string literal."""
    if isinstance(node, J.Literal):
        v = node.value
        return isinstance(v, str) and v.startswith('"')
    return False


def _get_type_name(node) -> str:
    """Extract simple class name from a javalang type node (ReferenceType/BasicType)."""
    if node is None:
        return "object"
    if isinstance(node, J.BasicType):
        return node.name
    if isinstance(node, J.ReferenceType):
        # Get the deepest sub_type's name, or the main name
        cur = node
        while cur.sub_type:
            cur = cur.sub_type
        return cur.name if cur.name else "object"
    return fqn_simple(str(node))


def _is_raw_non_string(node) -> bool:
    """Check if node is a simple variable, number, or boolean — not a string and not an expression."""
    if isinstance(node, J.Literal):
        v = node.value
        if isinstance(v, str) and v.startswith('"'):
            return False  # it IS a string
        return True  # number, char, boolean
    if isinstance(node, J.MemberReference):
        return True  # simple variable
    if isinstance(node, bool) or isinstance(node, (int, float)):
        return True
    return False  # complex expression — don't wrap

def _trans_stmt(stmt, mmap: dict, indent: int) -> list[str]:
    pre = "    " * indent
    if stmt is None:
        return [f"{pre}pass"]

    t = type(stmt).__name__

    if t == "LocalVariableDeclaration":
        out = []
        for d in stmt.declarators:
            init = _trans_expr_jl(d.initializer, mmap) if d.initializer else "None"
            out.append(f"{pre}{d.name} = {init}")
        return out

    if t == "StatementExpression":
        return _trans_stmt_expr(stmt.expression, mmap, indent)

    if t == "TryStatement":
        return _trans_try(stmt, mmap, indent)

    if t == "IfStatement":
        cond = _trans_expr_jl(stmt.condition, mmap)
        out = [f"{pre}if {cond}:"]
        for s in (stmt.then_statement or []):
            if isinstance(s, J.BlockStatement):
                for bs in s.statements:
                    out.extend(_trans_stmt(bs, mmap, indent + 1))
            else:
                out.extend(_trans_stmt(s, mmap, indent + 1))
        if stmt.else_statement:
            out.append(f"{pre}else:")
            if isinstance(stmt.else_statement, J.BlockStatement):
                for bs in stmt.else_statement.statements:
                    out.extend(_trans_stmt(bs, mmap, indent + 1))
            else:
                out.extend(_trans_stmt(stmt.else_statement, mmap, indent + 1))
        return out

    if t == "BlockStatement":
        out = []
        for s in stmt.statements:
            out.extend(_trans_stmt(s, mmap, indent))
        return out

    return [f"{pre}# ?{t}"]


def _trans_stmt_expr(expr, mmap: dict, indent: int) -> list[str]:
    pre = "    " * indent
    if isinstance(expr, J.MethodInvocation):
        method = expr.member
        if method in _ASSERT:
            return [f"{pre}{_trans_assert_jl(expr, mmap)}"]
    return [f"{pre}{_trans_expr_jl(expr, mmap)}"]


def _trans_assert_jl(node: J.MethodInvocation, mmap: dict) -> str:
    method = node.member
    args = [_trans_expr_jl(a, mmap) for a in (node.arguments or [])]

    if method == "assertTrue":
        if len(args) == 1: return f"self.assertTrue({args[0]})"
        return f"self.assertTrue({args[1]}, {args[0]})"
    if method == "assertFalse":
        if len(args) == 1: return f"self.assertFalse({args[0]})"
        return f"self.assertFalse({args[1]}, {args[0]})"
    if method == "assertEquals":
        if len(args) == 2: return f"self.assertEqual({args[1]}, {args[0]})"
        if len(args) >= 3: return f"self.assertEqual({args[2]}, {args[1]}, {args[0]})"
    if method == "assertNotNull":
        return f"self.assertIsNotNone({args[0]})"
    if method == "assertNull":
        return f"self.assertIsNone({args[0]})"
    if method == "assertArrayEquals":
        if len(args) == 2: return f"self.assertEqual(list({args[0]}), list({args[1]}))"
        if len(args) >= 3: return f"self.assertEqual(list({args[1]}), list({args[2]}), {args[0]})"
    if method == "fail":
        msg = args[0] if args else "''"
        return f"self.fail({msg})"
    return f"# UNTRANSLATED {method}: {args}"


def _trans_expr_jl(node, mmap: dict) -> str:
    if node is None: return "None"
    if isinstance(node, str): return node
    if isinstance(node, bool): return "True" if node else "False"
    if isinstance(node, (int, float)): return str(node)

    t = type(node).__name__

    if t == "Literal":
        v = node.value
        if v == "null": return "None"
        if v == "true": return "True"
        if v == "false": return "False"
        if isinstance(v, str):
            v = re.sub(r"[lLdDfF]$", "", v)
        return str(v)

    if t == "MemberReference":
        return node.member

    if t == "ClassReference":
        return fqn_simple(str(node.type))

    if t == "BinaryOperation":
        l = _trans_expr_jl(node.operandl, mmap)
        r = _trans_expr_jl(node.operandr, mmap)
        op = node.operator
        if op == "&&": return f"({l} and {r})"
        if op == "||": return f"({l} or {r})"
        # String concatenation: wrap leaf non-string operands in str()
        if op == "+":
            l_raw = _is_raw_non_string(node.operandl)
            r_raw = _is_raw_non_string(node.operandr)
            # One side must be a string literal for this to be string concat
            has_str = _is_literal_str(node.operandl) or _is_literal_str(node.operandr)
            if has_str:
                if l_raw: l = f"str({l})"
                if r_raw: r = f"str({r})"
        return f"{l} {op} {r}"

    if t == "MethodInvocation":
        method = node.member
        py_m = py_method(method, mmap)
        args = ", ".join(_trans_expr_jl(a, mmap) for a in (node.arguments or []))
        if node.qualifier:
            recv = _trans_expr_jl(node.qualifier, mmap)
            if py_m == "__class__":
                return f"type({recv})"
            # Strip FQCN to short class name for static calls
            recv_short = fqn_simple(recv) if "." in recv else recv
            return f"{recv_short}.{py_m}({args})"
        return f"{py_m}({args})"

    if t == "ClassCreator":
        cls = _get_type_name(node.type)
        args = ", ".join(_trans_expr_jl(a, mmap) for a in (node.arguments or []))
        return f"{cls}({args})"

    if t == "ArrayCreator":
        init = node.initializer
        if init and hasattr(init, 'initializers'):
            vals = ", ".join(_trans_expr_jl(a, mmap) for a in init.initializers)
            return f"[{vals}]"
        return "[]"

    if t == "Cast":
        cast_type = str(node.type)
        inner = _trans_expr_jl(node.expression, mmap)
        if cast_type in ("int", "long", "short", "byte"):
            return f"int({inner})"
        if cast_type in ("float", "double"):
            return f"float({inner})"
        return inner

    if t == "TernaryExpression":
        cond = _trans_expr_jl(node.condition, mmap)
        t_val = _trans_expr_jl(node.if_true, mmap)
        f_val = _trans_expr_jl(node.if_false, mmap)
        return f"({t_val} if {cond} else {f_val})"

    if t == "ArraySelector":
        arr = _trans_expr_jl(node.expression, mmap)
        idx = _trans_expr_jl(node.index, mmap)
        return f"{arr}[{idx}]"

    if t == "Assignment":
        return f"{_trans_expr_jl(node.expressionl, mmap)} = {_trans_expr_jl(node.value, mmap)}"

    return f"_UNTRANSLATED_{t}_"


def _trans_try(stmt: J.TryStatement, mmap: dict, indent: int) -> list[str]:
    pre = "    " * indent
    body = list(stmt.block or [])
    catches = list(stmt.catches or [])

    # Randoop expected-exception pattern: body ends with Assert.fail()
    is_randoop = False
    if body:
        last = body[-1]
        if (isinstance(last, J.StatementExpression) and
            isinstance(last.expression, J.MethodInvocation) and
            last.expression.member == "fail"):
            is_randoop = True

    if is_randoop and catches:
        out = [f"{pre}with self.assertRaises(Exception):"]
        inner = body[:-1]
        if inner:
            for s in inner:
                out.extend(_trans_stmt(s, mmap, indent + 1))
        else:
            out.append(f"{pre}    pass")
        return out

    out = [f"{pre}try:"]
    for s in body:
        out.extend(_trans_stmt(s, mmap, indent + 1))
    for catch in catches:
        out.append(f"{pre}except Exception:")
        if not catch.block:
            out.append(f"{pre}    pass  # Expected exception")
        else:
            for s in catch.block:
                out.extend(_trans_stmt(s, mmap, indent + 1))
    return out


def _translate_with_regex(java_code: str, mmap: dict) -> list[str]:
    """Fallback: translate Java body with regex."""
    lines = []
    # Extract the method body
    m = re.search(r"public\s+\w+\s+\w+\s*\([^)]*\)\s*throws\s+\w+\s*\{(.*)\}\s*$",
                  java_code, re.DOTALL)
    if not m:
        return ["    pass"]
    body = m.group(1).strip()
    for stmt in re.split(r";\s*\n", body):
        stmt = stmt.strip()
        if not stmt: continue

        # Variable declaration: Type name = expr
        vm = re.match(r"([\w.]+(?:<.*?>)?(?:\[\])?)\s+(\w+)\s*=\s*(.+)$", stmt)
        if vm:
            init = translate_expr(vm.group(3), mmap)
            lines.append(f"        {vm.group(2)} = {init}")
            continue

        # Assert call
        if "Assert." in stmt or "assert" in stmt.lower():
            lines.append(f"        {translate_assert(stmt, mmap)}")
            continue

        # Other
        lines.append(f"        {translate_expr(stmt, mmap)}")

    return lines if lines else ["        pass"]


# ── File processing ──────────────────────────────────────────────────

def get_indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def fill_one(py_file: Path, java_file: Path) -> str:
    """Fill Java test body into Python skeleton. Returns the filled Python code."""
    py_code = py_file.read_text(encoding="utf-8")
    java_code = java_file.read_text(encoding="utf-8")

    # Build method map from Python wrapper class
    mmap = build_method_map(py_code)

    # Translate Java body
    body_lines = translate_java_body(java_code, mmap)
    if not body_lines:
        body_lines = ["        pass"]

    # Find the test function and replace its body
    py_lines = py_code.split("\n")
    test_func_pattern = re.compile(r"def\s+(?:test_)?(\w+_test_(\d+))\s*\(")

    out_lines = []
    i = 0
    replaced = False
    while i < len(py_lines):
        line = py_lines[i]
        m = test_func_pattern.search(line)
        if m and not replaced:
            name = m.group(1)
            base_indent = get_indent(line)
            func_indent = "    " * (base_indent // 4 + 1)

            # Write function signature
            out_lines.append(line)
            i += 1

            # Determine the function body indent (signature indent + 4)
            body_indent = base_indent + 4

            # Write new body
            for bl in body_lines:
                out_lines.append(bl)

            # Skip old body: skip all lines with indent > base_indent (the old function body)
            while i < len(py_lines):
                stripped = py_lines[i].strip()
                cur_indent = get_indent(py_lines[i])
                if stripped == "":
                    i += 1
                elif cur_indent > base_indent:
                    i += 1  # This is part of the old body, skip it
                else:
                    break  # Back to class-level or top-level indent
            replaced = True
        else:
            out_lines.append(line)
            i += 1

    return "\n".join(out_lines)


def main():
    # Read wanted mapping
    wanted = {}
    with open(CSV_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            norm = {}
            for k, v in row.items():
                norm[k.strip().lstrip('﻿').strip()] = v.strip() if v else ''
            fn = norm.get('文件名', '')
            cls = fn.replace('.java', '')
            num = norm.get('测试编号', '')
            wanted.setdefault(cls, {} )[num] = norm.get('方法名', '')

    total = sum(len(v) for v in wanted.values())
    print(f"目标: {total} 个方法, {len(wanted)} 个类")
    print(f"Python骨架: {PY_SKEL_DIR}")
    print(f"Java测试: {JAVA_TEST_DIR}")
    print(f"输出: {OUTPUT_DIR}")
    print(f"javalang: {'可用' if HAS_JAVALANG else '仅regex'}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ok, missing_py, missing_java, err = 0, 0, 0, 0

    for cls_name in sorted(wanted):
        out_dir = OUTPUT_DIR / cls_name
        out_dir.mkdir(parents=True, exist_ok=True)

        for num, method_name in wanted[cls_name].items():
            func_name = f"{method_name}_test_{num}"
            py_file = PY_SKEL_DIR / cls_name / f"{func_name}.py"
            java_file = JAVA_TEST_DIR / cls_name / f"{func_name}.java"

            out_file = out_dir / f"{func_name}.py"

            if not py_file.exists():
                missing_py += 1; continue
            if not java_file.exists():
                missing_java += 1; continue

            try:
                result = fill_one(py_file, java_file)
                out_file.write_text(result, encoding="utf-8")
                ok += 1
            except Exception as e:
                err += 1
                if err <= 5:
                    print(f"  ERR {cls_name}/{func_name}: {e}")

        if ok % 200 == 0:
            print(f"  [{ok}/{total}] ok={ok} missing_py={missing_py} missing_java={missing_java} err={err}")

    print(f"\n{'='*60}")
    print(f"完成! ok={ok} missing_py={missing_py} missing_java={missing_java} err={err}")
    print(f"输出: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
