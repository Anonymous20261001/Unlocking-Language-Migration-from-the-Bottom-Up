#!/usr/bin/env python3
"""
Translate Java Randoop regression test cases into Python stub function bodies.

Reads migration_mapping.csv to find Java-Python file pairs, parses each Java
test method, translates the behavior (setup, method calls, assertions) to
equivalent Python code, and fills in the stub function body.

Usage:
  python translate_tests.py [--dry-run] [--limit N] [--class CLS] [-v]
  python translate_tests.py --restore   # restore all stubs from zip first
"""

import csv, re, sys, argparse
from pathlib import Path

# ---- paths ----------------------------------------------------------------
BASE = Path("/root/autodl-tmp/api_translation")
JAVA_DIR = BASE / "Java_test_cases4python"
PY_DIR = BASE / "PythonAPI_splitted_method"
MAPPING_CSV = BASE / "migration_mapping.csv"

stats = {"processed": 0, "assertions": 0, "no_assert": 0, "errors": 0, "skipped": 0}

# ==========================================================================
# 1. Method-name mapping (Python wrapper class -> Java names)
# ==========================================================================

def camel_to_snake(name: str) -> str:
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
    return s.lower()

def build_method_map(py_src: str) -> dict:
    """Parse Python class and return {JavaName: python_name}."""
    mm = {}
    for m in re.finditer(r"^\s*def\s+(\w+)\s*\(", py_src, re.MULTILINE):
        py = m.group(1)
        if py.startswith("_") and not py.startswith("__"):
            continue
        mm[py] = py  # python name -> itself
        # java-style camelCase version
        java = re.sub(r"_([a-z])", lambda x: x.group(1).upper(), py)
        if java != py:
            mm[java] = py
    # dunder bridges
    if re.search(r"def\s+__str__", py_src):   mm["toString"] = "__str__"
    if re.search(r"def\s+__eq__", py_src):    mm["equals"] = "__eq__"
    if re.search(r"def\s+__hash__", py_src):  mm["hashCode"] = "__hash__"
    if re.search(r"def\s+__len__", py_src):   mm["size"] = "__len__"
    return mm

# module-level cache, set per file
_METHOD_MAP = {}

# Hardcoded Java→Python method name mappings (stdlib Java→Pythonic equivalents)
_STANDARD_MAP = {
    "toString": "__str__",
    "hashCode": "__hash__",
    "equals": "__eq__",
    "getClass": "__class__",  # handled before method calls, but safety
    "size": "__len__",
    "clone": "clone",  # no standard Python equivalent
    "finalize": "__del__",
}

def py_method(java_name: str) -> str:
    """Look up Python method name, with fallback heuristic."""
    if java_name in _STANDARD_MAP:
        return _STANDARD_MAP[java_name]
    if java_name in _METHOD_MAP:
        return _METHOD_MAP[java_name]
    snake = camel_to_snake(java_name)
    if snake in _METHOD_MAP.values():
        return snake
    return snake

# ==========================================================================
# 2. Expression translator
# ==========================================================================

def fqn_simple(fqn: str) -> str:
    """java.util.zip.Adler32 -> Adler32"""
    return re.sub(r"<.*?>", "", fqn).split(".")[-1]

def _match_paren(s: str, start: int) -> int:
    """Return index of ) that closes the ( at start."""
    d = 0
    for i in range(start, len(s)):
        if s[i] == "(":   d += 1
        elif s[i] == ")":
            d -= 1
            if d == 0: return i
    return -1

def _match_brace(s: str, start: int) -> int:
    """Return index of } that closes { at start."""
    d = 0
    for i in range(start, len(s)):
        if s[i] == "{":   d += 1
        elif s[i] == "}":
            d -= 1
            if d == 0: return i
    return -1

def _split_args(s: str) -> list[str]:
    """Split comma-separated args respecting nested parens/strings."""
    parts = []; cur = ""; depth = 0; in_str = False; sc = None
    for ch in s:
        if in_str:
            cur += ch
            if ch == sc and (len(cur) < 2 or cur[-2] != "\\"): in_str = False
        elif ch == '"':
            in_str = True; sc = ch; cur += ch
        elif ch == "(":
            depth += 1; cur += ch
        elif ch == ")":
            depth -= 1; cur += ch
        elif ch == "," and depth == 0:
            parts.append(cur.strip()); cur = ""
        else:
            cur += ch
    if cur.strip(): parts.append(cur.strip())
    return parts

