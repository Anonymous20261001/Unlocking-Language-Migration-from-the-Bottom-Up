"""
Generate Randoop tests for methods in new_methods_list.csv.
Output: new_Java_test_cases/{ClassName}/{method}_test_{number}.java

Adapted from generate_randoop_tests.py:
- Input from CSV instead of JavaAPI_splitted_method
- Skip def-use pruning + validation (minimal benefit, high cost)
- More workers for CPU parallelism
"""

import csv, os, re, shutil, signal, subprocess, sys, tempfile, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

# ── Paths ────────────────────────────────────────────────────────────
RANDOOP_JAR = "/root/autodl-tmp/Java2Python/randoop-all-4.3.4.jar"
INPUT_DIR = Path("/root/autodl-tmp/Java2Python/new_method_by_method")
CSV_PATH = "/root/autodl-tmp/Java2Python/new_methods_list.csv"
OUTPUT_DIR = Path("/root/autodl-tmp/Java2Python/new_Java_test_cases")
LOG_FILE = OUTPUT_DIR / "_progress.log"
RECORD_CSV = OUTPUT_DIR / "_generation_record.csv"

TIME_LIMIT = 45        # seconds per Randoop mode
HARD_TIMEOUT = 120     # hard kill per invocation
OUTPUT_LIMIT = 300     # max tests per Randoop run
MAXSIZE = 5            # max sequence size
WORKERS = 8            # parallel class processing
MAX_HELPERS = 15       # max helper classes per classlist

NOISE = {'equals', 'getClass', 'hashCode', 'toString', 'format', 'println',
         'assertTrue', 'assertFalse', 'assertEquals', 'assertNotNull',
         'assertArrayEquals', 'fail', 'out', 'err'}

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


# ── CSV parsing ──────────────────────────────────────────────────────

def parse_csv():
    """Parse new_methods_list.csv -> {class_name: {fqcn, methods: [(num, method_name, argc)]}}"""
    data = {}
    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:  # utf-8-sig handles BOM
        reader = csv.DictReader(f)
        for row in reader:
            # Normalize keys: strip whitespace and BOM artifacts
            normalized = {}
            for k, v in row.items():
                clean_k = k.strip().lstrip('﻿').strip()
                normalized[clean_k] = v.strip() if v else ""

            filename = normalized.get("文件名", "")
            class_name = filename.replace(".java", "")
            fqcn = normalized.get("类全名 (FQCN)", "") or normalized.get("类全名", "")
            method_name = normalized.get("方法名", "")
            test_num = normalized.get("测试编号", "")

            if not class_name or not fqcn or not method_name:
                continue

            if class_name not in data:
                data[class_name] = {"fqcn": fqcn, "methods": []}
            data[class_name]["methods"].append((test_num, method_name))

    return data


def get_argc_from_file(class_name, method_name, test_num):
    """Read the wrapper file to determine argc for a specific method."""
    wrapper_file = INPUT_DIR / class_name / f"{method_name}_test_{test_num}.java"
    if not wrapper_file.exists():
        # Try without test number (different naming)
        candidates = list((INPUT_DIR / class_name).glob(f"{method_name}_test_*.java"))
        if candidates:
            wrapper_file = candidates[0]
        else:
            return None

    content = wrapper_file.read_text(errors="replace")
    # Find the method signature: public void methodName_test_NNN(...)
    m = re.search(r'public\s+\w+\s+' + re.escape(method_name) + r'_test_\d+\s*\(([^)]*)\)',
                  content)
    if not m:
        return None
    args = m.group(1).strip()
    if not args:
        return 0
    # Count top-level commas
    depth, cnt = 0, 1
    for ch in args:
        if ch in '<([':
            depth += 1
        elif ch in '>)]':
            depth -= 1
        elif ch == ',' and depth == 0:
            cnt += 1
    return cnt


def get_helper_classes(class_name, fqcn):
    """Collect imports from wrapper files to build classlist helpers."""
    d = INPUT_DIR / class_name
    if not d.is_dir():
        return []

    imports = set()
    for f in d.glob("*.java"):
        content = f.read_text(errors="replace")
        imports.update(re.findall(r'^import\s+([\w.]+);', content, re.MULTILINE))

    api_short = fqcn.split('.')[-1]
    helpers = []
    for imp in sorted(imports):
        if imp == fqcn or imp.endswith('.' + api_short):
            continue
        if imp.startswith('java.lang.') or imp.startswith('org.junit'):
            continue
        if imp.startswith('java.util.function.'):
            continue
        helpers.append(imp)
        impl = INTERFACE_IMPL.get(imp)
        if impl and impl not in helpers and impl != fqcn:
            helpers.append(impl)
    return helpers[:MAX_HELPERS]


