"""
Verify/reproduce benchmark + javadoc results:
A) Skeleton compile re-check: re-run g++ on all skeleton-fail entries, categorize errors
B) Behavior re-run: recompile + rerun the 5851 benchmark tests, reclassify PASS/INCONSISTENT/CRASH
"""
import csv, subprocess, os, re, json, tempfile, shutil, time
from pathlib import Path
from collections import Counter
import multiprocessing as mp

BASE = Path('/root/autodl-tmp/Java2C++')

# ── Categorization (same as analysis_report.txt) ────────────────────
def categorize(err):
    """Categorize a g++ stderr into the report's taxonomy."""
    el = err.lower()
    if 'no such file or directory' in el and 'gmpxx' in el:
        return 'other_missing_gmp'
    if "'find' is not a member of 'std'" in el or "'find' is not a member of" in el:
        return 'other_missing_algorithm_include'
    if 'does not name a type' in el or 'no type named' in el or "' is not a type" in el:
        return 'type_not_found'
    if 'no matching function' in el or 'no match for call' in el or 'no match for' in el and 'operator' in el:
        return 'no_matching_function'
    if 'cannot convert' in el or 'invalid conversion' in el or 'could not convert' in el:
        return 'type_conversion'
    if 'incomplete type' in el or 'invalid use of incomplete' in el:
        return 'incomplete_type'
    if 'has no member named' in el or 'no member named' in el or 'is not a member of' in el:
        return 'member_not_found'
    if 'was not declared' in el or 'not declared in this scope' in el:
        return 'undeclared_var'
    if 'expected' in el and ('before' in el or 'at end of input' in el or 'after' in el or "‘" in err or "'" in err):
        if 'end of input' in el or 'at end of' in el:
            return 'code_structure'
        return 'code_structure'
    if 'return-statement' in el and 'void' in el:
        return 'return_type_mismatch'
    if 'is private' in el or 'is protected' in el:
        return 'access_control'
    if 'redefinition' in el:
        return 'redefinition'
    if 'static assertion failed' in el or 'static_assert' in el:
        return 'static_assert_failed'
    if 'no match for' in el:
        return 'no_matching_function'
    if 'error:' in el:
        return 'other'
    return 'other'


def compile_check_file(path_str):
    """Run g++ -fsyntax-only, return (ok, error_text)."""
    r = subprocess.run(['g++', '-std=c++17', '-fsyntax-only', '-w', path_str],
                       capture_output=True, text=True, timeout=15)
    if r.returncode == 0:
        return True, ''
    return False, r.stderr[:1500]


# ── Task A: skeleton compile re-check ───────────────────────────────
def skeleton_task(args):
    ds, cls, fn, path_str = args
    ok, err = compile_check_file(path_str)
    return {'dataset': ds, 'class': cls, 'file': fn, 'ok': ok,
            'error': err if not ok else '', 'category': categorize(err) if not ok else ''}


