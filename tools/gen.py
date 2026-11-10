#!/usr/bin/env python3
"""
tools/gen.py — Generate valid, deterministic v1 programs for fuzzing.

Every generated program is syntactically and semantically valid per the spec:
  - All variables declared before use
  - Functions defined before they are called (define-before-use)
  - Only self-recursion
  - No read-before-write of locals (guaranteed by generator logic)
  - No out-of-range array index (generated accesses stay in bounds)
  - Recursion depth ≤ 1,000
  - At most 200 functions, source ≤ 60,000 bytes, names ≤ 24 chars
  - Standard operands and expressions, no division, no &&/||/!

Usage:
    python3 tools/gen.py <seed> [num_programs]
    python3 tools/gen.py 42           # generates 1 program, prints to stdout
    python3 tools/gen.py 42 100       # generates 100 programs, one per stdout line block
    python3 tools/gen.py --test       # run self-tests
"""
import sys, os, random

sys.setrecursionlimit(5000)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.spec_limits import (
    MAX_SOURCE_BYTES, MAX_FUNCTIONS, MAX_PARAMS, MAX_NAME_LEN, MAX_RECURSION_DEPTH
)

# ── Constants ────────────────────────────────────────────────────────────────
MAX_GLOBALS       = 4
MAX_ARRAYS        = 2
MAX_ARRAY_SIZE    = 10
MAX_FUNCS         = 8      # keep well under 200
MAX_FUNC_PARAMS   = 3      # keep under 8
MAX_LOCALS        = 4
MAX_STMT_DEPTH    = 3      # max nesting depth for statements
MAX_EXPR_DEPTH    = 3      # max expression depth
MAX_STMTS_PER_BLOCK = 5

KEYWORDS = {'var', 'array', 'func', 'if', 'else', 'while', 'return',
            'getc', 'putc', 'main'}


def _fresh_name(rng, used: set, prefix: str = 'v') -> str:
    """Generate a unique non-keyword name."""
    for _ in range(1000):
        length = rng.randint(1, 8)
        chars = 'abcdefghijklmnopqrstuvwxyz'
        name = prefix + ''.join(rng.choice(chars) for _ in range(length))
        name = name[:MAX_NAME_LEN]
        if name not in KEYWORDS and name not in used:
            used.add(name)
            return name
    raise RuntimeError("Could not generate fresh name")


