#!/usr/bin/env python3
"""Differential test of a Tier 3 compiler binary (SUBLEQ image run on tools/vm)
against tools/v1i.py.   Usage: run_diff_tier3.py COMPILER.txt [N] [start_seed]"""
import sys, os, subprocess, glob
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tools.gen import generate
comp = sys.argv[1]
N = int(sys.argv[2]) if len(sys.argv) > 2 else 100
S0 = int(sys.argv[3]) if len(sys.argv) > 3 else 0
env = dict(os.environ, VM_LIMIT='20000000000')
def check(src, label):
    ref = subprocess.run([sys.executable, f'{ROOT}/tools/v1i.py', '/dev/stdin'], input=src,
                         capture_output=True, timeout=120)
    if ref.returncode != 0: return 'skip'
    c = subprocess.run([f'{ROOT}/tools/vm', comp], input=src, capture_output=True, timeout=600, env=env)
    if c.returncode != 0 or not c.stdout.strip():
        print(f'  FAIL {label}: compile rc={c.returncode}'); return 'fail'
    r = subprocess.run([f'{ROOT}/tools/vm', '/dev/stdin'], input=c.stdout, capture_output=True,
                       timeout=300, env=env)
    if r.returncode == 0 and r.stdout == ref.stdout: return 'ok'
    print(f'  FAIL {label}: got={r.stdout[:40]!r} want={ref.stdout[:40]!r}'); return 'fail'
res = {'ok': 0, 'fail': 0, 'skip': 0}
for f in sorted(glob.glob(f'{ROOT}/tests/reference/*.v1')):
    res[check(open(f,'rb').read(), os.path.basename(f))] += 1
for f in sorted(glob.glob(f'{ROOT}/tests/tier3/*.v1')):
    res[check(open(f,'rb').read(), 'tier3/'+os.path.basename(f))] += 1
for seed in range(S0, S0 + N):
    res[check(generate(seed).encode(), f'seed={seed}')] += 1
print(f"  Tier3 differential: {res['ok']} ok, {res['fail']} fail, {res['skip']} skipped")
sys.exit(1 if res['fail'] else 0)
