# Rule Change Drill Log

Design changes made while building, and a map of what to touch if a rule changes.
(No organiser-issued rule changes had been received when this was written.)

## Changes made during the project

| # | Change | Why | Where |
|---|--------|-----|-------|
| 1 | Return address moved from call-site patching to a per-function data cell (`NRC`) | Recursion overwrote the shared `RETJMP` target | `tier2/core.py` |
| 2 | Assignments evaluate into a temp, then copy | `x = 1 + x` read the clobbered `x` (found by fuzzing) | `tier2/core.py` |
| 3 | Recursion stacks sized to the real frame; temps reused per statement | `hanoi.txt` 136k -> 17k words; makes room for Tier 3 | `tier2/core.py` |
| 4 | O(1) data-offset lookups in assembler/linker | Quadratic link time on a 14 KB program | `tools/asm.py`, `tier2/core.py` |
| 5 | Added `tools/run_diff_test.py` | `run_gen_test.py` only validates the generator, it never ran the compiler | `tools/` |
| 6 | Tier 3 written directly in v1 (no transpiler) | One-pass design is far smaller than a port of `core.py` | `tier3/tier3.v1` |
| 8 | Binary multiply (31 unrolled steps) replaces repeated addition | `x * 1103515245` exceeded 2e10 steps; limit is 1e8 | `tier2/core.py`, `tier3/tier3.v1` |
| 9 | Tier 2 multiply is a shared routine (`MUL_ENTRY`, `MUL_NRC`) instead of inline per `*` | A mul-heavy 20 KB program emitted 12.6M words (> memory) | `tier2/core.py` |
| 7 | `tools/vm` untracked, rebuilt by `make test-m4` | A Linux binary was committed by mistake and broke macOS | `.gitignore`, `Makefile` |

## If a rule changes

| Rule | What to change |
|------|----------------|
| Branch is `<= 0` instead of `< 0` | `bneg`/`jz`/compare macros in `tools/asm.py` and `tier2/core.py`, and the matching helpers (`bnf`, `jz`, `cmpop`, `mkmul`) in `tier3.v1`. Probe `12 12 -1 1048575 13 6 15 16 -1 0 0 0 0 -65 0 -1 0` prints `A` under `<` (verified: the official VM and PROBLEM.pdf use strict `<`). |
| Memory size or I/O ports change | `tools/spec_limits.py`; port operands (`1048576`/`1048577`) in `tier3.v1` `gch`/`pch` |
| Source or function limits grow | Array caps at the top of `tier3.v1` (`code`, `di`, `pool`, `nms`, ...) |
| Larger recursion depth | Stack is a zero region, so no code change; check total memory fits |
| New operator | Add a token in `nt()`, a level in `lv()`, and emission in `eop()` (Tier 3); the same three places exist in `tier2/core.py` |
| Output format (e.g. one word per line) | `po()` in `tier3.v1`, `main()` in `tier2/core.py` |

`make official` replays every artifact on the official VM binaries (42 cases, all OK).