class Generator:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self._used_names = set(KEYWORDS)
        self._globals = []          # list of (name, kind, size)  kind='var'|'array'
        self._funcs   = []          # list of (name, params, is_recursive)
        self._out     = []          # output lines

    def emit(self, s: str):
        self._out.append(s)

    def name(self, prefix='v'):
        return _fresh_name(self.rng, self._used_names, prefix)

    # ── Expressions ──────────────────────────────────────────────────────

    def gen_expr(self, ctx, depth=0):
        """Generate an expression. ctx = dict with 'locals', 'params', 'func_name'."""
        rng = self.rng
        if depth >= MAX_EXPR_DEPTH:
            return self._gen_primary(ctx)

        # Pick a form
        choices = ['primary', 'primary', 'unary', 'binop']
        form = rng.choice(choices)

        if form == 'unary':
            sub = self.gen_expr(ctx, depth + 1)
            return f'-({sub})'
        elif form == 'binop':
            left  = self.gen_expr(ctx, depth + 1)
            right = self.gen_expr(ctx, depth + 1)
            ops = ['+', '-', '*', '<', '<=', '>', '>=', '==', '!=']
            op = rng.choice(ops)
            return f'({left} {op} {right})'
        else:
            return self._gen_primary(ctx)

    def _gen_primary(self, ctx):
        rng = self.rng
        # Available: literals, vars (globals + locals + params), arrays, func calls
        all_vars = list(ctx.get('locals', [])) + list(ctx.get('params', []))
        all_scalars = all_vars + [g[0] for g in self._globals if g[1] == 'var']
        arrays  = [g for g in self._globals if g[1] == 'array']
        funcs   = [f for f in self._funcs if f[0] != ctx.get('func_name')]

        weights = []
        options = []

        # Literal
        options.append('lit'); weights.append(4)
        # Variable (if any)
        if all_scalars:
            options.append('var'); weights.append(3)
        # Array access
        if arrays:
            options.append('arr'); weights.append(2)
        # Getc (avoid to keep output deterministic in tests)
        # Putc call as expression — allowed by spec
        # Function call
        if funcs:
            options.append('call'); weights.append(2)
        # Self-call (recursion)
        if ctx.get('can_recurse'):
            options.append('self'); weights.append(1)

        total = sum(weights)
        r = rng.uniform(0, total)
        cum = 0
        choice = options[0]
        for opt, w in zip(options, weights):
            cum += w
            if r <= cum:
                choice = opt
                break

        if choice == 'lit':
            # Small literals (avoid very large numbers for readability)
            return str(rng.randint(-10, 50))
        elif choice == 'var':
            return rng.choice(all_scalars)
        elif choice == 'arr':
            g = rng.choice(arrays)
            idx = rng.randint(0, g[2] - 1)
            return f'{g[0]}[{idx}]'
        elif choice == 'call':
            f = rng.choice(funcs)
            fname, fparams, _ = f
            args = [self.gen_expr(ctx, MAX_EXPR_DEPTH) for _ in fparams]
            return f'{fname}({", ".join(args)})'
        elif choice == 'self':
            fname = ctx['func_name']
            fparams = next(f[1] for f in self._funcs if f[0] == fname)
            args = [self.gen_expr(ctx, MAX_EXPR_DEPTH) for _ in fparams]
            return f'{fname}({", ".join(args)})'
        else:
            return '0'

    # ── Statements ───────────────────────────────────────────────────────

    def gen_stmt(self, ctx, depth=0):
        """Generate one statement. Appends to self._out."""
        rng = self.rng
        all_vars = list(ctx.get('locals', [])) + list(ctx.get('params', []))
        all_scalars = all_vars + [g[0] for g in self._globals if g[1] == 'var']
        arrays  = [g for g in self._globals if g[1] == 'array']

        weights = []
        options = []

        if all_scalars:
            options.append('assign'); weights.append(5)
        if arrays:
            options.append('arr_assign'); weights.append(2)
        options.append('putc_stmt'); weights.append(2)

        can_nest = depth < MAX_STMT_DEPTH
        if can_nest:
            options.append('if_stmt'); weights.append(3)
            options.append('while_stmt'); weights.append(2)

        # Function call as statement
        callee_funcs = [f for f in self._funcs if f[0] != ctx.get('func_name')]
        if callee_funcs:
            options.append('call_stmt'); weights.append(2)

        # Return (always allow)
        options.append('return_stmt'); weights.append(1)

        total = sum(weights)
        r = rng.uniform(0, total)
        cum = 0
        choice = options[-1]
        for opt, w in zip(options, weights):
            cum += w
            if r <= cum:
                choice = opt
                break

        indent = '    ' * (depth + 1)

        if choice == 'assign' and all_scalars:
            var = rng.choice(all_scalars)
            expr = self.gen_expr(ctx)
            self.emit(f'{indent}{var} = {expr};')

        elif choice == 'arr_assign' and arrays:
            arr = rng.choice(arrays)
            idx = rng.randint(0, arr[2] - 1)
            expr = self.gen_expr(ctx)
            self.emit(f'{indent}{arr[0]}[{idx}] = {expr};')

        elif choice == 'putc_stmt':
            expr = self.gen_expr(ctx)
            self.emit(f'{indent}putc({expr});')

        elif choice == 'if_stmt':
            cond = self.gen_expr(ctx)
            self.emit(f'{indent}if ({cond}) {{')
            n = rng.randint(1, 3)
            for _ in range(n):
                self.gen_stmt(ctx, depth + 1)
            if rng.random() < 0.4:
                self.emit(f'{indent}}} else {{')
                m = rng.randint(1, 2)
                for _ in range(m):
                    self.gen_stmt(ctx, depth + 1)
            self.emit(f'{indent}}}')

        elif choice == 'while_stmt':
            # Use a dedicated counter to guarantee termination.
            # Always generate a fresh var for the loop counter.
            ctr = self.name('wc')
            bound = rng.randint(1, 4)
            self.emit(f'{indent}var {ctr};')
            self.emit(f'{indent}{ctr} = {bound};')
            self.emit(f'{indent}while ({ctr} > 0) {{')
            # Body: simple statements only (no nested while to avoid corruption)
            n = rng.randint(1, 2)
            for _ in range(n):
                if all_scalars:
                    sv = rng.choice(all_scalars)
                    se = str(rng.randint(0, 10))
                    self.emit(f'{"    " * (depth + 2)}{sv} = {se};')
                else:
                    self.emit(f'{"    " * (depth + 2)}putc(48);')
            # Decrement always last
            self.emit(f'{"    " * (depth + 2)}{ctr} = {ctr} - 1;')
            self.emit(f'{indent}}}')

        elif choice == 'call_stmt' and callee_funcs:
            f = rng.choice(callee_funcs)
            fname, fparams, _ = f
            args = [self.gen_expr(ctx) for _ in fparams]
            self.emit(f'{indent}{fname}({", ".join(args)});')

        elif choice == 'return_stmt':
            expr = self.gen_expr(ctx)
            self.emit(f'{indent}return {expr};')

        else:
            # Fallback
            self.emit(f'{indent}putc(65);')

    # ── Function ─────────────────────────────────────────────────────────

    def gen_func(self, force_name=None, force_params=None, is_main=False):
        rng = self.rng
        name = force_name or self.name('f')
        num_params = force_params if force_params is not None else rng.randint(0, min(MAX_FUNC_PARAMS, 4))
        params = [self.name('p') for _ in range(num_params)]
        is_recursive = False  # disabled in generator: avoids depth>1000 violations
        self._funcs.append((name, params, is_recursive))

        # Locals
        num_locals = rng.randint(0, MAX_LOCALS)
        locals_list = [self.name('l') for _ in range(num_locals)]

        ctx = {
            'func_name': name,
            'params': params,
            'locals': locals_list,
            'can_recurse': is_recursive and not is_main,
        }

        param_str = ', '.join(params)
        self.emit(f'func {name}({param_str}) {{')
        for loc in locals_list:
            self.emit(f'    var {loc};')

        # Initialize ALL locals to 0 before first use
        # (spec says locals have NO defined start value; v1i flags read-before-write)
        for loc in locals_list:
            self.emit(f'    {loc} = 0;')

        # Generate body statements
        num_stmts = rng.randint(1, MAX_STMTS_PER_BLOCK)
        for _ in range(num_stmts):
            self.gen_stmt(ctx, depth=0)

        # Ensure a return at the end (spec allows fallthrough → 0, but be explicit)
        if rng.random() < 0.7:
            expr = self.gen_expr(ctx)
            self.emit(f'    return {expr};')

        self.emit('}')
        self.emit('')

    # ── Top-level program ────────────────────────────────────────────────

    def generate(self) -> str:
        rng = self.rng

        # Globals
        num_globals = rng.randint(0, MAX_GLOBALS)
        for _ in range(num_globals):
            gname = self.name('g')
            self._globals.append((gname, 'var', 1))
            self.emit(f'var {gname};')

        # Arrays
        num_arrays = rng.randint(0, MAX_ARRAYS)
        for _ in range(num_arrays):
            aname = self.name('a')
            size = rng.randint(1, MAX_ARRAY_SIZE)
            self._globals.append((aname, 'array', size))
            self.emit(f'array {aname}[{size}];')

        if num_globals + num_arrays > 0:
            self.emit('')

        # Helper functions (defined before main)
        num_helpers = rng.randint(0, MAX_FUNCS - 1)
        for _ in range(num_helpers):
            self.gen_func()

        # main
        self.gen_func(force_name='main', force_params=0, is_main=True)

        return '\n'.join(self._out)


