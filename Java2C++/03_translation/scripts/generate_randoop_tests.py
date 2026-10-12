"""
Generate Randoop tests for ALL classes in JavaAPI_splitted_method, one test
file per wrapper method, preserving the RAW Randoop test body verbatim.

Approach (NOT the trimming approach in RANDOOP_EXTRACTION_LOGIC.md):
- Keep the full Randoop test body: fully-qualified names, all assertions,
  expected-exception try/catch blocks. Only `if (debug) ...` lines removed.
- Cross-class deps: wrapper imports (class B needed by class A's methods)
  are passed to Randoop via --classlist, with common interfaces mapped to
  concrete impls (Collection -> ArrayList, ...) so arguments are constructible.
- Type-aware attribution: a test is attributed to method m of target class A
  only if the receiver variable's declared type IS A (or a static call on A),
  so B.add() is never mis-attributed to A.add().
- One best test per wrapper method; output file names mirror the wrapper:
  Java_test_cases4python/{Class}/{method}_test_{number}.java

Resume-safe: already-generated files are skipped on re-run.
"""
import argparse, csv, os, re, shutil, signal, subprocess, sys, tempfile, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

# Paths: overridable via env for server deployment
RANDOOP_JAR = os.environ.get(
    "RANDOOP_JAR", "/Users/jeff/randoop/build/libs/randoop-all-4.3.4.jar")
JAVA_SPLIT = Path(os.environ.get(
    "JAVA_SPLIT", "/Users/jeff/PycharmProjects/JavaData/JavaAPI_splitted_method"))
OUTPUT_DIR = Path(os.environ.get(
    "OUTPUT_DIR", "/Users/jeff/PycharmProjects/Java_test_cases4python"))
LOG_FILE = OUTPUT_DIR / "_progress.log"
RECORD_CSV = OUTPUT_DIR / "_generation_record.csv"

TIME_LIMIT = 30        # seconds per Randoop mode
HARD_TIMEOUT = 90      # hard kill per Randoop invocation
OUTPUT_LIMIT = 200
MAXSIZE = 5
WORKERS = 4
MAX_HELPERS = 15

NOISE = {'equals', 'getClass', 'hashCode', 'toString', 'format', 'println',
         'assertTrue', 'assertFalse', 'assertEquals', 'assertNotNull',
         'assertArrayEquals', 'fail', 'out', 'err'}

# Classes whose test execution touches filesystem / network / GUI. With the
# sandbox-exec isolation below they are safe to run; kept here only for
# reference / optional --skip-dangerous.
DANGEROUS = {
    "FileAutoTest", "FileDescriptorAutoTest", "FileInputStreamAutoTest",
    "FileOutputStreamAutoTest", "FilePermissionAutoTest",
    "ProcessBuilderAutoTest", "SocketAutoTest", "SocketPermissionAutoTest",
    "InetSocketAddressAutoTest", "WebSocketHandshakeExceptionAutoTest",
    "SecurityManagerAutoTest", "URLClassLoaderAutoTest", "URLPermissionAutoTest",
    "ClipboardAutoTest", "TrayIconAutoTest",
    "DefaultDesktopManagerAutoTest",
    "BasicDesktopIconUIAutoTest", "BasicDesktopPaneUIAutoTest",
    "JDesktopPaneAutoTest", "MetalDesktopIconUIAutoTest",
    "MultiDesktopIconUIAutoTest", "MultiDesktopPaneUIAutoTest",
    "SynthDesktopIconUIAutoTest", "SynthDesktopPaneUIAutoTest",
    "PrintEventAutoTest", "PrintJobAttributeEventAutoTest",
    "PrintJobEventAutoTest", "PrintServiceAttributeEventAutoTest",
    "PrinterIOExceptionAutoTest", "PrinterInfoAutoTest",
    "PrinterLocationAutoTest", "PrinterMakeAndModelAutoTest",
    "PrinterMessageFromOperatorAutoTest", "PrinterMoreInfoAutoTest",
    "PrinterMoreInfoManufacturerAutoTest", "PrinterNameAutoTest",
    "PrinterResolutionAutoTest", "PrinterStateReasonsAutoTest",
    "PrinterURIAutoTest", "MediaPrintableAreaAutoTest",
}

