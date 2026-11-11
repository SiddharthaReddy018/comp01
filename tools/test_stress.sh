#!/usr/bin/env bash
# Worst-case size/time check: ~60KB (200 funcs) through C1 (tier3 compiled by tier2) and ~20KB through tier2.
# Verifies output word count < 2^20, steps < 1e10, and that compiled output matches tools/v1i.py.
set -euo pipefail
cd "$(dirname "$0")/.."; T=$(mktemp -d)
python3 tools/gen_stress.py 60000 1 200 > $T/s60.v1
python3 tools/gen_stress.py 20000 1 50  > $T/s20.v1
python3 tier2/compile.py < tier3/tier3.v1 > $T/C1.txt
for f in s20 s60; do
  want=$(python3 tools/v1i.py $T/$f.v1)
  s=$(date +%s); python3 tier2/compile.py < $T/$f.v1 > $T/$f.t2; t=$(( $(date +%s)-s ))
  [ "$(tools/vm $T/$f.t2 2>/dev/null)" = "$want" ] || { echo "FAIL $f tier2 output"; exit 1; }
  VM_STATS=1 VM_LIMIT=10000000000 tools/vm $T/C1.txt < $T/$f.v1 > $T/$f.c1 2> $T/$f.err
  w=$(wc -w < $T/$f.c1); st=$(sed -n 's/.*halted after \([0-9]*\) steps.*/\1/p' $T/$f.err)
  [ "$w" -lt 1048576 ] && [ "$st" -lt 10000000000 ] || { echo "FAIL $f limits w=$w steps=$st"; exit 1; }
  [ "$(VM_LIMIT=100000000 tools/vm $T/$f.c1 2>/dev/null)" = "$want" ] || { echo "FAIL $f C1 output"; exit 1; }
  echo "  OK $f: $(wc -c < $T/$f.v1) bytes, tier2 ${t}s, C1 steps=$st words=$w"
done
rm -rf $T
