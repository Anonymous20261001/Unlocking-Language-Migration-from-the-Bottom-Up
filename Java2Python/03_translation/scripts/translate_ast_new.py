#!/usr/bin/env python3
"""
AST-based Java → Python test translator using javalang.

Parses Java Randoop test methods with javalang's AST and emits equivalent
Python code for the stub function body. Handles try-catch, generics, casts,
and all JUnit assertion patterns correctly.

Extended to handle:
- Java_benchmark files (with PascalCase naming, no existing Python stubs)
- Java_test_cases4python files (with existing stubs, snake_case naming)
- Creating new Python files from sibling mock code when stubs don't exist

Usage:
  python translate_ast_new.py [--dry-run] [--limit N] [--class CLS] [-v]
  python translate_ast_new.py --benchmark-missing FILE  # translate benchmark-only files
  python translate_ast_new.py --test4py-missing         # translate the 94 missing from test4python
"""

import csv, re, sys, argparse, keyword
import ast as _pyast
from pathlib import Path
from collections import defaultdict
import javalang
from javalang import tree as J

BASE = Path("/root/autodl-tmp/Java2Python")
API_BASE = Path("/root/autodl-tmp/api_translation")
JAVA_DIR = BASE / "Java_test_cases4python"
JAVA_BENCH_DIR = API_BASE / "Java_benchmark"
PY_DIR = BASE / "PythonAPI_splitted_method"
MAPPING_CSV = BASE / "Java_test_cases4python" / "_generation_record.csv"

stats = {"ok": 0, "assert": 0, "no_assert": 0, "try_catch": 0, "err": 0, "skip": 0, "created": 0}
err_detail = defaultdict(int)

# ═══════════════════════════════════════════════════════════════════════════
# Method name mapping
# ═══════════════════════════════════════════════════════════════════════════

_STD = {"toString": "__str__", "hashCode": "__hash__", "equals": "__eq__",
        "getClass": "__class__", "size": "__len__", "finalize": "__del__"}
_ASSERT = {"assertTrue", "assertFalse", "assertEquals", "assertNotNull",
           "assertNull", "assertArrayEquals", "assertSame", "assertNotSame",
           "assertThat", "fail"}
_MMAP = {}

def build_mmap(src: str):
    _MMAP.clear()
    for m in re.finditer(r"^\s*def\s+(\w+)\s*\(", src, re.MULTILINE):
        py = m.group(1)
        if py.startswith("_") and not py.startswith("__"): continue
        _MMAP[py] = py
        java = re.sub(r"_([a-z])", lambda x: x.group(1).upper(), py)
        if java != py: _MMAP[java] = py
        # trailing-underscore convention for keyword-colliding methods:
        # def and_() serves Java and(), def xor_() serves Java xor(), ...
        if py.endswith("_") and not py.endswith("__"):
            base = py[:-1]
            _MMAP.setdefault(base, py)
            java_b = re.sub(r"_([a-z])", lambda x: x.group(1).upper(), base)
            _MMAP.setdefault(java_b, py)
    for dunder, java in [("__str__","toString"), ("__eq__","equals"),
                          ("__hash__","hashCode"), ("__len__","size")]:
        if f"def {dunder}" in src: _MMAP[java] = dunder

def py_method(java: str) -> str:
    if java in _ASSERT: return java  # NEVER rename assertion methods
    if java in _STD: return _STD[java]
    if java in _MMAP: return _MMAP[java]
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", java).lower()
    if s in _MMAP.values(): return s
    if keyword.iskeyword(s): return s + "_"  # .not() / .and() / .or() are syntax errors
    return s

# ═══════════════════════════════════════════════════════════════════════════
# Expression translator
# ═══════════════════════════════════════════════════════════════════════════

def _last_type_name(t) -> str:
    """Walk ReferenceType chain to get simple class name."""
    if t is None: return "Object"
    if isinstance(t, J.BasicType): return t.name
    if isinstance(t, J.ReferenceType):
        cur, last = t, t.name
        while cur.sub_type: cur = cur.sub_type; last = cur.name
        return last
    return str(t)

def _simple(s: str) -> str:
    """java.util.ArrayList → ArrayList"""
    return re.sub(r"<.*?>", "", s).split(".")[-1]

