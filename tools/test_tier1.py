#!/usr/bin/env python3
"""Verify tier1/bigmul.txt and tier1/hanoi.txt on tools/vm against Python oracles."""
import subprocess, random, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VM = f'{ROOT}/tools/vm'
def run(prog, inp):
    r = subprocess.run([VM, f'{ROOT}/{prog}'], input=inp, capture_output=True,
                       env=dict(os.environ, VM_STATS='1', VM_LIMIT='100000000'))
    e = r.stderr.decode()
    return r.stdout, (int(e.split('halted after')[1].split()[0]) if 'halted after' in e else 10**9)
def hanoi(n, a, c, b):
    return '' if n == 0 else hanoi(n-1, a, b, c) + a + c + '\n' + hanoi(n-1, b, c, a)
random.seed(7); bad = 0; mx = 0
cases = [(0,0),(0,5),(7,8),(10**39,10**39),(10**40-1,10**40-1),
         (12345678901234567890, 98765432109876543210)]
cases += [(random.randrange(10**random.randint(1,40)), random.randrange(10**random.randint(1,40))) for _ in range(60)]
for x, y in cases:
    out, st = run('tier1/bigmul.txt', f'{x}\n{y}\n'.encode()); mx = max(mx, st)
    if out != f'{x*y}\n'.encode() or st >= 10**8: bad += 1; print('  FAIL bigmul', x, y)
print(f'  bigmul: {len(cases)-bad}/{len(cases)} ok, max steps {mx}')
mh = 0; hb = 0
for n in range(1, 9):
    out, st = run('tier1/hanoi.txt', f'{n}\n'.encode()); mh = max(mh, st)
    if out != hanoi(n, 'A', 'C', 'B').encode() or st >= 10**8: hb += 1; print('  FAIL hanoi', n)
print(f'  hanoi: {8-hb}/8 ok, max steps {mh}')
sys.exit(1 if bad or hb else 0)