# ── Randoop execution ────────────────────────────────────────────────

def run_randoop(testclass=None, classlist=None, time_limit=TIME_LIMIT):
    """Run Randoop, return (output_dir, returncode)."""
    outdir = tempfile.mkdtemp(prefix="randoop_out_")
    tmp_cwd = tempfile.mkdtemp(prefix="randoop_cwd_")

    cmd = [
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


# ── Randoop output parsing ───────────────────────────────────────────

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
    """Minimal cleanup: drop debug lines, re-indent."""
    lines = []
    for line in body.split("\n"):
        s = line.strip()
        if not s:
            continue
        if s.startswith("if (debug)") or "System.out.format" in s:
            continue
        lines.append(s)
    out, depth = [], 0
    for s in lines:
        if s.startswith("}"):
            depth = max(0, depth - 1)
        out.append("        " + "    " * depth + s)
        if s.endswith("{"):
            depth += 1
    return "\n".join(out)


def attribute_tests(outdir, target_fqn, wanted=frozenset()):
    """Parse Randoop output -> {api_method: [(body, called_methods_set)]}"""
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

            scan = re.sub(r'//.*', '', body)
            var_types = {}
            for dm in re.finditer(
                    r'([\w.]+)(?:<[^;=]*?>)?(\[\])?\s+(\w+)\s*=', scan):
                var_types[dm.group(3)] = dm.group(1).split('.')[-1]

            methods = set()
            for cm in re.finditer(r'(\w+)\.(\w+)\(', scan):
                recv, meth = cm.group(1), cm.group(2)
                if meth in NOISE and meth not in wanted:
                    continue
                if var_types.get(recv) == target_short:
                    methods.add(meth)
            for cm in re.finditer(
                    re.escape(target_fqn) + r'\.(\w+)\(', scan):
                if cm.group(1) not in NOISE or cm.group(1) in wanted:
                    methods.add(cm.group(1))
            for meth in methods:
                results[meth].append((body, frozenset(methods)))

    return results


def _top_level_argc(s):
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
    counts = []
    for m in re.finditer(r'\.' + re.escape(name) + r'\(', text):
        inner = extract_balanced(text, m.end() - 1, '(', ')')
        if inner is not None:
            counts.append(_top_level_argc(inner))
    return counts


def pick_best(candidates, method_name, argc):
    """Pick the best test from candidates. Priority:
    1. arg count matches (correct overload)
    2. no env-specific paths
    3. stronger oracle: value assertions > expected-exception > none
    4. fewest OTHER target-class methods called
    5. exactly one target call
    6. more assertions, then shorter."""
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


# ── Per-class worker ─────────────────────────────────────────────────

def process_class(class_name, info, time_limit):
    """Run Randoop for one class, write per-method test files.
    info = {"fqcn": str, "methods": [(num, name, argc), ...]}
    Returns list of record dicts."""
    records = []
    fqcn = info["fqcn"]
    methods = info["methods"]  # list of (num, name, argc)

    helpers = get_helper_classes(class_name, fqcn)
    wanted = frozenset(m for _n, m, _a in methods)

    # Mode 1: target class alone
    out1, _ = run_randoop(testclass=fqcn, time_limit=time_limit)
    merged = attribute_tests(out1, fqcn, wanted)
    shutil.rmtree(out1, ignore_errors=True)

    # Mode 2: target + helper classes
    if helpers:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(fqcn + "\n")
            for h in helpers:
                f.write(h + "\n")
            cl_path = f.name
        out2, _ = run_randoop(classlist=cl_path, time_limit=time_limit)
        for meth, bodies in attribute_tests(out2, fqcn, wanted).items():
            merged[meth].extend(bodies)
        shutil.rmtree(out2, ignore_errors=True)
        os.unlink(cl_path)

    class_dir = OUTPUT_DIR / class_name
    class_dir.mkdir(parents=True, exist_ok=True)

    added = 0
    for num, method_name, argc in sorted(methods, key=lambda x: x[0]):
        best = pick_best(merged.get(method_name, []), method_name, argc)
        if best:
            code = make_test_file(class_name, method_name, num, fqcn, best)
            (class_dir / f"{method_name}_test_{num}.java").write_text(code)
            added += 1
            records.append({"class": class_name, "number": num,
                            "method": method_name, "status": "generated"})
        else:
            records.append({"class": class_name, "number": num,
                            "method": method_name, "status": "no_test"})

    n_no = sum(1 for r in records if r["status"] == "no_test")
    log(f"  {class_name}: +{added} generated, {n_no} uncovered "
        f"(randoop covered {len(merged)} methods, {len(helpers)} helpers)")
    return records


# ── Existing coverage (resume) ───────────────────────────────────────

def get_existing():
    existing = set()
    if not OUTPUT_DIR.exists():
        return existing
    for d in OUTPUT_DIR.iterdir():
        if not d.is_dir() or d.name.startswith(("_", ".")):
            continue
        for f in d.glob("*.java"):
            m = re.match(r'\w+?_test_(\d+)\.java$', f.name)
            if m:
                existing.add((d.name, m.group(1)))
    return existing


# ── Main ─────────────────────────────────────────────────────────────

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="process first N classes")
    ap.add_argument("--only", nargs="*", help="only process these class names")
    ap.add_argument("--time-limit", type=int, default=TIME_LIMIT)
    ap.add_argument("--workers", type=int, default=WORKERS)
    args = ap.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Parse CSV
    csv_data = parse_csv()
    log(f"Parsed CSV: {len(csv_data)} classes, "
        f"{sum(len(v['methods']) for v in csv_data.values())} methods")

    # Enrich with argc from wrapper files
    for class_name, info in csv_data.items():
        enriched = []
        for num, method_name in info["methods"]:
            argc = get_argc_from_file(class_name, method_name, num)
            enriched.append((num, method_name, argc))
        info["methods"] = enriched

    # Resume support
    existing = get_existing()
    log(f"Existing (resume): {len(existing)} files")

    # Build work list
    work = []
    skipped_existing = 0
    for class_name, info in sorted(csv_data.items()):
        if args.only and class_name not in args.only:
            continue
        methods = info["methods"]
        if all((class_name, num) in existing for num, _m, _a in methods):
            skipped_existing += 1
            continue
        work.append((class_name, info))

    if args.limit:
        work = work[:args.limit]

    total_methods = sum(len(info["methods"]) for _c, info in work)
    log("=" * 60)
    log(f"Randoop generation for new_method_by_method")
    log(f"  classes to process: {len(work)}  methods: {total_methods}")
    log(f"  already done: {skipped_existing} classes")
    log(f"  time-limit: {args.time_limit}s x2 modes  workers: {args.workers}")
    log("=" * 60)

    if not work:
        log("Nothing to do!")
        return

    all_records = []
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(process_class, class_name, info, args.time_limit): class_name
                for class_name, info in work}
        for fut in as_completed(futs):
            cls = futs[fut]
            done += 1
            try:
                all_records.extend(fut.result())
            except Exception as e:
                log(f"  ❌ {cls}: worker crashed: {e}")
                # Mark all methods of this class as errored
                for num, method_name, _argc in csv_data[cls]["methods"]:
                    if (cls, num) not in existing:
                        all_records.append({"class": cls, "number": num,
                                            "method": method_name,
                                            "status": "error"})
            if done % 20 == 0:
                gen = sum(1 for r in all_records if r["status"] == "generated")
                no_t = sum(1 for r in all_records if r["status"] == "no_test")
                log(f"── progress: {done}/{len(work)} classes, "
                    f"{gen} generated, {no_t} uncovered ──")

    # Write records
    with open(RECORD_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["class", "number", "method", "status"])
        w.writeheader()
        w.writerows(sorted(all_records, key=lambda r: (r["class"], r["number"])))

    gen = sum(1 for r in all_records if r["status"] == "generated")
    no_t = sum(1 for r in all_records if r["status"] == "no_test")
    err = sum(1 for r in all_records if r["status"] == "error")
    log("")
    log("=" * 60)
    log(f"DONE. generated: {gen}  uncovered: {no_t}  errors: {err}")
    log(f"Record: {RECORD_CSV}")
    log("=" * 60)


if __name__ == "__main__":
    main()
