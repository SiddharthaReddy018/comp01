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