def run_skeleton_check():
    tasks = []
    # benchmark 1274
    with open(BASE / 'translation_result.csv', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            if row['compile_status'] == 'fail':
                p = BASE / 'CppAPI_splitted_method' / row['class'] / f"{row['cpp_function']}.cpp"
                tasks.append(('benchmark', row['class'], f"{row['cpp_function']}.cpp", str(p)))
    # javadoc 429 + 16 empty
    with open(BASE / 'pipeline/summary_1754.csv', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            if row['s25_status'] != 'PASS':  # FAIL or empty
                p = BASE / 'pipeline/02_CppJavadoc_splitted_method' / row['class_dir'] / row['cpp_file']
                if p.exists():
                    tasks.append(('javadoc', row['class_dir'], row['cpp_file'], str(p)))

    print(f"Task A: {len(tasks)} skeleton files to re-check")
    results = []
    with mp.Pool(16) as pool:
        for i, r in enumerate(pool.imap_unordered(skeleton_task, tasks, chunksize=20)):
            results.append(r)
            if (i + 1) % 200 == 0:
                print(f"  [{i+1}/{len(tasks)}]")
    return results


# ── Task B: behavior re-run for benchmark 5851 ──────────────────────
def has_assert_code(code):
    return bool(re.search(r'\bassert\s*\(', code))


def behavior_task(args):
    cls, fn, path_str = args
    """Compile with main wrapper, run, classify."""
    code = Path(path_str).read_text(encoding='utf-8', errors='replace')
    has_assert = has_assert_code(code)

    tmpdir = tempfile.mkdtemp(prefix='repro_')
    try:
        # main wrapper: find test function name
        func_name = fn[:-4]  # strip .cpp
        wrapper = f'void {func_name}();\nint main() {{ {func_name}(); return 0; }}\n'
        wp = Path(tmpdir) / 'main.cpp'
        wp.write_text(wrapper)
        binary = Path(tmpdir) / 'test.out'

        r = subprocess.run(['g++', '-std=c++17', '-O0', '-o', str(binary), path_str, str(wp)],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return {'class': cls, 'file': fn, 'status': 'COMPILE_FAIL', 'has_assert': has_assert}

        r = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return {'class': cls, 'file': fn, 'status': 'PASS', 'has_assert': has_assert}
        elif r.returncode < 0:  # killed by signal
            return {'class': cls, 'file': fn, 'status': f'CRASH({r.returncode})', 'has_assert': has_assert}
        else:
            # assert failure → INCONSISTENT (behavior differs from Java expectation)
            return {'class': cls, 'file': fn, 'status': 'INCONSISTENT', 'has_assert': has_assert}
    except subprocess.TimeoutExpired:
        return {'class': cls, 'file': fn, 'status': 'TIMEOUT', 'has_assert': has_assert}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def run_behavior_check():
    tasks = []
    with open(BASE / 'translation_result.csv', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            if row['translated_compile'] == 'pass':
                p = BASE / 'Cpp_benchmark_translated' / row['class'] / f"{row['cpp_function']}.cpp"
                if p.exists():
                    tasks.append((row['class'], f"{row['cpp_function']}.cpp", str(p)))

    print(f"Task B: {len(tasks)} benchmark tests to re-run")
    results = []
    with mp.Pool(16) as pool:
        for i, r in enumerate(pool.imap_unordered(behavior_task, tasks, chunksize=10)):
            results.append(r)
            if (i + 1) % 500 == 0:
                print(f"  [{i+1}/{len(tasks)}]")
    return results


def main():
    which = os.environ.get('TASK', 'A')  # A=skeleton, B=behavior, AB=both
    t0 = time.time()

    if which in ('A', 'AB'):
        print(f"[{time.strftime('%H:%M:%S')}] Task A: skeleton compile re-check")
        skel = run_skeleton_check()
        skel_path = BASE / 'pipeline/repro_skeleton_check.csv'
        with open(skel_path, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=['dataset', 'class', 'file', 'ok', 'category', 'error'])
            w.writeheader()
            for r in skel:
                w.writerow(r)
        cnt = Counter(r['ok'] for r in skel)
        cat = Counter(r['category'] for r in skel if not r['ok'])
        print(f"  Skeleton: OK={cnt.get(True,0)} FAIL={cnt.get(False,0)} ({(time.time()-t0):.0f}s)")
        print(f"  Categories: {dict(cat)}")
        print(f"  Saved: {skel_path}")

    if which in ('B', 'AB'):
        print(f"[{time.strftime('%H:%M:%S')}] Task B: behavior re-run")
        behav = run_behavior_check()
        behav_path = BASE / 'pipeline/repro_behavior_rerun.csv'
        with open(behav_path, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=['class', 'file', 'status', 'has_assert'])
            w.writeheader()
            for r in behav:
                w.writerow(r)
        cnt = Counter(r['status'] for r in behav)
        print(f"  Behavior: {dict(cnt)}")
        print(f"  PASS: {cnt.get('PASS',0)}  INCONSISTENT: {cnt.get('INCONSISTENT',0)}  CRASH: {sum(v for k,v in cnt.items() if k.startswith('CRASH'))}  COMPILE_FAIL: {cnt.get('COMPILE_FAIL',0)}")
        print(f"  Saved: {behav_path}")

        # Compare with original CSV
        orig = Counter()
        with open(BASE / 'translation_result.csv', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if row['translated_compile'] == 'pass':
                    orig[row['behavior_status']] += 1
        print(f"  Original CSV: {dict(orig)}")

    print(f"Total: {(time.time()-t0):.0f}s")


if __name__ == '__main__':
    main()
