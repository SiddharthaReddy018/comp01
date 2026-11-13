# COMP01: Compile Yourself

A compiler for the small language **v1**, for a machine with one instruction (subtract, and jump if
the result is negative). It comes in three tiers, and the Tier 3 compiler is written in v1 and
compiles itself to a bitwise fixpoint (C2 == C3).

Python 3 standard library only. No build step. Written for the COMP01 problem in LLH-26.

## Status

| Item | Result |
|------|--------|
| Tier 1: `echo`, `reverse`, `bigmul`, `hanoi` | all correct; worst case 632,249 steps (limit 10^8) |
| Tier 2: v1 compiler in Python | 19 reference programs and a 100-program differential against an independent interpreter, all pass |
| Tier 3: v1 compiler in v1 (`tier3/tier3.v1`) | 22,770 bytes, 57 functions; differential against the interpreter, all pass |
| Bootstrap | C2 == C3, bitwise identical, 52,056 words; self-compile takes 5.7e7 steps (limit 10^10) |
| Official VM replay (`make official`) | 46 cases, 0 failures |

## Run it

```bash
# compile a v1 program and run it
python3 tier2/compile.py < program.v1 > program.txt
tools/vm program.txt < input.txt

# build the local VM first if tools/vm is missing (the official ./vm is a drop-in replacement)
gcc -O2 -o tools/vm tools/vm.c
```

Details are in `tier2/BUILD.md`.

## Run the tests

```bash
SKIP_OFFICIAL=1 make test    # everything except the replay on the official VM binaries (a few minutes)
make demo                    # short live tour of all three tiers
```

To also replay everything on the official VM binaries, point `COMP01_KIT` at the
`Compilers/COMP01` folder of the LLH-26 repo (needs Linux, or Docker on macOS):

```bash
export COMP01_KIT=/path/to/LLH-26/Compilers/COMP01
export VM_LIMIT=10000000000
make test && make official
```

## Repository layout

| Path | Contents |
|------|----------|
| `tier1/` | The four machine programs. `echo.txt` and `reverse.txt` are built by `tools/build_tier1.py`; `bigmul.txt` and `hanoi.txt` are compiled by our Tier 2 from `bigmul.v1` and `hanoi.v1` |
| `tier2/` | The v1 compiler in Python (`compile.py` entry point, `core.py` lexer, parser and code generator) and `BUILD.md` |
| `tier3/tier3.v1` | The v1 compiler written in v1: one pass, no syntax tree |
| `tools/` | VM (`vm.c`), assembler and linker (`asm.py`), independent interpreter and oracle (`v1i.py`), random program generator and minimizer, differential harnesses, stress generator, official-VM replay script |
| `tests/` | Reference programs with expected output, Tier 3 edge programs, a minimized fuzz case |
| `DESIGN_LOG.md` | What was tried, what failed, what was learned |

## How it works

- **The toolkit.** Copy, add, jump, and compare are built from the single instruction. Branching
  happens only when the result is below zero, so comparisons are written to be exact even when the
  subtraction would overflow (`2000000000 < -2000000000` is 0).
- **Pointer access.** SUBLEQ has no indirect addressing, so array reads and writes patch the
  address fields of their own instructions (self-modifying code), then run them.
- **Function calls.** Each function's locals are static cells. A return jumps through a
  per-function cell `NRC_<fn>` that the epilogue writes into the return instruction. Patching the
  return at each call site was tried and broke recursion, so `NRC` is data and recursive frames
  save and restore it like any other cell.
- **Recursion.** A self-call pushes the live cells of the frame on a stack and pops them after
  the call. The stack pointer is stored negated so the patch sequence is short.
- **Multiplication.** A 31-step binary multiply, entered at the highest bit that can matter;
  multiplication by a literal 0..255 is expanded inline.
- **Optimizations.** Constant folding, assignment without a temporary, literal array indexes read
  as plain cells, compare against zero in one or two instructions, call arguments written straight
  into the callee's parameters, operands read in place.
- **Self-hosting.** `C1 = Tier2(tier3.v1)`, `C2 = C1(tier3.v1)`, `C3 = C2(tier3.v1)`, and the test
  checks `C2 == C3`. C2 is also validated against the interpreter, so the fixpoint is not trivial.

## Known limits

- The largest global array that compiles and runs under Tier 3 is 1,046,782 words (the machine has
  1,048,576). The spec gives no maximum.
- Each self-call site inlines a push and pop of every live cell, which makes recursion fast but
  makes code larger. A single 20 KB function with about 24 live locals and 800 recursive call sites
  would not fit in memory. Ordinary programs are far below that.
- `%`, `/`, `&&`, `||`, `for` and `++` are not part of v1 and are rejected.
