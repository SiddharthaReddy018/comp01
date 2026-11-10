#!/usr/bin/env python3
"""Differential test: tier2 compiler + tools/vm vs tools/v1i.py on generated programs.
Usage: python3 tools/run_diff_test.py [N] [start_seed]"""
import sys, os, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tools.gen import generate

N = int(sys.argv[1]) if len(sys.argv) > 1 else 100
S0 = int(sys.argv[2]) if len(sys.argv) > 2 else 0
py = sys.executable
ok = fail = skip = 0
for seed in range(S0, S0 + N):
    src = generate(seed).encode()
    ref = subprocess.run([py, f'{ROOT}/tools/v1i.py', '/dev/stdin'], input=src,
                         capture_output=True, timeout=60)
    if ref.returncode != 0:
        skip += 1; print(f'  SKIP seed={seed}: v1i rc={ref.returncode}'); continue
    c = subprocess.run([py, f'{ROOT}/tier2/compile.py'], input=src,
                       capture_output=True, timeout=120)
    if c.returncode != 0:
        fail += 1; print(f'  FAIL seed={seed}: compile: {c.stderr.decode()[:120]}'); continue
    r = subprocess.run([f'{ROOT}/tools/vm', '/dev/stdin'], input=c.stdout,
                       capture_output=True, timeout=120,
                       env=dict(os.environ, VM_LIMIT='1000000000'))
    if r.returncode == 0 and r.stdout == ref.stdout:
        ok += 1
    else:
        fail += 1
        print(f'  FAIL seed={seed}: vm rc={r.returncode} got={r.stdout[:40]!r} want={ref.stdout[:40]!r}')
print(f'  Differential: {ok}/{N} pass, {fail} fail, {skip} skipped')
sys.exit(0 if fail == 0 else 1)
