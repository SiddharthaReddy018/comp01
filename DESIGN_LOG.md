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

## Open item
The brief text says branch on `r <= 0`; `vm.c` and `ABI.md` say `r < 0`. All codegen assumes
strict `<`. Verify on the official VM (probe in `docs/CHANGES.md`).

