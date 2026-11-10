#!/usr/bin/env python3
"""Run generator validation: generate N programs, run each through v1i.py."""
import sys, os, subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.gen import generate

N = int(sys.argv[1]) if len(sys.argv) > 1 else 100
v1i = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v1i.py')

ok = fail = 0
for seed in range(N):
    src = generate(seed)
    r = subprocess.run(
        [sys.executable, v1i, '/dev/stdin'],
        input=src.encode(), capture_output=True, timeout=15
    )
    if r.returncode == 0:
        ok += 1
    else:
        fail += 1
        print(f'  FAIL seed={seed}: {r.stderr.decode()[:100]}')

print(f'  Generator: {ok}/{N} valid')
sys.exit(0 if fail == 0 else 1)
