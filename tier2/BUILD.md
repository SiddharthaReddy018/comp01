# Tier 2: building and running the v1 compiler

The compiler is written in Python 3 (standard library only; developed on 3.12). There is
nothing to build.

## Run

```bash
python3 tier2/compile.py < program.v1 > program.txt     # compile: v1 source -> machine words
tools/vm program.txt < input.txt                         # run on the machine
```

The compiler reads the whole v1 program from standard input and prints
whitespace-separated decimal words (the format `vm` reads) to standard output.
Exit status is non-zero and a message goes to standard error on a compile error.
Output is deterministic (no dependence on hash order or time).

## Build the local VM (macOS / Linux)

```bash
gcc -O2 -o tools/vm tools/vm.c      # the official ./vm is a drop-in replacement
```

## Test

```bash
make test-m4        # reference programs, expected outputs
make test-m5        # 100 random programs vs the v1 interpreter (tools/v1i.py)
make test           # everything, including the Tier 3 bootstrap
```

## Layout

| File | Role |
|------|------|
| `tier2/compile.py` | entry point (reads stdin, writes stdout) |
| `tier2/core.py` | lexer, parser, code generator |
| `tools/asm.py` | assembler/linker with the SUBLEQ macros (copy, add, jump, ...) |
