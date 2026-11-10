# COMP01 ABI (Application Binary Interface)

**Version:** M0 — Architecture contracts. Updated as milestones progress.

---

## 1. Machine Recap

The COMP01 machine is a **SUBLEQ** (SUBtract and branch if Less than or EQual to zero) computer.

One instruction at address `pc` (three consecutive words `a`, `b`, `c`):

```
r     = mem[a] - mem[b]
mem[a] = r
if r < 0: pc = c
else:     pc = pc + 3
```

- **N = 1,048,576** words; addresses `0 .. N−1`; signed 32-bit wraparound
- **IN = N−2 = 1,048,574** — read as `b`: returns next input byte (0–255) or −1 at EOF
  - IN as `a` is an **error stop**
- **OUT = N−1 = 1,048,575** — always reads as 0
  - If `a == OUT`: prints low 8 bits of `r` (= `0 − mem[b]`), stores nothing
- **Normal halt:** `pc` goes outside `0 .. N−3` after a step
- **Error stop:** IN as first operand, or any operand outside `0 .. N−1`

---

## 2. Fixed Cell Layout

All fixed cells are placed at the beginning of every compiled image, right after the 3-word bootstrap jump at address 0.

```
Address | Symbol  | Initial value | Invariant
--------|---------|---------------|----------------------------------
0       | (bootstrap triple word 0) | NEG1_ADDR | part of jump to main
1       | (bootstrap triple word 1) | ZERO_ADDR | part of jump to main
2       | (bootstrap triple word 2) | main_entry | patched in pass 2
3       | ZERO    | 0             | always 0 (not emitted; natural)
4       | NEG1    | -1            | always -1 (emitted)
5       | ONE     | 1             | always +1 (emitted)
6       | RET     | 0             | function return value (caller-clobbered)
7       | SP      | 0             | stack pointer (index from stack_base)
8       | SCR1    | 0             | scratch cell 1
9       | SCR2    | 0             | scratch cell 2
10      | SCR3    | 0             | scratch cell 3
```

> **Note:** `ZERO` at address 3 is 0 and is NOT emitted (machine starts all words at 0).  
> `NEG1` at address 4 (value −1) and `ONE` at address 5 (value +1) ARE emitted.

**Bootstrap (addresses 0–2):**
```
(NEG1_ADDR=4, ZERO_ADDR=3, main_entry)
```
Effect: `r = −1 − 0 = −1 < 0` → `pc = main_entry`. NEG1 unchanged (mem[4] = −1). ✓

---

## 3. Calling Convention

### 3.1 Static Blocks (non-recursive functions)

Every function has a **fixed static block** allocated at compile time:

```
[ param_0 | param_1 | ... | param_P−1 | local_0 | ... | local_L−1 | temp_0 | ... | temp_T−1 | ret_slot ]
```