# Interfaces that Randoop cannot instantiate -> concrete impls to add to the
# classlist so arguments of these types become constructible.
INTERFACE_IMPL = {
    "java.util.Collection": "java.util.ArrayList",
    "java.util.List": "java.util.ArrayList",
    "java.util.Set": "java.util.HashSet",
    "java.util.SortedSet": "java.util.TreeSet",
    "java.util.NavigableSet": "java.util.TreeSet",
    "java.util.Map": "java.util.HashMap",
    "java.util.SortedMap": "java.util.TreeMap",
    "java.util.NavigableMap": "java.util.TreeMap",
    "java.util.Queue": "java.util.ArrayDeque",
    "java.util.Deque": "java.util.ArrayDeque",
    "java.util.Iterator": "java.util.ArrayList",
    "java.util.Enumeration": "java.util.Vector",
}

_log_lock = Lock()


def log(msg):
    t = time.strftime("%H:%M:%S")
    line = f"[{t}] {msg}"
    with _log_lock:
        print(line, flush=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")


# ── Java wrapper analysis ──────────────────────────────────────────

def get_fqn(class_name):
    """Find the fully-qualified name of the API class under test."""
    d = JAVA_SPLIT / class_name
    if not d.is_dir():
        return None
    for f in sorted(d.glob("*.java")):
        content = f.read_text(errors="replace")
        m = re.search(r'new\s+([\w.]+)\s*\(', content)
        if not m:
            m = re.search(r'([\w.]+)\.\w+\s*\(', content)  # static-only classes
        if m:
            cn = m.group(1).split('.')[-1]
            for imp in re.findall(r'^import\s+([\w.]+);', content, re.MULTILINE):
                if imp.endswith("." + cn):
                    return imp
            return f"java.lang.{cn}"
    return None


def get_java_methods(class_name):
    """Return {test_number: (api_method_name, argc)} from wrapper files.
    argc distinguishes overloads (e.g. listIterator() vs listIterator(int));
    None when the wrapper call cannot be parsed."""
    d = JAVA_SPLIT / class_name
    if not d.is_dir():
        return {}
    info = {}
    for f in sorted(d.glob("*.java")):
        m = re.match(r'(\w+?)_test_(\d+)\.java$', f.name)
        if not m:
            continue
        name_from_file, num = m.group(1), m.group(2)
        content = f.read_text(errors="replace")
        cm = re.search(r'instance\.(\w+)\s*\(([^)]*)\)', content)
        if cm:
            args = cm.group(2).strip()
            info[num] = (cm.group(1), 0 if not args else args.count(',') + 1)
        else:
            info[num] = (name_from_file, None)
    return info


def get_helper_classes(class_name, api_fqn):
    """Wrapper imports = classes the API's methods need as arguments (class B).
    Interfaces are supplemented with concrete impls so Randoop can build them."""
    d = JAVA_SPLIT / class_name
    imports = set()
    for f in d.glob("*.java"):
        imports.update(re.findall(r'^import\s+([\w.]+);',
                                  f.read_text(errors="replace"), re.MULTILINE))
    api_short = api_fqn.split('.')[-1]
    helpers = []
    for imp in sorted(imports):
        if imp == api_fqn or imp.endswith('.' + api_short):
            continue
        if imp.startswith('java.lang.') or imp.startswith('org.junit'):
            continue
        if imp.startswith('java.util.function.'):   # lambdas: Randoop can't build
            continue
        helpers.append(imp)
        impl = INTERFACE_IMPL.get(imp)
        if impl and impl not in helpers and impl != api_fqn:
            helpers.append(impl)
    return helpers[:MAX_HELPERS]


# ── Randoop execution (sandboxed) ──────────────────────────────────
#
# Randoop EXECUTES the code under test while generating sequences, so e.g.
# File.setReadOnly() / FileOutputStream / Socket calls really run. Isolation
# is platform-dependent:
#   macOS: sandbox-exec — file writes only inside the invocation's temp cwd
#          + output dir, all network denied.
#   Linux: unshare -n — fresh network namespace (no external network).
#          File writes rely on the disposable container + per-run tmpdirs.

IS_MAC = sys.platform == "darwin"


def _unshare_works():
    """`unshare` existing isn't enough — containers often deny the syscall."""
    if IS_MAC or not shutil.which("unshare"):
        return False
    try:
        return subprocess.run(["unshare", "-n", "true"],
                              capture_output=True, timeout=10).returncode == 0
    except Exception:
        return False


HAS_UNSHARE = _unshare_works()

SANDBOX_PROFILE = """(version 1)
(allow default)
(deny network*)
(deny file-write*)
(allow file-write*
    (subpath "{tmp_cwd}")
    (subpath "{outdir}")
    (literal "/dev/null")
    (literal "/dev/zero")
    (literal "/dev/random")
    (literal "/dev/urandom")
    (literal "/dev/dtracehelper")
    (regex #"^/dev/tty")
)
"""


def sandbox_prefix(tmp_cwd, outdir):
    """Command prefix isolating a child process, per platform."""
    if IS_MAC:
        profile_path = os.path.join(tmp_cwd, "_sandbox.sb")
        Path(profile_path).write_text(SANDBOX_PROFILE.format(
            tmp_cwd=os.path.realpath(tmp_cwd),
            outdir=os.path.realpath(outdir)))
        return ["sandbox-exec", "-f", profile_path]
    if HAS_UNSHARE:
        return ["unshare", "-n", "--"]
    return []                                     # rely on container isolation


def run_randoop(testclass=None, classlist=None, time_limit=TIME_LIMIT):
    """Run Randoop inside a sandbox. Returns (output_dir, rc)."""
    outdir = tempfile.mkdtemp(prefix="randoop_out_")
    tmp_cwd = tempfile.mkdtemp(prefix="randoop_cwd_")

    cmd = sandbox_prefix(tmp_cwd, outdir) + [
        "java", "-Djava.awt.headless=true",
        "-Djavax.accessibility.assistive_technologies=",
        "-Djava.io.tmpdir=" + tmp_cwd,
        "-XX:-UsePerfData",
        "-Xmx1500m", "-cp", RANDOOP_JAR,
        "randoop.main.Main", "gentests",
        f"--output-limit={OUTPUT_LIMIT}", f"--maxsize={MAXSIZE}",
        f"--time-limit={time_limit}", f"--junit-output-dir={outdir}",
        "--regression-test-basename=Test",
        "--no-error-revealing-tests=true",
        "--randomseed=42", "--progressdisplay=false",
    ]
    if classlist:
        cmd.append(f"--classlist={classlist}")
    else:
        cmd.append(f"--testclass={testclass}")

    env = os.environ.copy()
    env["DISPLAY"] = ""

    p = None
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, start_new_session=True, cwd=tmp_cwd, env=env)
        p.communicate(timeout=HARD_TIMEOUT)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
        p.wait()
        rc = -1
    finally:
        shutil.rmtree(tmp_cwd, ignore_errors=True)
    return outdir, rc


