# COMP01 Codegen Reference

**Version:** M0 (machine idioms; estimates labeled; updated after M4S)**

---

## 1. Machine Instruction

One SUBLEQ instruction = three consecutive words `(a, b, c)`:

```
r = mem[a] - mem[b]
mem[a] = r
if r < 0: pc = c
else:     pc = pc + 3
```

All three fields are **absolute addresses**. Every `c` field is set to the
"next instruction" address unless a branch is desired.

---

## 2. Fixed Cell Layout

| Symbol | Offset from code_base | Invariant |
|--------|----------------------|-----------|
| ZERO   | +0 | always 0  |
| NEG1   | +1 | always −1 |
| ONE    | +2 | always +1 |
| RET    | +3 | function return value (caller-clobbered) |
| SP     | +4 | stack pointer (index into stack region) |
| SCR1   | +5 | scratch cell 1 (clobbered by idioms) |
| SCR2   | +6 | scratch cell 2 |
| SCR3   | +7 | scratch cell 3 |
| PATCH_A| +8 | owned patch slot for pointer writes |
| PATCH_B| +9 | owned patch slot for pointer reads |

`NEG1` and `ONE` are non-zero and **are emitted** in the image (at the fixed
address). `ZERO` is at address 3 and is naturally 0 — not emitted.

---

## 3. Core Machine Idioms

### 3.1 Unconditional Jump to `target`

```
(NEG1, ZERO, target)
```

`r = −1 − 0 = −1 < 0` → branch taken. `mem[NEG1] = −1` (unchanged).

**Words:** 3

---

### 3.2 Clear cell X

```
(X, X, next)
```

`r = mem[X] − mem[X] = 0`; `mem[X] = 0`. Branch: `r = 0` → not taken.

**Words:** 3

---

### 3.3 Copy X → T  (using SCR1 as scratch Z)

```
(Z, Z, +3)      ; clear Z
(Z, X, +3)      ; Z = 0 − X = −X
(T, T, +3)      ; clear T
(Z2,Z2,+3)      ; clear SCR2 (alias W)
(W,  Z, +3)     ; W = 0 − Z = 0 − (−X) = X
(T,  W, next)   ; T = 0 − X ... wait: T is cleared, so T = 0 − W = 0 − X
```

> Wait — corrected idiom (requires 2 scratch cells Z and W):
>
> ```
> Z  Z  +3      ; Z = 0
> Z  X  +3      ; Z = −X
> W  W  +3      ; W = 0
> W  Z  +3      ; W = 0 − (−X) = X
> T  T  +3      ; T = 0
> T  W  next    ; T = 0 − X ... still wrong!
> ```
>
> The key insight: `mem[a] = mem[a] − mem[b]`.
> After `T T +3`: T = 0.
> After `T W next`: T = 0 − mem[W] = 0 − X. WRONG!
>
> **Correct copy idiom:** To set T = X, we need T = 0 − (−X).
> Since `−X` is in Z after step 2:
> ```
> Z Z +3        ; Z = 0
> Z X +3        ; Z = 0 − X = −X
> T T +3        ; T = 0
> T Z next      ; T = 0 − Z = 0 − (−X) = X  ✓
> Z Z (cleanup) ; restore Z to 0 (optional, but good hygiene)
> ```
>
> This works because `T Z next` → `T = T − mem[Z] = 0 − (−X) = X`. ✓

**Canonical copy(X → T):** 4 instructions (12 words), 1 scratch cell Z.

```
Z  Z  +3      ;  Z ← 0
Z  X  +3      ;  Z ← 0 − X = −X
T  T  +3      ;  T ← 0
T  Z  next    ;  T ← 0 − (−X) = X
              ;  (Z = −X; caller clears if reused)
```

**Words:** 12 (+3 if Z cleanup needed)

---

### 3.4 Negate X in place  (using SCR1=Z, SCR2=W)

We want X_new = −X_old.

```
Z  Z  +3      ;  Z ← 0
Z  X  +3      ;  Z ← −X            (X unchanged — a=Z, b=X)
W  W  +3      ;  W ← 0
W  Z  +3      ;  W ← 0 − (−X) = X
X  X  +3      ;  X ← 0
X  W  next    ;  X ← 0 − X_old = −X_old  ✓
              ;  (Z=−X_old, W=X_old; clean up as needed)
```

**Words:** 18, 2 scratch cells.

---

### 3.5 Add Y to T  (T += Y, using SCR1=Z)

```
Z  Z  +3      ;  Z ← 0
Z  Y  +3      ;  Z ← −Y
T  Z  next    ;  T ← T − (−Y) = T + Y  ✓
              ;  Z cleanup optional
```

