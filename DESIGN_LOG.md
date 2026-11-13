# COMP01 Design Log

What was tried, what failed, what was learned. Numbers are from the final tree.

## Design in one paragraph

Two compilers share one back end idea. Tier 2 (Python) parses to a syntax tree and emits SUBLEQ
through an assembler (`tools/asm.py`). Tier 3 (`tier3/tier3.v1`) is a one-pass compiler written in v1
with no tree, because v1 has no lists or dictionaries and mutual recursion is forbidden, so one
expression function `pe(level, dest)` and one block function `pb()` do all the work. Both tiers
emit the same code shapes, so every code generation change has to land in both. Frames are static
cells; recursion saves live cells on a stack.

## What failed, and what fixed it

| Problem | Cause | Fix |
|---|---|---|
| Recursion broke (`fact3`, `recursion_max`) | The callee's return jump was patched at each call site, so an inner call overwrote the outer return target | Data-driven return cell `NRC_<fn>`, saved and restored in recursive frames like any other cell |
| 98/100 on the first differential run | `x = <expr using x>` wrote partial results into `x` | Use a temp, later replaced by a precise rule (below) that proves when writing straight into `x` is safe |
| `run_gen_test.py` gave false comfort | It only validated the generator | Added `run_diff_test.py`: compiler output against the independent interpreter `v1i.py` |
| Multiply was far too slow | Repeated addition: `x * 1103515245` cost more than 2e10 steps (limit 1e8) | 31-step binary multiply in both tiers; later entered at the highest bit that can matter |
| 20 KB program with many `*` overflowed memory | The binary multiply was inlined, about 1,400 words per `*` | One shared `MUL` routine with its own return cell; literals 0..255 still expand inline |
| First hanoi image was 136k words | A 1,000-deep stack sized for 128 cells | Exact frame sizing and temp reuse |
| Tier 2 link time was quadratic | Data cells looked up linearly | Offset dictionaries |
| 55 KB dense program overflowed Tier 3's code buffer | Buffer too small | Raised to 380,000 words |
| Tier 2 crashed on recursion that appears only in an `if` or `while` condition | The recursion detector scanned statement values only, so no frame save was emitted | Scan conditions and call-statement arguments; test `rec_cond` |
| Tier 2 crashed on a local declared twice (for example in `if` and `else`) | Duplicate assembler label | Fresh cell per declaration, as Tier 3 already did; test `redecl` |

The last two were found by writing rule-change drills (adding `for`, `&&`, `++`, `/`, bare `return`)
against our own compiler and by differential tests against `v1i.py`.

## Tier 3 and the bootstrap

Porting `core.py` and `asm.py` to v1 bit for bit was rejected on paper: too large for the 60 KB limit and
it needs data structures v1 lacks. The one-pass design is 22,770 bytes with 57 functions.
`C1 = Tier2(tier3.v1)`, `C2 = C1(tier3.v1)`, `C3 = C2(tier3.v1)`; C2 == C3 at 52,056 words. Self-compile
takes 5.7e7 steps (limit 1e10). C2 is also run through the differential suite, so the fixpoint is not
trivially true.

## Optimizations (all in both tiers)

| Change | Idea | Measured effect |
|---|---|---|
| Inline double-and-add for `x * literal` (0..255) | No call to `MUL` | not measured on its own |
| Leaf operands in place, fused compare and branch | No copy to a temp, no separate flag | not measured on its own |
| Constant folding; assignment without a temp; literal array index as a plain cell | Fold `+ - *` with 32-bit wrap; write straight into `x` when `x` is only read on the left spine (and for a global, no call in a right operand); `a[3]` is a fixed cell | not measured on its own |
| Compare against literal 0 | SBN only branches on `< 0`, so test `x` directly; `x > 0` is `0 - x < 0`, guarded by an `x < 0` test because `0 - INT_MIN` wraps | loop with three zero compares: 195,083 to 45,051 steps (Tier 2) |
| Multiply entry dispatch; call arguments straight into callee parameters | Skip leading zero bits (exact: the accumulator is still 0); no copy when no later argument contains a call | multiply loop 71,998 to 38,582; call loop 36,556 to 30,556; `bigmul` worst case 962,189 to 646,989 |
| Leaf array indexes in place; commutative operand order | `a[i]` and `a[i] = v` use the cells directly; `y + x` becomes `x + y` | array loop of 500 iterations: 52,541 to 40,541 steps |

Rejected as not worth the risk: loop rotation (about 1 step in 16 per iteration, needs a second
parse of the condition in the one-pass compiler), inlining, common subexpressions, loop-invariant
motion (Tier 3 has no tree).

## Verification

- `make test`: 19 reference programs, 100 random programs against `v1i.py`, Tier 1 oracles
  (hanoi n = 1..8, bigmul 66 cases), Tier 3 differential, bootstrap.
- `make official`: replays 46 cases on the official Linux VMs, 0 failures. The branch rule is strict
  `r < 0` in the official VM, confirmed by running it directly.
- Stress: a 59 KB, 75-function program through Tier 3; a 20 KB program of multiplies through both tiers;
  200 chained functions; 900 globals.

## Known limits

- Largest global array that compiles and runs under Tier 3: 1,046,782 words (the spec gives no maximum).
- Each self-call site inlines a push and pop of every live cell (about 58 words per cell). A single
  20 KB function with 24 live locals and about 800 recursive call sites does not fit in memory, and
  Tier 3's 380,000-word code buffer would overrun first. Realistic programs use a tenth of that.
- Locals are function-scoped, not block-scoped. Declaring a name twice gives a new cell.
