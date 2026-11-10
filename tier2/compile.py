#!/usr/bin/env python3
"""
tier2/compile.py — Tier 2 compiler shim.

Usage:
    python3 tier2/compile.py < program.v1 > program.txt

Reads v1 source from stdin, writes SUBLEQ machine program to stdout.
"""
import sys
sys.setrecursionlimit(10000)
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tier2.core as core
core.main()