def _wrap(node, s: str) -> str:
    """Apply Java unary prefix operators javalang attaches to the node.

    javalang parses -1 as Literal(value='1', prefix_operators=['-']); reading
    only .value silently drops the sign, so every branch must funnel through
    this helper."""
    for op in reversed(getattr(node, "prefix_operators", None) or []):
        if op == "-": s = f"-{s}"
        elif op == "!": s = f"not ({s})"
        elif op == "~": s = f"~{s}"
        # unary '+' is a no-op
    return s

def _char_ord(expr):
    """Return the numeric value of a (possibly cast-nested) Java char literal, else None."""
    while isinstance(expr, J.Cast) and not (getattr(expr, "prefix_operators", None) or []):
        expr = expr.expression
    if isinstance(expr, J.Literal):
        v = expr.value
        if isinstance(v, str) and len(v) >= 3 and v.startswith("'") and v.endswith("'"):
            try:
                c = _pyast.literal_eval(v)
            except Exception:
                return None
            if isinstance(c, str) and len(c) == 1:
                n = ord(c)
                for op in (getattr(expr, "prefix_operators", None) or []):
                    if op == "-": n = -n
                    elif op == "~": n = ~n
                return n
    return None

def trans_expr(node) -> str:
    """Recursive expression translator."""
    # -- primitives / null / strings --
    if node is None: return "None"
    if isinstance(node, str):
        return _simple(node) if "." in node else node
    if isinstance(node, bool): return "True" if node else "False"
    if isinstance(node, (int, float)): return str(node)

    # -- Literal --
    if isinstance(node, J.Literal):
        v = node.value
        if v == "null": return "None"
        if v == "true": return _wrap(node, "True")
        if v == "false": return _wrap(node, "False")
        if isinstance(v, str):
            # long suffix: 10L, 0x1FL (hex digits keep their trailing d/f)
            if re.fullmatch(r'(?:0[xX][0-9a-fA-F_]+|\d[\d_]*)[lL]', v):
                return _wrap(node, v[:-1])
            # float/double suffix on decimal forms, incl. scientific: 1.0f, 2.14E9f, 10f, 100.f
            if re.fullmatch(r'(?:\d[\d_]*\.?[\d_]*|\.[\d_]+)(?:[eE][+-]?\d+)?[fFdD]', v):
                return _wrap(node, v[:-1])
        return _wrap(node, str(v))

    # -- MemberReference (variable name) --
    if isinstance(node, J.MemberReference):
        m = node.member
        if keyword.iskeyword(m): m += "_"  # FileDescriptor.in → in_ (keeps file parseable)
        return _wrap(node, m)

    # -- ClassReference (e.g. in static field access) --
    if isinstance(node, J.ClassReference):
        return _wrap(node, _last_type_name(node.type))

    # -- BinaryOperation --
    if isinstance(node, J.BinaryOperation):
        l = trans_expr(node.operandl); r = trans_expr(node.operandr); op = node.operator
        if op == "==": return f"{l} == {r}"
        if op == "!=": return f"{l} != {r}"
        if op == "&&": return f"({l} and {r})"
        if op == "||": return f"({l} or {r})"
        return f"{l} {op} {r}"

    # -- MethodInvocation --
    if isinstance(node, J.MethodInvocation):
        method = node.member
        py = py_method(method)
        args = ", ".join(trans_expr(a) for a in (node.arguments or []))
        if node.qualifier:
            recv = trans_expr(node.qualifier)
            if py == "__class__":
                # Java x.getClass() returns the Class object; x.__class__() would
                # construct a new instance — type(x) is the faithful equivalent
                return _wrap(node, f"type({recv})")
            return _wrap(node, f"{recv}.{py}({args})")
        return _wrap(node, f"{py}({args})")

    # -- ClassCreator (new Foo(args)) --
    if isinstance(node, J.ClassCreator):
        cls = _last_type_name(node.type)
        args = ", ".join(trans_expr(a) for a in (node.arguments or []))
        return _wrap(node, f"{cls}({args})")

    # -- ArrayCreator (new Type[] {vals}) --
    if isinstance(node, J.ArrayCreator):
        # initializer is an ArrayInitializer with .initializers list
        init = node.initializer
        init_list = init.initializers if isinstance(init, J.ArrayInitializer) else init
        is_empty = not init_list or (isinstance(init_list, (list, tuple)) and len(init_list) == 0)
        type_name = _last_type_name(node.type) if node.type else ""

        if is_empty:
            if type_name == "byte":
                return 'b""'
            return "[]"

        vals = ", ".join(trans_expr(a) for a in init_list)
        if type_name == "byte":
            return f"bytes([{vals}])"
        return f"[{vals}]"

    # -- Cast --
    if isinstance(node, J.Cast):
        cast_type = _last_type_name(node.type)
        if cast_type in ("int", "long", "short", "byte", "float", "double"):
            # (int)'a' → 97 : Java chars are numeric under a numeric cast
            ch = _char_ord(node.expression)
            if ch is not None:
                s = f"{float(ch)}" if cast_type in ("float", "double") else str(ch)
                return _wrap(node, s)
        inner = trans_expr(node.expression)
        if cast_type in ("int", "long", "short", "byte"):
            # For numeric casts on numerics, just return the inner value
            if node.expression and isinstance(node.expression, (J.Literal, int)):
                return _wrap(node, inner)
            if node.expression and isinstance(node.expression, J.Cast):
                return _wrap(node, inner)  # nested numeric casts collapse
            return _wrap(node, f"int({inner})")
        if cast_type in ("float", "double"):
            return _wrap(node, f"float({inner})")
        if cast_type == "char" and re.fullmatch(r"\d+", inner):
            return _wrap(node, f"chr({inner})")  # (char) 97 → chr(97)
        # reference cast: no-op
        return _wrap(node, inner)

    # -- TernaryExpression --
    if isinstance(node, J.TernaryExpression):
        return f"({trans_expr(node.if_true)} if {trans_expr(node.condition)} else {trans_expr(node.if_false)})"

    # -- ArraySelector (arr[idx]) --
    if isinstance(node, J.ArraySelector):
        return f"{trans_expr(node.expression)}[{trans_expr(node.index)}]"

    # -- Assignment (in expression context) --
    if isinstance(node, J.Assignment):
        return f"{trans_expr(node.expressionl)} = {trans_expr(node.value)}"

    # untranslatable construct: emit a bare name so the file still parses and
    # the test errors honestly with NameError instead of hiding the gap
    return f"_UNTRANSLATED_{type(node).__name__}"


