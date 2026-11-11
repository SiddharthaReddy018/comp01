# Demo Q&A (short answers)

## Pointer access (self-modifying a/b/c fields)
SUBLEQ has no indirect addressing. To read `a[i]`: compute `ptr = base + i`, store `-ptr`.
Three instructions elsewhere in memory are "patch slots": clear a field (`F -= F`), then
`F -= negptr` so the field now holds `ptr`. The following instruction (already laid out with
placeholder `0` operands) then runs with the real address. Writes patch three fields
(clear.a, clear.b, store.a); reads patch one. Array base addresses and the field addresses are
filled after linking (`_arr_patches`, `tier2/core.py`; `pe`/array helpers in `tier3.v1`).
Pointers are kept negated so that patching is two instructions.

## Calls and returns
No return stack. Every function has a data cell `NRC_<fn>` holding `-return_address`.
Caller: `NRC = 0; NRC -= ret_cell` (ret_cell holds the address, filled at link time), copy
args to the callee's parameter cells, jump to entry. Epilogue: clear the `c` field of its
final jump, `c -= NRC` (so c = return address), execute the jump. Because the return address
is *data*, recursion works: a self-call pushes NRC, params, locals and temps onto a per-function
stack, calls, then pops. The earlier design patched RETJMP at the call site and broke when inner
calls overwrote the outer return target (see DESIGN_LOG). `MUL` is a leaf routine entered the
same way via `MUL_NRC`.

## How mul, signed compare and IO are built
- add `x += y`: `Z -= y; x -= Z; Z = 0` (negate through a scratch cell).
- mul: take absolute values, 31 unrolled shift-and-add steps over constants 2^30..1
  (`mr += mr; mb -= 2^i; if mb<0 undo else mr += ma`), apply sign. ~300 steps, exact for
  32-bit wrap including -2^31.
- signed `<` without overflow: if signs differ the answer is `a < 0`; if equal the difference
  cannot overflow so test `a - b < 0`. `==` tests `d<0` and `-d<0`.
- IO: `getc` is `x -= IN` style read (b = IN gives the byte or -1); `putc(e)` is `OUT -= (-e)`,
  where a = OUT prints the low 8 bits of `0 - mem[b]`.

## Tier 3 bootstrap and the C2 == C3 fixpoint
C1 = Tier2(tier3.v1) runs on the VM. C2 = C1(tier3.v1), C3 = C2(tier3.v1). C1 != C2 is expected
(Tier 2 and Tier 3 lay memory out differently). C2 == C3 because C2 and C3 are both produced by the
same compiler logic from the same source, so the compiler's output is a fixed point of
itself. It is not vacuous: C2 passes the same differential suite (169 programs) against the
`v1i.py` oracle, so it is also correct. 42,533 words.

## Changed-rule drills (where to edit)
| Rule change | Tier 2 (`tier2/core.py`) | Tier 3 (`tier3/tier3.v1`) |
|---|---|---|
| unary `!` | add token + `_parse_unary` node; emit `x = (x == 0)` via `_emit_signed_cmp` with zero | add token in `nt()`, handle in unary part of `pe`, emit compare-with-zero |
| `else if` | `if` parser: after `else` accept `if` as a single-statement block | `pb()` after `else`: if next token is `if`, parse one statement instead of a block |
| `%` | needs division loop: parse like `*`; emit repeated subtract or shift-subtract routine like MUL | new level in `lv()`, shared routine like `MUL` |
| bigger param limit | `MAX_PARAMS` | param arrays/caps in `tier3.v1` |
| `break` | loop stack of end labels; `break` = jump to current loop end | same via a loop-end patch chain (like return chain) |
| array bounds check | before `_emit_arr_read/_write`: compare idx with size, jump to halt (-1) | emit the same compare inside the array access helper |
| branch `<=0` instead of `<0` | see docs/CHANGES.md |
Always rerun: `make test` and `COMP01_KIT=<dir> make official`.