# ── Randoop output parsing (type-aware, body kept verbatim) ────────

def extract_balanced(text, open_pos, open_char='{', close_char='}'):
    depth = 1
    for i in range(open_pos + 1, len(text)):
        if text[i] == open_char:
            depth += 1
        elif text[i] == close_char:
            depth -= 1
            if depth == 0:
                return text[open_pos + 1:i]
    return None


def clean_body(body):
    """Minimal, non-semantic cleanup: drop `if (debug) ...;` lines, dedent,
    re-indent to 8 spaces. Everything else stays verbatim."""
    lines = []
    for line in body.split("\n"):
        s = line.strip()
        if not s:
            continue
        if s.startswith("if (debug)") or "System.out.format" in s:
            continue
        lines.append(s)
    # naive re-indent: nested blocks (try/catch) get one extra level
    out, depth = [], 0
    for s in lines:
        if s.startswith("}"):
            depth = max(0, depth - 1)
        out.append("        " + "    " * depth + s)
        if s.endswith("{"):
            depth += 1
    return "\n".join(out)


def attribute_tests(outdir, target_fqn, wanted=frozenset()):
    """Parse Randoop output -> {api_method: [raw_test_body]}.
    A body is attributed to method m only when the call receiver's declared
    type is the target class, or the call is static on the target FQN.
    NOISE methods are still attributed when they are wrapper targets (wanted),
    e.g. an equals_test_NNNN wrapper for ArrayList.equals()."""
    target_short = target_fqn.split('.')[-1]
    results = defaultdict(list)
    if not os.path.isdir(outdir):
        return results

    for fn in sorted(os.listdir(outdir)):
        if not fn.endswith(".java") or fn == "Test.java":
            continue
        content = Path(outdir, fn).read_text(errors="replace")

        for tm in re.finditer(r'@Test\s+public\s+void\s+\w+\(\)[^{]*', content):
            brace = content.find('{', tm.end() - 1)
            if brace < 0:
                continue
            body = extract_balanced(content, brace)
            if body is None:
                continue

            # scan comment-stripped text only: Randoop comments out "flaky"
            # statements, and calls inside comments must not attribute
            scan = re.sub(r'//.*', '', body)

            # var -> declared type (short name), from declarations in the body
            var_types = {}
            for dm in re.finditer(
                    r'([\w.]+)(?:<[^;=]*?>)?(\[\])?\s+(\w+)\s*=', scan):
                var_types[dm.group(3)] = dm.group(1).split('.')[-1]

            methods = set()
            # instance calls: receiver's declared type must be the target
            for cm in re.finditer(r'(\w+)\.(\w+)\(', scan):
                recv, meth = cm.group(1), cm.group(2)
                if meth in NOISE and meth not in wanted:
                    continue
                if var_types.get(recv) == target_short:
                    methods.add(meth)
            # static calls on the target class (FQN or short)
            for cm in re.finditer(
                    re.escape(target_fqn) + r'\.(\w+)\(', scan):
                if cm.group(1) not in NOISE or cm.group(1) in wanted:
                    methods.add(cm.group(1))
            # constructor use counts for <init> wrappers named like the class
            for meth in methods:
                results[meth].append((body, frozenset(methods)))

    return results