# ═══════════════════════════════════════════════════════════════════════════
# Statement translator
# ═══════════════════════════════════════════════════════════════════════════

def trans_stmt(stmt, indent: int = 0) -> list[str]:
    """Return list of (unindented) Python source lines."""
    pre = "    " * indent

    # ── LocalVariableDeclaration ──
    if isinstance(stmt, J.LocalVariableDeclaration):
        out = []
        for d in stmt.declarators:
            init = trans_expr(d.initializer) if d.initializer else "None"
            out.append(f"{pre}{d.name} = {init}")
        return out

    # ── StatementExpression (method call, assertion, assignment) ──
    if isinstance(stmt, J.StatementExpression):
        return _trans_stmt_expr(stmt, indent)

    # ── TryStatement ──
    if isinstance(stmt, J.TryStatement):
        return _trans_try(stmt, indent)

    # ── IfStatement ──
    if isinstance(stmt, J.IfStatement):
        out = [f"{pre}if {trans_expr(stmt.condition)}:"]
        for s in (stmt.then_statement or []):
            if isinstance(s, J.BlockStatement):
                for bs in s.statements: out.extend(trans_stmt(bs, indent + 1))
            else:
                out.extend(trans_stmt(s, indent + 1))
        if stmt.else_statement:
            out.append(f"{pre}else:")
            if isinstance(stmt.else_statement, J.BlockStatement):
                for bs in stmt.else_statement.statements: out.extend(trans_stmt(bs, indent + 1))
            else:
                out.extend(trans_stmt(stmt.else_statement, indent + 1))
        return out

    # ── BlockStatement ──
    if isinstance(stmt, J.BlockStatement):
        out = []
        for s in stmt.statements: out.extend(trans_stmt(s, indent))
        return out

    # ── ReturnStatement ──
    if isinstance(stmt, J.ReturnStatement):
        return [f"{pre}return {trans_expr(stmt.expression)}" if stmt.expression else f"{pre}return"]

    # ── ThrowStatement ──
    if isinstance(stmt, J.ThrowStatement):
        return [f"{pre}raise {trans_expr(stmt.expression)}"]

    # ── AssertStatement ──
    if isinstance(stmt, J.AssertStatement):
        return [f"{pre}assert {trans_expr(stmt.condition)}"]

    # ── SynchronizedStatement ──
    if isinstance(stmt, J.SynchronizedStatement):
        out = [f"{pre}# synchronized({trans_expr(stmt.lock)})"]
        for s in (stmt.block or []): out.extend(trans_stmt(s, indent))
        return out

    return [f"{pre}# ?{type(stmt).__name__}"]


