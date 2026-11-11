#!/usr/bin/env python3
"""Worst-case-size v1 program generator. Usage: gen_stress.py TARGET_BYTES [SEED] [NFUNCS]
Bodies are sized by search so output lands in [0.93*T, T]. Deterministic per (T, seed)."""
import sys, random

def nm(p, i, long_=False):
    n = p + '%03d' % i
    return (n + 'x' * 24)[:24] if long_ else n

def build(B, NF, seed):
    R = random.Random(seed)
    G = [nm('g', i, i % 4 == 0) for i in range(20)]
    A = [nm('a', i, True) for i in range(6)]
    out = [f'var {g};' for g in G] + [f'array {a}[64];' for a in A]
    fn = []
    for i in range(NF - 1):
        name = nm('f', i, i % 3 == 0)
        np_ = 8 if i % 25 == 0 else R.randint(0, 3)
        ps = [nm('p%d' % k, i, i % 40 == 0) for k in range(np_)]
        loc = [nm('l%d' % k, i, i % 40 == 0) for k in range(3)]
        pool = ps + loc + G
        def term():
            r = R.random()
            if r < .45: return R.choice(pool)
            if r < .65: return str(R.choice([0, 1, 2147483647, R.randint(0, 100000)]))
            if r < .85:
                a = R.choice(A)
                return f'{a}[{R.randint(0, 63)}]' if R.random() < .5 else \
                       f'{a}[({R.choice(pool)} < {R.choice(pool)}) + ({R.choice(pool)} == {R.choice(pool)})]'
            return '(' + R.choice(pool) + ' - ' + R.choice(pool) + ')'
        o = [f'func {name}({", ".join(ps)}) {{'] + [f'    var {l};' for l in loc]
        o.append(f'    {loc[0]} = 0; {loc[1]} = 0; {loc[2]} = 0;')
        used = 0
        while used < B:
            k = R.randint(1, max(1, min(40, (B - used) // 14)))
            ex = term()
            for _ in range(k): ex += ' ' + R.choice('+-*') + ' ' + term()
            if R.random() < .3: st = f'    {R.choice(A)}[{R.randint(0, 63)}] = {ex};'
            else: st = f'    {R.choice(loc + G[:5])} = {ex};'
            o.append(st); used += len(st)
            if R.random() < .2:
                s2 = (f'    if ({R.choice(pool)} < {R.choice(pool)}) {{ {loc[1]} = {loc[1]} + 1; }} '
                      f'else {{ if ({loc[2]} == 0) {{ {loc[2]} = 3; }} }}')
                o.append(s2); used += len(s2)
            if R.random() < .1:
                s3 = f'    {loc[0]} = 0; while ({loc[0]} < 3) {{ {loc[0]} = {loc[0]} + 1; }} // loop'
                o.append(s3); used += len(s3)
        if fn:
            pn, pc = next((x for x in reversed(fn) if x[1] <= 3), fn[-1])
            o.append(f'    {loc[1]} = {loc[1]} + {pn}({", ".join(R.choice(pool) for _ in range(pc))});')
        o += [f'    return {loc[0]} + {loc[1]};', '}']
        out += o; fn.append((name, np_))
    pn, pc = fn[-1]
    out += ['func main() {', '    var r;',
            f'    r = {pn}({", ".join(str(k) for k in range(pc))});',
            '    putc(48 + (r < 0));', '    putc(10);', '}']
    return '\n'.join(out) + '\n'

if __name__ == '__main__':
    T = int(sys.argv[1]); seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    NF = int(sys.argv[3]) if len(sys.argv) > 3 else 200
    lo, hi = 0, 4000
    best = build(0, NF, seed)
    for _ in range(14):
        mid = (lo + hi) // 2; s = build(mid, NF, seed)
        if len(s) <= T: best, lo = s, mid + 1
        else: hi = mid - 1
    sys.stdout.write(best)