def _top_level_argc(s):
    """Number of top-level comma-separated arguments in an arg string."""
    s = s.strip()
    if not s:
        return 0
    depth, cnt, in_str, in_chr, prev = 0, 1, False, False, ''
    for ch in s:
        if in_str:
            in_str = not (ch == '"' and prev != '\\')
        elif in_chr:
            in_chr = not (ch == "'" and prev != '\\')
        elif ch == '"':
            in_str = True
        elif ch == "'":
            in_chr = True
        elif ch in '([<':
            depth += 1
        elif ch in ')]>':
            depth -= 1
        elif ch == ',' and depth == 0:
            cnt += 1
        prev = ch
    return cnt


def count_call_args(text, name):
    """Arg counts of each `.name(...)` call found in text."""
    counts = []
    for m in re.finditer(r'\.' + re.escape(name) + r'\(', text):
        inner = extract_balanced(text, m.end() - 1, '(', ')')
        if inner is not None:
            counts.append(_top_level_argc(inner))
    return counts


def pick_best(candidates, method_name, argc):
    """candidates: [(body, target_methods_called)]. Prefer, in order:
    1. a call with the wrapper's arg count (right OVERLOAD)
    2. no env-specific paths (portable assertions)
    3. stronger oracle: value assertions > expected-exception > none
    4. fewest OTHER target-class methods called (focused attribution)
    5. exactly one target call (no duplicated statements)
    6. more assertions, then shorter. Body itself is never modified."""
    if not candidates:
        return None

    def score(item):
        b, meths = item
        scan = re.sub(r'//.*', '', b)
        counts = count_call_args(scan, method_name)
        n_match = sum(1 for c in counts if argc is None or c == argc)
        has_env = ('/var/folders' in b or '/private/' in b or '/tmp/' in b
                   or 'randoop_cwd_' in b)
        n_assert = len(re.findall(r'org\.junit\.Assert\.assert\w+\(', b))
        has_exc = 'Expected exception' in b or 'org.junit.Assert.fail' in b
        oracle_rank = 0 if n_assert > 0 else (1 if has_exc else 2)
        n_extra = len(meths - {method_name})
        return (0 if n_match > 0 else 1, 1 if has_env else 0, oracle_rank,
                n_extra, abs((n_match or len(counts)) - 1), -n_assert, len(b))

    return sorted(candidates, key=score)[0][0]


# ── Def-use pruning + runtime validation ───────────────────────────
#
# Prune statements unrelated to the API under test: keep the target call,
# its backward slice, and assertions whose variables trace back to the
# target call (return value or receiver). Statements feeding only removed
# assertions are dropped. Because observer/mutator purity cannot be decided
# statically (dropping `boolean b = list.add(x)` with dead `b` would change
# list state), every pruned body is compiled & executed in the sandbox and
# reverted to the original on any failure.