def _trans_stmt_expr(stmt: J.StatementExpression, indent: int) -> list[str]:
    """Handle a StatementExpression — may be an assertion or a bare call."""
    pre = "    " * indent
    expr = stmt.expression

    # Check if this is a JUnit assertion call
    if isinstance(expr, J.MethodInvocation):
        qual = expr.qualifier or ""
        method = expr.member
        if method in _ASSERT and ("Assert" in str(qual) or "Assert" in method):
            return [_trans_assert(expr, pre)]

    # Regular expression statement
    return [f"{pre}{trans_expr(expr)}"]


def _trans_assert(node: J.MethodInvocation, pre: str) -> str:
    """Translate JUnit assertion to Python assert."""
    method = node.member
    args = [trans_expr(a) for a in (node.arguments or [])]

    def _split_concat(msg):
        """Split a Java concat chain on top-level '+' only (never inside string literals)."""
        parts, cur, i, q = [], "", 0, None
        while i < len(msg):
            c = msg[i]
            if q:
                cur += c
                if c == "\\" and i + 1 < len(msg):
                    cur += msg[i + 1]; i += 1
                elif c == q:
                    q = None
            elif c in "\"'":
                q = c; cur += c
            elif c == "+":
                parts.append(cur.strip()); cur = ""
            else:
                cur += c
            i += 1
        parts.append(cur.strip())
        return [p for p in parts if p]

    def _fstr(msg):
        """Convert Java concat to f-string."""
        msg = msg.strip()
        if msg.startswith('f"') or msg.startswith("f'"): return msg
        if "+" not in msg: return msg
        parts = []
        for t in _split_concat(msg):
            if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
                text = t[1:-1]
                # literal text inside an f-string: double the braces. Quotes inside
                # Java string content are already backslash-escaped — leave them.
                parts.append(text.replace("{", "{{").replace("}", "}}"))
            else:
                parts.append("{" + t + "}")
        return 'f"' + "".join(parts) + '"'

    def a(i): return args[i] if i < len(args) else "None"
    def msg(i): return _fstr(args[i]) if i < len(args) else "''"

    if method == "assertTrue":
        if len(args) == 1: return f"{pre}assert {a(0)}"
        return f"{pre}assert {a(1)}, {msg(0)}"

    if method == "assertFalse":
        if len(args) == 1: return f"{pre}assert not ({a(0)})"
        return f"{pre}assert not ({a(1)}), {msg(0)}"

    if method == "assertEquals":
        if len(args) == 2: return f"{pre}assert {a(1)} == {a(0)}, f'{{{a(1)}}} != {{{a(0)}}}'"
        if len(args) >= 3: return f"{pre}assert {a(2)} == {a(1)}, {msg(0)}"

    if method == "assertNotNull":
        return f"{pre}assert {a(0)} is not None"

    if method == "assertNull":
        return f"{pre}assert {a(0)} is None"

    if method == "assertArrayEquals":
        if len(args) == 2: return f"{pre}assert list({a(0)}) == list({a(1)}), f'{{list({a(0)})}} != {{list({a(1)})}}'"
        if len(args) >= 3: return f"{pre}assert list({a(1)}) == list({a(2)}), {msg(0)}"

    if method == "assertSame":
        if len(args) >= 2: return f"{pre}assert {a(1)} is {a(0)}"

    if method == "assertNotSame":
        if len(args) >= 2: return f"{pre}assert {a(1)} is not {a(0)}"

    if method == "fail":
        return f"{pre}assert False, {msg(0) if args else repr('Expected exception')}"

    return f"{pre}# UNTRANSLATED {method}: {args}"


def _is_fail_stmt(s) -> bool:
    """True for `org.junit.Assert.fail(...)` statements."""
    return (isinstance(s, J.StatementExpression)
            and isinstance(s.expression, J.MethodInvocation)
            and s.expression.member == "fail"
            and "Assert" in (s.expression.qualifier or ""))


