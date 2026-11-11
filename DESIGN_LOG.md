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
C2 == C3 bitwise (40,662 words). Self-compile 170M steps (target 3e9). C2 re-validated by
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