- **params:** one cell per parameter (P ≤ 8)
- **locals:** one cell per `var x;` declaration in the function
- **temps:** one cell per expression temporary (determined in pass 1)
- **ret_slot:** one cell holding the return address (address of caller's post-call instruction)

The call graph is a DAG plus self-loops (define-before-use rule, only self-recursion).
So non-recursive calls have unique static targets — static blocks are safe.

### 3.2 Non-Recursive Call Sequence

Calling `result = f(arg0, arg1)`:

```
Step 1: Evaluate arg0 → CALLER_TEMP0
Step 2: Evaluate arg1 → CALLER_TEMP1
        [ALL args evaluated before ANY copy to callee]

Step 3: Copy CALLER_TEMP0 → f.param0
Step 4: Copy CALLER_TEMP1 → f.param1

Step 5: Patch f.ret_slot ← (address after the call jump)
        [ret_slot address is a compile-time constant; patch its VALUE]
        This is a pointer-write to f.ret_slot's known address.

Step 6: Unconditional jump to f_entry:
        (NEG1, ZERO, f_entry)

--- f executes ---

Step 7: [addr_after_call]: Copy RET → CALLER_RESULT
        [immediately, before any further call that would clobber RET]
```

> **Key rule:** Arguments are evaluated into CALLER-owned temporaries. Callee
> parameter cells are written only AFTER all arguments are fully evaluated.
> This prevents `f(1, f(2,3))` from clobbering arg0 when evaluating arg1.

### 3.3 Return Sequence

At end of function (or at `return e;`):

```
Step 1: Evaluate e → expr_cell   [or use ZERO for fall-through return]
Step 2: Copy expr_cell → RET
Step 3: Indirect jump through ret_slot:
        [Since SUBLEQ's 'c' field is an immediate address, not a pointer,
         we use a self-modifying jump: at call time, the caller patched
         RETURN_JUMP_SITE+2 with the return address.
         RETURN_JUMP_SITE is a per-function 3-word cell:]

        (NEG1, ZERO, ret_addr)   ; ret_addr was patched in by caller
```

Each function owns a unique `RETURN_JUMP_SITE` triple whose `c` field is
patched by the caller before every call.

**Fall-through return 0:** The compiler emits at the end of every function body:
```
(ZERO, ZERO, next)      ; RET = 0 (clear ZERO into RET... actually:)
; Clear RET, then leave it at 0:
(RET, RET, +3)          ; RET ← 0
(NEG1, ZERO, ret_addr)  ; indirect jump (patched)
```

### 3.4 Self-Recursive Call Sequence

For a recursive call `result = f(arg0, arg1)` inside function `f`:

```
Step 1: Evaluate arg0 → CALLER_TEMP0
Step 2: Evaluate arg1 → CALLER_TEMP1

Step 3: PUSH — save entire static block onto stack:
        for each cell C in [param0..paramP, local0..localL, temp0..tempT, ret_slot]:
            mem[stack_base + SP] ← mem[C]
            SP += 1

Step 4: Copy CALLER_TEMP0 → f.param0
Step 5: Copy CALLER_TEMP1 → f.param1

Step 6: Patch RETURN_JUMP_SITE+2 ← (addr_after_recursive_call)

Step 7: Jump to f_entry:
        (NEG1, ZERO, f_entry)

--- recursive call executes ---

Step 8: [addr_after_recursive_call]:
        SAVE_RETVAL ← RET   [immediately! before POP restores temps]

Step 9: POP — restore static block from stack:
        SP -= block_size
        for each cell C in [param0..paramP, local0..localL, temp0..tempT, ret_slot]:
            mem[C] ← mem[stack_base + SP]
            SP += 1

Step 10: result is in SAVE_RETVAL
```

> **Important:** RET is **not** part of the saved block. It is copied into a
> caller-owned temp (`SAVE_RETVAL`) immediately after return and before the POP.
> Expression temporaries ARE part of the saved block (a temp may hold a partial
> value while the recursive call runs).

### 3.5 Stack Layout

```
Address              Contents
stack_base + 0       frame 0, cell 0
stack_base + 1       frame 0, cell 1
...
stack_base + B−1     frame 0, cell B−1 (B = block_size of recursive function)
stack_base + B       frame 1, cell 0
...
```

Stack region size: `(max_block_size + 2) × 1,001`
- `max_block_size`: the largest static block among all self-recursive functions
- `1,001`: supports recursion depth up to 1,000 (spec limit) plus one frame for the initial call
- `+2`: safety margin for SP and boundary checking

**SP semantics:**
- SP = 0 at program start (stack empty)
- Push: write cells to `stack_base + SP .. stack_base + SP + B−1`, then `SP += B`
- Pop: `SP -= B`, read cells from `stack_base + SP .. stack_base + SP + B−1`

**Overflow check (debug build):** After every push, verify `SP ≤ max_SP`.

---

## 4. Main Entry and Termination

```
Address 0: (NEG1_ADDR, ZERO_ADDR, main_entry)   ← bootstrap jump
```

- `main()` takes no parameters (called with no arguments from bootstrap)
- `main`'s `ret_slot` is **pre-initialized to −1** (value −1 in that cell)
- When `main` returns, the RETURN_JUMP_SITE jumps to the value in `ret_slot` = −1
- `pc = −1` is outside `0 .. N−3` → **normal halt, exit status 0** ✓

The main function's RETURN_JUMP_SITE `c` field is patched to `main.ret_slot_addr`
at compile time (not at runtime), and `main.ret_slot` is initialized to −1 at load
time... wait: since we emit the value −1 in main's ret_slot cell, the machine
starts with −1 there. The indirect jump sends pc = −1 → halt. ✓

**Testing main placement:** main must work correctly whether it is defined
first, last, or between other functions in the source.

---

## 5. Worked Machine-Instruction Examples

### Example 1: Unconditional Jump to address 42

```
Instruction at address 10: (4, 3, 42)
   a=4 (NEG1_ADDR), b=3 (ZERO_ADDR), c=42
   r = mem[4] - mem[3] = -1 - 0 = -1
   mem[4] = -1   (NEG1 unchanged)
   r < 0 → pc = 42  ✓
```

### Example 2: Clear cell at address 20

```
Instruction at address 10: (20, 20, 13)
   r = mem[20] - mem[20] = 0
   mem[20] = 0
   r = 0 → not taken → pc = 13  ✓
```

### Example 3: Copy mem[X=25] → T=30 (using SCR1=8 as Z)

```
Addr 10: (8, 8, 13)    ; Z=SCR1 ← 0
Addr 13: (8, 25, 16)   ; Z ← 0 - mem[25] = -X
Addr 16: (30, 30, 19)  ; T ← 0
Addr 19: (30, 8, 22)   ; T ← 0 - Z = 0 - (-X) = X  ✓
```

After: mem[30] = X, mem[8] = -X (Z holds -X; clean up with (8,8,...) if needed)

### Example 4: Add mem[Y=35] to T=30 (using SCR1=8 as Z)

```
Addr 22: (8, 8, 25)    ; Z ← 0
Addr 25: (8, 35, 28)   ; Z ← 0 - Y = -Y
Addr 28: (30, 8, 31)   ; T ← T - (-Y) = T + Y  ✓
```

### Example 5: putc(e) where e is in cell 50

Negate e into cell P=55, then print:

```
; Negate copy: P = -e (using Z=8, W=9)
Addr 31: (8, 8, 34)    ; Z ← 0
Addr 34: (8, 50, 37)   ; Z ← -e
Addr 37: (9, 9, 40)    ; W ← 0
Addr 40: (9, 8, 43)    ; W ← 0-(-e) = e
Addr 43: (55, 55, 46)  ; P ← 0
Addr 46: (55, 9, 49)   ; P ← 0 - e = -e

; Print
Addr 49: (1048575, 55, 52)  ; r = 0 - mem[55] = 0-(-e) = e; prints low 8 bits  ✓
```

### Example 6: getc() → result in cell V=60

```
Addr 52: (60, 60, 55)       ; clear V
Addr 55: (60, 1048574, 58)  ; V = 0 - IN = -byte  (or 1 at EOF since IN=-1 → V=0-(-1)=1)
; Negate: V_result = -V = byte (or -1 at EOF)
Addr 58: (8, 8, 61)         ; Z ← 0
Addr 61: (8, 60, 64)        ; Z ← -V
Addr 64: (60, 60, 67)       ; V ← 0
Addr 67: (60, 8, 70)        ; V ← 0-Z = 0-(-V_old) = V_old... wait

; After addr 55: V = 0 - byte = -byte
; After addr 61: Z = -V = -(-byte) = byte
; After addr 64: V = 0
; After addr 67: V = 0 - Z = 0 - byte = -byte  ← WRONG, we want byte

; Correction: use W as intermediary
Addr 58: (8,  8,  61)       ; Z ← 0
Addr 61: (8,  60, 64)       ; Z ← 0 - V = 0 - (-byte) = byte
Addr 64: (9,  9,  67)       ; W ← 0
Addr 67: (9,  8,  70)       ; W ← 0 - Z = 0 - byte = -byte ... still wrong!

; The DIRECT approach: after (60, IN, next): V = -byte.
; The v1 getc() contract: return byte (0..255) or -1 at EOF.
; After the read: V = -byte. So actual byte = 0 - V.
; We need to negate V in place.
; Negate-in-place using Z(=8) and W(=9):
Addr 58: (8,  8,  61)       ; Z ← 0
Addr 61: (8,  60, 64)       ; Z ← 0 - V = -(-byte) = byte  [Z = byte]
Addr 64: (9,  9,  67)       ; W ← 0
Addr 67: (9,  8,  70)       ; W ← 0 - Z = 0 - byte = -byte  [W = -byte]
Addr 70: (60, 60, 73)       ; V ← 0
Addr 73: (60, 9,  76)       ; V ← 0 - W = 0 - (-byte) = byte  ✓
```

After addr 73: `mem[60] = byte` (or −1 at EOF). ✓

### Example 7: Array Read  `T = a[i]`  (a base=100, i in cell=65, T=70)

```
; Compute addr = base + i into ADDR_CELL=75
; (copy of i plus constant 100)
...                             ; ADDR_CELL = 100 + mem[65]  (arithmetic)

; INST_SITE is a fixed 3-word template at compile-time address, say 200:
; Initially: (70, ???, 203)   where ??? = INST_SITE+1 = 201

; Patch INST_SITE+1 (addr 201) ← value of ADDR_CELL:
; (This is a pointer-write to address 201, which is a known compile-time constant)
; It's done the same as an array write but to a fixed address.

; Clear T (cell 70):
Addr X: (70, 70, X+3)

; Execute the patched instruction:
; INST_SITE+0 = 70 (T)
; INST_SITE+1 = addr (patched)
; INST_SITE+2 = next
; Executes: T = T - mem[addr] = 0 - mem[a[i]]  → T = -a[i]

; Negate T → T = a[i]  (using SCR1, SCR2)
...
```

Each array-access site owns its own INST_SITE — patch slots are never shared.

### Example 8: Array Write  `a[i] = e`

```
; SITE_CLEAR: (???, ???, next)   — to be patched with addr in both a and b fields
; SITE_WRITE: (???, NEG_E_CELL, next)  — to be patched with addr in a field

; Compute addr = base + i → ADDR_CELL
; Compute e → E_CELL
; Negate: NEG_E_CELL = -E_CELL

; Patch SITE_CLEAR+0 and SITE_CLEAR+1 ← ADDR_CELL value
; Patch SITE_WRITE+0 ← ADDR_CELL value

; Execute SITE_CLEAR: mem[addr] = mem[addr] - mem[addr] = 0
; Execute SITE_WRITE: mem[addr] = 0 - mem[NEG_E_CELL] = 0 - (-e) = e  ✓
```

### Example 9: Function Call  `result = f(x, y)`

Assume: f_entry=300, f.param0=310, f.param1=311, f.ret_slot=315,
        RETURN_JUMP_SITE at f=316 (3 words: 316,317,318).
        x in cell 50, y in cell 51. Caller owns TEMP0=80, TEMP1=81, RESULT=82.

```
; Evaluate args → caller temps (already done: TEMP0=x, TEMP1=y)

; Copy TEMP0 → f.param0
(SCR, SCR, +3)   ; SCR ← 0
(SCR, 80,  +3)   ; SCR ← -x
(310, 310, +3)   ; f.param0 ← 0
(310, SCR, +3)   ; f.param0 ← x  ✓

; Copy TEMP1 → f.param1 (similar)
...              ; f.param1 ← y  ✓

; Patch RETURN_JUMP_SITE+2 (addr 318) ← addr_after_call
; (Pointer-write to compile-time address 318)
...              ; mem[318] ← addr_after_call

; Jump to f:
(4, 3, 300)      ; pc ← 300  (NEG1, ZERO, f_entry)

; --- f executes, returns ---

; addr_after_call:
; Copy RET (cell 6) → RESULT (cell 82):
(SCR, SCR, +3)
(SCR, 6,   +3)   ; SCR ← -RET
(82,  82,  +3)   ; RESULT ← 0
(82,  SCR, +3)   ; RESULT ← RET  ✓
```

### Example 10: Recursion Save/Restore

For `f` calling itself, block = [param0=310, param1=311, local0=312, temp0=313, ret_slot=315],
block_size = 5, stack_base = 900000, SP_cell = 7.

```
; --- PUSH (before recursive call) ---
; Save block to stack_base + SP

; For each of the 5 cells, copy cell → mem[stack_base + SP_value + k]
; SP_value is dynamic (read from SP cell 7 at runtime)
; This requires runtime address computation (pointer write):
;   dest_addr = stack_base + SP_value + k (computed each step)
;   then write mem[dest_addr] ← source_cell

; After saving all 5 cells:
; SP += 5  (increment SP by block_size)
; (SCR ← 0; SCR ← -5; SP_cell -= SCR = SP_cell + 5)

; --- RECURSIVE CALL ---
; (same as non-recursive: copy new args, patch ret_slot, jump)

; --- POST-CALL ---
; SAVE_RETVAL ← RET  (copy RET immediately)

; --- POP (restore block from stack) ---
; SP -= 5
; For each cell k (0..4):
;   src_addr = stack_base + SP_value + k (computed)
;   copy mem[src_addr] → original_cell[k]
```

---

## 6. Signed Comparison  (overflow-safe)

Spec: compare TRUE signed values. Subtraction can overflow for mixed signs.

```
signed_lt(x, y):
  if sign(x) != sign(y):
      return 1 if x < 0 else 0   # sign of x determines
  else:
      d = x - y                   # same sign: no overflow
      return 1 if d < 0 else 0
```

Implemented as a shared subroutine. Called via standard call convention.
Arguments in dedicated cells `CMP_X`, `CMP_Y`. Returns 0 or 1 in RET.

Test cases required: (−2147483648, 1), (1, −2147483648), (2000000000, −2000000000),
(−2000000000, 2000000000), (0, 0), (−1, 0), (0, −1), (INT_MAX, INT_MIN).

---

## 7. Two-Pass Compilation

**Why two passes?**
1. Address 0 must jump to `main`, which may be defined anywhere in source
2. `if`/`while` require forward branch targets (branch destinations unknown in pass 1)
3. Single-pass with in-memory output buffer is impractical in C1 (memory is tight)

**Pass 1:** Walk source, count all instruction words, record:
- Function entry addresses (by definition order, sequence number)
- Label addresses (by sequence number within each function)
- Sizes of: constant pool, global scalars, global arrays, function blocks
- Result: exact address of every symbol

**Pass 2:** Re-walk the same source with known addresses:
- Emit (stream to stdout) every word as a decimal integer
- Assert at end: emitted word count == pass-1 count
- Assert: function addresses match, label addresses match

**Determinism:** Both passes run identically (same code path). Any divergence
is a compiler bug — caught by the pass-consistency assertion.

---

## 8. Constraint Summary

| Rule | Consequence |
|------|-------------|
| Define-before-use | No forward calls; call graph is DAG + self-loops |
| Only self-recursion | Static blocks safe for non-self calls |
| No `var` start value | Never emit zeroing code for locals |
| Globals start at 0 | Never emit zeroing code for globals/arrays |
| Recursion ≤ 1,000 deep | Stack sized for 1,001 frames |
| IN never as `a` | getc uses `(T, IN, next)` — T is `a` |
| OUT always reads 0 | putc: `(OUT, neg_e_cell, next)` prints e |
| `c` is immediate address | Computed jumps require patching the `c` field |
| No division in v1 | Print decimal via subtraction; multiply via binary method |
| 32-bit signed wrap | Use unsigned intermediate arithmetic; no UB |