def _trans_try(stmt: J.TryStatement, indent: int) -> list[str]:
    """Translate try-catch.

    Randoop's expected-exception pattern (try body ends with Assert.fail and
    every catch block is empty) becomes a flag check: ANY exception counts as
    the expected behavior, but no exception must FAIL the test. A plain
    `except Exception:` around `assert False` would swallow the AssertionError
    (unlike Java, where fail()'s AssertionError is an Error the specific catch
    never captures) and make the test unfailable."""
    pre = "    " * indent
    body = list(stmt.block or [])
    catches = list(stmt.catches or [])
    randoop = (body and _is_fail_stmt(body[-1]) and catches
               and all(not c.block for c in catches) and not stmt.finally_block)

    if randoop:
        out = [f"{pre}_raised = False", f"{pre}try:"]
        inner = body[:-1]
        if inner:
            for s in inner:
                out.extend(trans_stmt(s, indent + 1))
        else:
            out.append(f"{pre}    pass")
        out.append(f"{pre}except Exception:")
        out.append(f"{pre}    _raised = True  # any exception matches Java's observed behavior")
        out.append(f"{pre}assert _raised, 'Expected exception'")
        return out

    out = [f"{pre}try:"]
    for s in body:
        if _is_fail_stmt(s):
            out.append(f"{pre}    assert False, 'Expected exception'")
            continue
        out.extend(trans_stmt(s, indent + 1))
    if catches:
        # let the fail-marker's AssertionError escape the broad handler below
        out.append(f"{pre}except AssertionError:")
        out.append(f"{pre}    raise")
    for catch in catches:
        out.append(f"{pre}except Exception:")
        if not catch.block:
            out.append(f"{pre}    pass  # Expected exception")
        else:
            for s in catch.block:
                out.extend(trans_stmt(s, indent + 1))

    if stmt.finally_block:
        out.append(f"{pre}finally:")
        for s in stmt.finally_block:
            out.extend(trans_stmt(s, indent + 1))

    return out


# ═══════════════════════════════════════════════════════════════════════════
# Full method translator
# ═══════════════════════════════════════════════════════════════════════════

def _fix_paren_neg(src: str) -> str:
    """Rewrite (-1) → -1 before parsing.

    javalang silently drops the unary minus of a *parenthesized* negative
    numeric literal — `(-1)` parses to Literal(value='1', prefix_operators=[])
    while bare `-1` keeps its sign. Randoop wraps every negative literal in
    parens, so strip the paren pair (blank the two separator chars, positions
    of all other tokens unchanged)."""
    try:
        toks = list(javalang.tokenizer.tokenize(src))
    except Exception:
        return src
    offs, total = [], 0
    for ln in src.splitlines(keepends=True):
        offs.append(total); total += len(ln)
    def apos(tok):
        return offs[tok.position[0] - 1] + tok.position[1] - 1
    s = list(src)
    for i in range(len(toks) - 3):
        t0, t1, t2, t3 = toks[i], toks[i + 1], toks[i + 2], toks[i + 3]
        if (t0.value == '(' and t1.value == '-' and t3.value == ')'
                and type(t2).__name__.endswith(('Integer', 'FloatingPoint'))):
            s[apos(t0)] = ' '
            s[apos(t3)] = ' '
    return ''.join(s)


def translate_body(java_code: str) -> list[str]:
    """Return Python body lines (indented with 4 spaces)."""
    try:
        tree = javalang.parse.parse(java_code)
    except Exception:
        return []

    for _, node in tree:
        if isinstance(node, J.MethodDeclaration):
            method = node
            break
    else:
        return []

    lines = []
    for stmt in (method.body or []):
        lines.extend(trans_stmt(stmt, 1))  # indent=1: body is inside function

    if not lines:
        lines.append("    pass")
    return lines


# ═══════════════════════════════════════════════════════════════════════════
# Python-file updater
# ═══════════════════════════════════════════════════════════════════════════

def _match_paren(s: str, start: int) -> int:
    d = 0
    for i in range(start, len(s)):
        if s[i] == "(": d += 1
        elif s[i] == ")":
            d -= 1
            if d == 0: return i
    return -1

