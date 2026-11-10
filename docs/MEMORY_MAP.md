# COMP01 Memory Map and Capacity Table

**Version:** M0 (estimates; updated after M4S measurements)

---

## 1. Machine Summary

| Property | Value |
|----------|-------|
| Total words | N = 1,048,576 |
| Address range | 0 .. N−1 |
| Word size | 32-bit signed, wraparound |
| Input port IN | N−2 = 1,048,574 |
| Output port OUT | N−1 = 1,048,575 |
| Usable range | 0 .. N−3 = 1,048,573 |
| Program load | address 0, rest zero |

---

## 2. Compiled Program Image Layout (low → high addresses)

```
┌─────────────────────────────────────────────────────────┐  addr 0
│  Bootstrap (jump to main)                               │  3 words
│  SUBLEQ triple: (NEG1_ADDR, ZERO_ADDR, main_entry)      │
├─────────────────────────────────────────────────────────┤  addr 3
│  Fixed cells                                            │  10 words
│  ZERO=0, NEG1=−1, ONE=1, RET, SP                        │
│  SCRATCH1, SCRATCH2, SCRATCH3, PATCH_A, PATCH_B         │
├─────────────────────────────────────────────────────────┤  addr 13
│  Constant pool (deduplicated)                           │  ~50 words est.
│  Powers of 10 (1,10,100,...,10^9,10^10)                │
│  Other non-zero constants from expressions              │
├─────────────────────────────────────────────────────────┤  ~addr 63
│  Runtime subroutines                                    │  ~600 words est.
│  - signed_lt(x, y) → 1/0                               │
│  - signed_le, signed_gt, signed_ge (derived)           │
│  - multiply(x, y) → product                            │
│  - print_decimal(x)                                     │
│  - stack push/pop helpers                               │
├─────────────────────────────────────────────────────────┤  ~addr 663
│  Generated function code                                │  varies
│  (all function bodies in definition order)              │
│  main's address patched into bootstrap at addr 2        │
├─────────────────────────────────────────────────────────┤
│  Global scalars                                         │  ≤ 60,000 words
│  One word per `var g;` at module level                  │
├─────────────────────────────────────────────────────────┤
│  Global arrays                                          │  ≤ N−2 total
│  Contiguous, one word per element                       │
├─────────────────────────────────────────────────────────┤
│  Function static blocks                                 │  200 × ~40 est.
│  Per function: [params | locals | temps | ret_addr]     │
│  (zero-initialized → NOT emitted; above last code word) │
├─────────────────────────────────────────────────────────┤
│  (zero gap — not emitted, naturally zero in machine)    │
├─────────────────────────────────────────────────────────┤
│  Runtime stack                                          │  ≤ ~40,000 words
│  Grows upward from stack_base                           │
│  Size: (max_block + 2) × 1,001                          │
├─────────────────────────────────────────────────────────┤
│  (remaining gap to IN)                                  │
├─────────────────────────────────────────────────────────┤  addr 1,048,574
│  IN = N−2  (input port)                                 │  reserved
├─────────────────────────────────────────────────────────┤  addr 1,048,575
│  OUT = N−1 (output port)                                │  reserved
└─────────────────────────────────────────────────────────┘
```

> [!IMPORTANT]
> Only code words and **non-zero** constants are emitted. Zero data (globals,
> arrays, function blocks, stack) lives above the last emitted word and is
> naturally zero in the machine. Never emit zeroing code.

---

## 3. Tier 3 Compiler Memory Layout (C1 running on the VM)

When `tier3.v1` is compiled by Tier 2 to produce C1, C1 itself runs as a
SUBLEQ program and needs extra space for its compiler data structures.

```
┌─────────────────────────────────────────────────────────┐  addr 0
│  C1 code image (compiled tier3.v1)                      │  est. 50,000–120,000 words
├─────────────────────────────────────────────────────────┤
│  C1 global scalars and arrays                           │
│  - Function table: 200 × ~4 words = 800 words           │
│  - Variable table: ~2,000 entries × ~4 words = 8,000    │
│  - Label table: ~20,000 entries × 2 words = 40,000      │
│  - Name intern buffer: ~60,000 chars = 60,000 words     │
├─────────────────────────────────────────────────────────┤
│  Source buffer                                          │  60,000 words
│  One char per word (efficiency tradeoff; see §6)        │
├─────────────────────────────────────────────────────────┤
│  C1 function static blocks                              │  ~8,000 words est.
├─────────────────────────────────────────────────────────┤
│  C1 runtime stack                                       │  ~20,000 words est.
├─────────────────────────────────────────────────────────┤
│  Patch slots for pointer access in C1 itself            │  ~1,000 words est.
├─────────────────────────────────────────────────────────┤
│  (gap)                                                  │
├─────────────────────────────────────────────────────────┤  addr 1,048,574
│  IN / OUT                                               │
└─────────────────────────────────────────────────────────┘
```

**[ESTIMATE — replace after M4S]** The C1 budget equation:

```
C1_code + data_tables + source_buffer + func_blocks + stack ≤ 1,048,574

Est: 100,000  +  109,800  +  60,000  +  8,000  +  20,000 = 297,800  ← well within budget

Aggressive bound:
  200,000 + 150,000 + 60,000 + 10,000 + 40,000 = 460,000  ← still within N−2
```

