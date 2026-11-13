#!/usr/bin/env python3
"""COMP01 specification limits — single source of truth.

Every constant derived from the official PROBLEM.pdf.
Import this everywhere; C code gets a generated header.
"""

# Machine
N = 1_048_576          # memory words (addresses 0..N-1)
ADDR_IN  = N - 2       # 1_048_574  — input port
ADDR_OUT = N - 1       # 1_048_575  — output port
WORD_BITS = 32
WORD_MIN = -(1 << 31)  # -2_147_483_648
WORD_MAX = (1 << 31) - 1  # 2_147_483_647
PC_START = 0

# Step limits
STEP_LIMIT_TIER12 = 100_000_000    # 10^8
STEP_LIMIT_TIER3  = 10_000_000_000 # 10^10

# v1 language limits
MAX_SOURCE_BYTES   = 60_000
MAX_HIDDEN_BYTES   = 20_000   # hidden Tier 2 programs
MAX_FUNCTIONS      = 200
MAX_PARAMS         = 8
MAX_NAME_LEN       = 24
MAX_RECURSION_DEPTH = 1_000
MAX_LITERAL_VALUE  = 2_147_483_647  # largest decimal literal in v1

# Tier 1 specific
REVERSE_MAX_BYTES  = 1_000
BIGMUL_MAX_DIGITS  = 40
HANOI_MAX_N        = 8

# Compilation
COMPILE_TIME_LIMIT_S = 60    # seconds

# Tier 3 targets (estimates, updated after M4S measurements)
TIER3_V1_SIZE_TARGET = 45_000   # bytes, target
TIER3_V1_SIZE_HARD   = 60_000   # bytes, hard limit
TIER3_STEP_TARGET    = 3_000_000_000  # 3×10^9 steps target for self-compile
TIER3_STEP_HARD      = 10_000_000_000 # 10^10 hard limit

# Stack sizing (derived)
# Stack region = (largest_recursive_block + 2) × (MAX_RECURSION_DEPTH + 1)
# Actual value computed after codegen is known

# Compile time target
COMPILE_TIME_TARGET_S = 10   # seconds, target for 20k/60k byte inputs