def update_python(py_path: Path, java_code: str, py_src: str, dry: bool) -> str:
    """Fill the test-function body only; mocks are never touched.
    Returns '' on success, else a reason string (caller exposes it)."""
    build_mmap(py_src)
    java_code = _fix_paren_neg(java_code)

    # extract java method name
    try:
        tree = javalang.parse.parse(java_code)
    except Exception:
        return "java_parse"
    method_name = None
    for _, node in tree:
        if isinstance(node, J.MethodDeclaration):
            method_name = node.name; break
    if not method_name: return "java_parse"

    tn = re.search(r"_(\d+)$", method_name)
    tn = tn.group(1) if tn else ""

    # find Python function
    def find_func(pat):
        for m in re.finditer(rf"def\s+({pat})\s*\(", py_src):
            nm = m.group(1); ps = m.end() - 1
            cl = _match_paren(py_src, ps)
            if cl == -1: continue
            after = py_src[cl + 1:].lstrip()
            if after.startswith("->"): after = re.sub(r"^->\s*[^:\s]+\s*", "", after).lstrip()
            if after.startswith(":"):
                params = py_src[ps + 1:cl]
                return (nm, params, m.start())
        return None

    r = find_func(rf"(?:test_)?{re.escape(method_name)}")
    if not r and tn: r = find_func(rf"\w*{tn}")
    if not r: r = find_func(r"\w*(?:_test_)?\d+")
    if not r: return "no_py_func"

    fname, params, fstart = r

    # function end
    rem = py_src[fstart:]
    em = re.search(r"\n(?=def\s+|class\s+)", rem[1:])
    fend = fstart + em.start() + 1 if em else len(py_src)

    # translate
    body = translate_body(java_code)
    if not body: return "empty_body"

    new_func = f"def {fname}({params.strip()}):\n"
    for line in body:
        new_func += f"{line}\n" if line.strip() else "\n"
    new_func += "\n"

    new_src = py_src[:fstart] + new_func + py_src[fend:]

    if not dry:
        py_path.write_text(new_src, encoding="utf-8")

    if "try:" in new_func: stats["try_catch"] += 1
    return ""


# ═══════════════════════════════════════════════════════════════════════════
# New-file creation (for benchmark tests without Python stubs)
# ═══════════════════════════════════════════════════════════════════════════

def _is_skip_java(java_code: str) -> bool:
    """Detect Java files that Randoop didn't generate a real test for."""
    return ("No Randoop test found" in java_code
            or "Randoop did not generate" in java_code
            or "TODO: Randoop" in java_code)

def _get_sibling_mock(class_dir: Path) -> str | None:
    """Extract mock/wrapper/importer code from an existing Python file in the same class.
    Returns everything before the first test-function definition."""
    py_files = sorted(class_dir.glob("*.py"))
    if not py_files:
        return None
    src = py_files[0].read_text(encoding="utf-8")
    # Find the first test function definition
    test_match = re.search(r"\n(def\s+(?:test_)?\w*(?:_test_\d+|_test\d+)?)\s*\(", src)
    if test_match:
        return src[:test_match.start()].rstrip() + "\n\n"
    # Fallback: find last non-test def and cut there
    defs = list(re.finditer(r"\ndef\s+(\w+)\s*\(", src))
    for m in reversed(defs):
        name = m.group(1)
        if not re.search(r'_test_\d+$|^test_', name):
            # This is a mock method, not a test — keep going back
            continue
        # Found first test function — cut before it
        return src[:m.start()].rstrip() + "\n\n"
    return src