def translate_expr(expr: str) -> str:
    """Recursively translate a Java expression to Python.

    Order matters:
    1. Strip casts
    2. Translate 'new' (BEFORE method calls — otherwise FQN constructors
       like 'new javax.ATR()' are confused with method calls on package names)
    3. Translate method calls
    4. Translate literals and other patterns
    """
    expr = expr.strip()
    if not expr:
        return expr

    # --- Step 1: strip all Java casts globally ---
    # Order matters: special patterns first, then general removal.
    # (int)'c' -> ord('c')   [MUST be before generic (int) removal]
    expr = re.sub(r"\(int\)\s*'([^'])'", lambda m: str(ord(m.group(1))), expr)
    # (char)N -> chr(N)
    expr = re.sub(r"\(char\)\s*(\d+)", r"chr(\1)", expr)
    # FQN reference casts: (java.lang.Object), (foo.bar.SomeType<G>)
    expr = re.sub(r"\([\w.]+(?:\.[\w]+)+(?:<[^>]*>)?\)\s*", "", expr)
    # Single-word class-name casts: (Object), (String), (ATR) — start with uppercase
    expr = re.sub(r"\([A-Z]\w*(?:<[^>]*>)?\)\s*", "", expr)
    # Primitive numeric casts: (int), (short), (byte), (long) — remove
    expr = re.sub(r"\((?:int|short|byte|long)\)\s*", "", expr)
    # (float)/(double) on a numeric literal: just strip the cast
    expr = re.sub(r"\((?:float|double)\)\s*(\d+\.?\d*)", r"\1", expr)
    # clean up extra spaces
    expr = re.sub(r"\s{2,}", " ", expr).strip()

    # --- Step 2: translate 'new' expressions FIRST ---
    # This must happen before method-call translation so that
    # 'new javax.smartcardio.ATR(byteArray0)' becomes 'ATR(byteArray0)'
    # and isn't mistaken for a method call on package 'javax.smartcardio'.

    # new byte[] {}
    if re.fullmatch(r"new\s+byte\s*\[\s*\]\s*\{\s*\}", expr):
        return 'b""'
    # new byte[] {vals}
    m = re.fullmatch(r"new\s+byte\s*\[\s*\]\s*\{([^}]*)\}", expr)
    if m:
        inner = m.group(1).strip()
        return f"bytes([{translate_expr(inner)}])" if inner else 'b""'
    # new SomeType[] {}
    if re.fullmatch(r"new\s+([\w.]+)\s*\[\s*\]\s*\{\s*\}", expr):
        return "[]"
    # new SomeType[] {vals}
    m = re.fullmatch(r"new\s+([\w.]+)\s*\[\s*\]\s*\{([^}]*)\}", expr)
    if m:
        return f"[{translate_expr(m.group(2).strip())}]"
    # new ClassName(args) — handles generics in class name
    # e.g. new java.util.ArrayList<Foo>(100) → ArrayList(100)
    m = re.match(r"new\s+([\w.]+(?:<[^>]*>)?)\s*\(", expr)
    if m:
        cls = fqn_simple(m.group(1))  # fqn_simple strips generics and gets last segment
        paren_start = m.end() - 1  # position of (
        close = _match_paren(expr, paren_start)
        if close != -1:
            args = expr[paren_start + 1:close].strip()
            return f"{cls}({translate_expr(args)})" if args else f"{cls}()"

    # --- Step 3: .getClass() -> type(x) (BEFORE method calls, so it's not
    #             treated as a method call on a variable) ---
    expr = re.sub(r"(\w+)\.getClass\(\)", r"type(\1)", expr)

    # --- Step 4: translate method calls ---
    expr = _translate_method_calls(expr)

    # --- Step 5: literals ---
    expr = re.sub(r"\bnull\b", "None", expr)
    expr = re.sub(r"\btrue\b", "True", expr)
    expr = re.sub(r"\bfalse\b", "False", expr)
    expr = re.sub(r"(\d+)L\b", r"\1", expr)
    expr = re.sub(r"(\d+\.\d+)[fFdD]\b", r"\1", expr)
    expr = re.sub(r"'([^'])'", r'"\1"', expr)   # char literal

    # --- Step 6: FQN static fields (java.math.BigInteger.ONE -> BigInteger.ONE) ---
    # Step 2 already handles 'new pkg.Cls<T>(args)' -> 'Cls(args)'.
    # For anything remaining: only match pkg.pkg.Cls.FIELD (3+ segments).
    expr = re.sub(
        r"(?<!\bnew\s)([a-z_]\w*\.[a-z_]\w*\.[\w.]+)\.([A-Z_][A-Za-z_0-9]*)",
        lambda m: f"{fqn_simple(m.group(1))}.{m.group(2)}",
        expr
    )

    return expr


