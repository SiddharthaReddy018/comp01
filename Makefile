# COMP01 Makefile
# Determinism: fixed hash seed, C locale
export PYTHONHASHSEED := 0
export LC_ALL := C

SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c

COMP01_KIT ?=
SKIP_OFFICIAL ?= 0
ARTIFACTS := artifacts/test-results

$(ARTIFACTS):
	mkdir -p $(ARTIFACTS)

# Guard: official VM must be present unless SKIP_OFFICIAL=1
define check_kit
	@if [ "$(SKIP_OFFICIAL)" != "1" ]; then \
		if [ -z "$(COMP01_KIT)" ]; then \
			echo "ERROR: COMP01_KIT is not set. Set it or use SKIP_OFFICIAL=1"; \
			exit 1; \
		fi; \
		if [ ! -f "$(COMP01_KIT)/VM_tier1and2" ] || [ ! -f "$(COMP01_KIT)/VM_tier3" ]; then \
			echo "ERROR: VM binaries not found in COMP01_KIT=$(COMP01_KIT)"; \
			exit 1; \
		fi; \
	fi
endef

.PHONY: clean test demo

clean:
	rm -rf $(ARTIFACTS)/*
	@echo "Cleaned artifacts."

# M0: architecture contracts
.PHONY: test-m0 accept-m0
test-m0:
	@echo "=== M0: Architecture Contracts ==="
	@test -s docs/ABI.md          || { echo "FAIL: docs/ABI.md missing or empty"; exit 1; }
	@test -s docs/MEMORY_MAP.md   || { echo "FAIL: docs/MEMORY_MAP.md missing or empty"; exit 1; }
	@test -s docs/CODEGEN.md      || { echo "FAIL: docs/CODEGEN.md missing or empty"; exit 1; }
	@test -s docs/ASSUMPTIONS.md  || { echo "FAIL: docs/ASSUMPTIONS.md missing or empty"; exit 1; }
	@test -s tools/spec_limits.py || { echo "FAIL: tools/spec_limits.py missing or empty"; exit 1; }
	@python3 -c "import tools.spec_limits as s; assert s.N == 1048576" \
		|| { echo "FAIL: spec_limits.py import check failed"; exit 1; }
	@echo "PASS: All M0 contract documents present and spec_limits.py valid."

accept-m0: test-m0
	@echo "M0 ACCEPTED"

# ── M1: VM and assembler ──────────────────────────────────────────────────────
.PHONY: test-m1 accept-m1
test-m1: | $(ARTIFACTS)
	@echo "=== M1: VM and Assembler ==="
	@echo "--- Building VM ---"
	gcc -O2 -Wall -o tools/vm tools/vm.c 2>&1 | grep -v "unused function" || true
	@test -x tools/vm || { echo "FAIL: vm build failed"; exit 1; }
	@echo "--- Running assembler unit tests ---"
	python3 tools/asm.py
	@echo "--- Running v1i unit tests ---"
	python3 tools/v1i.py --test
	$(call check_kit)
	@if [ "$(SKIP_OFFICIAL)" = "1" ]; then \
		echo "OFFICIAL VM: NOT TESTED (SKIP_OFFICIAL=1)"; \
	else \
		echo "--- Official VM differential (TODO: 2000-program suite) ---"; \
		echo "OFFICIAL VM: NOT IMPLEMENTED YET"; \
	fi
	@echo "PASS: M1 local tests complete."

accept-m1: test-m1
	@echo "M1 ACCEPTED"

# ── M2: echo and reverse ──────────────────────────────────────────────────────
.PHONY: test-m2 accept-m2
test-m2: | $(ARTIFACTS)
	@echo "=== M2: Tier 1 — echo and reverse ==="
	@echo "--- Building tier1 programs ---"
	python3 tools/build_tier1.py
	@echo "--- Testing ECHO ---"
	@# Empty input
	@echo -n "" | tools/vm tier1/echo.txt | diff - /dev/null || { echo "FAIL: echo empty"; exit 1; }
	@echo "  PASS: echo empty"
	@# Single byte
	@echo -n "A" | tools/vm tier1/echo.txt | diff - <(echo -n "A") || { echo "FAIL: echo single"; exit 1; }
	@echo "  PASS: echo single byte"
	@# All byte values 1..255 (no NUL — VM stdin handling)
	@python3 -c "import sys; sys.stdout.buffer.write(bytes(range(1,256)))" | \
		tools/vm tier1/echo.txt | \
		diff - <(python3 -c "import sys; sys.stdout.buffer.write(bytes(range(1,256)))") || \
		{ echo "FAIL: echo all bytes"; exit 1; }
	@echo "  PASS: echo all bytes 1-255"
	@# Step count for 1000 bytes << 10^8
	@steps=$$(python3 -c "import sys; sys.stdout.buffer.write(b'x'*1000)" | \
		VM_STATS=1 VM_LIMIT=100000000 tools/vm tier1/echo.txt 2>&1 | \
		grep "halted after" | grep -o "[0-9]*" | head -1); \
	echo "  ECHO steps for 1000 bytes: $$steps"; \
	python3 -c "s=int('$$steps'); assert s < 100000000, f'too slow: {s}'"
	@echo "--- Testing REVERSE ---"
	@# Empty input
	@echo -n "" | tools/vm tier1/reverse.txt | diff - /dev/null || { echo "FAIL: reverse empty"; exit 1; }
	@echo "  PASS: reverse empty"
	@# Single byte
	@echo -n "Z" | tools/vm tier1/reverse.txt | diff - <(echo -n "Z") || { echo "FAIL: reverse single"; exit 1; }
	@echo "  PASS: reverse single"
	@# 5 bytes reversed
	@echo -n "Hello" | tools/vm tier1/reverse.txt | diff - <(echo -n "olleH") || { echo "FAIL: reverse 5"; exit 1; }
	@echo "  PASS: reverse 5 bytes"
	@# 1000 bytes
	@python3 -c "import sys; sys.stdout.buffer.write(bytes(range(1,101))*10)" | \
		tools/vm tier1/reverse.txt | \
		diff - <(python3 -c "import sys; sys.stdout.buffer.write(bytes(range(100,0,-1))*10)") || \
		{ echo "FAIL: reverse 1000"; exit 1; }
	@echo "  PASS: reverse 1000 bytes"
	@# Step count
	@steps=$$(python3 -c "import sys; sys.stdout.buffer.write(bytes(range(1,101))*10)" | \
		VM_STATS=1 VM_LIMIT=100000000 tools/vm tier1/reverse.txt > /dev/null 2>&1; \
		python3 -c "import sys; sys.stdout.buffer.write(bytes(range(1,101))*10)" | \
		VM_STATS=1 tools/vm tier1/reverse.txt 2>&1 | grep "halted after" | grep -o "[0-9]*" | head -1); \
	echo "  REVERSE steps for 1000 bytes: $$steps"; \
	python3 -c "s=int('$$steps'); assert s < 100000000, f'too slow: {s}'"
	$(call check_kit)
	@if [ "$(SKIP_OFFICIAL)" = "1" ]; then \
		echo "OFFICIAL VM: NOT TESTED (SKIP_OFFICIAL=1)"; \
	fi
	@echo "PASS: M2 complete."

accept-m2: test-m2
	@echo "M2 ACCEPTED"

# ── M3: v1 interpreter, gen, minimize ────────────────────────────────────────
.PHONY: test-m3 accept-m3
test-m3: | $(ARTIFACTS)
	@echo "=== M3: v1 interpreter, generator, minimizer ==="
	@echo "--- Reference suite (hand-written from spec) ---"
	@fail=0; for f in tests/reference/*.v1; do \
		name=$$(basename $$f .v1); \
		exp="tests/reference/$$name.expected"; \
		got=$$(PYTHONHASHSEED=0 LC_ALL=C python3 tools/v1i.py "$$f" 2>/dev/null); \
		want=$$(cat "$$exp"); \
		if [ "$$got" = "$$want" ]; then echo "  PASS: $$name"; \
		else echo "  FAIL: $$name"; echo "    got:  $$(echo $$got | head -c 80)"; \
		     echo "    want: $$(echo $$want | head -c 80)"; fail=1; fi; \
	done; test $$fail -eq 0
	@echo "--- v1i unit tests ---"
	python3 tools/v1i.py --test
	@echo "--- Generator: 100 valid programs ---"
	python3 tools/run_gen_test.py 100
	@echo "--- Minimizer self-tests ---"
	python3 tools/minimize.py --test
	@echo "PASS: M3 complete."

accept-m3: test-m3
	@echo "M3 ACCEPTED"

# ── M4: Tier 2 compiler ──────────────────────────────────────────────────────
.PHONY: test-m4 accept-m4 test-m5 accept-m5
test-m4: | $(ARTIFACTS)
	@echo "=== M4: Tier 2 compiler, reference suite ==="
	@gcc -O2 -o tools/vm tools/vm.c
	@fail=0; for f in tests/reference/*.v1; do \
		name=$$(basename $$f .v1); exp="tests/reference/$$name.expected"; \
		got=$$(python3 tier2/compile.py < "$$f" | tools/vm /dev/stdin 2>&1); want=$$(cat "$$exp"); \
		if [ "$$got" = "$$want" ]; then echo "  PASS: $$name"; \
		else echo "  FAIL: $$name (got: '$$got', want: '$$want')"; fail=1; fi; \
	done; test $$fail -eq 0
	@echo "PASS: M4 complete."

accept-m4: test-m4
	@echo "M4 ACCEPTED"

# ── M5: differential hardening ───────────────────────────────────────────────
test-m5: test-m4
	@echo "=== M5: differential fuzz (tier2+vm vs v1i), 100 programs ==="
	python3 tools/run_gen_test.py 100
	python3 tools/run_diff_test.py 100
	@echo "PASS: M5 complete."

accept-m5: test-m5
	@echo "M5 ACCEPTED"

.PHONY: accept-m6
test-m6: test-m5
	@echo "=== M6: Tier 1 bigmul + hanoi (compiled by Tier 2) ==="
	python3 tier2/compile.py < tier1/bigmul.v1 > tier1/bigmul.txt
	python3 tier2/compile.py < tier1/hanoi.v1 > tier1/hanoi.txt
	python3 tools/test_tier1.py
	@echo "PASS: M6 complete."

accept-m6: test-m6
	@echo "M6 ACCEPTED"

# ── M7: Tier 3 compiler (tier3/tier3.v1, written in v1) ─────────────────────
.PHONY: test-m7 accept-m7 test-m8 accept-m8
C1 = $(ARTIFACTS)/C1.txt
C2 = $(ARTIFACTS)/C2.txt
C3 = $(ARTIFACTS)/C3.txt
VMBIG = VM_LIMIT=10000000000

$(C1): tier3/tier3.v1 tier2/core.py tier2/compile.py | $(ARTIFACTS)
	python3 tier2/compile.py < tier3/tier3.v1 > $@

test-m7: test-m6 $(C1)
	@echo "=== M7: tier3.v1 (v1 compiler in v1), compiled by Tier 2 = C1 ==="
	@gcc -O2 -o tools/vm tools/vm.c
	python3 tools/check_tier3.py
	python3 tools/v1i.py tier3/tier3.v1 < tests/reference/fact3.v1 > /dev/null
	$(VMBIG) python3 tools/run_diff_tier3.py $(C1) 100
	@echo "PASS: M7 complete."

accept-m7: test-m7
	@echo "M7 ACCEPTED"

# ── M8: self-hosting triple bootstrap ────────────────────────────────────────
test-m8: test-m7
	@echo "=== M8: C1 = Tier2(tier3.v1); C2 = C1(tier3.v1); C3 = C2(tier3.v1) ==="
	$(VMBIG) tools/vm $(C1) < tier3/tier3.v1 > $(C2)
	$(VMBIG) tools/vm $(C2) < tier3/tier3.v1 > $(C3)
	@cmp $(C2) $(C3) && echo "  FIXPOINT: C2 == C3 (bitwise identical, $$(wc -w < $(C2)) words)"
	$(VMBIG) python3 tools/run_diff_tier3.py $(C2) 150 1000
	@echo "PASS: M8 complete."

accept-m8: test-m8
	@echo "M8 ACCEPTED"

# ── M9: docs + demo ──────────────────────────────────────────────────────────
.PHONY: test-m9 accept-m9 demo test
test-m9: test-m8
	@echo "=== M9: documentation and demo ==="
	@for f in docs/EXPLAIN.md docs/CHANGES.md DESIGN_LOG.md; do \
		test -s $$f || { echo "FAIL: $$f missing"; exit 1; }; \
		! grep -q "TBD after M9" $$f || { echo "FAIL: $$f still TBD"; exit 1; }; done
	@$(MAKE) --no-print-directory demo SKIP_OFFICIAL=1 > $(ARTIFACTS)/demo.log
	@echo "PASS: M9 complete."

accept-m9: test-m9
	@echo "M9 ACCEPTED"

test: test-m9

demo: $(C1)
	@gcc -O2 -o tools/vm tools/vm.c
	@echo "--- Tier 1: echo / reverse"
	@printf 'hello\n' | tools/vm tier1/echo.txt
	@printf 'abc\n' | tools/vm tier1/reverse.txt; echo
	@echo "--- Tier 1: bigmul (20-digit x 20-digit)"
	@printf '12345678901234567890\n98765432109876543210\n' | tools/vm tier1/bigmul.txt
	@echo "--- Tier 1: hanoi n=3"
	@echo 3 | tools/vm tier1/hanoi.txt | tr '\n' ' '; echo
	@echo "--- Tier 2: compile + run tests/reference/fact3.v1"
	@python3 tier2/compile.py < tests/reference/fact3.v1 | tools/vm /dev/stdin
	@echo "--- Tier 3: C1 = Tier2(tier3.v1); C2 = C1(tier3.v1); C3 = C2(tier3.v1)"
	@$(VMBIG) tools/vm $(C1) < tier3/tier3.v1 > $(C2)
	@$(VMBIG) tools/vm $(C2) < tier3/tier3.v1 > $(C3)
	@cmp $(C2) $(C3) && echo "fixpoint: C2 == C3 ($$(wc -w < $(C2)) words)"
	@echo "--- Tier 3: compile fact3.v1 with C2 and run it"
	@tools/vm $(C2) < tests/reference/fact3.v1 | tools/vm /dev/stdin

# Replay artifacts on the official VM binaries (needs docker or Linux; set COMP01_KIT)
.PHONY: official
official:
	tools/official_check.sh
