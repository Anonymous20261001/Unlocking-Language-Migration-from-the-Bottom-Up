import csv, glob, os, re, random, json

BASE = "/root/autodl-tmp/Java2C#"
random.seed(20261002)

JAVA_SKIP = {'asserttrue','assertfalse','assertequals','assertarrayequals','assertnotnull',
             'assertnull','fail','assertsame','tostring','equals','gethashcode','getclass',
             'hashcode','string.valueof'}
CS_SKIP = {'debug.assert','object.equals','object.referenceequals','console.error','throw',
           'console.writeline','tostring','gettype'}

def java_body(path):
    code = open(path, encoding='utf-8', errors='replace').read()
    m = re.search(r'public\s+void\s+(\w+_test_\d+)\s*\([^)]*\)\s*throws\s+\w+\s*\{', code)
    if not m: return None, ''
    name = m.group(1)
    start = m.end()
    depth = 0
    for i in range(start-1, len(code)):
        if code[i]=='{': depth+=1
        elif code[i]=='}':
            depth-=1
            if depth==0: return name, code[start:i]
    return name, ''

def cs_body(path):
    if not os.path.exists(path): return None, '', 'FILE_MISSING'
    code = open(path, encoding='utf-8', errors='replace').read()
    m = re.search(r'public\s+void\s+(\w+[Tt]est[_\w]*\d*)\s*\(\s*\)\s*\{', code)
    if not m: return None, '', 'NO_TEST_METHOD'
    name = m.group(1)
    start = m.end()
    depth = 0
    for i in range(start-1, len(code)):
        if code[i]=='{': depth+=1
        elif code[i]=='}':
            depth-=1
            if depth==0: return name, code[start:i], ''
    return name, '', 'UNCLOSED'

def java_api_calls(body):
    calls = set()
    body2 = '\n'.join(l for l in body.split('\n') if not l.strip().startswith('//'))
    for m in re.finditer(r'(?:(\w+)\.)?(\w+)\s*\(', body2):
        prefix, name = m.group(1), m.group(2).lower()
        if name in JAVA_SKIP: continue
        if re.search(r'_test_\d+$', name): continue
        calls.add(name)
    for m in re.finditer(r'new\s+(?:[\w]+\.)*(\w+)\s*(?:<[^>]*>)?\s*\(', body2):
        calls.add('new_'+m.group(1).lower())
    calls = {c for c in calls if not ('new_'+c) in calls}
    return calls

def cs_api_calls(body):
    calls = set()
    for m in re.finditer(r'\w+\.(\w+)(?=\s*[;=,)\.]|\s*$)', body):
        # property read like obj.DigestAlgorithm
        name = m.group(1).lower()
        if name not in ('count','length','value','item','key','current'): calls.add(name)
    for m in re.finditer(r'(?:(\w+)\.)?(\w+)\s*\(', body):
        prefix, name = m.group(1), m.group(2).lower()
        full = f'{prefix}.{name}' if prefix else name
        if full in CS_SKIP or name in ('exception','if','return'): continue
        if name in ('assert','fail') or full.endswith('.assert'): continue
        calls.add(name)
    for m in re.finditer(r'new\s+(?:[\w]+\.)*(\w+)\s*(?:<[^>]*>)?\s*\(', body):
        calls.add('new_'+m.group(1).lower())
    calls = {c for c in calls if not ('new_'+c) in calls}
    return calls

def java_asserts(body):
    kinds = {}
    for kind in ['assertTrue','assertEquals','assertNotNull','assertNull','assertArrayEquals','fail']:
        kinds[kind] = len(re.findall(r'\b'+kind+r'\s*\(', body))
    return kinds

def cs_asserts(body):
    return {'debug_assert': len(re.findall(r'Debug\.Assert\s*\(', body)),
            'throw': len(re.findall(r'throw\s+new\s+Exception', body)),
            'removed': len(re.findall(r'//\s*removed', body))}

def java_literals(body):
    # expected-value literals: quoted strings + numbers in assertions
    lits = set()
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"', body):
        s = m.group(1)
        if len(s) >= 2 and not s.startswith("'"):  # meaningful strings
            lits.add(s)
    for m in re.finditer(r'\b(\d+(?:\.\d+)?[dDfFLl]?)\b', body):
        lits.add(m.group(1).lower())
    return lits