**Words:** 9

---

### 3.6 Subtract Y from T  (T −= Y)

```
T  Y  next    ;  T ← T − Y  (direct, 1 instruction!)
```

**Words:** 3

---

### 3.7 Conditional branch: if X < 0 goto `target`

```
(X, ZERO, target)
```

`r = X − 0 = X`. Branch taken iff `X < 0`. `mem[X]` is clobbered — X = X. ✓

**Words:** 3

---

### 3.8 Conditional branch: if X == Y goto `target`  (via tmp T)

```
; Copy X → T, subtract Y, branch if T == 0 (not directly testable)
; Instead: use two checks (T < 0 and T > 0, both skip the branch)
T  T  +3
T  Z  +3        ; T = X (copy via double-negate, see §3.3)
...             ; ... actually:
                ; compute D = X − Y in cell D
D  D  +3
D  Z  +3        ; D = X (copy X)
D  Y  +3        ; D = X − Y
                ; if D == 0, branch
                ; can't directly test == 0, so use two branches:
(D, ZERO, skip_if_neg)   ; if D < 0, don't branch  → fall through
(ZERO, D,  skip_if_pos)  ; r = 0 − D; if D > 0 (r < 0), don't branch
(NEG1, ZERO, target)     ; D == 0: take branch
skip_if_neg: ...
skip_if_pos: ...          ; merge point
```

This three-instruction idiom handles equality. Words: varies; typically ~18.

---

### 3.9 putc(e)

Evaluate `e` into cell T. Then negate T into cell P (= −e):

```
; P = −T (negate-and-copy)
P  P  +3
P  T  +3        ; P = 0 − T = −T = −e

(OUT, P, next)  ; r = 0 − mem[P] = 0 − (−e) = e; prints low 8 bits of e
```

**Key:** `a = OUT` triggers print. `r = mem[OUT] − mem[P] = 0 − (−e) = e`. ✓

**Words:** ~9

---

### 3.10 getc() → result in T

```
T  T  +3        ; clear T
(T, IN, next)   ; T = 0 − next_byte_or_−1

; Now T = −byte at EOF: T = −(−1) = 1 (since IN returns −1)
; The v1 value is v = 0 − T = byte (or −1 at EOF)
; We need to negate T to get the actual value:
; ... use negate idiom → V = −T
```

After `(T, IN, next)`: T = −b where b is the byte (0..255) or −1 at EOF.
So T = −b. The returned value must be b = 0 − T. We negate:

```
V  V  +3
V  T  +3        ; V = 0 − T = 0 − (−b) = b  ✓  (or −1 at EOF)
```

**Important:** IN can never be the first operand (error stop). Read IN exactly once per getc call.

**Words:** ~9

---

### 3.11 Array Read:  T = a[i]

The address `addr = base_a + i` is computed at runtime.

```
; Step 1: compute addr into cell ADDR_CELL
; (copy base_a + i into ADDR_CELL via arithmetic)

; Step 2: patch the 'b' field of a prepared instruction
; The instruction template is at a fixed address INST_SITE:
;   INST_SITE+0 = T_addr    (destination)
;   INST_SITE+1 = ???       (to be patched with computed address)
;   INST_SITE+2 = next_addr

; Patch INST_SITE+1 ← ADDR_CELL value:
; (This is itself a pointer write — see §3.12)
; Actually the patch slot INST_SITE+1 is known at compile time.
; We write ADDR_CELL's value there via a pointer-write sequence.

; Step 3: execute the now-patched instruction:
;   T = T − mem[addr]  → after clearing T: T = −mem[addr]
;   Then negate: T = mem[addr]
```

Each array-access site has its own dedicated patch slot (never shared).

---

### 3.12 Array Write:  a[i] = e

```
; Compute addr = base_a + i into ADDR_CELL
; Compute e into E_CELL
; Negate E into NEG_E: NEG_E = −e

; The instruction to patch is of the form (ADDR_CELL_VALUE, ZERO, next)
; which will do: mem[addr] = mem[addr] − 0 = mem[addr] ... no, that reads.

; For write, we need: mem[addr] = new_value
; Idiom:
;   First clear mem[addr] via patched self-clear: (addr, addr, next) [patched]
;   Then subtract (−e) from mem[addr]: (addr, NEG_E_CELL, next) [patched]
; Both instructions have addr patched into their 'a' (and first's 'b') fields.
; Each patch slot is owned exclusively by this site.
```

---

### 3.13 Function Call  (non-recursive: result = f(arg0, arg1))

