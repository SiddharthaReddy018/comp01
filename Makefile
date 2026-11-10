# COMP01 Makefile
# Determinism: fixed hash seed, C locale
export PYTHONHASHSEED := 0
export LC_ALL := C

SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c

COMP01_KIT ?=
SKIP_OFFICIAL ?= 0
ARTIFACTS := artifacts/test-results

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

# Placeholder targets for future milestones
.PHONY: test-m1 test-m2 test-m3
.PHONY: test-m4a test-m4b test-m4s test-m4c test-m4d test-m4e
.PHONY: test-m5 test-m6 test-m7 test-m8 test-m9

test-m1 test-m2 test-m3 test-m4a test-m4b test-m4s test-m4c test-m4d test-m4e test-m5 test-m6 test-m7 test-m8 test-m9:
	@echo "Milestone $@ not yet implemented."
	@exit 1