def main():
    # build sample pool
    pool = []
    with open('compile_nofw_results.csv') as f:
        for r in csv.DictReader(f):
            if r['passed'] == 'True':
                pool.append(('old_benchmark', r['class'], r['number'], r['java_test_name']+'.java'))
    with open('pipeline_cs/method_report.csv') as f:
        for r in csv.DictReader(f):
            if r['test_body_translated'] == 'YES':
                pool.append(('new_pipeline', r['class'], r['number'], r['filename'].replace('.cs','.java')))
    print(f'Pool: {len(pool)} translated units')
    sample = random.sample(pool, 150)

    audit = []
    for ds, cls, num, java_fn in sample:
        if ds == 'old_benchmark':
            java_path = f'Java_benchmark/{cls}/{java_fn}'
            cs_paths = glob.glob(f'CsAPI_benchmark_translated/{cls}/*{num}*.cs')
        else:
            java_path = f'new_Java_test_cases/{cls}/{java_fn}'
            cs_paths = [f'pipeline_cs/03_CsAPI_test_cases/{cls}/{java_fn.replace(".java",".cs")}']
        row = {'dataset': ds, 'class': cls, 'number': num}
        jname, jb = java_body(java_path)
        row['java_method'] = jname or 'N/A'
        if not jb:
            row.update({'cs_method':'','api_mapped':'','asserts':'','literals_kept':'','verdict':'JAVA_BODY_PARSE_FAIL','run_pass':''})
            audit.append(row); continue
        cname, cb, cerr = cs_body(cs_paths[0] if cs_paths else '')
        row['cs_method'] = cname or cerr
        if not cb:
            row.update({'api_mapped':'','asserts':'','literals_kept':'','verdict':cerr or 'EMPTY_BODY','run_pass':''})
            audit.append(row); continue
        jc, cc = java_api_calls(jb), cs_api_calls(cb)
        # get-prefix normalization: getXxx ~ Xxx (property or method)
        jc_norm = {c[3:] if c.startswith('get') else c for c in jc}
        cc_norm = {c[3:] if c.startswith('get') else c for c in cc}
        mapped = jc_norm & cc_norm
        row['api_mapped'] = f'{len(mapped)}/{len(jc)}'
        ja, ca = java_asserts(jb), cs_asserts(cb)
        row['asserts'] = f'java:{sum(ja.values())}(T{ja["assertTrue"]}E{ja["assertEquals"]}N{ja["assertNotNull"]}U{ja["assertNull"]}A{ja["assertArrayEquals"]}F{ja["fail"]}) cs:{sum(ca.values())}(A{ca["debug_assert"]}T{ca["throw"]}R{ca["removed"]})'
        jl, cl = java_literals(jb), java_literals(cb)
        kept = jl & cl
        row['literals_kept'] = f'{len(kept)}/{len(jl)}'
        # run result from merged
        run = ''
        with open('pipeline_cs/merged_8895.csv') as f:
            for r in csv.DictReader(f):
                if r['dataset']==ds and r['class']==cls and r['number']==num:
                    run = r['run_pass']; break
        row['run_pass'] = run
        # verdict
        if len(mapped) == len(jc):
            if len(kept) == len(jl):
                verdict = 'consistent'
            else:
                verdict = 'minor_diff (literals)'
        elif len(mapped) > 0:
            verdict = 'minor_diff (partial api)'
        else:
            verdict = 'major_diff (no api mapped)'
        if jname and cname and jname.lower() != cname.lower().replace('_test_','_test_'):
            pass
        row['verdict'] = verdict
        audit.append(row)

    fields = ['dataset','class','number','java_method','cs_method','api_mapped','asserts',
              'literals_kept','run_pass','verdict']
    with open('/tmp/translation_audit.csv','w',newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(audit)
    from collections import Counter
    vc = Counter(r['verdict'].split(' ')[0] for r in audit)
    print(f'Audited: {len(audit)}')
    print(f'Verdicts: {dict(vc)}')

if __name__ == '__main__':
    main()
