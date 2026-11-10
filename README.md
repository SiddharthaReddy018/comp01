# COMP01 — Self-Hosting Compiler

A correct, efficient, self-hosting compiler for the COMP01 one-instruction (SUBLEQ) machine.

## Quick Start

```bash
export COMP01_KIT="/path/to/LLH-26/Compilers/COMP01"
make test        # full suite
make demo        # live demo
```

## Structure

| Directory | Contents |
|-----------|----------|
| `docs/`   | ABI, memory map, codegen, assumptions |
| `tools/`  | VM, assembler, interpreter, fuzzer, transpiler |
| `tier1/`  | Hand-assembled programs (echo, reverse, bigmul, hanoi) |
| `tier2/`  | v1 compiler (Python) |
| `tier3/`  | Self-hosting compiler (v1) |
| `tests/`  | All test suites |
| `artifacts/` | Test results and benchmarks |

## Milestones

See DESIGN_LOG.md for what was tried and what failed.
