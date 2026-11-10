#!/usr/bin/env python3
"""
tools/v1i.py — Independent v1 interpreter.

Exact 32-bit signed semantics, independent of compiler code generation.
Flags:
  - read of unassigned local variable
  - out-of-range array index
  - recursion deeper than 1,000

Usage:
    python3 tools/v1i.py program.v1 [< input]
    python3 tools/v1i.py --test     (run self-tests)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.spec_limits import (
    MAX_SOURCE_BYTES, MAX_FUNCTIONS, MAX_PARAMS, MAX_NAME_LEN,
    MAX_RECURSION_DEPTH, WORD_MIN, WORD_MAX
)

# ------------------------------------------------------------------ utilities

def wrap32(x):
    """Wrap to signed 32-bit integer."""
    x = x & 0xFFFFFFFF
    if x >= 0x80000000:
        x -= 0x100000000
    return x

def signed_lt(x, y):
    """True signed < comparison (overflow-safe per v1 spec)."""
    if (x < 0) != (y < 0):
        return 1 if x < 0 else 0
    return 1 if (x - y) < 0 else 0

def signed_le(x, y): return 1 if (signed_lt(x, y) or x == y) else 0
def signed_gt(x, y): return signed_lt(y, x)
def signed_ge(x, y): return signed_le(y, x)

# ------------------------------------------------------------------ lexer

KEYWORDS = {'var', 'array', 'func', 'if', 'else', 'while', 'return',
            'getc', 'putc'}

TK_NAME   = 'NAME'
TK_INT    = 'INT'
TK_SEMI   = ';'
TK_COMMA  = ','
TK_LPAR   = '('
TK_RPAR   = ')'
TK_LBRACE = '{'
TK_RBRACE = '}'
TK_LBRAK  = '['
TK_RBRAK  = ']'
TK_EQ     = '='
TK_PLUS   = '+'
TK_MINUS  = '-'
TK_STAR   = '*'
TK_LT     = '<'
TK_LE     = '<='
TK_GT     = '>'
TK_GE     = '>='
TK_EQEQ   = '=='
TK_NEQ    = '!='
TK_EOF    = 'EOF'

class LexError(Exception): pass
class ParseError(Exception): pass
class RuntimeError_(Exception): pass

class Lexer:
    def __init__(self, src):
        self.src = src
        self.pos = 0
        self.line = 1
        self._tok = None
        self._val = None
        self.advance()

    def _skip(self):
        while self.pos < len(self.src):
            c = self.src[self.pos]
            if c == '\n':
                self.line += 1
                self.pos += 1
            elif c in ' \t\r':
                self.pos += 1
            elif c == '/' and self.pos + 1 < len(self.src) and self.src[self.pos+1] == '/':
                while self.pos < len(self.src) and self.src[self.pos] != '\n':
                    self.pos += 1
            else:
                break

    def advance(self):
        self._skip()
        if self.pos >= len(self.src):
            self._tok = TK_EOF
            self._val = None
            return

        c = self.src[self.pos]

        # Integer literal
        if c.isdigit():
            start = self.pos
            while self.pos < len(self.src) and self.src[self.pos].isdigit():
                self.pos += 1
            val = int(self.src[start:self.pos])
            if val > MAX_LITERAL_VALUE:
                raise LexError(f"line {self.line}: integer literal {val} > 2147483647")
            self._tok = TK_INT
            self._val = val
            return

        # Name or keyword — keywords get their own token; identifiers get TK_NAME
        if c.isalpha() or c == '_':
            start = self.pos
            while self.pos < len(self.src) and (self.src[self.pos].isalnum() or self.src[self.pos] == '_'):
                self.pos += 1
            name = self.src[start:self.pos]
            if len(name) > MAX_NAME_LEN:
                raise LexError(f"line {self.line}: name '{name}' exceeds {MAX_NAME_LEN} chars")
            if name in KEYWORDS:
                self._tok = name   # keyword token = keyword string e.g. 'var','func'
                self._val = name
            else:
                self._tok = TK_NAME  # 'NAME'
                self._val = name
            return

        # Two-char operators
        two = self.src[self.pos:self.pos+2]
        if two == '<=': self._tok = TK_LE;   self._val = None; self.pos += 2; return
        if two == '>=': self._tok = TK_GE;   self._val = None; self.pos += 2; return
        if two == '==': self._tok = TK_EQEQ; self._val = None; self.pos += 2; return
        if two == '!=': self._tok = TK_NEQ;  self._val = None; self.pos += 2; return

        # Single-char
        singles = {';':TK_SEMI, ',':TK_COMMA, '(':TK_LPAR, ')':TK_RPAR,
                   '{':TK_LBRACE, '}':TK_RBRACE, '[':TK_LBRAK, ']':TK_RBRAK,
                   '=':TK_EQ, '+':TK_PLUS, '-':TK_MINUS, '*':TK_STAR,
                   '<':TK_LT, '>':TK_GT}
        if c in singles:
            self._tok = singles[c]
            self._val = None
            self.pos += 1
            return

        raise LexError(f"line {self.line}: unexpected character {c!r}")

    @property
    def tok(self): return self._tok
    @property
    def val(self): return self._val

    def expect(self, t):
        if self._tok != t:
            raise ParseError(f"line {self.line}: expected {t!r}, got {self._tok!r}")
        v = self._val if self._val is not None else self._tok
        self.advance()
        return v

    def expect_name(self):
        """Expect any identifier (including those that happen to be non-reserved words).
        Keywords (var/array/func/if/else/while/return) are reserved; getc/putc are built-ins.
        Regular identifiers come through as TK_NAME."""
        if self._tok != TK_NAME:
            raise ParseError(f"line {self.line}: expected identifier, got {self._tok!r}")
        v = self._val
        self.advance()
        return v

    def eat(self, t):
        if self._tok == t:
            self.advance()
            return True
        return False

    def kw(self, name):
        """Check if current token is keyword 'name'."""
        return self._val == name  # keywords stored in _val regardless of _tok

    def expect_kw(self, name):
        """Consume keyword 'name' or raise ParseError."""
        if not self.kw(name):
            raise ParseError(f"line {self.line}: expected keyword {name!r}, got {self._val!r}")
        self.advance()


MAX_LITERAL_VALUE = 2147483647

# ------------------------------------------------------------------ AST nodes (simple dicts)

def mk(kind, **kw): return {'kind': kind, **kw}

# ------------------------------------------------------------------ parser

class Parser:
    def __init__(self, src):
        self.lex = Lexer(src)
        self.funcs = {}   # name → {params, locals_order, body}

    def parse_program(self):
        """Returns (globals_dict, arrays_dict, funcs_list)"""
        globs = {}     # name → 0
        arrays = {}    # name → size
        funcs = []     # list of func AST nodes in order

        while self.lex.tok != TK_EOF:
            if self.lex.kw('var'):
                self.lex.advance()
                name = self.lex.expect_name()
                self.lex.expect(TK_SEMI)
                if name in globs or name in arrays:
                    raise ParseError(f"Duplicate global: {name}")
                globs[name] = 0
            elif self.lex.kw('array'):
                self.lex.advance()
                name = self.lex.expect_name()
                self.lex.expect(TK_LBRAK)
                size = self.lex.expect(TK_INT)
                self.lex.expect(TK_RBRAK)
                self.lex.expect(TK_SEMI)
                if name in globs or name in arrays:
                    raise ParseError(f"Duplicate global: {name}")
                arrays[name] = size
            elif self.lex.kw('func'):
                f = self.parse_func(globs, arrays, funcs)
                funcs.append(f)
            else:
                raise ParseError(f"line {self.lex.line}: unexpected {self.lex.tok!r} val={self.lex.val!r}")

        return globs, arrays, funcs

    def parse_func(self, globs, arrays, funcs_so_far):
        self.lex.expect_kw('func')
        name = self.lex.expect_name()
        self.lex.expect(TK_LPAR)
        params = []
        while self.lex.tok != TK_RPAR:
            p = self.lex.expect_name()
            params.append(p)
            if not self.lex.eat(TK_COMMA):
                break
        self.lex.expect(TK_RPAR)
        if len(params) > MAX_PARAMS:
            raise ParseError(f"Function {name} has {len(params)} params, max {MAX_PARAMS}")
        # Build set of known functions for call validation
        known_funcs = {f['name'] for f in funcs_so_far}
        known_funcs.add(name)  # self-recursion allowed
        body = self.parse_block(params, globs, arrays, known_funcs, name)
        return mk('func', name=name, params=params, body=body)

    def parse_block(self, params, globs, arrays, known_funcs, cur_func):
        self.lex.expect(TK_LBRACE)
        stmts = []
        locals_set = set(params)  # track declared locals in scope
        while self.lex.tok != TK_RBRACE:
            s = self.parse_stmt(locals_set, params, globs, arrays, known_funcs, cur_func)
            if s is not None:
                stmts.append(s)
        self.lex.expect(TK_RBRACE)
        return stmts

    def parse_stmt(self, locals_set, params, globs, arrays, known_funcs, cur_func):
        tok = self.lex.tok
        tokval = self.lex.val

        if tokval == 'var':
            self.lex.advance()
            name = self.lex.expect_name()
            self.lex.expect(TK_SEMI)
            if name in locals_set:
                raise ParseError(f"Duplicate local: {name}")
            locals_set.add(name)
            return mk('var_decl', name=name)

        if tokval == 'if':
            self.lex.advance()
            self.lex.expect(TK_LPAR)
            cond = self.parse_expr(locals_set, params, globs, arrays, known_funcs)
            self.lex.expect(TK_RPAR)
            then = self.parse_block(params, globs, arrays, known_funcs, cur_func)
            else_ = None
            if self.lex.kw('else'):
                self.lex.advance()
                else_ = self.parse_block(params, globs, arrays, known_funcs, cur_func)
            return mk('if', cond=cond, then=then, else_=else_)

        if tokval == 'while':
            self.lex.advance()
            self.lex.expect(TK_LPAR)
            cond = self.parse_expr(locals_set, params, globs, arrays, known_funcs)
            self.lex.expect(TK_RPAR)
            body = self.parse_block(params, globs, arrays, known_funcs, cur_func)
            return mk('while', cond=cond, body=body)

        if tokval == 'return':
            self.lex.advance()
            expr = self.parse_expr(locals_set, params, globs, arrays, known_funcs)
            self.lex.expect(TK_SEMI)
            return mk('return', expr=expr)

        # Assignment or call statement (user identifier or builtin getc/putc)
        if tok == TK_NAME or tok in ('getc', 'putc'):
            name = self.lex.val
            self.lex.advance()
            if self.lex.tok == TK_LPAR:
                # Call statement
                self.lex.advance()
                args = self.parse_arglist(locals_set, params, globs, arrays, known_funcs)
                self.lex.expect(TK_RPAR)
                self.lex.expect(TK_SEMI)
                if name not in known_funcs and name != 'getc' and name != 'putc':
                    raise ParseError(f"Undefined function: {name}")
                return mk('call_stmt', name=name, args=args)
            if self.lex.tok == TK_LBRAK:
                # Array assignment: a[e] = e;
                self.lex.advance()
                idx = self.parse_expr(locals_set, params, globs, arrays, known_funcs)
                self.lex.expect(TK_RBRAK)
                self.lex.expect(TK_EQ)
                val = self.parse_expr(locals_set, params, globs, arrays, known_funcs)
                self.lex.expect(TK_SEMI)
                return mk('arr_assign', name=name, idx=idx, val=val)
            if self.lex.tok == TK_EQ:
                # Variable assignment: x = e;
                self.lex.advance()
                val = self.parse_expr(locals_set, params, globs, arrays, known_funcs)
                self.lex.expect(TK_SEMI)
                return mk('assign', name=name, val=val)
            raise ParseError(f"line {self.lex.line}: unexpected token after name {name!r}")

        raise ParseError(f"line {self.lex.line}: unexpected {tok!r} in statement")

    def parse_arglist(self, locals_set, params, globs, arrays, known_funcs):
        args = []
        if self.lex.tok == TK_RPAR:
            return args
        while True:
            args.append(self.parse_expr(locals_set, params, globs, arrays, known_funcs))
            if not self.lex.eat(TK_COMMA):
                break
        return args

    def parse_expr(self, locals_set, params, globs, arrays, known_funcs):
        """Precedence climbing: unary minus > * > +- > comparisons."""
        return self._parse_cmp(locals_set, params, globs, arrays, known_funcs)

    def _parse_cmp(self, ls, ps, gs, ars, kf):
        left = self._parse_add(ls, ps, gs, ars, kf)
        while self.lex.tok in (TK_LT, TK_LE, TK_GT, TK_GE, TK_EQEQ, TK_NEQ):
            op = self.lex.tok
            self.lex.advance()
            right = self._parse_add(ls, ps, gs, ars, kf)
            left = mk('binop', op=op, left=left, right=right)
        return left

    def _parse_add(self, ls, ps, gs, ars, kf):
        left = self._parse_mul(ls, ps, gs, ars, kf)
        while self.lex.tok in (TK_PLUS, TK_MINUS):
            op = self.lex.tok
            self.lex.advance()
            right = self._parse_mul(ls, ps, gs, ars, kf)
            left = mk('binop', op=op, left=left, right=right)
        return left

    def _parse_mul(self, ls, ps, gs, ars, kf):
        left = self._parse_unary(ls, ps, gs, ars, kf)
        while self.lex.tok == TK_STAR:
            self.lex.advance()
            right = self._parse_unary(ls, ps, gs, ars, kf)
            left = mk('binop', op='*', left=left, right=right)
        return left

    def _parse_unary(self, ls, ps, gs, ars, kf):
        if self.lex.tok == TK_MINUS:
            self.lex.advance()
            operand = self._parse_unary(ls, ps, gs, ars, kf)
            return mk('unary', op='-', operand=operand)
        return self._parse_primary(ls, ps, gs, ars, kf)

    def _parse_primary(self, ls, ps, gs, ars, kf):
        tok = self.lex.tok

        if tok == TK_INT:
            v = self.lex.val
            self.lex.advance()
            return mk('int', val=v)

        if tok == TK_LPAR:
            self.lex.advance()
            e = self.parse_expr(ls, ps, gs, ars, kf)
            self.lex.expect(TK_RPAR)
            return e

        if tok == TK_NAME or tok in ('getc', 'putc'):
            name = self.lex.val
            self.lex.advance()
            if self.lex.tok == TK_LPAR:
                self.lex.advance()
                args = self.parse_arglist(ls, ps, gs, ars, kf)
                self.lex.expect(TK_RPAR)
                if name not in kf and name != 'getc' and name != 'putc':
                    raise ParseError(f"Undefined function: {name}")
                return mk('call', name=name, args=args)
            if self.lex.tok == TK_LBRAK:
                self.lex.advance()
                idx = self.parse_expr(ls, ps, gs, ars, kf)
                self.lex.expect(TK_RBRAK)
                return mk('arr_read', name=name, idx=idx)
            return mk('var', name=name)

        raise ParseError(f"line {self.lex.line}: unexpected {tok!r} in expression")


# ------------------------------------------------------------------ interpreter

SENTINEL = object()   # marks unassigned locals

class Interpreter:
    def __init__(self, src, stdin=None, stdout=None):
        sys.setrecursionlimit(20000)  # allow up to 1000 v1 calls deep (each ~12 Python frames)
        if len(src) > MAX_SOURCE_BYTES:
            raise RuntimeError_(f"Source too large: {len(src)} > {MAX_SOURCE_BYTES}")
        self.src = src
        self.stdin = stdin or sys.stdin.buffer
        self.stdout = stdout or sys.stdout.buffer
        self._input_ended = False
        self._depth = -1  # -1 so main() starts at depth 0

    def run(self):
        parser = Parser(self.src)
        globs, arrays, funcs = parser.parse_program()

        if len(funcs) > MAX_FUNCTIONS:
            raise RuntimeError_(f"Too many functions: {len(funcs)} > {MAX_FUNCTIONS}")

        # Build function table
        func_table = {}
        for f in funcs:
            func_table[f['name']] = f

        if 'main' not in func_table:
            raise RuntimeError_("No main() function defined")

        # Initialize globals
        genv = {}
        for name in globs:
            genv[name] = 0
        arr_data = {}
        for name, size in arrays.items():
            arr_data[name] = [0] * size

        # Call main
        try:
            self._call(func_table['main'], [], genv, arr_data, func_table)
        except _Return:
            pass

    def _getc(self):
        if self._input_ended:
            return -1
        b = self.stdin.read(1)
        if not b:
            self._input_ended = True
            return -1
        return b[0]

    def _putc(self, v):
        self.stdout.write(bytes([wrap32(v) & 0xFF]))
        self.stdout.flush()

    def _call(self, func, arg_vals, genv, arr_data, func_table):
        self._depth += 1
        if self._depth > MAX_RECURSION_DEPTH + 1:  # +1: 1000 recursive + base
            raise RuntimeError_(f"Recursion depth exceeded {MAX_RECURSION_DEPTH}")

        # Build local environment: params + locals (use SENTINEL for unassigned)
        lenv = {}
        for i, pname in enumerate(func['params']):
            lenv[pname] = arg_vals[i] if i < len(arg_vals) else 0

        try:
            result = self._exec_block(func['body'], lenv, genv, arr_data, func_table)
        except _Return as r:
            result = r.value
        finally:
            self._depth -= 1

        return 0 if result is None else result

    def _exec_block(self, stmts, lenv, genv, arr_data, func_table):
        for stmt in stmts:
            self._exec_stmt(stmt, lenv, genv, arr_data, func_table)
        return None

    def _exec_stmt(self, stmt, lenv, genv, arr_data, func_table):
        k = stmt['kind']

        if k == 'var_decl':
            lenv[stmt['name']] = SENTINEL

        elif k == 'assign':
            val = wrap32(self._eval(stmt['val'], lenv, genv, arr_data, func_table))
            name = stmt['name']
            if name in lenv:
                lenv[name] = val
            elif name in genv:
                genv[name] = val
            else:
                raise RuntimeError_(f"Undefined variable: {name}")

        elif k == 'arr_assign':
            name = stmt['name']
            idx = wrap32(self._eval(stmt['idx'], lenv, genv, arr_data, func_table))
            val = wrap32(self._eval(stmt['val'], lenv, genv, arr_data, func_table))
            if name not in arr_data:
                raise RuntimeError_(f"Undefined array: {name}")
            arr = arr_data[name]
            if idx < 0 or idx >= len(arr):
                raise RuntimeError_(f"Array {name}[{idx}] out of range (size {len(arr)})")
            arr[idx] = val

        elif k == 'if':
            cond = self._eval(stmt['cond'], lenv, genv, arr_data, func_table)
            if cond != 0:
                self._exec_block(stmt['then'], lenv, genv, arr_data, func_table)
            elif stmt['else_']:
                self._exec_block(stmt['else_'], lenv, genv, arr_data, func_table)

        elif k == 'while':
            while self._eval(stmt['cond'], lenv, genv, arr_data, func_table) != 0:
                self._exec_block(stmt['body'], lenv, genv, arr_data, func_table)

        elif k == 'return':
            val = wrap32(self._eval(stmt['expr'], lenv, genv, arr_data, func_table))
            raise _Return(val)

        elif k == 'call_stmt':
            self._eval_call(stmt['name'], stmt['args'], lenv, genv, arr_data, func_table)

        else:
            raise RuntimeError_(f"Unknown stmt kind: {k}")

    def _eval(self, expr, lenv, genv, arr_data, func_table):
        k = expr['kind']

        if k == 'int':
            return expr['val']

        if k == 'var':
            name = expr['name']
            if name in lenv:
                v = lenv[name]
                if v is SENTINEL:
                    raise RuntimeError_(f"Read of unassigned local: {name}")
                return v
            if name in genv:
                return genv[name]
            raise RuntimeError_(f"Undefined variable: {name}")

        if k == 'arr_read':
            name = expr['name']
            idx = wrap32(self._eval(expr['idx'], lenv, genv, arr_data, func_table))
            if name not in arr_data:
                raise RuntimeError_(f"Undefined array: {name}")
            arr = arr_data[name]
            if idx < 0 or idx >= len(arr):
                raise RuntimeError_(f"Array {name}[{idx}] out of range (size {len(arr)})")
            return arr[idx]

        if k == 'unary':
            v = self._eval(expr['operand'], lenv, genv, arr_data, func_table)
            return wrap32(-v)

        if k == 'binop':
            # Left-to-right evaluation
            lv = self._eval(expr['left'], lenv, genv, arr_data, func_table)
            rv = self._eval(expr['right'], lenv, genv, arr_data, func_table)
            op = expr['op']
            if op == '+': return wrap32(lv + rv)
            if op == '-': return wrap32(lv - rv)
            if op == '*': return wrap32(lv * rv)
            if op == '<':  return signed_lt(lv, rv)
            if op == '<=': return signed_le(lv, rv)
            if op == '>':  return signed_gt(lv, rv)
            if op == '>=': return signed_ge(lv, rv)
            if op == '==': return 1 if lv == rv else 0
            if op == '!=': return 1 if lv != rv else 0
            raise RuntimeError_(f"Unknown op: {op}")

        if k == 'call':
            return self._eval_call(expr['name'], expr['args'], lenv, genv, arr_data, func_table)

        raise RuntimeError_(f"Unknown expr kind: {k}")

    def _eval_call(self, name, args, lenv, genv, arr_data, func_table):
        # Evaluate all arguments left-to-right first
        arg_vals = [wrap32(self._eval(a, lenv, genv, arr_data, func_table)) for a in args]

        if name == 'getc':
            return self._getc()
        if name == 'putc':
            self._putc(arg_vals[0] if arg_vals else 0)
            return 0

        if name not in func_table:
            raise RuntimeError_(f"Undefined function: {name}")

        func = func_table[name]
        if len(arg_vals) != len(func['params']):
            raise RuntimeError_(f"Wrong arg count for {name}: got {len(arg_vals)}, expected {len(func['params'])}")

        return self._call(func, arg_vals, genv, arr_data, func_table)


class _Return(Exception):
    def __init__(self, value): self.value = value


# ------------------------------------------------------------------ main

def interpret(src, stdin=None, stdout=None):
    interp = Interpreter(src, stdin, stdout)
    interp.run()


def main():
    if '--test' in sys.argv:
        _run_tests()
        return

    if len(sys.argv) < 2:
        print("usage: v1i.py program.v1 [< input]", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1], 'r') as f:
        src = f.read()

    try:
        interpret(src, sys.stdin.buffer, sys.stdout.buffer)
    except (LexError, ParseError, RuntimeError_) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


def _run_tests():
    import io
    passed = 0
    failed = 0

    def check(name, src, stdin_data, expected_out):
        nonlocal passed, failed
        out_buf = io.BytesIO()
        in_buf = io.BytesIO(stdin_data)
        try:
            interpret(src, in_buf, out_buf)
            got = out_buf.getvalue()
            if got == expected_out:
                print(f"  PASS: {name}")
                passed += 1
            else:
                print(f"  FAIL: {name}")
                print(f"    expected: {expected_out!r}")
                print(f"    got:      {got!r}")
                failed += 1
        except Exception as e:
            print(f"  FAIL: {name} — exception: {e}")
            failed += 1

    def check_error(name, src, stdin_data=b''):
        nonlocal passed, failed
        out_buf = io.BytesIO()
        in_buf = io.BytesIO(stdin_data)
        try:
            interpret(src, in_buf, out_buf)
            print(f"  FAIL: {name} — expected error but got none")
            failed += 1
        except (LexError, ParseError, RuntimeError_):
            print(f"  PASS: {name} (error raised as expected)")
            passed += 1

    print("=== v1i.py unit tests ===")

    # Spec example 1: fact(3) prints "6\n"
    check("fact(3) = 6", """