def _translate_method_calls(expr: str) -> str:
    """Find and translate all obj.method(args) patterns with balanced parens.

    Handles both instance calls (aTR1.equals(x)) and static calls
    (java.lang.Boolean.compare(x, y)).
    """
    result = []
    i = 0
    while i < len(expr):
        # Look for <receiver>.<method>(
        # receiver can be: simple_var, obj.field, pkg.Class (multi-segment FQN)
        m = re.search(r"(\w[\w.]*)\.(\w+)\s*\(", expr[i:])
        if not m:
            result.append(expr[i:])
            break

        result.append(expr[i:i + m.start()])
        receiver = m.group(1)
        method = m.group(2)
        paren_start = i + m.end() - 1

        close = _match_paren(expr, paren_start)
        if close == -1:
            result.append(expr[i + m.start():])
            i = len(expr)
            break

        args_str = expr[paren_start + 1:close]
        translated_args = ", ".join(
            translate_expr(a) for a in _split_args(args_str)
        ) if args_str.strip() else ""

        # Simplify receiver if it looks like a FQN package.Class
        # Criteria: contains dot AND last segment starts with uppercase
        if "." in receiver:
            parts = receiver.split(".")
            if parts[-1] and parts[-1][0].isupper():
                # This is pkg.pkg.ClassName — simplify to ClassName
                receiver = parts[-1]

        py_m = py_method(method)
        result.append(f"{receiver}.{py_m}({translated_args})")
        i = close + 1

    return "".join(result)


# ==========================================================================
# 3. Statement translator
# ==========================================================================

def translate_stmt(line: str) -> str:
    """Translate one Java statement (no trailing ;) to Python."""
    line = line.strip()
    if not line:
        return ""

    # comments
    if line.startswith("//"):
        return f"# {line[2:].strip()}"

    # assertions
    if "org.junit.Assert." in line:
        return _translate_assert(line)

    # try {
    if line.rstrip() == "try {":
        return "try:"

    # } catch (Ex e) {
    m = re.match(r"\}\s*catch\s*\(([\w.]+)\s+(\w+)\)\s*\{", line)
    if m:
        return "except Exception:"

    # } alone
    if line == "}":
        return ""

    # variable declaration: [Type] varName = expr
    m = re.match(
        r"(?:[\w.]+(?:<[^>]*>)?(?:\s*\[\s*\])?\s+)"  # type
        r"(\w+)\s*=\s*(.+)",                           # name = expr
        line
    )
    if m:
        var = m.group(1)
        rhs = m.group(2)
        return f"{var} = {translate_expr(rhs)}"

    # bare method call or anything else
    return translate_expr(line)