```
; 1. Evaluate arg0 into CALLER_TEMP0
; 2. Evaluate arg1 into CALLER_TEMP1
;    (all args evaluated before any copy to callee)

; 3. Copy CALLER_TEMP0 → f.param0
; 4. Copy CALLER_TEMP1 → f.param1

; 5. Patch f's return-address slot: f.ret_addr ← addr_after_call
;    (via pointer-write idiom on the fixed slot address — it's a compile-time constant)

; 6. Jump to f's entry:
(NEG1, ZERO, f_entry)

; 7. addr_after_call: copy RET → CALLER_RESULT (before any further call)
copy RET → CALLER_RESULT
```

---

### 3.14 Function Return

At the end of function body, with result in expr_cell:

```
; Store result in RET:
copy expr_cell → RET   (or clear+store 0 for fall-through)

; Jump through the return-address slot (self-modifying via patch):
; The slot f.ret_addr holds the caller's return address.
; We jump to it:
(NEG1, ZERO, f.ret_addr_as_indirect_jump_target)
```

Actually, since `f.ret_addr` holds the address to jump **to**, we need an
indirect jump. This is a compiled-in unconditional jump whose `c` field IS
`f.ret_addr`. Since `c` is a fixed compile-time address (the slot), and
the slot's value is the runtime return address, the SUBLEQ machine jumps
to `mem[c]` only if the branch is taken — but `c` is not dereferenced!

**Key point:** SUBLEQ uses `c` as a direct program counter value, not as a
pointer. So `Return = jump to the value stored in f.ret_addr` requires a
**self-modifying jump**:

```
; Patch the 'c' field of a jump instruction with f.ret_addr's value.
; The jump instruction is at a fixed site JUMP_SITE (compile-time).
; At call time, the return address was stored directly in f.ret_addr_slot.
; At return time:
;   - f.ret_addr_slot contains the return address (a compile-time-known cell)
;   - Patch JUMP_SITE+2 ← value from f.ret_addr_slot
;   - Then: (NEG1, ZERO, ret_addr) where ret_addr was just patched in

; Alternative (simpler): store ret_addr in a cell, then:
(NEG1, ZERO, cell_holding_ret_addr)  ; BUT 'c' is not dereferenced!
```

The standard approach: `c` in a SUBLEQ instruction is an immediate address,
not a pointer. So to do a computed/indirect jump, we **patch the `c` field**
of a template jump instruction with the runtime value.

**Return sequence:**
```
; Given: f.ret_slot holds the return address (integer value = address of caller's next instruction)
; RETURN_JUMP_SITE is a fixed compile-time address with:
;   RETURN_JUMP_SITE+0 = NEG1_ADDR
;   RETURN_JUMP_SITE+1 = ZERO_ADDR
;   RETURN_JUMP_SITE+2 = ??? (to be patched at runtime)

; At call entry, the caller patches RETURN_JUMP_SITE+2 ← caller_next_addr
; (via a pointer-write to the known compile-time address RETURN_JUMP_SITE+2)

; At return:
(NEG1, ZERO, *)   ; * was patched to caller_next_addr — this IS the return jump!
```

