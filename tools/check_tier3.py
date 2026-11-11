#!/usr/bin/env python3
"""Check tier3/tier3.v1 against the spec limits (size, functions, name length, params)."""
import re, sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tools import spec_limits as L
path = sys.argv[1] if len(sys.argv) > 1 else f'{ROOT}/tier3/tier3.v1'
src = open(path).read()
errs = []
if len(src.encode()) > L.MAX_SOURCE_BYTES: errs.append(f'size {len(src.encode())} > {L.MAX_SOURCE_BYTES}')
funcs = re.findall(r'\bfunc\s+(\w+)\s*\(([^)]*)\)', src)
if len(funcs) > L.MAX_FUNCTIONS: errs.append(f'{len(funcs)} functions > {L.MAX_FUNCTIONS}')
for n, ps in funcs:
    k = len([p for p in ps.split(',') if p.strip()])
    if k > L.MAX_PARAMS: errs.append(f'{n}: {k} params')
for n in set(re.findall(r'[A-Za-z_]\w*', src)):
    if len(n) > L.MAX_NAME_LEN: errs.append(f'name too long: {n}')
if '/*' in src: errs.append('block comment')
print(f'  tier3.v1: {len(src.encode())} bytes (target {L.TIER3_V1_SIZE_TARGET}), {len(funcs)} functions')
print('  limits: ' + ('FAIL ' + '; '.join(errs) if errs else 'OK'))
sys.exit(1 if errs else 0)