def create_new_python_file(py_path: Path, java_method_name: str,
                           java_code: str, mock_code: str, dry: bool) -> str:
    """Create a new Python test file: mock code + translated test function.
    Returns '' on success, else a reason string."""
    body = translate_body(java_code)
    if not body:
        return "empty_body"

    # Use test_ prefix for the Python function name
    py_func_name = "test_" + java_method_name

    new_func = f"def {py_func_name}():\n"
    for line in body:
        new_func += f"{line}\n" if line.strip() else "\n"
    new_func += "\n"

    full_src = mock_code.rstrip() + "\n\n" + new_func.strip() + "\n"

    if not dry:
        py_path.parent.mkdir(parents=True, exist_ok=True)
        py_path.write_text(full_src, encoding="utf-8")
        stats["created"] += 1

    if "try:" in new_func:
        stats["try_catch"] += 1
    return ""


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def process_row(row, dry, verbose=False):
    if row["status"] != "migrate": stats["skip"] += 1; return True
    jp = JAVA_DIR / row["class_name"] / row["java_file"]
    pp = PY_DIR / row["class_name"] / row["python_file"]
    reason = ""
    if not jp.exists(): reason = "missing_java"
    elif not pp.exists(): reason = "missing_py"
    if not reason:
        try:
            jc = jp.read_text(encoding="utf-8"); pc = pp.read_text(encoding="utf-8")
        except Exception:
            reason = "read_fail"
    if not reason:
        reason = update_python(pp, jc, pc, dry)
    if reason:
        stats["err"] += 1; err_detail[reason] += 1
        if verbose: print(f"  ERR[{reason}] {row['class_name']}/{row['java_file']}")
        return False
    stats["ok"] += 1
    if "org.junit.Assert" in jc: stats["assert"] += 1
    else: stats["no_assert"] += 1
    return True

