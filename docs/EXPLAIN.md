# COMP01 Explanation Guide

How the toolchain works, end to end, and why each piece looks the way it does.

## 1. The machine and the language

**Machine (SUBLEQ).** 2^20 signed 32-bit words. One instruction `a b c`:
`mem[a] -= mem[b]; if (result < 0) pc = c else pc += 3` (strict `<`, as implemented in
`tools/vm.c` and written in `docs/ABI.md`). Reading operand `b = IN` yields the next stdin
byte or -1; writing with `a = OUT` prints the low 8 bits of `0 - mem[b]`. A jump outside
`0..N-3` halts.

**Language v1.** Top-level `var`, `array a[N]`, `func f(p, ...)`. Statements: local `var`,
assignment, array assignment, call, `if/else`, `while`, `return e;`, `putc(e)`, `getc()`.
Expressions: integers, `+ - *`, unary `-`, `< <= > >= == !=` (value 0/1), calls, indexing,
`getc()`, `putc(e)`. No division, no pointers, no strings. 32-bit wrap-around arithmetic.
Only direct self-recursion is allowed; functions are defined before use.

## 2. Pipeline and tiers

| Tier | What | Written in | Where |
|------|------|-----------|-------|
| 1 | Hand-written SUBLEQ: `echo`, `reverse`; `bigmul`, `hanoi` (v1 source compiled by Tier 2) | SUBLEQ / v1 | `tier1/` |
| 2 | v1 -> SUBLEQ compiler | Python (stdlib only) | `tier2/core.py`, `tier2/compile.py`, `tools/asm.py` |
| 3 | v1 -> SUBLEQ compiler, **in v1**, one pass | v1 | `tier3/tier3.v1` |

Reference tools: `tools/v1i.py` (v1 interpreter, the semantic oracle), `tools/gen.py`
(random valid-program generator), `tools/minimize.py`, `tools/vm.c` (VM), `tools/asm.py`
(assembler with macros).

## 3. Code generation model (shared by Tier 2 and Tier 3)

* **Static allocation.** Every global, parameter, local and temporary is one fixed memory
  cell. Fixed cells at 3..10: `NEG1, ZERO, ONE, RET, SP, S1, S2, S3`.
* **Primitive.** Everything is built from `sub(x,y)` = `x -= y` (instruction `x y next`).
  `copy`, `add`, `negate` go through scratch cells `S1/S2`. `bneg(x,L)` is the instruction
  `x ZERO L` (jump iff `x < 0`, `x` unchanged). Unconditional jump is `NEG1 ZERO L`.
* **Truth values.** Comparisons produce 0/1. Signed `<` handles overflow by testing signs
  first (different signs: answer is `a < 0`; same signs: the difference cannot overflow).
  Equality tests `x - y` for zero by two `bneg` probes (`v < 0`, `-v < 0`).
* **Self-modifying indirect access.** SUBLEQ has no indirect addressing, so array reads and
  writes *patch operand words of later instructions* with the computed address
  (clear the field, then subtract the negated pointer). Pointers are built negated
  (`np = -(base+idx)`) so patching takes two instructions.
* **Calls and returns without a return stack.** Each function has a cell `NRC` that holds
  `-return_address`. The caller sets it (`NRC = 0; NRC -= ret_cell`), then jumps to the
  entry. The epilogue patches the `c` field of its final jump from `NRC` (two
  instructions) and executes it. Because the address is *data*, nested/recursive calls can
  save and restore it like any other cell. (An earlier design patched the jump at each
  call site, which broke recursion: inner calls overwrote the outer return target.)
* **Recursion.** A self-call copies the caller's frame (NRC, params, locals, temps) onto a
  stack, evaluates arguments, calls, then restores the frame. Argument temps are evaluated
  *before* the push, so `f(n-1) + f(n-2)` is correct.