def _translate_assert(line: str) -> str:
    """Translate org.junit.Assert.X(...) to Python assert statement."""
    m = re.search(r"org\.junit\.Assert\.(\w+)\s*\((.+)\)\s*;?\s*$", line, re.DOTALL)
    if not m:
        return f"# UNTRANSLATED: {line}"

    kind = m.group(1)
    args_str = m.group(2).strip()
    parts = _split_args(args_str)

    def e(s): return translate_expr(s)

    def m(s): return _translate_msg(s)  # message translator
    def v(s): return translate_expr(s)  # value/condition translator

    if kind == "assertTrue":
        if len(parts) == 1: return f"assert {v(parts[0])}"
        return f"assert {v(parts[1])}, {m(parts[0])}"

    if kind == "assertFalse":
        if len(parts) == 1: return f"assert not ({v(parts[0])})"
        return f"assert not ({v(parts[1])}), {m(parts[0])}"

    if kind == "assertEquals":
        if len(parts) == 2:
            exp = v(parts[0]); act = v(parts[1])
            return f"assert {act} == {exp}, f'{{{act}}} != {{{exp}}}'"
        if len(parts) >= 3:
            exp = v(parts[1]); act = v(parts[2])
            return f"assert {act} == {exp}, {m(parts[0])}"

    if kind == "assertNotNull":
        return f"assert {v(parts[0])} is not None"

    if kind == "assertNull":
        return f"assert {v(parts[0])} is None"

    if kind == "assertArrayEquals":
        if len(parts) == 2:
            a = v(parts[0]); b = v(parts[1])
            return f"assert list({a}) == list({b}), f'{{list({a})}} != {{list({b})}}'"
        if len(parts) >= 3:
            a = v(parts[1]); b = v(parts[2])
            return f"assert list({a}) == list({b}), {m(parts[0])}"

    if kind == "assertSame":
        if len(parts) == 2:
            return f"assert {v(parts[1])} is {v(parts[0])}"
        if len(parts) >= 3:
            return f"assert {v(parts[2])} is {v(parts[1])}, {m(parts[0])}"

    if kind == "assertNotSame":
        if len(parts) == 2:
            return f"assert {v(parts[1])} is not {v(parts[0])}"
        if len(parts) >= 3:
            return f"assert {v(parts[2])} is not {v(parts[1])}, {m(parts[0])}"

    if kind == "fail":
        return f"assert False, {m(parts[0])}" if parts else "assert False, 'Expected exception'"

    return f"# UNTRANSLATED ASSERT ({kind}): {line}"


def _fix_concat(msg: str) -> str:
    """Convert Java-style string concatenation to Python f-string.

    "'" + var + "' != '" + val + "'"  →  f"'{var}' != '{val}'"

    Works on the ORIGINAL Java expression (before general translate_expr).
    """
    msg = msg.strip()
    if msg.startswith('f"') or msg.startswith("f'"):
        return msg
    if not msg.startswith('"') or "+" not in msg:
        return msg  # simple string, no concat

    # Split on " + " (not inside string literals)
    # This is a Java string concat expression like:
    #   "'" + var + "' != '" + value + "'"
    # We need to convert to: f"'{var}' != '{value}'"
    tokens = re.split(r'\s*\+\s*', msg)
    result_parts = []
    for tok in tokens:
        tok = tok.strip()
        if tok.startswith('"') and tok.endswith('"'):
            # String literal: extract content
            result_parts.append(tok[1:-1])
        elif tok.startswith("'") and tok.endswith("'"):
            # Char literal: extract content  (after Java-to-Python: 'x' -> "x")
            result_parts.append(tok[1:-1])
        else:
            # Variable or expression: translate then interpolate
            result_parts.append("{" + translate_expr(tok) + "}")
    return 'f"' + "".join(result_parts) + '"'


def _translate_msg(msg: str) -> str:
    """Translate a Java assertion message string to Python.

    Handles string concatenation and literal translation.
    """
    msg = msg.strip()
    # If it's a simple string, just translate it
    if msg.startswith('"') and "+" not in msg:
        return msg
    # If it has concatenation, convert to f-string
    if "+" in msg:
        return _fix_concat(msg)
    # Otherwise, translate as expression
    return translate_expr(msg)


# ==========================================================================
# 4. Full test-body translator
# ==========================================================================