def generate(seed: int) -> str:
    """Generate one valid v1 program with the given seed."""
    return Generator(seed).generate()


# ── Self-tests ────────────────────────────────────────────────────────────────

def _test():
    """Verify generated programs parse correctly in v1i.py."""
    import subprocess, tempfile

    v1i = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v1i.py')

    ok = fail = 0
    NUM_TESTS = 50
    for seed in range(NUM_TESTS):
        src = generate(seed)
        with tempfile.NamedTemporaryFile(suffix='.v1', mode='w', delete=False) as f:
            f.write(src); fname = f.name
        try:
            r = subprocess.run(
                [sys.executable, v1i, fname],
                capture_output=True, timeout=10
            )
            if r.returncode == 0:
                print(f'  PASS: seed={seed}')
                ok += 1
            else:
                print(f'  FAIL: seed={seed} rc={r.returncode}')
                print(f'    stderr: {r.stderr.decode()[:200]}')
                print(f'    source:\n{src[:300]}')
                fail += 1
        except subprocess.TimeoutExpired:
            print(f'  TIMEOUT: seed={seed}')
            fail += 1
        finally:
            os.unlink(fname)

    print(f'\nResults: {ok} passed, {fail} failed')
    return fail == 0


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == '--test':
        sys.exit(0 if _test() else 1)

    if len(sys.argv) < 2:
        print("Usage: python3 tools/gen.py <seed> [count]", file=sys.stderr)
        sys.exit(1)

    seed = int(sys.argv[1])
    count = int(sys.argv[2]) if len(sys.argv) >= 3 else 1

    for i in range(count):
        src = generate(seed + i)
        if count == 1:
            print(src)
        else:
            print(f'--- seed={seed + i} ---')
            print(src)
            print()