* **Temporaries** are allocated per expression node and released at the end of each
  statement (frames stay small: `hanoi.txt` went from 136k to 17k words).
* **Evaluation order** is strictly left to right; assignments evaluate into a temporary and
  then copy, so `x = 1 + x` and `x = f(x) + x` read the old `x`.

## 4. Tier 3: a compiler written in v1

`tier3/tier3.v1` (~13.7 KB, 44 functions) reads the program from stdin and writes the image.

**One pass, no AST.** Lexer, parser and code generator are fused: `pe(level, dest)` parses
and emits an expression into cell `dest`; `pb()` parses a block and emits statements.
v1 forbids mutual recursion, so each recursive construct lives in a single function:
`pe` handles every precedence level (and calls, indexing, parentheses), `pb` handles
nested blocks and statements. A call *statement* re-enters `pe(3, ...)` with the already
consumed name in `pnm`.

**Operands carry their region.** An operand is `kind*4194304 + value + 2`:
kind 0 absolute, 1 scalar-data region, 2 frame region. The final addresses are only known
at the end, so the output stage adds the region base. Layout of the produced image:

```
0..10   bootstrap + fixed cells      11..    code        then scalar data (S)
                  (zero-filled, NOT emitted:)  frames (F) | arrays (A) | recursion stack
```

Only code and scalar data are printed; the rest is zero memory the VM already provides.

**Frames are contiguous per function**, so a recursive call saves/restores them with one
shared `COPY` routine (a self-modifying loop) instead of per-cell code. `MUL` (sign
normalisation + 31 unrolled shift-and-add steps over constant cells 2^30..1) is a shared routine as well; both are emitted once
at the start of the image and called through the same `NRC` mechanism as user functions.

**Names** are interned through a 1024-bucket hash into ids; keywords are pre-interned, so
symbol tables are plain arrays indexed by id (global kind/cell, local cell).
**Forward jumps** use back-patching with the target stored in the placeholder `c` word;
returns chain through the same words and are resolved at the end of each function.

## 5. Bootstrapping

```
C1 = Tier2(tier3.v1)     python3 tier2/compile.py < tier3/tier3.v1
C2 = C1(tier3.v1)        tools/vm C1 < tier3.v1
C3 = C2(tier3.v1)        tools/vm C2 < tier3.v1
C2 == C3                 bitwise (40,662 words)
```
`C1 != C2` is expected: Tier 2 and Tier 3 lay memory out differently. The fixpoint proves
that C2 is a stable compiler, and the differential suite (below) proves it is a *correct*
one, so the fixpoint is not an artefact of a consistently-wrong compiler.

## 6. Verification

| Check | Command |
|-------|---------|
| VM / assembler units | `make test-m1` |
| Tier 2 vs oracle on reference tests | `make test-m4` |
| Tier 2 vs `v1i` on random programs | `make test-m5` (400 programs run during development) |
| Tier 1 programs vs Python oracles | `make test-m6` (bigmul 66 cases, hanoi n=1..8) |
| Tier 3 (C1) vs `v1i` | `make test-m7` (reference + edge + generated) |
| Fixpoint + C2 vs `v1i` | `make test-m8` |
| Everything + demo | `make test` |

Bugs the fuzzer found that hand-written tests did not: assignment aliasing
(`x = expr(x)` clobbering `x` mid-expression) and, earlier, recursion corrupting return
addresses.

## 7. Known limits

* Multiplication is a 31-step binary routine (about 300 steps per product, exact for the full 32-bit wrap including -2^31); it needs no division.
* `tier3.v1` assumes valid input (no diagnostics) and define-before-use for functions.
* Capacity: 380k code words, 110k scalar cells, 30k identifier characters, 4k distinct
  names per compile; a dense 55 KB program compiles in ~650M steps.
* The branch condition is strict `<`; if the official VM differs, `bneg` and the compare
  sequences are the only places that depend on it (see `docs/CHANGES.md`).
