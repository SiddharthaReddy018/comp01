#!/usr/bin/env python3
"""
tools/build_tier1.py — Build tier1/echo.txt and tier1/reverse.txt.

ECHO:    Copy every byte (including 0) from stdin to stdout until EOF.
REVERSE: Read up to 1000 bytes (no NUL in input), reverse and print.

Bigmul and hanoi are compiled from v1 source files by Tier 2 (see tier1/*.v1).

Usage:
    python3 tools/build_tier1.py         # builds echo.txt and reverse.txt
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.asm import Assembler, FIXED
from tools.spec_limits import ADDR_IN, ADDR_OUT

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def save(name, words):
    path = os.path.join(ROOT, 'tier1', name)
    with open(path, 'w') as f:
        f.write(' '.join(str(w) for w in words) + '\n')
    print(f"  wrote {path} ({len(words)} words)")
    return path

# ════════════════════════════════════════════════════════════════════════
# ECHO
# ════════════════════════════════════════════════════════════════════════
def build_echo():
    """
    Loop: ch=getc(); if ch<0: halt; putc(ch); goto loop
    ~39 steps/byte.
    """
    a = Assembler()
    ch = a.alloc('CH', 0)

    loop = a.here()
    a.getc(ch)
    a.branch_if_neg(ch, 'eof')
    a.putc(ch)
    a.jump(loop)

    a.label('eof')
    a.jump(-1)

    return a.link()

# ════════════════════════════════════════════════════════════════════════
# REVERSE
# ════════════════════════════════════════════════════════════════════════
def build_reverse():
    """
    Read phase: buf[0..cnt-1] = bytes from stdin; stop at EOF or cnt==MAX.
    Print phase: print buf[cnt-1], buf[cnt-2], ..., buf[0].

    Pointer WRITE (buf[ptr]=ch) using self-modifying SUBLEQ:
      WCLR: mem[ptr] -= mem[ptr]  → 0    (clear: a=ptr, b=ptr)
      WSTO: mem[ptr] -= mem[SCR3]         (store: a=ptr, b=SCR3=-ch → adds ch)

    Patching code-word at address K to hold V (K is a known literal):
      (K, K, next)         -- r = mem[K]-mem[K]=0, stored back: mem[K]=0
      (K, neg_v_cell, next)-- r = 0 - (-V) = V, stored back: mem[K]=V
    Post-link fixup: fill K into the 'a' (and 'b') fields of these instructions.

    CRITICAL: When calling copy(src, 'SCR1'), MUST use scratch='SCR2' to
    avoid aliasing (SCR1 as both scratch and destination corrupts the copy).
    """
    MAX = 1000
    a = Assembler()

    # ── data ────────────────────────────────────────────────────────────
    _buf  = a.alloc_array('BUF', MAX)
    _cnt  = a.alloc('CNT',  0)
    _idx  = a.alloc('IDX',  0)
    _ch   = a.alloc('CH',   0)
    _one  = a.alloc('ONE',  1)
    _max1 = a.alloc('MAX1', MAX - 1)
    _bbas = a.alloc('BBAS', 0)        # filled post-link with addr of BUF[0]
    _ptr  = a.alloc('PTR',  0)
    _nptr = a.alloc('NPTR', 0)        # = -ptr (computed at runtime)

    def mark(): return len(a._code)

    # ── PHASE 1: READ ────────────────────────────────────────────────────
    read_loop = a.here()

    # SCR1 = (MAX-1) - cnt; if SCR1 < 0 → cnt >= MAX → stop
    # Use SCR2 as scratch for copy to SCR1 (avoids SCR1 aliasing)
    a.copy(_max1, 'SCR1', scratch='SCR2')
    a.sub(_cnt, 'SCR1')           # SCR1 = (MAX-1) - cnt
    a.branch_if_neg('SCR1', 'done_read')

    a.getc(_ch)
    a.branch_if_neg(_ch, 'done_read')

    # ptr = bbas + cnt
    # Use SCR2 as scratch for copy to ptr (ptr is a data cell, not a fixed reg)
    a.copy(_bbas, _ptr, scratch='SCR1')
    a.add(_cnt, _ptr)

    # nptr = -ptr; use SCR1 as scratch
    a.copy(_ptr, _nptr, scratch='SCR1')
    a.negate_inplace(_nptr)

    # -- Patch WCLR[a] = ptr (clear then set) --
    wclr_a_p1 = mark(); a.instruction(0, 0, a.here_plus(3))
    wclr_a_p2 = mark(); a.instruction(0, _nptr, a.here_plus(3))

    # -- Patch WCLR[b] = ptr --
    wclr_b_p1 = mark(); a.instruction(0, 0, a.here_plus(3))
    wclr_b_p2 = mark(); a.instruction(0, _nptr, a.here_plus(3))

    # -- Patch WSTO[a] = ptr --
    wsto_a_p1 = mark(); a.instruction(0, 0, a.here_plus(3))
    wsto_a_p2 = mark(); a.instruction(0, _nptr, a.here_plus(3))

    # neg_ch → SCR3
    a.copy(_ch, 'SCR3', scratch='SCR1')
    a.negate_inplace('SCR3')

    # WCLR: mem[ptr] = 0  (a=ptr, b=ptr; both patched above)
    wclr = mark(); a.instruction(0, 0, a.here_plus(3))

    # WSTO: mem[ptr] = ch  (a=ptr; b=SCR3=-ch → mem[ptr]-=(-ch)=ch)
    wsto = mark(); a.instruction(0, 'SCR3', a.here_plus(3))

    a.add(_one, _cnt)
    a.jump(read_loop)

    # ── PHASE 2: PRINT REVERSED ──────────────────────────────────────────
    a.label('done_read')

    # idx = cnt - 1
    a.copy(_cnt, _idx, scratch='SCR1')
    a.sub(_one, _idx)

    print_loop = a.here()
    a.branch_if_neg(_idx, 'done_print')

    # ptr = bbas + idx
    a.copy(_bbas, _ptr, scratch='SCR1')
    a.add(_idx, _ptr)

    # nptr = -ptr
    a.copy(_ptr, _nptr, scratch='SCR1')
    a.negate_inplace(_nptr)

    # -- Patch RLRD[b] = ptr --
    rlrd_b_p1 = mark(); a.instruction(0, 0, a.here_plus(3))
    rlrd_b_p2 = mark(); a.instruction(0, _nptr, a.here_plus(3))

    # Clear SCR1
    a.clear('SCR1')

    # RLRD: SCR1 -= mem[ptr]  → SCR1 = -buf[idx]
    rlrd = mark(); a.instruction('SCR1', 0, a.here_plus(3))

    # ch = -SCR1 = buf[idx]
    a.clear(_ch)
    a.sub('SCR1', _ch)   # ch -= SCR1 → ch = -(-buf[idx]) = buf[idx]

    a.putc(_ch)
    a.sub(_one, _idx)
    a.jump(print_loop)

    a.label('done_print')
    a.jump(-1)

    # ── Link ─────────────────────────────────────────────────────────────
    words = a.link()
    code_len = len(a._code)
    data_base = 11 + code_len

    def da(name):
        """Absolute address of data cell `name`."""
        off = 0
        for n in a._data_names:
            if n == name:
                return data_base + off
            off += a._data_sizes[n]
        raise KeyError(name)

    def ca(off): return 11 + off

    # ── Post-link fixup ───────────────────────────────────────────────────

    # 1. Fill BBAS = address of BUF[0]
    words[da('BBAS')] = da('BUF')

    # 2. Patch WCLR[a] patching instructions
    wclr_a = ca(wclr)
    words[ca(wclr_a_p1) + 0] = wclr_a   # p1.a
    words[ca(wclr_a_p1) + 1] = wclr_a   # p1.b (self-clear)
    words[ca(wclr_a_p2) + 0] = wclr_a   # p2.a

    # 3. Patch WCLR[b] patching instructions
    wclr_b = ca(wclr) + 1
    words[ca(wclr_b_p1) + 0] = wclr_b
    words[ca(wclr_b_p1) + 1] = wclr_b
    words[ca(wclr_b_p2) + 0] = wclr_b

    # 4. Patch WSTO[a] patching instructions
    wsto_a = ca(wsto)
    words[ca(wsto_a_p1) + 0] = wsto_a
    words[ca(wsto_a_p1) + 1] = wsto_a
    words[ca(wsto_a_p2) + 0] = wsto_a

    # 5. Patch RLRD[b] patching instructions
    rlrd_b = ca(rlrd) + 1
    words[ca(rlrd_b_p1) + 0] = rlrd_b
    words[ca(rlrd_b_p1) + 1] = rlrd_b
    words[ca(rlrd_b_p2) + 0] = rlrd_b

    # Sanity
    assert words[da('ONE')]  == 1,       f"ONE={words[da('ONE')]}"
    assert words[da('MAX1')] == MAX - 1, f"MAX1={words[da('MAX1')]}"
    assert words[da('BBAS')] == da('BUF')
    assert len(words) <= 1_048_576 - 2

    return words


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--only', choices=['echo', 'reverse'])
    args = p.parse_args()

    if not args.only or args.only == 'echo':
        print("Building echo.txt ...")
        save('echo.txt', build_echo())

    if not args.only or args.only == 'reverse':
        print("Building reverse.txt ...")
        save('reverse.txt', build_reverse())

    print("Done.")