def prune_body(body, target_fqn, method_name, argc=None):
    """Return pruned body, or None if unprunable / nothing removed.
    try/catch blocks are treated as atomic units: a block containing the
    target call is the target statement; unrelated blocks/statements around
    it are pruned by the same def-use rules. When argc is given, only calls
    with that arg count are targets (overload-exact); falls back to
    name-only matching when no call matches."""
    target_short = target_fqn.split('.')[-1]

    lines = [s.strip() for s in body.split('\n')
             if s.strip() and not s.strip().startswith('if (debug)')]

    # group lines into units: single ';' statements or whole try/catch blocks
    units, buf, pending_comments = [], '', []
    i = 0
    while i < len(lines):
        s = lines[i]
        if s.startswith('//'):
            pending_comments.append(s)
            i += 1
            continue
        if s.startswith('try'):
            if buf:
                return None
            depth = s.count('{') - s.count('}')
            block = pending_comments + [s]
            pending_comments = []
            i += 1
            while i < len(lines) and depth > 0:
                depth += lines[i].count('{') - lines[i].count('}')
                block.append(lines[i])
                i += 1
            if depth != 0:
                return None
            units.append((block, True))
            continue
        buf = (buf + ' ' + s).strip() if buf else s
        if buf.endswith(';'):
            units.append((pending_comments + [buf], False))
            pending_comments, buf = [], ''
        i += 1
    if buf or not units:
        return None

    n = len(units)
    def_var, var_def_idx, var_types = [None] * n, {}, {}
    is_assert, scan = [False] * n, [''] * n
    for idx, (block, in_try) in enumerate(units):
        # comment-stripped text; vars declared INSIDE a try block are scoped
        # to it and never registered as definitions
        scan[idx] = ' '.join(re.sub(r'//.*', '', l) for l in block)
        if not in_try:
            s = block[-1]
            is_assert[idx] = bool(s.startswith('org.junit.Assert.')
                                  or re.match(r'assert\w+\(', s))
            m = re.match(r'([\w.]+(?:<.*?>)?(?:\[\])*)\s+(\w+)\s*=\s*(.*);$', s)
            if m and not is_assert[idx]:
                def_var[idx] = m.group(2)
                var_def_idx[m.group(2)] = idx
                var_types[m.group(2)] = m.group(1).split('<')[0].split('.')[-1]
                scan[idx] = m.group(3)

    def used_vars(idx):
        return {v for v in re.findall(r'\b([A-Za-z_]\w*)\b', scan[idx])
                if v in var_def_idx and v != def_var[idx]}

    # target units: target-method call on a target-typed receiver, or static.
    # Each call records (receiver_or_None, argc) for overload matching.
    targets_match, targets_any, unit_calls = [], [], {}
    for idx in range(n):
        if is_assert[idx]:
            continue
        calls = []
        for rm in re.finditer(r'(\w+)\.' + re.escape(method_name) + r'\(',
                              scan[idx]):
            if var_types.get(rm.group(1)) == target_short:
                inner = extract_balanced(scan[idx], rm.end() - 1, '(', ')')
                calls.append((rm.group(1),
                              None if inner is None else _top_level_argc(inner)))
        for rm in re.finditer(re.escape(target_fqn) + r'\.'
                              + re.escape(method_name) + r'\(', scan[idx]):
            inner = extract_balanced(scan[idx], rm.end() - 1, '(', ')')
            calls.append((None,
                          None if inner is None else _top_level_argc(inner)))
        if not calls:
            continue
        unit_calls[idx] = calls
        targets_any.append(idx)
        if argc is None or any(c == argc for _r, c in calls):
            targets_match.append(idx)
    targets = targets_match or targets_any
    if not targets:
        return None

    derived = set()
    for idx in targets:
        if def_var[idx]:
            derived.add(def_var[idx])             # return value
        derived.update(r for r, _c in unit_calls[idx] if r)  # receivers

    def slice_in(keep, seeds):
        frontier = set(seeds)
        while frontier:
            j = var_def_idx[frontier.pop()]
            if j not in keep:
                keep.add(j)
                frontier |= used_vars(j)

    keep = set(targets)
    for idx in targets:
        slice_in(keep, used_vars(idx))

    # assertions tracing back to the target stay (plus their slices)
    for idx in range(n):
        if is_assert[idx] and used_vars(idx) & derived:
            keep.add(idx)
            slice_in(keep, used_vars(idx))

    # void calls on kept variables: cannot prove purity — keep them.
    # (non-target try blocks are droppable: the risky call threw, so it
    # completed no mutation; the runtime validation guards the rare rest)
    kept_vars = {def_var[idx] for idx in keep if def_var[idx]}
    for idx, (block, in_try) in enumerate(units):
        if idx in keep or is_assert[idx] or in_try or def_var[idx] is not None:
            continue
        rm = re.match(r'(\w+)\.\w+\(', block[-1])
        if rm and rm.group(1) in kept_vars:
            keep.add(idx)

    if len(keep) == n:
        return None
    out = []
    for idx in sorted(keep):
        out.extend(units[idx][0])
    return '\n'.join(out)


