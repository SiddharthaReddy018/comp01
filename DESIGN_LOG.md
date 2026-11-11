# COMP01 Design Log

What was tried, what failed, what was learned.

---

## M0 — Architecture Contracts

**Date:** 2026-11-10

**Decisions:**
- Two-pass compiler design chosen (pass 1: parse/count, pass 2: emit)
- Static function blocks with DAG + self-loop call graph
- Caller-owned temporaries, single RET cell for return values
- Stack sized for 1,000-deep recursion of the largest frame
- Performance targets: 215M ref / official parity gate / 300M stretch

**Open questions:** See docs/ASSUMPTIONS.md §10D

---

## M1-M3 - VM, assembler, reference tools
VM and assembler unit-tested (12/12 each). `v1i.py` is the semantic oracle; `gen.py` +
`minimize.py` give reproducible random programs and shrinking failures.

## M4 - Tier 2 compiler
- **Tried:** patching the callee's return jump at each call site. **Failed:** recursion
  (`fact3`, `recursion_max`): inner calls overwrite the outer return target.
- **Fixed:** data-driven return address `NRC_<fn>`, saved in recursive frames. 8/8 reference tests.

## M5 - Hardening
- `run_gen_test.py` only validated the generator; added `run_diff_test.py` (compiler vs `v1i`).
- First run: 98/100. Cause: `x = <expr using x>` compiled partial results straight into `x`.
  Fixed with a temp. 400/400 afterwards.

## M6 - bigmul, hanoi
Written in v1, compiled by Tier 2. bigmul max 1.6M steps, hanoi 0.4M. The first hanoi image
was 136k words (1000 x 128 stack): fixed in M7 prep by exact frame sizing and temp reuse.

## M7 - Tier 3
- **Tried (on paper):** porting `core.py` + `asm.py` to v1 bit-for-bit. Rejected: would exceed
  the 60 KB limit and needs lists/dicts v1 does not have.
- **Chose:** a one-pass compiler (no AST). Mutual recursion is forbidden in v1, so one
  `pe(level, dest)` and one `pb()`. Shared `MUL` and `COPY` routines keep code small.
- **Result:** 13.7 KB. Worked on the first end-to-end run (68/68 differential).
- Hit: Tier 2 link time was quadratic in data cells; fixed with offset dicts.
- Hit: a 55 KB dense program overflowed the 200k-word code buffer; raised to 380k.

## M8 - Bootstrap
C2 == C3 bitwise (42,533 words). Self-compile 170M steps (target 3e9). C2 re-validated by
the differential suite so the fixpoint is not trivially true.

## M9 - Docs and demo
`docs/EXPLAIN.md`, `docs/CHANGES.md`, `make demo`, `make test`.

## Post-M9 review against PROBLEM.pdf
- Branch condition: PROBLEM.pdf and the official `VM_tier1and2` (probe run in Docker) both use
  strict `r < 0`, so all codegen is right. (A pasted brief said `<=`; it was wrong.)
- **Multiply was too slow.** Repeated addition made `x * 1103515245` cost more than 2e10 steps
  (limit 1e8), which would fail any PRNG/hash test. Replaced in Tier 2 and Tier 3 by a 31-step
  binary multiply (~300 steps, 7.8k steps for the 20-iteration LCG). It also fixes
  `(-2^31) * odd`. New reference test `tests/reference/mulbig.v1` (256 products vs `v1i`).
- `tier2/BUILD.md` was still a stub; written.


## Hardening pass (official-VM verification)
- Ran both official Linux ELF VMs directly. `make official`: **42/42 OK, fail=0** (4 Tier 1 programs,
  17 reference programs through Tier 2, 19 through C1 (reference + tier3 edge tests), boot2/boot3 on VM_tier3; was 26 before
  the new edge tests). C2 == C3 (42,533 words). `probe.txt` prints `A` on both VMs.
- Tier 1 byte-exact on the official VM: hanoi n=1..8 equals a reference generator (one move per
  line, trailing newline), max 405,526 steps; bigmul 157 cases incl. 0*0, 0*x, 40x40 digits,
  max 1.76M steps; echo/reverse on empty input and 1000 bytes.
- **Failed / found:** Tier 2 inlined the 31-step multiply (~1,400 words per `*`). A 20 KB
  program with many `*` produced 12.6M words, far over the 1,048,576-word memory.
  **Fix:** one shared `MUL` routine, entered through its own `MUL_NRC` cell with the same
  data-driven return as functions (`tier2/core.py`, `_emit_multiply` / `_emit_mul_routine`).
  Same 20 KB program: 524k words. Reference, differential and fixpoint suites unchanged.
- Earlier recursion bug (kept here on purpose): patching the callee's RETJMP at each call site
  made inner recursive calls overwrite the outer return address (`fact3`, `recursion_max`).
  Fixed by the per-function `NRC_<fn>` cell, which recursive frames save and restore like data.
- New reference tests: params8, io_edges (getc EOF, putc low 8 bits), cmp_literals (2e9 compares,
  wraparound, 2147483647), control (else { if }, while truthiness, local hides global),
  names_comments (24-char names), syntax_misc, deep_rec (depth 999), bigarray (1M-word array).
- `tools/gen_stress.py`: ~59 KB / 75-function program: C1 emits 131k words and the output matches
  the oracle; a 19 KB program through Tier 2 compiles in 0.2 s.
- **Known limit:** Tier 3 arrays are safe up to about 1,046,885 words (Tier 2: 1,047,133); the spec
  gives no maximum. Not changed, because editing `tier3.v1` changes C2/C3.