func fact(n) {
    if (n < 2) { return 1; }
    return n * fact(n - 1);
}
func main() { putc(48 + fact(3)); putc(10); }
""", b'', b'6\n')

    # Spec example 2: square/total prints "ok\n"
    check("square/total = ok", """
var total;
array sq[5];
func square(x) { return x * x; }
func main() {
    var i;
    i = 0;
    while (i < 5) {
        sq[i] = square(i + 1);
        total = total + sq[i];
        i = i + 1;
    }
    if (total == 55) { putc(111); putc(107); }
    putc(10);
}
""", b'', b'ok\n')

    # Signed comparison: 2000000000 < -2000000000 == 0
    check("signed cmp: 2G < -2G == 0", """
func main() {
    var x;
    var y;
    x = 2000000000;
    y = -2000000000;
    if (x < y) { putc(49); } else { putc(48); }
    putc(10);
}
""", b'', b'0\n')

    # Signed comparison: -2000000000 < 2000000000 == 1
    check("signed cmp: -2G < 2G == 1", """
func main() {
    var x;
    var y;
    x = -2000000000;
    y = 2000000000;
    if (x < y) { putc(49); } else { putc(48); }
    putc(10);
}
""", b'', b'1\n')

    # 32-bit wraparound: 2147483647 + 1 = -2147483648
    check("wraparound +1", """
