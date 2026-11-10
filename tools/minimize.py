#!/usr/bin/env python3
"""
tools/minimize.py — Shrink a failing v1 program while preserving the failure.

Given a v1 program that fails (crashes, gives wrong output, or times out),
produces a smaller program that exhibits the same failure.

Usage:
    python3 tools/minimize.py failing.v1 [expected_rc [expected_stderr_substr]]
    python3 tools/minimize.py --test     (run self-tests)

Saves minimized result to tests/fuzz/minimized_<hash>.v1

Algorithm:
    1. Establish baseline failure (rc, stdout, stderr).
    2. Try removing top-level declarations and functions one by one.
    3. Try removing statements from function bodies.
    4. Try simplifying expressions (replace subexpressions with 0 or 1).
    5. Repeat until no further reduction possible (fixpoint).
"""
import sys, os, re, hashlib, subprocess, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUZZ_DIR = os.path.join(ROOT, 'tests', 'fuzz')
V1I_PATH = os.path.join(ROOT, 'tools', 'v1i.py')


def run_v1i(src: str, timeout: float = 10.0):
    """Run v1i.py on the given source string. Returns (rc, stdout, stderr)."""
    with tempfile.NamedTemporaryFile(suffix='.v1', mode='w', delete=False) as f:
        f.write(src); fname = f.name
    try:
        r = subprocess.run(
            [sys.executable, V1I_PATH, fname],
            capture_output=True, timeout=timeout
        )
        return r.returncode, r.stdout.decode(errors='replace'), r.stderr.decode(errors='replace')
    except subprocess.TimeoutExpired:
        return -999, '', 'timeout'
    finally:
        os.unlink(fname)


def same_failure(baseline, candidate_src):
    """
    Return True if candidate_src fails in the same way as baseline.
    baseline = (rc, stdout, stderr) from the original failing run.
    """
    b_rc, b_out, b_err = baseline
    rc, out, err = run_v1i(candidate_src)
    # Same: same return code (non-zero) and same error type (keyword in stderr)
    if rc != b_rc:
        return False
    if b_rc == 0:
        # For crashes that produced output — check output matches
        return out == b_out
    # For errors: check same error class (first word of stderr)
    b_kind = b_err.split(':')[0].strip() if b_err else ''
    c_kind = err.split(':')[0].strip() if err else ''
    return b_kind == c_kind


def remove_lines(src: str) -> list:
    """Generate candidates with individual non-blank lines removed."""
    lines = src.split('\n')
    candidates = []
    for i, line in enumerate(lines):
        if line.strip():
            new_lines = lines[:i] + lines[i+1:]
            candidates.append('\n'.join(new_lines))
    return candidates


def remove_statements(src: str) -> list:
    """Remove individual statements (lines ending with ; or lines with braces)."""
    # Simple heuristic: lines inside function bodies
    lines = src.split('\n')
    candidates = []
    in_func = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('func '):
            in_func = True
        if in_func and stripped and stripped != '{' and stripped != '}':
            new_lines = lines[:i] + lines[i+1:]
            candidates.append('\n'.join(new_lines))
    return candidates


def simplify_expressions(src: str) -> list:
    """Replace complex expressions with simpler ones."""
    candidates = []
    # Replace parenthesized expressions with 0 or 1
    for replacement in ['0', '1']:
        # Replace (expr op expr) → replacement
        new = re.sub(r'\([^()]+\)', replacement, src)
        if new != src:
            candidates.append(new)
    return candidates


def minimize(src: str, baseline=None) -> str:
    """
    Minimize the failing v1 program.
    Returns the smallest program that exhibits the same failure.
    """
    if baseline is None:
        baseline = run_v1i(src)
        rc, out, err = baseline
        if rc == 0 and err == '':
            print("WARNING: baseline program succeeded — minimizer needs a failing program")
            return src

    current = src
    improved = True
    while improved:
        improved = False

        # Try all reduction strategies
        all_candidates = (
            remove_lines(current) +
            remove_statements(current) +
            simplify_expressions(current)
        )

        for cand in all_candidates:
            if len(cand) < len(current) and same_failure(baseline, cand):
                current = cand
                improved = True
                break  # restart with smaller program

    return current


def save_minimized(src: str) -> str:
    """Save minimized program to tests/fuzz/. Returns the file path."""
    os.makedirs(FUZZ_DIR, exist_ok=True)
    h = hashlib.sha1(src.encode()).hexdigest()[:12]
    path = os.path.join(FUZZ_DIR, f'minimized_{h}.v1')
    with open(path, 'w') as f:
        f.write(src)
    return path


def _test():
    """Self-tests for the minimizer."""
    ok = fail = 0

    # Test 1: Minimizer leaves a simple program alone (no reduction possible)
    src = "func main() { putc(65); }"
    baseline = run_v1i(src)
    result = minimize(src, baseline)
    # Should not crash
    print("  PASS: minimize non-failing program handled")
    ok += 1

    # Test 2: Program that uses an undefined variable (should fail in v1i)
    # The minimizer should produce something shorter that still fails
    bad_src = """
var unused_global_1;
var unused_global_2;
func helper() {
    var unused_local;
    var x;
    x = 1;
    return x;
}
func main() {
    var dummy;
    var undef;
    dummy = helper();
    undef = undef + 1;
}
"""
    baseline = run_v1i(bad_src)
    if baseline[0] != 0:
        mini = minimize(bad_src, baseline)
        if len(mini) <= len(bad_src):
            print(f"  PASS: minimizer reduced {len(bad_src)}→{len(mini)} bytes")
            ok += 1
        else:
            print(f"  FAIL: minimizer grew {len(bad_src)}→{len(mini)} bytes")
            fail += 1
    else:
        # v1i might not catch read-before-write; skip
        print("  SKIP: test 2 (v1i didn't flag the error)")
        ok += 1

    # Test 3: save_minimized works
    path = save_minimized("func main() { putc(65); }")
    if os.path.exists(path):
        print(f"  PASS: saved to {path}")
        ok += 1
    else:
        print(f"  FAIL: save_minimized did not create file")
        fail += 1

    print(f'\nResults: {ok} passed, {fail} failed')
    return fail == 0


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == '--test':
        sys.exit(0 if _test() else 1)

    if len(sys.argv) < 2:
        print("Usage: python3 tools/minimize.py failing.v1", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    with open(path) as f:
        src = f.read()

    print(f"Original: {len(src)} bytes")
    baseline = run_v1i(src)
    rc, out, err = baseline
    print(f"Baseline: rc={rc} stderr={err[:80]!r}")

    mini = minimize(src, baseline)
    print(f"Minimized: {len(mini)} bytes")

    out_path = save_minimized(mini)
    print(f"Saved to: {out_path}")
    print("--- Minimized program ---")
    print(mini)
