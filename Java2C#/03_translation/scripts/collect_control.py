"""Control group: 50 random compile-SUCCESS units, scan for Java residue patterns."""
import csv, os, re, json, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect_residue import PATTERNS

BASE = "/root/autodl-tmp/Java2C#"
random.seed(20260915)

# collect PASS units
units = []
with open(f'{BASE}/compile_nofw_results.csv') as f:
    for r in csv.DictReader(f):
        if r['passed'] == 'True':
            units.append(('old_benchmark', r['class'], r['cs_file']))
with open(f'{BASE}/pipeline_cs/method_report.csv') as f:
    for r in csv.DictReader(f):
        if r['skeleton_compile'] == 'PASS':
            units.append(('new_pipeline', r['class'], r['filename']))
print(f'PASS units pool: {len(units)}')

sample = random.sample(units, 50)
results = []
for dataset, cls, cs_file in sample:
    path = (f"{BASE}/CsAPI_splitted_nofw/{cls}/{cs_file}" if dataset == 'old_benchmark'
            else f"{BASE}/pipeline_cs/02_CsAPI_splitted_nofw/{cls}/{cs_file}")
    if not os.path.exists(path):
        continue
    text = open(path, encoding='utf-8', errors='replace').read()
    found = []
    for name, pat in PATTERNS.items():
        m = pat.search(text)
        if m:
            # locate line
            line_no = text[:m.start()].count('\n') + 1
            line_text = text.split('\n')[line_no-1].strip()[:150]
            found.append({'pattern': name, 'line': line_no, 'context': line_text})
    results.append({'dataset': dataset, 'class': cls, 'file': cs_file, 'residues': found})

with_residue = [r for r in results if r['residues']]
print(f'Control group: {len(results)} PASS units analyzed')
print(f'Units containing >=1 Java residue pattern: {len(with_residue)} '
      f'({100*len(with_residue)/max(1,len(results)):.0f}%)')

from collections import Counter
pat_counter = Counter()
for r in results:
    for f in r['residues']:
        pat_counter[f['pattern']] += 1
print(f'Pattern hits: {dict(pat_counter)}')

json.dump(results, open(f'{BASE}/error_taxonomy/data/residue_control.json', 'w'), ensure_ascii=False, indent=1)
print('Saved to residue_control.json')