def _split_java_stmts(body: str) -> list[str]:
    """Split Java source into logical statements."""

    def _split_try_catch(block: str) -> list[str]:
        m = re.match(r"try\s*\{(.+)\}\s*catch\s*\([^)]+\)\s*\{(.*)\}\s*$", block, re.DOTALL)
        if not m:
            return [block]
        lines = ["try {"]

        # try body: split on ; respecting nested {} and strings
        try_body = m.group(1).strip()
        for stmt in _split_on_semicolons(try_body):
            lines.append("    " + stmt.strip())

        lines.append("} catch (Exception e) {")

        catch_body = m.group(2).strip()
        for stmt in _split_on_semicolons(catch_body):
            stmt = stmt.strip()
            if stmt and not stmt.startswith("//"):
                lines.append("    " + stmt)

        lines.append("}")
        return lines

    def _split_on_semicolons(text: str) -> list[str]:
        """Split on ; respecting nested {} and strings."""
        stmts = []; cur = ""; depth = 0; in_str = False; sc = None
        for ch in text:
            if in_str:
                cur += ch
                if ch == sc and (len(cur) < 2 or cur[-2] != "\\"): in_str = False
            elif ch == '"':
                in_str = True; sc = ch; cur += ch
            elif ch == "{":
                depth += 1; cur += ch
            elif ch == "}":
                depth -= 1; cur += ch
            elif ch == ";" and depth == 0:
                if cur.strip(): stmts.append(cur.strip())
                cur = ""
            else:
                cur += ch
        if cur.strip(): stmts.append(cur.strip())
        return stmts

    # Phase 1: coalesce try-catch blocks into single items
    items = []
    i = 0
    chars = list(body)
    buf = ""; depth = 0
    while i < len(body):
        ch = body[i]
        if ch == "{" and "try" in buf and buf.strip().endswith("try"):
            # entered try block
            close = _match_brace(body, i)
            if close == -1:
                buf += ch; i += 1; continue
            # check if followed by catch
            after = body[close + 1:].lstrip()
            if after.startswith("catch"):
                # find catch block
                cm = re.match(r"catch\s*\([^)]+\)\s*\{", after)
                if cm:
                    catch_open = close + 1 + len(after[:cm.end()])
                    catch_close = _match_brace(body, catch_open)
                    if catch_close != -1:
                        block = body[i:catch_close + 1]
                        items.append(block)
                        i = catch_close + 1
                        buf = ""
                        continue
            buf += ch
        else:
            buf += ch
        i += 1

    if buf.strip():
        items.append(buf.strip())

    # Phase 2: split try-catch blocks into individual lines
    result = []
    for item in items:
        if item.startswith("try {"):
            result.extend(_split_try_catch(item))
        else:
            # split on semicolons
            for s in _split_on_semicolons(item):
                result.append(s)
    return result


def translate_body(java_body: str) -> list[str]:
    """Translate a Java method body to Python lines."""
    stmts = _split_java_stmts(java_body)
    out = []
    indent = 0
    for s in stmts:
        s = s.strip()
        if not s:
            continue
        if s == "}":
            indent = max(0, indent - 1)
            continue
        if s.endswith("{"):
            # Try-block opening
            inner = s[:-1].strip()
            if inner == "try":
                out.append("try:")
                indent += 1
                continue
        if s.startswith("} catch"):
            indent = max(0, indent - 1)
            out.append("except Exception:")
            indent += 1
            continue

        py = translate_stmt(s)
        if not py:
            continue
        out.append("    " * indent + py)

    if not out:
        out.append("pass")
    return out


# ==========================================================================
# 5. Python-file updater
# ==========================================================================

def extract_java_info(java_code: str) -> dict:
    """Extract test method name and body from a Java test file."""
    info = {"body": "", "test_method_name": ""}
    m = re.search(r"Randoop-generated regression test for\s+([\w.]+)\.(\w+)\(\)", java_code)
    if m:
        info["target_class"] = m.group(1)
        info["target_method"] = m.group(2)
    m = re.search(r"public\s+void\s+(\w+)\s*\(\s*\)\s*throws\s+Throwable\s*\{(.+)\}\s*$",
                  java_code, re.DOTALL)
    if m:
        info["test_method_name"] = m.group(1)
        info["body"] = m.group(2).strip()
    return info