def translate_single(java_path: Path, py_path: Path, class_name: str,
                     dry: bool, java_source: str = "test4py") -> str:
    """Translate one Java file → Python. Handles existing stubs and new files.
    Returns '' on success, else reason string."""
    if not java_path.exists():
        return "missing_java"

    try:
        java_code = java_path.read_text(encoding="utf-8")
    except Exception:
        return "read_fail"

    # Skip Randoop-empty tests
    if _is_skip_java(java_code):
        stats["skip"] += 1
        return "randooped_skip"

    # Preprocess and parse
    java_code_fixed = _fix_paren_neg(java_code)
    try:
        tree = javalang.parse.parse(java_code_fixed)
    except Exception:
        return "java_parse"

    method_name = None
    for _, node in tree:
        if isinstance(node, J.MethodDeclaration):
            method_name = node.name; break
    if not method_name:
        return "java_parse"

    # Check test body is non-empty
    has_assert = "org.junit.Assert" in java_code or "Assert." in java_code

    if py_path.exists():
        # ── Existing Python stub: fill in the body ──
        try:
            py_src = py_path.read_text(encoding="utf-8")
        except Exception:
            return "read_fail"
        reason = update_python(py_path, java_code_fixed, py_src, dry)
        if not reason:
            stats["ok"] += 1
            if has_assert: stats["assert"] += 1
            else: stats["no_assert"] += 1
        return reason
    else:
        # ── No Python stub: create new file from sibling mock ──
        class_dir = PY_DIR / class_name
        if not class_dir.exists():
            return "no_class_dir"
        mock_code = _get_sibling_mock(class_dir)
        if not mock_code:
            return "no_sibling_mock"
        reason = create_new_python_file(py_path, method_name, java_code_fixed,
                                         mock_code, dry)
        if not reason:
            stats["ok"] += 1
            if has_assert: stats["assert"] += 1
            else: stats["no_assert"] += 1
        return reason


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--class", dest="cls")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--benchmark-missing", type=str,
                    help="File listing benchmark-only Java files missing Python (one per line: Class/file.java)")
    ap.add_argument("--test4py-missing", action="store_true",
                    help="Translate the 94 entries marked 'missing' in the _generation_record.csv")
    ap.add_argument("--legacy", action="store_true",
                    help="Run the original migration_mapping.csv pipeline")
    args = ap.parse_args()

    # ── Mode 1: Benchmark-only files (234: no Python stubs) ──
    if args.benchmark_missing:
        bench_list = Path(args.benchmark_missing)
        if not bench_list.exists():
            print(f"File not found: {bench_list}"); return
        entries = []
        with open(bench_list) as f:
            for line in f:
                line = line.strip()
                if not line: continue
                parts = line.split("/", 1)
                if len(parts) == 2:
                    entries.append((parts[0], parts[1]))
        if args.limit:
            entries = entries[:args.limit]
        if args.cls:
            entries = [(c, f) for c, f in entries if c == args.cls]

        print(f"Benchmark missing: {len(entries)}  ({'DRY' if args.dry_run else 'LIVE'})")
        for i, (cls, java_name) in enumerate(entries):
            if i % 50 == 0:
                print(f"  [{i}/{len(entries)}] ok={stats['ok']} err={stats['err']} "
                      f"created={stats['created']} skip={stats['skip']} tc={stats['try_catch']}")
            jp = JAVA_BENCH_DIR / cls / java_name
            py_name = java_name.replace(".java", ".py")
            pp = PY_DIR / cls / py_name
            reason = translate_single(jp, pp, cls, args.dry_run, "benchmark")
            if reason:
                stats["err"] += 1
                err_detail[reason] += 1
                if args.verbose:
                    print(f"  ERR[{reason}] {cls}/{java_name}")
        print(f"\nDone. ok={stats['ok']} assert={stats['assert']} no_assert={stats['no_assert']} "
              f"try_catch={stats['try_catch']} err={stats['err']} skip={stats['skip']} "
              f"created={stats['created']}")
        if stats["err"]:
            print("err breakdown: " + "  ".join(f"{k}={v}" for k, v in sorted(err_detail.items()) if v))
        if args.dry_run: print("[DRY RUN]")
        return

    # ── Mode 2: test4python missing (94: existing Python stubs) ──
    if args.test4py_missing:
        if not MAPPING_CSV.exists():
            print(f"CSV not found: {MAPPING_CSV}"); return
        entries = []
        # Fix CSV: \r in the middle of lines (Windows CR corruption)
        raw_text = MAPPING_CSV.read_bytes().decode("utf-8").replace("\r", "")
        lines = [l for l in raw_text.split("\n") if l]
        reader = csv.DictReader(lines)
        for row in reader:
            if row.get("python_file", "").strip() == "missing":
                entries.append(row)
        if args.limit:
            entries = entries[:args.limit]
        if args.cls:
            entries = [r for r in entries if r["class"] == args.cls]

        print(f"Test4py missing: {len(entries)}  ({'DRY' if args.dry_run else 'LIVE'})")
        for i, row in enumerate(entries):
            if i % 20 == 0:
                print(f"  [{i}/{len(entries)}] ok={stats['ok']} err={stats['err']} "
                      f"skip={stats['skip']} tc={stats['try_catch']}")
            cls = row["class"]
            java_name = f"{row['method']}_test_{row['number']}.java"
            jp = JAVA_DIR / cls / java_name
            py_name = java_name.replace(".java", ".py")
            pp = PY_DIR / cls / py_name
            reason = translate_single(jp, pp, cls, args.dry_run, "test4py")
            if reason:
                stats["err"] += 1
                err_detail[reason] += 1
                if args.verbose:
                    print(f"  ERR[{reason}] {cls}/{java_name}")
        print(f"\nDone. ok={stats['ok']} assert={stats['assert']} no_assert={stats['no_assert']} "
              f"try_catch={stats['try_catch']} err={stats['err']} skip={stats['skip']} "
              f"created={stats['created']}")
        if stats["err"]:
            print("err breakdown: " + "  ".join(f"{k}={v}" for k, v in sorted(err_detail.items()) if v))
        if args.dry_run: print("[DRY RUN]")
        return

    # ── Mode 3: Legacy migration_mapping.csv pipeline (original behavior) ──
    legacy_csv = API_BASE / "migration_mapping.csv"
    if not legacy_csv.exists():
        print("No migration_mapping.csv for legacy mode, and no --benchmark-missing or --test4py-missing flag.")
        print("Use --benchmark-missing FILE, --test4py-missing, or --legacy with a valid migration CSV.")
        return
    with open(legacy_csv, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f)]
    if args.cls: rows = [r for r in rows if r["class_name"] == args.cls]
    if args.limit: rows = rows[:args.limit]
    mig = [r for r in rows if r["status"] == "migrate"]
    print(f"Legacy migrate: {len(mig)}  ({'DRY' if args.dry_run else 'LIVE'})")
    for i, r in enumerate(mig):
        if i % 250 == 0:
            print(f"  [{i}/{len(mig)}] ok={stats['ok']} err={stats['err']} tc={stats['try_catch']}")
        ok = process_row(r, dry=args.dry_run, verbose=args.verbose)
    print(f"\nDone. ok={stats['ok']} assert={stats['assert']} no_assert={stats['no_assert']} "
          f"try_catch={stats['try_catch']} err={stats['err']} skip={stats['skip']}")
    if stats["err"]:
        print("err breakdown: " + "  ".join(f"{k}={v}" for k, v in sorted(err_detail.items()) if v))
    if args.dry_run: print("[DRY RUN]")

if __name__ == "__main__":
    main()
