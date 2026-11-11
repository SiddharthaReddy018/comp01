#!/usr/bin/env bash
# Replay our artifacts on the OFFICIAL VM binaries (Linux ELF) and compare with tools/vm.
# Usage: COMP01_KIT=/path/to/kit tools/official_check.sh          (needs docker; or run on Linux)
# Test the script itself with our own VM:  OFFICIAL_LOCAL=1 tools/official_check.sh
set -euo pipefail
export VM_LIMIT=10000000000
cd "$(dirname "$0")/.."
D=artifacts/test-results/official; rm -rf "$D"; mkdir -p "$D"
gcc -O2 -o tools/vm tools/vm.c
case_() {  # name program input-file-or-string kind(1|3)
  local n=$1 prog=$2 in=$3 kind=$4
  printf '%s' "$in" > "$D/$n.in"; cp "$prog" "$D/$n.prog"
  VM_LIMIT=10000000000 tools/vm "$prog" < "$D/$n.in" > "$D/$n.want"; echo "$kind" > "$D/$n.kind"
}
case_ echo   tier1/echo.txt    $'hello\nworld' 1
case_ rev    tier1/reverse.txt 'The quick brown fox' 1
case_ bigmul tier1/bigmul.txt  $'12345678901234567890\n98765432109876543210\n' 1
case_ hanoi  tier1/hanoi.txt   $'8\n' 1
for f in tests/reference/*.v1; do
  n=ref_$(basename "$f" .v1)
  python3 tier2/compile.py < "$f" > "$D/$n.txt"; case_ "$n" "$D/$n.txt" '' 1
done
python3 tier2/compile.py < tier3/tier3.v1 > "$D/C1.txt"
tools/vm "$D/C1.txt" < tier3/tier3.v1 > "$D/C2.ours"
for f in tests/reference/*.v1 tests/tier3/*.v1; do
  n=t3_$(basename "$f" .v1); cp "$f" "$D/$n.src"
  cp "$D/C1.txt" "$D/$n.prog"; VM_LIMIT=10000000000 tools/vm "$D/C1.txt" < "$f" > "$D/$n.want"
  cp "$f" "$D/$n.in"; echo 3 > "$D/$n.kind"
done
cp "$D/C1.txt" "$D/boot2.prog"; cp tier3/tier3.v1 "$D/boot2.in"; cp "$D/C2.ours" "$D/boot2.want"; echo 3 > "$D/boot2.kind"
tools/vm "$D/C2.ours" < tier3/tier3.v1 > "$D/C3.ours"
cp "$D/C2.ours" "$D/boot3.prog"; cp tier3/tier3.v1 "$D/boot3.in"; cp "$D/C3.ours" "$D/boot3.want"; echo 3 > "$D/boot3.kind"
cmp "$D/C2.ours" "$D/C3.ours" && echo "ours: C2 == C3"
cat > "$D/inner.sh" <<'IN'
#!/bin/sh
# runs inside the kit directory mount: $1 = VM1 path, $2 = VM3 path, $3 = case dir
fail=0; n=0
for k in "$3"/*.kind; do
  b=${k%.kind}; vm=$1; [ "$(cat $k)" = 3 ] && vm=$2
  "$vm" "$b.prog" < "$b.in" > "$b.got" 2>"$b.err" || true
  n=$((n+1))
  if cmp -s "$b.want" "$b.got"; then echo "  OK   $(basename $b)"; else echo "  FAIL $(basename $b)"; fail=1; fi
done
# bootstrap on official VM: its C2 and C3 must equal ours and each other
echo "official checked $n cases, fail=$fail"; exit $fail
IN
chmod +x "$D/inner.sh"
if [ "${OFFICIAL_LOCAL:-0}" = 1 ]; then
  "$D/inner.sh" "$PWD/tools/vm" "$PWD/tools/vm" "$D"
else
  : "${COMP01_KIT:?set COMP01_KIT to the kit directory}"
  docker run --rm --platform linux/amd64 -v "$COMP01_KIT":/kit:ro -v "$PWD":/w -w /w ubuntu:24.04 \
    "$D/inner.sh" /kit/VM_tier1and2 /kit/VM_tier3 "$D"
fi
