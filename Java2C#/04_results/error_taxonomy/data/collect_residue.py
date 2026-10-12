"""
Java-residue evidence collection per HANDOVER_CS_RESIDUE.md (read-only analysis).
Compiles failed .cs units, extracts error lines, detects Java residue patterns.
"""
import csv, os, re, json, random
import subprocess
import multiprocessing as mp

BASE = "/root/autodl-tmp/Java2C#"
MCS = "mcs -target:library -r:System.dll,System.Core.dll,System.Drawing.dll,System.Numerics.dll -out:/dev/null"

# Java residue patterns (case-sensitive, per handover list)
PATTERNS = {
    'java_wrapper_type': re.compile(r'\b(Integer|Character|Boolean|Short|Long|Float|Double)\b'),
    'java_fqcn':         re.compile(r'\b(java|javax|jdk)\.'),
    'java_array_syntax': re.compile(r'\bString\[\]'),
    'java_annotation':   re.compile(r'@(Test|Override|Deprecated|FunctionalInterface|SafeVarargs)\b'),
    'java_sysout':       re.compile(r'\bSystem\.(out|err)\b'),
    'java_keyword':      re.compile(r'\b(boolean|final)\b|\bimplements\b'),
    'java_api_call':     re.compile(r'new\s+String\s*\(|\.equals\s*\('),
}

def compile_file(path):
    """Return list of (line_no, col, code, message)."""
    try:
        r = subprocess.run(MCS.split() + [path], capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return [('TIMEOUT', 0, 'TIMEOUT', 'timeout')]
    out = []
    for m in re.finditer(r'\((\d+),(\d+)\): error (CS\d+): ([^\n]*)', r.stderr):
        out.append((int(m.group(1)), int(m.group(2)), m.group(3), m.group(4)))
    return out

def find_residue(line_text):
    """Return list of pattern names found in a single line."""
    return [name for name, pat in PATTERNS.items() if pat.search(line_text)]

def analyze_failed_unit(args):
    """Returns dict with file info, errors, and residue findings."""
    dataset, cls, cs_file = args
    if dataset == 'old_benchmark':
        path = f"{BASE}/CsAPI_splitted_nofw/{cls}/{cs_file}"
    else:
        path = f"{BASE}/pipeline_cs/02_CsAPI_splitted_nofw/{cls}/{cs_file}"
    res = {'dataset': dataset, 'class': cls, 'file': cs_file, 'path': path,
           'errors': [], 'error_line_residue': [], 'file_level_residue': []}
    if not os.path.exists(path):
        res['missing'] = True
        return res
    errors = compile_file(path)
    res['errors'] = errors
    # file-level scan
    try:
        lines = open(path, encoding='utf-8', errors='replace').read().split('\n')
    except Exception:
        return res
    file_pats = set()
    for name, pat in PATTERNS.items():
        if pat.search('\n'.join(lines)):
            file_pats.add(name)
    res['file_level_residue'] = sorted(file_pats)
    # error-line scan
    line_pats = []
    for (ln, col, code, msg) in errors:
        if ln == 'TIMEOUT' or ln <= 0 or ln > len(lines):
            continue
        line_text = lines[ln-1]
        pats = find_residue(line_text)
        if pats:
            line_pats.append({'line': ln, 'col': col, 'code': code, 'msg': msg,
                              'line_text': line_text.strip()[:200], 'pats': pats})
    res['error_line_residue'] = line_pats
    return res

def main():
    # ── build failed-unit list ──
    units = []
    with open(f'{BASE}/compile_nofw_results.csv') as f:
        for r in csv.DictReader(f):
            if r['passed'] == 'False':
                units.append(('old_benchmark', r['class'], r['cs_file']))
    with open(f'{BASE}/pipeline_cs/method_report.csv') as f:
        for r in csv.DictReader(f):
            if r['skeleton_compile'] == 'FAIL':
                units.append(('new_pipeline', r['class'], r['filename']))
    print(f'Failed units: {len(units)}')

    # ── compile + analyze (cached) ──
    cache_path = f'{BASE}/error_taxonomy/data/residue_cache.json'
    if os.path.exists(cache_path):
        results = json.load(open(cache_path))
        print(f'Loaded {len(results)} cached results')
    else:
        with mp.Pool(8) as pool:
            results = []
            for i, r in enumerate(pool.imap_unordered(analyze_failed_unit, units, chunksize=10)):
                results.append(r)
                if (i+1) % 500 == 0:
                    print(f'  {i+1}/{len(units)}')
        json.dump(results, open(cache_path, 'w'))
        print(f'Compiled {len(results)} units, cached')

    # ── statistics by error code ──
    from collections import Counter, defaultdict
    code_residue = Counter()      # units whose error LINE contains residue, by first error code
    code_total = Counter()        # all units by first error code
    err_code_total = Counter()    # all error occurrences
    err_code_residue = Counter()  # error occurrences whose line has residue
    units_with_residue = 0
    units_no_compile_error = 0
    instances = []
    for res in results:
        errs = [e for e in res['errors'] if e[2].startswith('CS')]
        if not errs:
            units_no_compile_error += 1
            continue
        first_code = errs[0][2]
        code_total[first_code] += 1
        has_line_residue = len(res['error_line_residue']) > 0
        if has_line_residue:
            code_residue[first_code] += 1
            units_with_residue += 1
        for (ln, col, code, msg) in errs:
            err_code_total[code] += 1
        for e in res['error_line_residue']:
            err_code_residue[e['code']] += 1
            if len(instances) < 200:
                instances.append((res['dataset'], res['class'], res['file'], e))

    print(f'\nUnits with compile errors: {sum(code_total.values())}, '
          f'no-compile-error: {units_no_compile_error}')
    print(f'Units whose error line contains Java residue: {units_with_residue} '
          f'({100*units_with_residue/max(1,sum(code_total.values())):.1f}%)')
    print(f'\n{"error_code":<10} {"units":>6} {"units_with_residue":>19} {"%":>6}')
    for code in sorted(code_total, key=lambda c: -code_total[c]):
        n = code_total[code]
        r = code_residue.get(code, 0)
        print(f'{code:<10} {n:>6} {r:>19} {100*r/max(1,n):>5.1f}%')

    # pattern distribution on error lines
    pat_counter = Counter()
    for res in results:
        for e in res['error_line_residue']:
            for p in e['pats']:
                pat_counter[p] += 1
    print(f'\nResidue pattern hits on error lines: {dict(pat_counter)}')

    json.dump(instances, open(f'{BASE}/error_taxonomy/data/residue_instances.json', 'w'), ensure_ascii=False, indent=1)
    print(f'\nSaved {len(instances)} instances to residue_instances.json')

if __name__ == '__main__':
    main()