def _run_sandboxed(cmd, tmp_cwd, outdir, timeout):
    p = None
    try:
        p = subprocess.Popen(sandbox_prefix(tmp_cwd, outdir) + cmd,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, start_new_session=True, cwd=tmp_cwd)
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, out or ""
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
        p.wait()
        return -1, ""


def validate_pruned(pruned_map):
    """pruned_map: {num: (method_name, pruned_body)}. Compile & run all
    pruned bodies as one sandboxed JUnit class. Returns nums to REVERT."""
    if not pruned_map:
        return set()
    vdir = tempfile.mkdtemp(prefix="randoop_val_")
    src = ["import org.junit.Test;", "public class _Validate {"]
    for num, (_mname, pbody) in sorted(pruned_map.items()):
        src.append(f"  @Test public void m_{num}() throws Throwable {{")
        src.extend("    " + l.strip() for l in pbody.split("\n"))
        src.append("  }")
    src.append("}")
    Path(vdir, "_Validate.java").write_text("\n".join(src))

    rc, _ = _run_sandboxed(
        ["javac", "-cp", RANDOOP_JAR, "-d", vdir,
         os.path.join(vdir, "_Validate.java")],
        vdir, vdir, HARD_TIMEOUT)
    if rc != 0:
        shutil.rmtree(vdir, ignore_errors=True)
        return set(pruned_map)          # compile failed → revert all

    rc, out = _run_sandboxed(
        ["java", "-Djava.awt.headless=true", "-XX:-UsePerfData",
         "-Djava.io.tmpdir=" + vdir,
         "-cp", RANDOOP_JAR + os.pathsep + vdir,
         "org.junit.runner.JUnitCore", "_Validate"],
        vdir, vdir, HARD_TIMEOUT)
    shutil.rmtree(vdir, ignore_errors=True)
    if rc == 0:
        return set()
    failed = set(re.findall(r'^\d+\) m_(\w+)\(_Validate', out, re.MULTILINE))
    return failed if failed else set(pruned_map)  # crash/hang → revert all


def make_test_file(class_name, method_name, number, target_fqn, body):
    cleaned = clean_body(body)
    return f'''package generated.test;

import org.junit.Test;

public class {class_name} {{

    /** Randoop-generated regression test for {target_fqn}.{method_name}(). */
    @Test
    public void {method_name}_test_{number}() throws Throwable {{
{cleaned}
    }}
}}
'''


# ── Per-class worker ───────────────────────────────────────────────

def process_class(cls, java_methods, existing, time_limit):
    """Run Randoop (dual-mode) for one class, write per-method test files.
    Returns list of record dicts."""
    records = []
    fqn = get_fqn(cls)
    if not fqn:
        log(f"  ❌ {cls}: FQN not found")
        return [{"class": cls, "number": n, "method": m, "status": "no_fqn"}
                for n, (m, _a) in java_methods.items()]

    helpers = get_helper_classes(cls, fqn)
    wanted = frozenset(m for m, _a in java_methods.values())

    # Mode 1: target class alone (focused budget)
    out1, _ = run_randoop(testclass=fqn, time_limit=time_limit)
    merged = attribute_tests(out1, fqn, wanted)
    shutil.rmtree(out1, ignore_errors=True)

    # Mode 2: target + helper classes (cross-class arguments constructible)
    if helpers:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(fqn + "\n")
            for h in helpers:
                f.write(h + "\n")
            cl_path = f.name
        out2, _ = run_randoop(classlist=cl_path, time_limit=time_limit)
        for meth, bodies in attribute_tests(out2, fqn, wanted).items():
            merged[meth].extend(bodies)
        shutil.rmtree(out2, ignore_errors=True)
        os.unlink(cl_path)

    class_dir = OUTPUT_DIR / cls
    class_dir.mkdir(parents=True, exist_ok=True)

    # pick best test per method, prune, then batch-validate pruned bodies
    pending = []
    for num, (method_name, argc) in sorted(java_methods.items()):
        if (cls, num) in existing:
            records.append({"class": cls, "number": num, "method": method_name,
                            "status": "existing"})
            continue
        best = pick_best(merged.get(method_name, []), method_name, argc)
        if best:
            pending.append((num, method_name, best))
        else:
            records.append({"class": cls, "number": num, "method": method_name,
                            "status": "no_test"})

    pruned_map = {}
    argc_by_num = {num: a for num, (_m, a) in java_methods.items()}
    for num, method_name, body in pending:
        p = prune_body(body, fqn, method_name, argc_by_num.get(num))
        if p:
            pruned_map[num] = (method_name, p)
    reverted = validate_pruned(pruned_map)

    added = 0
    for num, method_name, body in pending:
        pruned_flag = "no"
        if num in pruned_map:
            if num in reverted:
                pruned_flag = "reverted"
            else:
                body = pruned_map[num][1]
                pruned_flag = "yes"
        code = make_test_file(cls, method_name, num, fqn, body)
        (class_dir / f"{method_name}_test_{num}.java").write_text(code)
        added += 1
        records.append({"class": cls, "number": num, "method": method_name,
                        "status": "generated", "pruned": pruned_flag})

    n_no = sum(1 for r in records if r["status"] == "no_test")
    n_pruned = sum(1 for r in records if r.get("pruned") == "yes")
    log(f"  {cls}: +{added} generated ({n_pruned} pruned, "
        f"{len(reverted)} reverted), {n_no} uncovered "
        f"(randoop covered {len(merged)} methods, {len(helpers)} helpers)")
    return records