func main() {
    var x;
    x = 2147483647;
    x = x + 1;
    if (x == -2147483647 - 1) { putc(89); } else { putc(78); }
    putc(10);
}
""", b'', b'Y\n')

    # Local hiding global
    check("local hides global", """
var x;
func main() {
    var x;
    x = 65;
    putc(x);
    putc(10);
}
""", b'', b'A\n')

    # Fall-through return 0
    check("fall-through return 0", """
func f() { var x; x = 1; }
func main() {
    var r;
    r = f();
    if (r == 0) { putc(89); } else { putc(78); }
    putc(10);
}
""", b'', b'Y\n')

    # getc / putc
    check("getc/putc echo", """
func main() {
    var c;
    c = getc();
    while (c != -1) {
        putc(c);
        c = getc();
    }
}
""", b'Hello', b'Hello')

    # Recursion depth 1000
    check("recursion depth 1000", """
func count(n) {
    if (n == 0) { return 0; }
    return 1 + count(n - 1);
}
func main() {
    var r;
    r = count(1000);
    if (r == 1000) { putc(89); } else { putc(78); }
    putc(10);
}
""", b'', b'Y\n')

    # Recursion depth > 1000 should error
    check_error("recursion > 1000 raises error", """
func count(n) {
    if (n == 0) { return 0; }
    return 1 + count(n - 1);
}
func main() { count(1002); }
""")

    # Read unassigned local
    check_error("read unassigned local raises error", """
func main() {
    var x;
    putc(x);
}
""")

    # Out-of-range array index
    check_error("array out of range raises error", """
array a[5];
func main() {
    var x;
    x = a[10];
}
""")

    # Array write / read
    check("array read/write", """
array a[3];
func main() {
    a[0] = 65;
    a[1] = 66;
    a[2] = 67;
    putc(a[0]);
    putc(a[1]);
    putc(a[2]);
    putc(10);
}
""", b'', b'ABC\n')

    # Evaluation order: left-to-right
    check("eval order left-to-right", """
var g;
func inc() {
    g = g + 1;
    return g;
}
func f(a, b) {
    if (a == 1) { if (b == 2) { putc(89); putc(10); return 0; } }
    putc(78); putc(10);
    return 0;
}
func main() {
    g = 0;
    f(inc(), inc());
}
""", b'', b'Y\n')

    print(f"\nResults: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