---

## 4. Capacity Table

Every table is bounded by a spec rule. The compiler exits with an explicit
"internal limit" error on overflow — never silent corruption.

| Region | Size Formula | Max Words | Spec Source |
|--------|-------------|-----------|-------------|
| Bootstrap | fixed | 3 | §2A machine |
| Fixed cells | fixed | 10 | architecture |
| Constant pool | deduplicated; ≤ unique lits | ~100 est. | — |
| Runtime subroutines | fixed (multiply, cmp, print) | ~600 est. | §2C |
| Code (Tier 2 program) | f(source) | unbounded → checked | N−2 |
| Global scalars | ≤ source / 7 chars per decl | 8,571 | 60,000-byte source |
| Global arrays | Σ sizes | ≤ N−2 | spec allows up to N |
| Function table | 200 entries × ~4 words | 800 | 200 functions |
| Variable table per fn | ≤ 8 params + locals | ≤ 200×32 = 6,400 | 8 params, 24-char names |
| Function static block | params + locals + temps + 1 | ≤ 200×(8+…) | 200 functions |
| Source buffer (C1) | 1 word/char | 60,000 | 60,000-byte source |
| Label table (C1) | ~2 × words_emitted | ~200,000 | pass-2 assertion |
| Runtime stack | (max_block+2) × 1,001 | ≤ 40,000 est. | 1,000 recursion depth |
| Name intern buffer (C1) | Σ name lengths | ≤ 200×24 = 4,800 | 200 functions × 24 chars |

---

## 5. Budget Equation (compiled v1 program)

For any program compiled by Tier 2, the generated image must satisfy:

```
image_end ≤ N − 2  (= 1,048,574)

where:
  image_end = end_of_code + end_of_data + stack_top

Breakdown:
  end_of_code  = addr after last emitted instruction word
  end_of_data  = end_of_function_blocks  (zero data not emitted)
  stack_top    = stack_base + stack_size
  stack_base   = end_of_data  (placed directly after data)
  stack_size   = (max_recursive_block + 2) × 1,001
```

The compiler MUST reject any program where `stack_top + 2 > N - 2`
(the +2 ensures SP and SP+1 never reach IN or OUT).

---

## 6. Zero-Initialization Rule

Per spec §2A: "Program loaded at address 0, every other word is 0."

**Consequence:** The machine initialises all memory to zero before running.

| Data | Start value | Emit? |
|------|-------------|-------|
| Global scalars | 0 (spec) | No — natural |
| Global arrays | 0 (spec) | No — natural |
| Function params | undefined (spec) | No |
| Function locals | undefined (spec) | No |
| Temporaries | undefined | No |
| Stack | 0 (natural) | No |
| Fixed cells ZERO | 0 | No (at load time it's already 0; NEG1 and ONE are non-zero and ARE emitted) |

The only words **emitted** are:
1. Code instructions (all three fields of each SUBLEQ triple)
2. Non-zero constants (NEG1, ONE, constant pool)
3. Any initial values explicitly non-zero (none in v1 — spec says globals start at 0)

---

## 7. Address Calculation (Two-Pass)

### Pass 1
- Walk the entire source
- Count: words per function, constants (deduplicated), global scalars, array totals
- Record: function entry addresses (by definition order), label offsets (sequence numbers)
- Result: exact address of every symbol

### Pass 2
- Re-walk the same source with known addresses
- Emit (stream to stdout): every word as a decimal integer with spaces
- Assert at end: emitted word count equals pass-1 count
- Assert: no region overlaps, `image_end ≤ N − 2`

> [!NOTE]
> Pass 2 streams directly to stdout because C1's own image may occupy much
> of the machine's memory — there is no room for a large output buffer.

---

## 8. Overlap and Bounds Checks (compiler must verify)

After pass 1, before emitting:

```
assert 0 < code_start < data_start < stack_base < stack_top + 2 < N - 2
assert no region spans [N-2, N-1]  (IN/OUT must not be overwritten)
assert array total + global_scalars < N - code_size - stack_size - 2
```

On any failure:
```
sys.stderr.write("internal limit exceeded: <region>\n")
sys.exit(1)
```

---

## 9. Patch Slots for Pointer Access

Each array-read or array-write **site** in generated code owns exactly one
patch slot — a cell whose `a` or `b` field is modified at runtime to hold the
computed address. Patch slots are **never shared** between dynamic operations
that could overlap.

The number of patch slots equals the number of array access sites in the
source (counted in pass 1). They are placed in the data region, after function
blocks.

---

## 10. Stack Pointer Protocol

| Cell | Purpose |
|------|---------|
| SP | Current top of stack (index into stack region) |

- Stack grows upward: push increments SP by block_size
- Stack shrinks: pop decrements SP by block_size  
- Stack base address is a compile-time constant (placed in constant pool)
- Debug build: after each push, check `SP + block_size + 2 < N - 2`; on overflow emit a SUBLEQ sequence that halts the machine (error stop via invalid address)

---

*[ESTIMATE label: all numbers in §3–§5 are projections based on typical SUBLEQ
codegen ratios. M4S measurements will replace them with exact figures.]*