def update_python(py_path: Path, java_info: dict, py_src: str, dry: bool) -> bool:
    """Fill in the test function body in one Python stub file."""
    global _METHOD_MAP
    _METHOD_MAP = build_method_map(py_src)

    test_name = java_info.get("test_method_name", "")
    if not test_name:
        return False

    # Extract test number for fallback matching
    tn_match = re.search(r"_(\d+)$", test_name)
    test_num = tn_match.group(1) if tn_match else ""

    # find function definition — use balanced-paren matching for params
    def _find_func(name_pat: str) -> tuple[str, str, int] | None:
        """Return (func_name, params, start_pos) or None."""
        for m in re.finditer(rf"def\s+({name_pat})\s*\(", py_src):
            func_nm = m.group(1)
            paren_start = m.end() - 1
            close = _match_paren(py_src, paren_start)
            if close == -1:
                continue
            params_str = py_src[paren_start + 1:close]
            # check for optional -> return_type : after close
            after = py_src[close + 1:].lstrip()
            # skip optional -> type annotation
            if after.startswith("->"):
                # strip -> Type annotation (e.g. "-> None:", "-> str:")
                after = re.sub(r"^->\s*[^:\s]+\s*", "", after).lstrip()
            if after.startswith(":"):
                return (func_nm, params_str, m.start())
        return None

    # Try exact name match
    result = _find_func(rf"(?:test_)?{re.escape(test_name)}")
    # fallback: function containing the test number
    if not result and test_num:
        result = _find_func(rf"\w*{test_num}")
    # fallback: any function with _test_ or _NNNN pattern
    if not result:
        result = _find_func(r"\w*(?:_test_)?\d+")
    if not result:
        return False

    func_name, params, func_start = result

    # find end of function
    remainder = py_src[func_start:]
    end_m = re.search(r"\n(?=def\s+|class\s+)", remainder[1:])
    func_end = func_start + end_m.start() + 1 if end_m else len(py_src)

    # translate body
    py_body = translate_body(java_info.get("body", ""))

    # build new function
    new_func = f"def {func_name}({params}):\n"
    for line in py_body:
        new_func += f"    {line}\n" if line.strip() else "\n"
    new_func += "\n"

    new_src = py_src[:func_start] + new_func + py_src[func_end:]

    if not dry:
        py_path.write_text(new_src, encoding="utf-8")
    return True


# ==========================================================================
# 6. Main loop
# ==========================================================================

def process_row(row: dict, dry: bool) -> bool:
    cls = row["class_name"]
    jf = row["java_file"]
    pf = row["python_file"]

    if row["status"] != "migrate":
        stats["skipped"] += 1
        return False

    jp = JAVA_DIR / cls / jf
    pp = PY_DIR / cls / pf
    if not jp.exists() or not pp.exists():
        stats["errors"] += 1
        return False

    try:
        jcode = jp.read_text(encoding="utf-8")
        pcode = pp.read_text(encoding="utf-8")
    except Exception:
        stats["errors"] += 1
        return False

    jinfo = extract_java_info(jcode)
    if not jinfo.get("body"):
        stats["errors"] += 1
        return False

    ok = update_python(pp, jinfo, pcode, dry)
    if not ok:
        stats["errors"] += 1
        return False

    stats["processed"] += 1
    if "org.junit.Assert" in jinfo["body"]:
        stats["assertions"] += 1
    else:
        stats["no_assert"] += 1
    return True


def main():
    ap = argparse.ArgumentParser(description="Translate Java tests -> Python stubs")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--class", dest="cls")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--restore", action="store_true",
                    help="Restore stubs from zip before running")
    args = ap.parse_args()

    if args.restore:
        import subprocess
        subprocess.run(["unzip", "-o", str(BASE / "PythonAPI_splitted_method.zip"),
                        "-d", str(BASE)], check=False)

    if not MAPPING_CSV.exists():
        print(f"Mapping not found: {MAPPING_CSV}"); sys.exit(1)

    with open(MAPPING_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if args.cls:
        rows = [r for r in rows if r["class_name"] == args.cls]
    if args.limit:
        rows = rows[:args.limit]

    migrating = [r for r in rows if r["status"] == "migrate"]
    creating = [r for r in rows if r["status"] == "create_new"]
    print(f"Migrate: {len(migrating)}  create_new: {len(creating)}  "
          f"({'DRY RUN' if args.dry_run else 'LIVE'})")

    for i, r in enumerate(migrating):
        if i % 250 == 0:
            print(f"  [{i}/{len(migrating)}] done={stats['processed']} err={stats['errors']}")
        ok = process_row(r, dry=args.dry_run)
        if not ok and args.verbose:
            print(f"  FAIL: {r['class_name']}/{r['java_file']}")

    print(f"\nDone. processed={stats['processed']} with_assert={stats['assertions']} "
          f"no_assert={stats['no_assert']} errors={stats['errors']} skipped={stats['skipped']}")
    if args.dry_run:
        print("[DRY RUN - no files modified]")


if __name__ == "__main__":
    main()
