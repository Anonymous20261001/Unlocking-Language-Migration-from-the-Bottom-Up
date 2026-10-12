#!/usr/bin/env python3
"""Retry loop: compile-check -> delete fails -> re-translate -> repeat."""
import subprocess, os, csv, sys
from pathlib import Path
from multiprocessing import Pool

OUT = Path('/root/autodl-tmp/Java2C++/Cpp_benchmark_translated')
MAPPING = Path('/root/autodl-tmp/Java2C++/mapping.csv')

def load_expected():
    with open(MAPPING, encoding='utf-8') as f:
        raw = f.read().replace('\r\n','\n').replace('\r','\n')
    result = []
    for row in csv.DictReader(raw.splitlines()):
        if row['compile_status'].strip() == 'pass':
            result.append((row['class'].strip(), row['cpp_function'].strip()))
    return result

def check_one(args):
    cls, fn = args
    path = OUT / cls / f'{fn}.cpp'
    if not path.exists():
        return (cls, fn, 'missing')
    r = subprocess.run(['g++', '-std=c++17', '-fsyntax-only', '-w', str(path)],
                      capture_output=True, text=True, timeout=15)
    return (cls, fn, 'pass' if r.returncode == 0 else 'fail')

expected = load_expected()
print(f'Expected: {len(expected)}', flush=True)

for round_num in range(1, 15):
    # Parallel compile check
    with Pool(32) as p:
        results = p.map(check_one, expected, chunksize=50)

    ok = sum(1 for r in results if r[2] == 'pass')
    fail = [(c,f) for c,f,s in results if s == 'fail']
    missing = [(c,f) for c,f,s in results if s == 'missing']

    print(f'\nRound {round_num}: ok={ok} fail={len(fail)} missing={len(missing)}', flush=True)

    if not fail and not missing:
        print('ALL PASS!', flush=True)
        break

    # Delete fails
    for cls, fn in fail:
        (OUT / cls / f'{fn}.cpp').unlink(missing_ok=True)

    total_todo = len(fail) + len(missing)
    if total_todo == 0:
        break

    # Run translate_v2 (will only process missing files due to resume)
    print(f'Retranslating {total_todo} files...', flush=True)
    subprocess.run([sys.executable, 'translate_v2.py'],
                  cwd='/root/autodl-tmp/Java2C++', timeout=7200)