# ── Existing coverage (resume) ─────────────────────────────────────

def get_existing():
    existing = set()
    for d in OUTPUT_DIR.iterdir():
        if not d.is_dir() or d.name.startswith(("_", ".")):
            continue
        for f in d.glob("*.java"):
            m = re.match(r'\w+?_test_(\d+)\.java$', f.name)
            if m:
                existing.add((d.name, m.group(1)))
    return existing


# ── Main ───────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="only process these classes")
    ap.add_argument("--limit", type=int, help="process first N pending classes")
    ap.add_argument("--time-limit", type=int, default=TIME_LIMIT)
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--skip-dangerous", action="store_true",
                    help="skip file/network/GUI classes despite the sandbox")
    args = ap.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    existing = get_existing()

    work, records, skipped = [], [], 0
    for d in sorted(JAVA_SPLIT.iterdir()):
        if not d.is_dir():
            continue
        cls = d.name
        if args.only and cls not in args.only:
            continue
        methods = get_java_methods(cls)
        if not methods:
            continue
        if cls in DANGEROUS and args.skip_dangerous:
            skipped += 1
            records.extend({"class": cls, "number": n, "method": m,
                            "status": "skipped_dangerous"}
                           for n, (m, _a) in methods.items())
            continue
        if all((cls, n) in existing for n in methods):
            records.extend({"class": cls, "number": n, "method": m,
                            "status": "existing"}
                           for n, (m, _a) in methods.items())
            continue
        work.append((cls, methods))

    if args.limit:
        work = work[:args.limit]

    total_methods = sum(len(m) for _, m in work)
    log("=" * 60)
    log(f"Randoop generation (raw bodies, per-method files)")
    log(f"  classes: {len(work)}  methods: {total_methods}  "
        f"skipped(dangerous): {skipped}  already done: {len(existing)}")
    log(f"  time-limit: {args.time_limit}s x2 modes, workers: {args.workers}")
    log("=" * 60)

    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(process_class, cls, methods, existing,
                          args.time_limit): cls
                for cls, methods in work}
        for fut in as_completed(futs):
            cls = futs[fut]
            done += 1
            try:
                records.extend(fut.result())
            except Exception as e:
                log(f"  ❌ {cls}: worker crashed: {e}")
            if done % 25 == 0:
                log(f"── progress: {done}/{len(work)} classes ──")

    with open(RECORD_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["class", "number", "method",
                                          "status", "pruned"], restval="")
        w.writeheader()
        w.writerows(sorted(records, key=lambda r: (r["class"], r["number"])))

    gen = sum(1 for r in records if r["status"] == "generated")
    no_t = sum(1 for r in records if r["status"] == "no_test")
    log("")
    log("=" * 60)
    log(f"DONE. generated: {gen}  uncovered: {no_t}  record: {RECORD_CSV}")
    log("=" * 60)


if __name__ == "__main__":
    main()