Each function has its own `RETURN_JUMP_SITE`. Callers patch `RETURN_JUMP_SITE+2`
directly (since it's a compile-time constant address).

---

### 3.15 Recursive Self-Call  (self = f calling f)

```
; 1. Evaluate all args into CALLER_TEMPs (as normal)

; 2. Push current static block onto stack:
;    block = [param0..paramN, local0..localM, temp0..tempK, ret_site_value]
;    For each cell in block:
;      copy cell → mem[SP_base + SP_offset]
;      SP_offset++
;    SP += block_size

; 3. Copy CALLER_TEMPs → f.param0..paramN  (same as non-recursive call)

; 4. Patch RETURN_JUMP_SITE+2 ← addr_after_recursive_call

; 5. Jump to f_entry

; 6. addr_after_recursive_call:
;    Copy RET → SAVED_RETVAL (before restoring block, which clobbers temps)

; 7. Pop static block:
;    SP -= block_size
;    For each cell in block (reverse order):
;      copy mem[SP_base + SP_offset] → cell

; 8. Result in SAVED_RETVAL (use it as an expression operand)
```

---

## 4. Signed Comparison Runtime Subroutine

v1 comparison `x < y` must work correctly even when `x − y` overflows.

**Rule (from spec):** Compare TRUE signed values: `2000000000 < −2000000000` is 0
(false); `−2000000000 < 2000000000` is 1 (true).

**Algorithm:**
```python
# If signs differ: answer follows sign of x (the smaller half)
# If signs same: x − y cannot overflow, test its sign
def signed_lt(x, y):
    if x < 0 and y >= 0:
        return 1   # x negative, y non-negative → x < y
    if x >= 0 and y < 0:
        return 0   # x non-negative, y negative → x >= y
    # Same sign: subtraction is safe
    return 1 if (x - y) < 0 else 0
```

Implemented as a shared runtime subroutine (~80–120 words). Takes x, y via
dedicated parameter cells; returns 0 or 1 in RET.

---

## 5. Multiplication Runtime Subroutine

v1 has `*` but the SUBLEQ machine has no multiply instruction.

**Algorithm:** Binary method with early exit by bit length.
- Determine number of bits in |y| by comparing with precomputed powers of 2
  (stored in constant pool)
- For each bit of |y| from LSB: if bit set, add current_power_of_x to result
- Double current_power_of_x each iteration (via add-to-self)
- Fix sign after: if exactly one of x, y is negative, negate result
- Special case: `INT_MIN × −1 = INT_MIN` (wraparound)

**[ESTIMATE]** Target worst case: ~400 steps for 32×32-bit multiply. Small
operands (many zero bits) far cheaper. M4S will measure.

**Word count [ESTIMATE]:** ~200–300 words for the subroutine.

---

## 6. Decimal Printing

v1 has no division. Print a signed 32-bit integer without division.

**Algorithm:**
```
1. If x < 0: print '-', negate x (handle INT_MIN = −2147483648 specially)
2. Find highest power of 10 ≤ x (compare against: 1,10,100,...,1000000000)
3. For each power p from highest to 1:
     digit = 0
     while x >= p: x -= p; digit++
     print chr(digit + '0')
4. After all powers: print digit for units
```

No division needed — only subtraction and comparison against powers of 10.
Powers of 10 live in the deduplicated constant pool.

**[ESTIMATE]** ~50–200 steps per digit, ~10 digits maximum. M4S measures.

---

## 7. Tier 3 Code-Size Projection

**[ESTIMATE — replace with M4S measurements]**

| Construct | Estimated words |
|-----------|----------------|
| Assignment | ~15–25 |
| If/else | ~30–60 |
| While | ~40–70 |
| getc() | ~12 |
| putc(e) | ~12 |
| Non-recursive call | ~30–60 (depends on args) |
| Recursive call | ~200+ (push/call/pop) |
| Array read | ~30–50 |
| Array write | ~40–70 |
| Multiplication | (subroutine call) |
| Signed comparison | (subroutine call) |

**v1 source → machine words ratio:** ~15–25 words per source statement (est.)

**Tier 3 self-hosting compiler projections:**
- tier3.v1 source: target ≤ 45,000 bytes (hard limit 60,000)
- Statements in tier3.v1: ~1,500–2,500 estimated
- Code words: ~30,000–60,000 estimated
- Total with data, stack, tables: **[see MEMORY_MAP.md §3]**

**Step projection:** ~500–2,000 steps per source byte compiled.
For 60,000-byte input: ~30M–120M steps. Well within 10^10 limit.

**Two-pass vs single-pass:** Two-pass chosen because:
- Address 0 must jump to main (which may be defined anywhere)
- if/while need forward targets (branch destinations not yet known in pass 1)
- Single-pass with in-memory backpatch would require buffering output (too much memory in C1)
- M4S will confirm this is the right choice with measurements

> [!NOTE]
> Performance targets for `tools/vm.c`:
> - Initial reference: **215M steps/sec**
> - Hard gate: **same-machine official VM parity**
> - Stretch goal: **300M steps/sec**

---

## 8. Summary Table: Idiom Word Costs

| Operation | Words | Notes |
|-----------|-------|-------|
| Unconditional jump | 3 | |
| Clear X | 3 | |
| Copy X→T | 12 | 1 scratch |
| Negate X in-place | 18 | 2 scratch |
| Add Y to T | 9 | 1 scratch |
| Subtract Y from T | 3 | direct |
| Branch if X<0 | 3 | clobbers X |
| putc(e) | ~9 | |
| getc() | ~9 | |
| Call (2 args) | ~60 | copy args + patch + jump + copy RET |
| Return | ~15 | copy to RET + indirect jump |
| Recursive call (2 args) | ~200+ | push + call + pop |
| Array read a[i] | ~40 | patch + read |
| Array write a[i]=e | ~60 | patch + clear + write |
| Signed lt(x,y) | (call) | ~80–120 word subroutine |
| Multiply(x,y) | (call) | ~200–300 word subroutine |
| Print decimal | (call) | ~100–150 word subroutine |

*All figures are [ESTIMATES] pending M4S measurement.*
