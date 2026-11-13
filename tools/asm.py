#!/usr/bin/env python3
"""
tools/asm.py — COMP01 SUBLEQ assembler with macro library.

Memory layout of every assembled program:
  addr 0: bootstrap triple word 0 = 3  (NEG1 addr)
  addr 1: bootstrap triple word 1 = 4  (ZERO addr)
  addr 2: bootstrap triple word 2 = code_start  → patched at link time
  addr 3: NEG1  = -1   (emitted)
  addr 4: ZERO  =  0   (naturally 0, not emitted)
  addr 5: ONE   = +1   (emitted)
  addr 6: RET   =  0   (function return value)
  addr 7: SP    =  0   (stack pointer)
  addr 8: SCR1  =  0   (scratch 1)
  addr 9: SCR2  =  0   (scratch 2)
  addr 10: SCR3 =  0   (scratch 3)
  addr 11..11+code_len-1: code
  addr 11+code_len..:    data cells

The bootstrap (3, 4, code_start) executes at pc=0:
  r = mem[3] - mem[4] = -1 - 0 = -1 < 0  → pc = code_start  ✓
  mem[3] = -1 (unchanged)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.spec_limits import N, ADDR_IN, ADDR_OUT

# Fixed cell addresses
FIXED = {
    'NEG1': 3, 'ZERO': 4, 'ONE': 5, 'RET': 6,
    'SP': 7, 'SCR1': 8, 'SCR2': 9, 'SCR3': 10,
}
NUM_FIXED = 11   # code starts at address 11; positions 0-10 reserved

class Assembler:
    def __init__(self):
        self._code  = []          # list of resolved/unresolved fields
        self._labels = {}         # label_name -> code word index
        self._data_names  = []    # ordered names
        self._data_sizes  = {}    # name -> int
        self._data_values = {}    # name -> [int, ...]

    # ── field normalization ──────────────────────────────────────────────────

    def _f(self, x):
        """Convert x to a storable field."""
        if isinstance(x, int):   return x
        if isinstance(x, tuple): return x          # tag: ('data',n), ('label',n), ('addr',n)
        if isinstance(x, str):
            if x in FIXED:       return FIXED[x]   # named fixed cell → int address
            return ('label', x)                     # forward/backward label ref
        raise TypeError(f"Bad field: {x!r}")

    def _emit3(self, a, b, c):
        self._code.append(self._f(a))
        self._code.append(self._f(b))
        self._code.append(self._f(c))

    # ── address helpers ──────────────────────────────────────────────────────

    def here(self):
        """Absolute address of the next instruction to be emitted."""
        return NUM_FIXED + len(self._code)

    def here_plus(self, n):
        return NUM_FIXED + len(self._code) + n

    def _next(self):
        """Address of the instruction 3 words after current position."""
        return NUM_FIXED + len(self._code) + 3

    # ── labels ───────────────────────────────────────────────────────────────

    def label(self, name):
        """Define a label at the current code position."""
        idx = len(self._code)
        if name in self._labels:
            raise ValueError(f"Duplicate label: {name!r}")
        self._labels[name] = idx
        return NUM_FIXED + idx

    # ── data allocation ──────────────────────────────────────────────────────

    def alloc(self, name, value=0):
        """Allocate a named scalar data cell. Returns a tag for use in instructions."""
        if name in self._data_sizes:
            raise ValueError(f"Duplicate: {name!r}")
        self._data_names.append(name)
        self._data_sizes[name] = 1
        self._data_values[name] = [int(value)]
        return ('data', name)

    def alloc_array(self, name, size, values=None):
        """Allocate a named array. Returns a tag."""
        if name in self._data_sizes:
            raise ValueError(f"Duplicate: {name!r}")
        self._data_names.append(name)
        self._data_sizes[name] = size
        vals = list(values) if values else [0] * size
        while len(vals) < size:
            vals.append(0)
        self._data_values[name] = vals
        return ('data', name)

    def _data_base(self):
        """Base address of data section."""
        return NUM_FIXED + len(self._code)

    def _data_offset(self, name):
        off = 0
        for n in self._data_names:
            if n == name:
                return off
            off += self._data_sizes[n]
        raise KeyError(name)

    # ── link ─────────────────────────────────────────────────────────────────

    def link(self):
        """Resolve all addresses. Returns list of ints (the program image)."""
        code_len = len(self._code)
        data_base = NUM_FIXED + code_len

        offs = {}; _o = 0
        for _n in self._data_names:
            offs[_n] = _o; _o += self._data_sizes[_n]

        def resolve(f):
            if isinstance(f, int):
                return f
            kind, name = f
            if kind == 'data':
                return data_base + offs[name]
            if kind == 'label':
                if name not in self._labels:
                    raise ValueError(f"Unresolved label: {name!r}")
                return NUM_FIXED + self._labels[name]
            if kind == 'data+':          # element of a data array: (name, index)
                return data_base + offs[name[0]] + name[1]
            if kind == 'addr':
                return name
            raise ValueError(f"Unknown tag kind: {kind!r}")

        code_start = NUM_FIXED  # always 11

        # Build output: 11 header words + code + data
        out = [
            3,            # addr 0: bootstrap triple a = NEG1_ADDR
            4,            # addr 1: bootstrap triple b = ZERO_ADDR
            code_start,   # addr 2: bootstrap triple c = code_start
            -1,           # addr 3: NEG1
            0,            # addr 4: ZERO
            1,            # addr 5: ONE
            0,            # addr 6: RET
            0,            # addr 7: SP
            0,            # addr 8: SCR1
            0,            # addr 9: SCR2
            0,            # addr 10: SCR3
        ]
        assert len(out) == NUM_FIXED

        for f in self._code:
            out.append(resolve(f))

        for name in self._data_names:
            for v in self._data_values[name]:
                out.append(int(v))

        return out

    # ── instruction macro ────────────────────────────────────────────────────

    def instruction(self, a, b, c):
        """Emit one raw SUBLEQ triple (a, b, c)."""
        self._emit3(a, b, c)

    # ── jump ─────────────────────────────────────────────────────────────────

    def jump(self, target):
        """Unconditional jump to target (int addr, label string, or data tag)."""
        self._emit3('NEG1', 'ZERO', target)

    # ── clear ────────────────────────────────────────────────────────────────

    def clear(self, x):
        """x ← 0.  Uses (x, x, next). 3 words."""
        xa = self._f(x)
        self._emit3(xa, xa, self._next())

    # ── copy ─────────────────────────────────────────────────────────────────

    def copy(self, src, dst, scratch='SCR1'):
        """dst ← src. 4 instr, 12 words. scratch ends = −src."""
        sa = self._f(src); da = self._f(dst); za = FIXED[scratch]
        self._emit3(za, za, self._next())   # Z ← 0
        self._emit3(za, sa, self._next())   # Z ← −src
        self._emit3(da, da, self._next())   # dst ← 0
        self._emit3(da, za, self._next())   # dst ← src ✓

    # ── add ──────────────────────────────────────────────────────────────────

    def add(self, src, dst, scratch='SCR1'):
        """dst += src. 3 instr, 9 words."""
        sa = self._f(src); da = self._f(dst); za = FIXED[scratch]
        self._emit3(za, za, self._next())   # Z ← 0
        self._emit3(za, sa, self._next())   # Z ← −src
        self._emit3(da, za, self._next())   # dst += src ✓

    # ── sub ──────────────────────────────────────────────────────────────────

    def sub(self, src, dst):
        """dst −= src. 1 instr, 3 words."""
        self._emit3(self._f(dst), self._f(src), self._next())

    # ── negate in place ──────────────────────────────────────────────────────

    def negate_inplace(self, x, scratch1='SCR1', scratch2='SCR2'):
        """x ← −x. 6 instr, 18 words."""
        xa = self._f(x); za = FIXED[scratch1]; wa = FIXED[scratch2]
        self._emit3(za, za, self._next())   # Z ← 0
        self._emit3(za, xa, self._next())   # Z ← −X
        self._emit3(wa, wa, self._next())   # W ← 0
        self._emit3(wa, za, self._next())   # W ← X
        self._emit3(xa, xa, self._next())   # X ← 0
        self._emit3(xa, wa, self._next())   # X ← −X_old ✓

    # ── branch if negative ───────────────────────────────────────────────────

    def branch_if_neg(self, x, target):
        """Branch to target if x < 0. x unchanged (x − 0 = x, stored back). 1 instr."""
        self._emit3(self._f(x), FIXED['ZERO'], self._f(target))

    # ── putc ─────────────────────────────────────────────────────────────────

    def putc(self, src, scratch='SCR1'):
        """Print low 8 bits of src. 3 instr, 9 words."""
        sa = self._f(src); za = FIXED[scratch]
        self._emit3(za, za, self._next())         # Z ← 0
        self._emit3(za, sa, self._next())         # Z ← −src
        self._emit3(ADDR_OUT, za, self._next())   # print 0−(−src) = src ✓

    # ── getc ─────────────────────────────────────────────────────────────────

    def getc(self, dst, scratch1='SCR1', scratch2='SCR2'):
        """Read one byte into dst. 8 instr, 24 words.
        dst = byte (0−255) or −1 at EOF."""
        da = self._f(dst); za = FIXED[scratch1]; wa = FIXED[scratch2]
        self._emit3(da, da, self._next())          # dst ← 0
        self._emit3(da, ADDR_IN, self._next())     # dst ← −byte (or +1 at EOF)
        # negate dst in place
        self._emit3(za, za, self._next())          # Z ← 0
        self._emit3(za, da, self._next())          # Z ← −dst = byte
        self._emit3(wa, wa, self._next())          # W ← 0
        self._emit3(wa, za, self._next())          # W ← −Z = −byte
        self._emit3(da, da, self._next())          # dst ← 0
        self._emit3(da, wa, self._next())          # dst ← 0−(−byte) = byte ✓


# ── unit tests ────────────────────────────────────────────────────────────────

def _test():
    import tempfile, subprocess, os as _os

    vm_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'vm')
    if not _os.path.exists(vm_path):
        print("SKIP: vm binary not found"); return True

    def run(words, stdin=b'', limit=None):
        env = dict(_os.environ)
        if limit: env['VM_LIMIT'] = str(limit)
        with tempfile.NamedTemporaryFile(suffix='.txt', mode='w', delete=False) as f:
            f.write(' '.join(str(w) for w in words)); fn = f.name
        try:
            r = subprocess.run([vm_path, fn], input=stdin,
                               capture_output=True, timeout=10, env=env)
            return r.returncode, r.stdout, r.stderr
        finally:
            _os.unlink(fn)

    ok = 0; fail = 0

    def check(name, words, stdin=b'', want_out=b'', want_rc=0):
        nonlocal ok, fail
        rc, out, err = run(words, stdin)
        if rc == want_rc and out == want_out:
            print(f"  PASS: {name}"); ok += 1
        else:
            print(f"  FAIL: {name}")
            print(f"    want rc={want_rc} out={want_out!r}")
            print(f"    got  rc={rc}      out={out!r} err={err!r}")
            fail += 1

    print("=== asm.py unit tests ===")

    # 1. PDF example (raw)
    check("PDF example prints A",
          [1048575,6,3, 7,8,-1, -65,-1,0], want_out=b'A')

    # 2. clear
    a = Assembler()
    xcell = a.alloc('X', 99)
    a.clear(xcell)
    a.jump(-1)
    check("clear: no crash", a.link())

    # 3. copy + print 'A'
    a = Assembler()
    neg65 = a.alloc('N', -65)
    dst   = a.alloc('D', 0)
    a.copy(neg65, dst)
    n = a.here_plus(3)
    a.instruction(ADDR_OUT, dst, n)
    a.jump(-1)
    check("copy + print A", a.link(), want_out=b'A')

    # 4. putc(66) = 'B'
    a = Assembler()
    v = a.alloc('V', 66)
    a.putc(v)
    a.jump(-1)
    check("putc(66)='B'", a.link(), want_out=b'B')

    # 5. getc then putc echo
    a = Assembler()
    ch = a.alloc('CH', 0)
    a.getc(ch)
    a.putc(ch)
    a.jump(-1)
    check("getc+putc echo 'X'", a.link(), stdin=b'X', want_out=b'X')

    # 6. add: 48+7=55='7'
    a = Assembler()
    acc = a.alloc('A', 48)
    addend = a.alloc('B', 7)
    a.add(addend, acc)
    a.putc(acc)
    a.jump(-1)
    check("add 48+7=55='7'", a.link(), want_out=b'7')

    # 7. negate_inplace(-65)=65='A'
    a = Assembler()
    v = a.alloc('V', -65)
    a.negate_inplace(v)
    a.putc(v)
    a.jump(-1)
    check("negate_inplace(-65)=65='A'", a.link(), want_out=b'A')

    # 8. branch_if_neg: skip 'N', print 'Y'
    a = Assembler()
    neg = a.alloc('NEG', -1)
    n_c = a.alloc('N_CH', ord('N'))
    y_c = a.alloc('Y_CH', ord('Y'))
    a.branch_if_neg(neg, 'skip')   # neg < 0 → jump to skip
    a.putc(n_c)                     # skipped
    a.label('skip')
    a.putc(y_c)
    a.jump(-1)
    check("branch_if_neg prints Y", a.link(), want_out=b'Y')

    # 9. IN as first operand → error exit 1
    words = [0]*11 + [ADDR_IN, 0, 0, 0, 0, -1]
    words[3] = -1; words[5] = 1   # NEG1=−1, ONE=1
    check("IN as a → error", words, want_rc=1)

    # 10. getc EOF → −1 → putc(−1 & 0xFF = 255)
    a = Assembler()
    ch = a.alloc('CH', 0)
    a.getc(ch)
    a.putc(ch)
    a.jump(-1)
    check("getc EOF=−1 → putc prints 255", a.link(), stdin=b'',
          want_out=bytes([255]))

    # 11. timeout → exit 2
    a = Assembler()
    top = a.here()
    a.jump(top)   # infinite loop
    rc, out, err = run(a.link(), limit=100)
    if rc == 2:
        print("  PASS: timeout → rc=2"); ok += 1
    else:
        print(f"  FAIL: timeout: rc={rc} err={err!r}"); fail += 1

    # 12. aliasing safety: clear(X) when X==SCR1 (should still work)
    a = Assembler()
    # SCR1 is at addr 8. Use it directly as a cell.
    # After clear(SCR1), SCR1=0. Then putc(SCR1) should print 0.
    a.clear('SCR1')
    a.putc('SCR1')   # print 0 & 0xFF = 0
    a.jump(-1)
    check("clear(SCR1) + putc = 0", a.link(), want_out=bytes([0]))

    print(f"\nResults: {ok} passed, {fail} failed")
    return fail == 0

if __name__ == '__main__':
    sys.exit(0 if _test() else 1)
