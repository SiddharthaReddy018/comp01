#!/usr/bin/env python3
"""
tier2/core.py — v1 to SUBLEQ compiler (Tier 2).

Reads v1 source from stdin, prints SUBLEQ machine program integers to stdout.

Architecture:
  - Single pass: build symbol tables then emit SUBLEQ via asm.py backend.
  - Return mechanism: each function has one return-jump instruction whose
    c-field is patched per call site at runtime (self-modifying SUBLEQ).
  - Array access: self-modifying SUBLEQ + post-link fixup for static addrs.
  - Recursion: not yet supported (raises CompileError).
  - Multiply: O(|b|) repeated-addition loop (documented limitation).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.asm import Assembler, FIXED
from tools.spec_limits import (
    N, MAX_SOURCE_BYTES, MAX_PARAMS, MAX_NAME_LEN, MAX_RECURSION_DEPTH
)

MAX_FRAME_SIZE = 128   # max cells per recursive frame (params+locals+temps)

# ════════════════════════════════════════════════════════════════════════════
# LEXER
# ════════════════════════════════════════════════════════════════════════════

KEYWORDS = {'var', 'array', 'func', 'if', 'else', 'while', 'return', 'getc', 'putc'}

TK_NAME   = 'NAME';  TK_INT  = 'INT';   TK_SEMI = ';'
TK_COMMA  = ',';     TK_LPAR = '(';     TK_RPAR = ')'
TK_LBRACE = '{';     TK_RBRACE = '}';   TK_LBRAK = '['; TK_RBRAK = ']'
TK_EQ     = '=';     TK_PLUS = '+';     TK_MINUS = '-'; TK_STAR = '*'
TK_LT     = '<';     TK_LE   = '<=';    TK_GT   = '>';  TK_GE   = '>='
TK_EQEQ   = '==';   TK_NEQ  = '!=';    TK_EOF  = 'EOF'


class CompileError(Exception):
    pass


class Lexer:
    def __init__(self, src):
        self.src = src; self.pos = 0; self.line = 1
        self._tok = None; self._val = None; self.advance()

    def _skip(self):
        while self.pos < len(self.src):
            c = self.src[self.pos]
            if c == '\n': self.line += 1; self.pos += 1
            elif c in ' \t\r': self.pos += 1
            elif c == '/' and self.pos+1 < len(self.src) and self.src[self.pos+1] == '/':
                while self.pos < len(self.src) and self.src[self.pos] != '\n': self.pos += 1
            else: break

    def advance(self):
        self._skip()
        if self.pos >= len(self.src): self._tok = TK_EOF; self._val = None; return
        p = self.pos; c = self.src[p]
        if c.isdigit():
            q = p
            while q < len(self.src) and self.src[q].isdigit(): q += 1
            self._tok = TK_INT; self._val = int(self.src[p:q]); self.pos = q; return
        if c.isalpha() or c == '_':
            q = p
            while q < len(self.src) and (self.src[q].isalnum() or self.src[q]=='_'): q += 1
            word = self.src[p:q]
            if len(word) > MAX_NAME_LEN:
                raise CompileError(f"Name too long: {word!r} at line {self.line}")
            self._tok = word if word in KEYWORDS else TK_NAME
            self._val = word; self.pos = q; return
        two = self.src[p:p+2]
        for s, t in [('<=',TK_LE),('>=',TK_GE),('==',TK_EQEQ),('!=',TK_NEQ)]:
            if two == s: self._tok = t; self._val = s; self.pos = p+2; return
        sym = {';':TK_SEMI,',':TK_COMMA,'(':TK_LPAR,')':TK_RPAR,
               '{':TK_LBRACE,'}':TK_RBRACE,'[':TK_LBRAK,']':TK_RBRAK,
               '=':TK_EQ,'+':TK_PLUS,'-':TK_MINUS,'*':TK_STAR,'<':TK_LT,'>':TK_GT}
        if c in sym: self._tok = sym[c]; self._val = c; self.pos = p+1; return
        raise CompileError(f"Unknown character {c!r} at line {self.line}")

    @property
    def tok(self): return self._tok
    @property
    def val(self): return self._val

    def eat(self, expected):
        if self._tok != expected:
            raise CompileError(f"Expected {expected!r}, got {self._tok!r} at line {self.line}")
        v = self._val; self.advance(); return v

    def kw(self, k): return self._tok == k
    def at(self, t): return self._tok == t

    def eat_name(self):
        if self._tok != TK_NAME:
            raise CompileError(f"Expected name, got {self._tok!r} at line {self.line}")
        v = self._val; self.advance(); return v


# ════════════════════════════════════════════════════════════════════════════
# PARSER
# ════════════════════════════════════════════════════════════════════════════

class Parser:
    def __init__(self, src): self.lex = Lexer(src)

    def parse_program(self):
        globals_list = []; arrays_dict = {}; funcs_list = []
        while not self.lex.at(TK_EOF):
            if self.lex.kw('var'):
                self.lex.advance(); name = self.lex.eat_name(); self.lex.eat(TK_SEMI)
                globals_list.append(name)
            elif self.lex.kw('array'):
                self.lex.advance(); name = self.lex.eat_name()
                self.lex.eat(TK_LBRAK); size = self.lex.eat(TK_INT); self.lex.eat(TK_RBRAK)
                self.lex.eat(TK_SEMI); arrays_dict[name] = size
            elif self.lex.kw('func'):
                funcs_list.append(self._parse_func())
            else:
                raise CompileError(f"Unexpected {self.lex.tok!r} at line {self.lex.line}")
        return globals_list, arrays_dict, funcs_list

    def _parse_func(self):
        self.lex.advance(); name = self.lex.eat_name(); self.lex.eat(TK_LPAR)
        params = []
        if not self.lex.at(TK_RPAR):
            params.append(self.lex.eat_name())
            while self.lex.at(TK_COMMA): self.lex.advance(); params.append(self.lex.eat_name())
        self.lex.eat(TK_RPAR)
        return {'name': name, 'params': params, 'body': self._parse_block()}

    def _parse_block(self):
        self.lex.eat(TK_LBRACE); stmts = []
        while not self.lex.at(TK_RBRACE): stmts.append(self._parse_stmt())
        self.lex.eat(TK_RBRACE); return stmts

    def _parse_stmt(self):
        L = self.lex
        if L.kw('var'):
            L.advance(); name = L.eat_name(); L.eat(TK_SEMI)
            return {'kind':'var_decl','name':name}
        if L.kw('if'):
            L.advance(); L.eat(TK_LPAR); cond = self._parse_expr(); L.eat(TK_RPAR)
            then = self._parse_block()
            else_ = None
            if L.kw('else'): L.advance(); else_ = self._parse_block()
            return {'kind':'if','cond':cond,'then':then,'else_':else_}
        if L.kw('while'):
            L.advance(); L.eat(TK_LPAR); cond = self._parse_expr(); L.eat(TK_RPAR)
            return {'kind':'while','cond':cond,'body':self._parse_block()}
        if L.kw('return'):
            L.advance(); e = self._parse_expr(); L.eat(TK_SEMI)
            return {'kind':'return','expr':e}
        if L.kw('putc'):
            L.advance(); L.eat(TK_LPAR); e = self._parse_expr(); L.eat(TK_RPAR); L.eat(TK_SEMI)
            return {'kind':'call_stmt','name':'putc','args':[e]}
        if L.kw('getc'):
            L.advance(); L.eat(TK_LPAR); L.eat(TK_RPAR); L.eat(TK_SEMI)
            return {'kind':'call_stmt','name':'getc','args':[]}
        if L.at(TK_NAME):
            name = L.eat_name()
            if L.at(TK_LBRAK):
                L.advance(); idx = self._parse_expr(); L.eat(TK_RBRAK)
                L.eat(TK_EQ); val = self._parse_expr(); L.eat(TK_SEMI)
                return {'kind':'arr_assign','name':name,'idx':idx,'val':val}
            if L.at(TK_EQ):
                L.advance(); val = self._parse_expr(); L.eat(TK_SEMI)
                return {'kind':'assign','name':name,'val':val}
            if L.at(TK_LPAR):
                L.advance(); args = []
                if not L.at(TK_RPAR):
                    args.append(self._parse_expr())
                    while L.at(TK_COMMA): L.advance(); args.append(self._parse_expr())
                L.eat(TK_RPAR); L.eat(TK_SEMI)
                return {'kind':'call_stmt','name':name,'args':args}
        raise CompileError(f"Unexpected {L.tok!r} at line {L.line}")

    def _parse_expr(self): return self._parse_cmp()

    def _parse_cmp(self):
        left = self._parse_add()
        OPS = {TK_LT:'<',TK_LE:'<=',TK_GT:'>',TK_GE:'>=',TK_EQEQ:'==',TK_NEQ:'!='}
        while self.lex.tok in OPS:
            op = OPS[self.lex.tok]; self.lex.advance()
            left = {'kind':'binop','op':op,'left':left,'right':self._parse_add()}
        return left

    def _parse_add(self):
        left = self._parse_mul()
        while self.lex.at(TK_PLUS) or self.lex.at(TK_MINUS):
            op = self.lex.val; self.lex.advance()
            left = self._mkbin(op, left, self._parse_mul())
        return left

    def _parse_mul(self):
        left = self._parse_unary()
        while self.lex.at(TK_STAR):
            self.lex.advance()
            left = self._mkbin('*', left, self._parse_unary())
        return left

    def _parse_unary(self):
        if self.lex.at(TK_MINUS):
            self.lex.advance()
            e = self._parse_unary()
            if e['kind'] == 'int': return {'kind':'int','val':wrap32(-e['val'])}
            return {'kind':'unary','op':'-','expr':e}
        return self._parse_primary()

    @staticmethod
    def _mkbin(op, l, r):
        # constant folding of + - * on two literals (32-bit wrap)
        if l['kind'] == 'int' and r['kind'] == 'int':
            a = l['val']; b = r['val']
            v = a + b if op == '+' else (a - b if op == '-' else a * b)
            return {'kind':'int','val':wrap32(v)}
        return {'kind':'binop','op':op,'left':l,'right':r}

    def _parse_primary(self):
        L = self.lex
        if L.at(TK_INT): v = L.eat(TK_INT); return {'kind':'int','val':v}
        if L.at(TK_LPAR): L.advance(); e = self._parse_expr(); L.eat(TK_RPAR); return e
        if L.kw('getc'): L.advance(); L.eat(TK_LPAR); L.eat(TK_RPAR); return {'kind':'getc'}
        if L.kw('putc'):
            L.advance(); L.eat(TK_LPAR); e = self._parse_expr(); L.eat(TK_RPAR)
            return {'kind':'putc','expr':e}
        if L.at(TK_NAME):
            name = L.eat_name()
            if L.at(TK_LBRAK):
                L.advance(); idx = self._parse_expr(); L.eat(TK_RBRAK)
                return {'kind':'arr_read','name':name,'idx':idx}
            if L.at(TK_LPAR):
                L.advance(); args = []
                if not L.at(TK_RPAR):
                    args.append(self._parse_expr())
                    while L.at(TK_COMMA): L.advance(); args.append(self._parse_expr())
                L.eat(TK_RPAR)
                return {'kind':'call','name':name,'args':args}
            return {'kind':'var','name':name}
        raise CompileError(f"Unexpected {L.tok!r} in expression at line {L.line}")


# ════════════════════════════════════════════════════════════════════════════
# COMPILER
# ════════════════════════════════════════════════════════════════════════════

def wrap32(x):
    x = x & 0xFFFFFFFF
    if x >= 0x80000000: x -= 0x100000000
    return x


class Compiler:
    def __init__(self):
        self.a = Assembler()
        self._globals = {}       # name -> {'kind','tag','size',...}
        self._funcs   = {}       # name -> FuncInfo dict
        self._const_pool = {}    # int -> data_tag
        self._label_ctr  = 0    # deterministic counter
        self._arr_patches  = [] # post-link array patch records
        self._call_sites   = [] # post-link call site records
        self._mul_used = False; self._mul = None; self._mul_ret = None
        self._bootstrap    = None

    # ── Labels ───────────────────────────────────────────────────────────────

    def _new_label(self, p='L'):
        self._label_ctr += 1
        return f'_{p}{self._label_ctr}'

    # ── Constants ────────────────────────────────────────────────────────────

    def _const(self, v):
        v = wrap32(v)
        if v not in self._const_pool:
            self._const_pool[v] = self.a.alloc(f'C{len(self._const_pool)}', v)
        return self._const_pool[v]

    # ── Temps ────────────────────────────────────────────────────────────────

    def _alloc_temp(self, fname):
        fi = self._funcs[fname]
        idx = fi['next_temp']; fi['next_temp'] += 1
        if idx < len(fi['temp_tags']):
            return fi['temp_tags'][idx]
        tag = self.a.alloc(f'T_{fname}_{idx}', 0)
        fi['temp_tags'].append(tag)
        return tag

    # ── Lookup ───────────────────────────────────────────────────────────────

    def _lookup(self, name, fname):
        lenv = self._funcs.get(fname, {}).get('lenv', {})
        if name in lenv: return lenv[name]
        if name in self._globals: return self._globals[name]['tag']
        raise CompileError(f"Undefined variable: {name!r}")

    # ── Branch helpers (data cells only — not SCR registers) ─────────────────

    def _branch_if_zero(self, cell, lbl):
        """Branch to lbl if mem[cell]==0. cell must be a data cell."""
        skip = self._new_label('bnz')
        self.a.branch_if_neg(cell, skip)
        self.a.copy(cell, 'SCR1', scratch='SCR2')
        self.a.negate_inplace('SCR1', scratch1='SCR2', scratch2='SCR3')
        self.a.branch_if_neg('SCR1', skip)
        self.a.jump(lbl)
        self.a.label(skip)

    def _branch_if_nonzero(self, cell, lbl):
        """Branch to lbl if mem[cell]!=0. cell must be a data cell."""
        self.a.branch_if_neg(cell, lbl)
        self.a.copy(cell, 'SCR1', scratch='SCR2')
        self.a.negate_inplace('SCR1', scratch1='SCR2', scratch2='SCR3')
        self.a.branch_if_neg('SCR1', lbl)

    # ── Signed comparison ─────────────────────────────────────────────────────

    def _emit_signed_cmp(self, x_cell, y_cell, result_cell, op, fal_lbl=None):
        """result_cell = (x op y) ? 1 : 0  — true signed per spec.
        With fal_lbl: no result; jump to fal_lbl when false, fall through when true."""
        if fal_lbl is None:
            one = self._const(1); zero = self._const(0)
        tru  = self._new_label('ct')
        fal  = fal_lbl if fal_lbl is not None else self._new_label('cf')
        end  = self._new_label('ce'); same = self._new_label('cs')
        xneg = self._new_label('cxn'); xge_yneg = self._new_label('cxyn')

        self.a.branch_if_neg(x_cell, xneg)

        # x >= 0
        self.a.branch_if_neg(y_cell, xge_yneg)
        self.a.jump(same)

        self.a.label(xge_yneg)       # x>=0, y<0 → x>y
        self.a.jump(tru if op in ('>', '>=', '!=') else fal)

        self.a.label(xneg)           # x<0
        self.a.branch_if_neg(y_cell, same)
        # x<0, y>=0 → x<y
        self.a.jump(tru if op in ('<', '<=', '!=') else fal)

        self.a.label(same)
        # Same sign: diff = x-y, no overflow
        self.a.copy(x_cell, 'SCR1', scratch='SCR2')
        self.a.sub(y_cell, 'SCR1')   # SCR1 = x-y

        if op == '<':
            self.a.branch_if_neg('SCR1', tru)
        elif op == '<=':
            # true iff NOT diff>0, i.e., -diff<0 → false
            self.a.copy('SCR1', 'SCR2', scratch='SCR3')
            self.a.negate_inplace('SCR2', scratch1='SCR3', scratch2='SCR1')
            self.a.branch_if_neg('SCR2', fal)
            self.a.jump(tru)
        elif op == '>':
            self.a.copy('SCR1', 'SCR2', scratch='SCR3')
            self.a.negate_inplace('SCR2', scratch1='SCR3', scratch2='SCR1')
            self.a.branch_if_neg('SCR2', tru)
        elif op == '>=':
            self.a.branch_if_neg('SCR1', fal)
            self.a.jump(tru)
        elif op == '==':
            self.a.branch_if_neg('SCR1', fal)
            self.a.copy('SCR1', 'SCR2', scratch='SCR3')
            self.a.negate_inplace('SCR2', scratch1='SCR3', scratch2='SCR1')
            self.a.branch_if_neg('SCR2', fal)
            self.a.jump(tru)
        elif op == '!=':
            self.a.branch_if_neg('SCR1', tru)
            self.a.copy('SCR1', 'SCR2', scratch='SCR3')
            self.a.negate_inplace('SCR2', scratch1='SCR3', scratch2='SCR1')
            self.a.branch_if_neg('SCR2', tru)

        self.a.jump(fal)
        if fal_lbl is not None:
            self.a.label(tru)
            return
        self.a.label(tru); self.a.copy(one,  result_cell); self.a.jump(end)
        self.a.label(fal); self.a.copy(zero, result_cell)
        self.a.label(end)

    def _emit_cmp_zero(self, x_cell, result_cell, op, fal_lbl=None):
        """x op 0 (literal zero on the right). SBN branches only on <0, so
        x>0 is tested as 0-x<0 in SCR1. No sign dispatch, no overflow case."""
        if fal_lbl is None:
            one = self._const(1); zero = self._const(0)
        tru = self._new_label('zt')
        fal = fal_lbl if fal_lbl is not None else self._new_label('zf')
        end = self._new_label('ze')
        Z = FIXED['SCR1']
        def pos_test(target, known_nonneg=False):   # jump to target when x > 0
            # 0 - INT_MIN wraps negative, so x<0 must be ruled out first
            skip = self._new_label('zs')
            if not known_nonneg: self.a.branch_if_neg(x_cell, skip)
            self.a.instruction(Z, Z, self.a._next())
            self.a.instruction(Z, self.a._f(x_cell), target)
            if not known_nonneg: self.a.label(skip)
        if op == '<':
            self.a.branch_if_neg(x_cell, tru)
        elif op == '>=':
            self.a.branch_if_neg(x_cell, fal)
            self.a.jump(tru)
        elif op == '>':
            pos_test(tru)
        elif op == '<=':
            pos_test(fal)
            self.a.jump(tru)
        elif op == '==':
            self.a.branch_if_neg(x_cell, fal)
            pos_test(fal, True)
            self.a.jump(tru)
        elif op == '!=':
            self.a.branch_if_neg(x_cell, tru)
            pos_test(tru, True)
        self.a.jump(fal)
        if fal_lbl is not None:
            self.a.label(tru)
            return
        self.a.label(tru); self.a.copy(one,  result_cell); self.a.jump(end)
        self.a.label(fal); self.a.copy(zero, result_cell)
        self.a.label(end)

    # ── Signed multiply (binary, ~300 steps) ─────────────────

    def _emit_multiply(self, a_cell, b_cell, result_cell):
        """Call the shared MUL routine (emitted once; ~1400 words inline per '*' overflowed memory)."""
        if not self._mul_used:
            self._mul_used = True
            self._mul = {n: self.a.alloc(n, 0) for n in ('MUL_A', 'MUL_B', 'MUL_R', 'MUL_S', 'MUL_NRC')}
        m = self._mul
        self.a.copy(a_cell, m['MUL_A']); self.a.copy(b_cell, m['MUL_B'])
        ret_cell = self.a.alloc(self._new_label('rc'), 0)
        ret_lbl = self._new_label('ret')
        nrc = m['MUL_NRC']
        self.a.instruction(nrc, nrc, self.a.here_plus(3))
        self.a.instruction(nrc, ret_cell, self.a.here_plus(3))
        self.a.jump('MUL_ENTRY')
        self.a.label(ret_lbl)
        self._call_sites.append({'callee': None, 'ret_cell': ret_cell, 'ret_lbl': ret_lbl})
        self.a.copy(m['MUL_R'], result_cell)

    def _emit_mul_const(self, dest, k, fname):
        """dest *= k for a literal 0 <= k <= 255: inline double-and-add (3 steps per add)."""
        if k == 0:
            self.a.copy(self._const(0), dest)
            return
        if k == 1:
            return
        tx = self._alloc_temp(fname)
        self.a.copy(dest, tx)
        for bit in bin(k)[3:]:
            self.a.add(dest, dest)
            if bit == '1': self.a.add(tx, dest)

    def _emit_mul_routine(self):
        zero = self._const(0); one = self._const(1); c2 = self._const(2)
        ma = self._mul['MUL_A']; mb = self._mul['MUL_B']
        mr = self._mul['MUL_R']; sg = self._mul['MUL_S']
        self.a.label('MUL_ENTRY')
        self.a.copy(zero, mr);   self.a.copy(zero, sg)

        # Handle sign of ma
        L1 = self._new_label('mn'); L2 = self._new_label('mp')
        self.a.branch_if_neg(ma, L1); self.a.jump(L2)
        self.a.label(L1); self.a.negate_inplace(ma); self.a.add(one, sg)
        self.a.label(L2)

        # Handle sign of mb
        L3 = self._new_label('mbn'); L4 = self._new_label('mbp')
        self.a.branch_if_neg(mb, L3); self.a.jump(L4)
        self.a.label(L3); self.a.negate_inplace(mb); self.a.add(one, sg)
        self.a.label(L4)

        # If sg==2 (both negative → positive), set sg=0
        Lsk = self._new_label('s2sk')
        self.a.copy(sg, 'SCR1', scratch='SCR2')
        self.a.sub(c2, 'SCR1')                              # SCR1 = sg-2
        self.a.branch_if_neg('SCR1', Lsk)                   # sg<2 → skip
        self.a.copy('SCR1', 'SCR2', scratch='SCR3')
        self.a.negate_inplace('SCR2', scratch1='SCR3', scratch2='SCR1')
        self.a.branch_if_neg('SCR2', Lsk)                   # sg>2 → skip (can't happen)
        self.a.copy(zero, sg)                                # sg==2 → set 0
        self.a.label(Lsk)

        # Binary multiply of |ma| by |mb| (mod 2^32), 31 unrolled steps:
        #   mr = 0; if mb<0 (only -2^31) {mr = ma; mb = 0}
        #   for i in 30..0: mr += mr; mb -= 2^i; if mb<0 {mb += 2^i} else {mr += ma}
        self.a.copy(zero, mr)
        # Entry points: skipping iterations i > i0 is exact when mb < 2^(i0+1)
        # (mr is 0 and those bits are 0). mb < 0 (only -2^31) always enters at 30.
        ENT = [3, 7, 11, 15, 19, 23, 27, 30]
        elab = {e: self._new_label('men') for e in ENT}
        Ltop = self._new_label('mtop'); Ldisp = self._new_label('mdsp')
        self.a.branch_if_neg(mb, Ltop); self.a.jump(Ldisp)
        self.a.label(Ltop); self.a.copy(ma, mr); self.a.copy(zero, mb)
        self.a.jump(elab[30])
        self.a.label(Ldisp)
        def tree(lo, hi):
            if lo == hi:
                self.a.jump(elab[ENT[lo]]); return
            mid = (lo + hi) // 2
            thr = self._const(1 << (ENT[mid] + 1))
            Ll = self._new_label('mtl')
            self.a.copy(mb, 'SCR1', scratch='SCR2'); self.a.sub(thr, 'SCR1')
            self.a.branch_if_neg('SCR1', Ll)
            tree(mid + 1, hi)
            self.a.label(Ll)
            tree(lo, mid)
        tree(0, len(ENT) - 1)
        for i in range(30, -1, -1):
            if i in elab: self.a.label(elab[i])
            pc = self._const(1 << i)
            Lu = self._new_label('mu'); Ln = self._new_label('mx')
            self.a.add(mr, mr)
            self.a.sub(pc, mb)
            self.a.branch_if_neg(mb, Lu)
            self.a.add(ma, mr)
            self.a.jump(Ln)
            self.a.label(Lu); self.a.add(pc, mb)
            self.a.label(Ln)

        # Apply sign
        Lok = self._new_label('sok')
        self._branch_if_zero(sg, Lok)
        self.a.negate_inplace(mr)
        self.a.label(Lok)

        # Return through MUL_NRC (same data-driven mechanism as functions)
        self.a.label('RETJMP_MUL')
        self._mul_ret = {'p1': len(self.a._code)}
        self.a.instruction(0, 0, self.a.here_plus(3))
        self._mul_ret['p2'] = len(self.a._code)
        self.a.instruction(0, self._mul['MUL_NRC'], self.a.here_plus(3))
        self._mul_ret['off'] = len(self.a._code)
        self.a.instruction(FIXED['NEG1'], FIXED['ZERO'], 0)

    # ── Array write: arr[idx] = val ───────────────────────────────────────────

    def _emit_arr_write(self, base_tag, idx_cell, val_cell):
        """Self-modifying SUBLEQ array write with post-link fixup."""
        ptr  = self.a.alloc(self._new_label('wp'),  0)
        nptr = self.a.alloc(self._new_label('wnp'), 0)
        nval = self.a.alloc(self._new_label('wnv'), 0)

        self.a.copy(base_tag, ptr);   self.a.add(idx_cell, ptr)
        self.a.copy(ptr, nptr);       self.a.negate_inplace(nptr)
        self.a.copy(val_cell, nval);  self.a.negate_inplace(nval)

        # Patch sequences: 2 instrs each set target_field_addr into the patch slots.
        # Fields to patch: WCLR.a, WCLR.b, WSTO.a (all with runtime ptr).
        p_ca = len(self.a._code)
        self.a.instruction(0, 0, self.a.here_plus(3))
        self.a.instruction(0, nptr, self.a.here_plus(3))
        p_cb = len(self.a._code)
        self.a.instruction(0, 0, self.a.here_plus(3))
        self.a.instruction(0, nptr, self.a.here_plus(3))
        p_sa = len(self.a._code)
        self.a.instruction(0, 0, self.a.here_plus(3))
        self.a.instruction(0, nptr, self.a.here_plus(3))

        wclr = len(self.a._code)
        self.a.instruction(0, 0, self.a.here_plus(3))   # (ptr,ptr,next) after patch
        wsto = len(self.a._code)
        self.a.instruction(0, nval, self.a.here_plus(3)) # (ptr,nval,next) after patch

        self._arr_patches.append(('w', p_ca, p_cb, p_sa, wclr, wsto))

    # ── Array read: result = arr[idx] ────────────────────────────────────────

    def _emit_arr_read(self, base_tag, idx_cell, result_cell):
        """Self-modifying SUBLEQ array read with post-link fixup."""
        ptr  = self.a.alloc(self._new_label('rp'),  0)
        nptr = self.a.alloc(self._new_label('rnp'), 0)

        self.a.copy(base_tag, ptr); self.a.add(idx_cell, ptr)
        self.a.copy(ptr, nptr);     self.a.negate_inplace(nptr)

        p_rb = len(self.a._code)
        self.a.instruction(0, 0, self.a.here_plus(3))
        self.a.instruction(0, nptr, self.a.here_plus(3))

        self.a.clear('SCR1')
        rlrd = len(self.a._code)
        self.a.instruction('SCR1', 0, self.a.here_plus(3))  # SCR1 -= mem[ptr]

        self.a.clear(result_cell)
        self.a.sub('SCR1', result_cell)   # result = -SCR1 = arr[idx]

        self._arr_patches.append(('r', p_rb, rlrd))

    # ── Expression compiler ───────────────────────────────────────────────────

    def _compile_expr(self, node, dest, fname):
        k = node['kind']
        if k == 'int':
            self.a.copy(self._const(node['val']), dest)
        elif k == 'var':
            c = self._lookup(node['name'], fname)
            if c != dest: self.a.copy(c, dest)
        elif k == 'arr_read':
            g = self._globals.get(node['name'])
            if g is None or g['kind'] != 'array':
                raise CompileError(f"Undefined array: {node['name']!r}")
            ec = self._elem_cell(node['name'], node['idx'])
            if ec is not None:                       # literal in-range index: direct cell
                if ec != dest: self.a.copy(ec, dest)
            else:
                if self._is_leaf(node['idx']):               # leaf index read in place
                    it = self._leaf_cell(node['idx'], fname)
                else:
                    it = self._alloc_temp(fname)
                    self._compile_expr(node['idx'], it, fname)
                self._emit_arr_read(g['base_tag'], it, dest)
        elif k == 'getc':
            self.a.getc(dest)
        elif k == 'putc':
            et = self._alloc_temp(fname)
            self._compile_expr(node['expr'], et, fname)
            self.a.putc(et)
            self.a.copy(self._const(0), dest)
        elif k == 'unary':
            self._compile_expr(node['expr'], dest, fname)
            self.a.negate_inplace(dest)
        elif k == 'binop':
            op = node['op']
            self._compile_expr(node['left'],  dest, fname)
            rn = node['right']
            if op == '*' and rn['kind'] == 'int' and 0 <= rn['val'] <= 255:
                self._emit_mul_const(dest, rn['val'], fname)
                return
            if self._is_leaf(rn):
                rt = self._leaf_cell(rn, fname)      # leaf operand used in place
            else:
                rt = self._alloc_temp(fname)
                self._compile_expr(rn, rt, fname)
            if op == '+': self.a.add(rt, dest)
            elif op == '-': self.a.sub(rt, dest)
            elif op == '*': self._emit_multiply(dest, rt, dest)
            elif op in ('<','<=','>','>=','==','!='):
                if rn['kind'] == 'int' and rn['val'] == 0: self._emit_cmp_zero(dest, dest, op)
                else: self._emit_signed_cmp(dest, rt, dest, op)
            else: raise CompileError(f"Unknown op: {op!r}")
        elif k == 'call':
            self._compile_call(node['name'], node['args'], dest, fname)
        else:
            raise CompileError(f"Unknown expr kind: {k!r}")

    def _is_leaf(self, n): return n['kind'] in ('int', 'var')

    def _elem_cell(self, name, idx):
        # data cell of a[idx] when idx is a literal inside the declared size, else None
        if idx['kind'] != 'int': return None
        g = self._globals[name]
        if 0 <= idx['val'] < g['size']: return ('data+', (g['arr_data_tag'][1], idx['val']))
        return None

    @staticmethod
    def _pure(n):
        # no call, getc or putc inside: operand order cannot matter
        k = n['kind']
        if k in ('int', 'var'): return True
        if k == 'binop': return Compiler._pure(n['left']) and Compiler._pure(n['right'])
        if k == 'arr_read': return Compiler._pure(n['idx'])
        if k == 'unary': return Compiler._pure(n['expr'])
        return False

    @staticmethod
    def _touches(n, name):
        # True if n contains a call or any read of array `name`
        k = n['kind']
        if k == 'call': return True
        if k == 'arr_read': return n['name'] == name or Compiler._touches(n['idx'], name)
        if k in ('int', 'getc', 'var'): return False
        if k == 'binop': return Compiler._touches(n['left'], name) or Compiler._touches(n['right'], name)
        return Compiler._touches(n['expr'], name)

    @staticmethod
    def _direct_elem_ok(n, name, c):
        # a[c] = n computed straight into the element: reads of that array only as a[c]
        # on the left spine; no call or read of the array in right operands
        k = n['kind']
        if k == 'binop':
            return (Compiler._direct_elem_ok(n['left'], name, c)
                    and not Compiler._touches(n['right'], name))
        if k == 'unary': return Compiler._direct_elem_ok(n['expr'], name, c)
        if k == 'arr_read':
            if n['name'] != name: return True            # index goes to a temp first
            return n['idx']['kind'] == 'int' and n['idx']['val'] == c
        return True   # leaf, getc, putc, call (args go to temps, result written last)

    @staticmethod
    def _mentions(n, x, calls):
        # True if expression n reads variable x (or, when calls is set, contains a call)
        k = n['kind']
        if k == 'var': return n['name'] == x
        if k == 'call':
            return calls or any(Compiler._mentions(a, x, calls) for a in n['args'])
        if k in ('int', 'getc'): return False
        if k == 'binop': return Compiler._mentions(n['left'], x, calls) or Compiler._mentions(n['right'], x, calls)
        if k == 'arr_read': return Compiler._mentions(n['idx'], x, calls)
        return Compiler._mentions(n['expr'], x, calls)   # unary, putc

    @staticmethod
    def _direct_ok(n, x, is_glob):
        # x = n may be computed straight into x if every read of x happens before
        # the first write of x: x only on the left spine, never in a right operand
        # (and for a global x no call in a right operand, the callee could read it).
        k = n['kind']
        if k == 'binop':
            return (Compiler._direct_ok(n['left'], x, is_glob)
                    and not Compiler._mentions(n['right'], x, is_glob))
        if k == 'unary': return Compiler._direct_ok(n['expr'], x, is_glob)
        return True   # leaf, getc, putc, arr_read (index goes to a temp), call (args go to temps)

    def _leaf_cell(self, n, fname):
        if n['kind'] == 'int': return self._const(n['val'])
        return self._lookup(n['name'], fname)

    def _cond_jump_false(self, node, lbl, fname):
        """Jump to lbl if node evaluates to 0; fall through otherwise."""
        if node['kind'] == 'binop' and node['op'] in ('<', '<=', '>', '>=', '==', '!='):
            l = node['left']; r = node['right']
            if self._is_leaf(l) and self._is_leaf(r):
                xc = self._leaf_cell(l, fname); yc = self._leaf_cell(r, fname)
            else:
                xc = self._alloc_temp(fname); self._compile_expr(l, xc, fname)
                if self._is_leaf(r): yc = self._leaf_cell(r, fname)
                else:
                    yc = self._alloc_temp(fname); self._compile_expr(r, yc, fname)
            if r['kind'] == 'int' and r['val'] == 0: self._emit_cmp_zero(xc, None, node['op'], fal_lbl=lbl)
            else: self._emit_signed_cmp(xc, yc, None, node['op'], fal_lbl=lbl)
        else:
            ct = self._alloc_temp(fname)
            self._compile_expr(node, ct, fname)
            self._branch_if_zero(ct, lbl)

    # ── Call compilation ──────────────────────────────────────────────────────

    def _compile_call(self, callee, arg_nodes, result_dest, caller):
        fi = self._funcs.get(callee)
        if fi is None: raise CompileError(f"Undefined function: {callee!r}")
        if len(arg_nodes) != len(fi['params']):
            raise CompileError(f"{callee!r}: expected {len(fi['params'])} args")
        is_self = (callee == caller)

        # Evaluate args into caller temps
        # An arg goes straight into the callee's param cell when no call occurs in it
        # or in any later arg (a call could overwrite that cell first); never for self-calls.
        jmax = -1
        for i, an in enumerate(arg_nodes):
            if Compiler._mentions(an, '', True): jmax = i
        arg_temps = []
        for i, an in enumerate(arg_nodes):
            if not is_self and i > jmax:
                self._compile_expr(an, fi['param_tags'][i], caller); arg_temps.append(None)
            else:
                t = self._alloc_temp(caller); self._compile_expr(an, t, caller); arg_temps.append(t)

        # For self-recursion: snapshot all live cells and push onto stack
        cells_to_save = []
        if is_self:
            cfi = self._funcs[caller]
            cells_to_save = ([cfi['neg_ret_cell']] + list(cfi['param_tags'])
                             + list(cfi['local_tags']) + list(cfi['temp_tags'][:cfi['next_temp']]))
            self._emit_push_frame(callee, cells_to_save)

        # Copy temps → callee params
        for pt, at in zip(fi['param_tags'], arg_temps):
            if at is not None: self.a.copy(at, pt)

        # Set callee NRC = -ret_addr (ret_cell holds +ret_addr, filled post-link)
        ret_cell = self.a.alloc(self._new_label('rc'), 0)
        ret_lbl  = self._new_label('ret')
        nrc      = fi['neg_ret_cell']
        self.a.instruction(nrc, nrc, self.a.here_plus(3))
        self.a.instruction(nrc, ret_cell, self.a.here_plus(3))
        self.a.jump(fi['entry_label'])
        self.a.label(ret_lbl)
        self._call_sites.append({'callee':callee,'ret_cell':ret_cell,'ret_lbl':ret_lbl})

        # For self-recursion: pop frame after return
        if is_self:
            self._emit_pop_frame(callee, cells_to_save)

        self.a.copy('RET', result_dest)

    # ── Statement compiler ────────────────────────────────────────────────────

    def _compile_stmt(self, node, fname):
        mark = self._funcs[fname]['next_temp']
        self._compile_stmt_inner(node, fname)
        self._funcs[fname]['next_temp'] = mark   # temps are dead at statement end

    def _compile_stmt_inner(self, node, fname):
        k = node['kind']
        if k == 'var_decl':
            tag = self.a.alloc(f'L_{fname}_{node["name"]}', 0)
            self._funcs[fname]['lenv'][node['name']] = tag
            self._funcs[fname]['local_tags'].append(tag)
        elif k == 'assign':
            name = node['name']; fi = self._funcs[fname]
            if name in fi['lenv']: dest = fi['lenv'][name]
            elif name in self._globals: dest = self._globals[name]['tag']
            else: raise CompileError(f"Undefined variable: {name!r}")
            is_glob = name not in fi['lenv']
            val = node['val']
            if (val['kind'] == 'binop' and val['op'] == '+' and val['right']['kind'] == 'var'
                    and val['right']['name'] == name and Compiler._pure(val['left'])
                    and not Compiler._mentions(val['left'], name, False)):
                val = {'kind': 'binop', 'op': '+', 'left': val['right'], 'right': val['left']}
            if self._direct_ok(val, name, is_glob):
                self._compile_expr(val, dest, fname)   # no temp
            else:
                vt = self._alloc_temp(fname)
                self._compile_expr(val, vt, fname)
                self.a.copy(vt, dest)
        elif k == 'arr_assign':
            g = self._globals.get(node['name'])
            if g is None or g['kind'] != 'array':
                raise CompileError(f"Undefined array: {node['name']!r}")
            ec = self._elem_cell(node['name'], node['idx'])
            if ec is not None:                       # literal in-range index: direct cell
                if self._direct_elem_ok(node['val'], node['name'], node['idx']['val']):
                    self._compile_expr(node['val'], ec, fname)
                else:
                    vt = self._alloc_temp(fname)
                    self._compile_expr(node['val'], vt, fname)
                    self.a.copy(vt, ec)
            else:
                ix = node['idx']; vl = node['val']
                # a leaf index stays in place unless it is a global that a call in the
                # value could change before the store (locals are restored by recursion)
                in_place = self._is_leaf(ix) and (ix['kind'] == 'int'
                           or ix['name'] in self._funcs[fname]['lenv']
                           or not Compiler._mentions(vl, '', True))
                if in_place: it = self._leaf_cell(ix, fname)
                else:
                    it = self._alloc_temp(fname); self._compile_expr(ix, it, fname)
                if self._is_leaf(vl): vt = self._leaf_cell(vl, fname)
                else:
                    vt = self._alloc_temp(fname); self._compile_expr(vl, vt, fname)
                self._emit_arr_write(g['base_tag'], it, vt)
        elif k == 'if':
            el = self._new_label('else'); en = self._new_label('endif')
            m0 = self._funcs[fname]['next_temp']
            self._cond_jump_false(node['cond'], el, fname)
            self._funcs[fname]['next_temp'] = m0     # condition temps are dead
            for s in node['then']: self._compile_stmt(s, fname)
            self.a.jump(en); self.a.label(el)
            if node['else_']:
                for s in node['else_']: self._compile_stmt(s, fname)
            self.a.label(en)
        elif k == 'while':
            ll = self._new_label('wl'); xl = self._new_label('wx')
            m0 = self._funcs[fname]['next_temp']
            self.a.label(ll)
            self._cond_jump_false(node['cond'], xl, fname)
            self._funcs[fname]['next_temp'] = m0     # condition temps are dead
            for s in node['body']: self._compile_stmt(s, fname)
            self.a.jump(ll); self.a.label(xl)
        elif k == 'return':
            rt = self._alloc_temp(fname)
            self._compile_expr(node['expr'], rt, fname)
            self.a.copy(rt, 'RET')
            self.a.jump(self._funcs[fname]['ret_jmp_lbl'])
        elif k == 'call_stmt':
            if node['name'] == 'putc':
                et = self._alloc_temp(fname)
                self._compile_expr(node['args'][0], et, fname)
                self.a.putc(et)
            elif node['name'] == 'getc':
                self.a.getc(self._alloc_temp(fname))
            else:
                t = self._alloc_temp(fname)
                self._compile_call(node['name'], node['args'], t, fname)
        else:
            raise CompileError(f"Unknown stmt kind: {k!r}")

    # ── Function compiler ──────────────────────────────────────────────────────

    def _compile_func(self, func_ast):
        fname = func_ast['name']; fi = self._funcs[fname]
        fi['lenv'] = {}; fi['local_tags'] = []; fi['temp_tags'] = []; fi['next_temp'] = 0
        for pname, ptag in zip(func_ast['params'], fi['param_tags']):
            fi['lenv'][pname] = ptag

        self.a.label(fi['entry_label'])
        for s in func_ast['body']: self._compile_stmt(s, fname)

        # Fall-through return 0
        self.a.copy(self._const(0), 'RET')
        # Epilogue: patch RETJMP c-field from NRC (data-driven return address).
        self.a.label(fi['ret_jmp_lbl'])
        fi['ret_patch_p1'] = len(self.a._code)
        self.a.instruction(0, 0, self.a.here_plus(3))                    # clear c-field
        fi['ret_patch_p2'] = len(self.a._code)
        self.a.instruction(0, fi['neg_ret_cell'], self.a.here_plus(3))   # c-field = -NRC = ret_addr
        fi['ret_jmp_offset'] = len(self.a._code)
        self.a.instruction(FIXED['NEG1'], FIXED['ZERO'], 0)

    # ── Frame push/pop for self-recursion ────────────────────────────────────

    def _emit_push_frame(self, fname, cells):
        """Push cells onto fname's stack (negated), ~9 steps per cell.
        sp_local holds -(absolute stack pointer), set post-link."""
        spn = self._funcs[fname]['sp_local']
        one = self._const(1)
        for cell in cells:
            p_ca = len(self.a._code)
            self.a.instruction(0, 0, self.a.here_plus(3))
            self.a.instruction(0, spn, self.a.here_plus(3))
            p_cb = len(self.a._code)
            self.a.instruction(0, 0, self.a.here_plus(3))
            self.a.instruction(0, spn, self.a.here_plus(3))
            p_sa = len(self.a._code)
            self.a.instruction(0, 0, self.a.here_plus(3))
            self.a.instruction(0, spn, self.a.here_plus(3))
            wclr = len(self.a._code)
            self.a.instruction(0, 0, self.a.here_plus(3))       # (sp,sp)   mem[sp] = 0
            wsto = len(self.a._code)
            self.a.instruction(0, cell, self.a.here_plus(3))    # (sp,cell) mem[sp] = -cell
            self._arr_patches.append(('w', p_ca, p_cb, p_sa, wclr, wsto))
            self.a.sub(one, spn)                                # sp += 1

    def _emit_pop_frame(self, fname, cells):
        """Pop cells in reverse order; stored values are negated, so result = 0 - mem[sp]."""
        spn = self._funcs[fname]['sp_local']
        neg1 = self._const(-1)
        for cell in reversed(cells):
            self.a.sub(neg1, spn)                               # sp -= 1
            self.a.clear(cell)
            p_rb = len(self.a._code)
            self.a.instruction(0, 0, self.a.here_plus(3))
            self.a.instruction(0, spn, self.a.here_plus(3))
            rlrd = len(self.a._code)
            self.a.instruction(cell, 0, self.a.here_plus(3))    # cell -= mem[sp] -> val
            self._arr_patches.append(('r', p_rb, rlrd))

    # ── Recursion detector ────────────────────────────────────────────────────

    def _is_recursive(self, func_ast):
        def stmts(ss, n):
            for s in ss:
                k = s['kind']
                if k == 'call_stmt' and s['name'] == n: return True
                if k == 'if':
                    if stmts(s['then'], n): return True
                    if s['else_'] and stmts(s['else_'], n): return True
                if k == 'while' and stmts(s['body'], n): return True
                e = s.get('val') or s.get('expr')
                if e and expr(e, n): return True
                if k == 'arr_assign' and expr(s['idx'], n): return True
            return False
        def expr(nd, n):
            if nd is None: return False
            k = nd.get('kind')
            if k == 'call':
                if nd['name'] == n: return True
                return any(expr(a, n) for a in nd['args'])
            if k == 'binop': return expr(nd['left'],n) or expr(nd['right'],n)
            if k == 'unary': return expr(nd['expr'], n)
            if k == 'arr_read': return expr(nd['idx'], n)
            if k == 'putc': return expr(nd['expr'], n)
            return False
        return stmts(func_ast['body'], func_ast['name'])

    # ── Compile top-level ─────────────────────────────────────────────────────

    def compile(self, src):
        # Reset
        self.a = Assembler(); self._globals = {}; self._funcs = {}
        self._const_pool = {}; self._label_ctr = 0
        self._arr_patches = []; self._call_sites = []; self._bootstrap = None
        self._mul_used = False; self._mul = None; self._mul_ret = None

        gl, ad, fl = Parser(src).parse_program()

        # Allocate globals
        for name in gl:
            tag = self.a.alloc(f'G_{name}', 0)
            self._globals[name] = {'kind':'global','tag':tag,'size':1}

        # Allocate arrays (sorted for determinism)
        for name in sorted(ad.keys()):
            sz  = ad[name]
            dt  = self.a.alloc_array(f'ARR_{name}', sz)
            bt  = self.a.alloc(f'ARR_BASE_{name}', 0)
            self._globals[name] = {'kind':'array','tag':bt,'size':sz,
                                   'base_tag':bt,'arr_data_tag':dt}

        # Pre-register all functions
        func_names = set()
        for fa in fl:
            fn = fa['name']
            if fn in func_names: raise CompileError(f"Duplicate function: {fn!r}")
            func_names.add(fn)
            if len(fa['params']) > MAX_PARAMS:
                raise CompileError(f"Too many params in {fn!r}")
            is_rec = self._is_recursive(fa)
            pts = [self.a.alloc(f'P_{fn}_{p}', 0) for p in fa['params']]
            # For recursive functions: allocate stack storage and sp cell.
            if is_rec:
                stk_data = None   # allocated after the body is compiled (exact frame size)
                stk_base = self.a.alloc(f'STK_BASE_{fn}', 0)  # filled post-link
                sp       = self.a.alloc(f'SP_{fn}', 0)
            else:
                stk_data = None; stk_base = None; sp = None
            self._funcs[fn] = {
                'params': fa['params'], 'param_tags': pts,
                'entry_label': f'FUNC_{fn}', 'ret_jmp_lbl': f'RETJMP_{fn}',
                'ret_jmp_offset': None,
                'neg_ret_cell': self.a.alloc(f'NRC_{fn}', 0),
                'ret_patch_p1': None, 'ret_patch_p2': None,
                'is_recursive': is_rec,
                'stack_data_tag': stk_data,  # the alloc_array tag
                'stack_base_tag': stk_base,  # scalar cell holding stk_data address
                'sp_local': sp,
                'lenv': {}, 'local_tags': [], 'temp_tags': [], 'next_temp': 0,
            }

        if 'main' not in self._funcs:
            raise CompileError("No main() function defined")

        main_fi = self._funcs['main']

        # Bootstrap: patch main's ret-jump c-field → halt, then jump to main
        brc = self.a.alloc(self._new_label('brc'), 0)   # +halt_addr (post-link)
        mn = main_fi['neg_ret_cell']
        self.a.instruction(mn, mn, self.a.here_plus(3))
        self.a.instruction(mn, brc, self.a.here_plus(3))
        self.a.jump(main_fi['entry_label'])
        halt_lbl = self._new_label('halt')
        self.a.label(halt_lbl)
        self.a.instruction(FIXED['NEG1'], FIXED['ZERO'], -1)   # pc=-1 → VM halts
        self._bootstrap = {'brc':brc,'halt_lbl':halt_lbl}

        # Compile all functions
        for fa in fl: self._compile_func(fa)
        if self._mul_used: self._emit_mul_routine()

        # Recursive-function stacks, sized to the exact frame (NRC + params + locals + temps)
        for fn in sorted(self._funcs):
            fi = self._funcs[fn]
            if fi['is_recursive']:
                frame = 1 + len(fi['param_tags']) + len(fi['local_tags']) + len(fi['temp_tags'])
                fi['stack_data_tag'] = self.a.alloc_array(
                    f'STK_{fn}', (MAX_RECURSION_DEPTH + 1) * frame)

        # Link
        words = self.a.link()
        code_len  = len(self.a._code)
        data_base = 11 + code_len

        _offs = {}; _o = 0
        for _n in self.a._data_names:
            _offs[_n] = _o; _o += self.a._data_sizes[_n]

        def da(tag):
            name = tag[1] if isinstance(tag, tuple) else tag
            return data_base + _offs[name]

        # Post-link: array base addresses
        for g in self._globals.values():
            if g['kind'] == 'array':
                words[da(g['base_tag'])] = da(g['arr_data_tag'])

        # Post-link: stack base addresses for recursive functions
        for finfo in self._funcs.values():
            if finfo['is_recursive']:
                words[da(finfo['stack_base_tag'])] = da(finfo['stack_data_tag'])
                words[da(finfo['sp_local'])] = -da(finfo['stack_data_tag'])

        # Post-link: array patches
        for patch in self._arr_patches:
            if patch[0] == 'w':
                _, pca, pcb, psa, wclr, wsto = patch
                Aca = 11 + wclr + 0;  Acb = 11 + wclr + 1;  Asa = 11 + wsto + 0
                words[11+pca+0] = Aca; words[11+pca+1] = Aca; words[11+pca+3] = Aca
                words[11+pcb+0] = Acb; words[11+pcb+1] = Acb; words[11+pcb+3] = Acb
                words[11+psa+0] = Asa; words[11+psa+1] = Asa; words[11+psa+3] = Asa
            elif patch[0] == 'r':
                _, prb, rlrd = patch
                Arb = 11 + rlrd + 1
                words[11+prb+0] = Arb; words[11+prb+1] = Arb; words[11+prb+3] = Arb

        # Post-link: epilogue patch sequences
        for fn in sorted(self._funcs):
            finfo = self._funcs[fn]
            if finfo['ret_jmp_offset'] is None:
                raise CompileError(f"Function {fn!r} never compiled")
            cfa = 11 + finfo['ret_jmp_offset'] + 2
            p1 = finfo['ret_patch_p1']; p2 = finfo['ret_patch_p2']
            words[11+p1+0] = cfa; words[11+p1+1] = cfa
            words[11+p2+0] = cfa

        if self._mul_used:
            cfa = 11 + self._mul_ret['off'] + 2
            p1 = self._mul_ret['p1']; p2 = self._mul_ret['p2']
            words[11+p1+0] = cfa; words[11+p1+1] = cfa
            words[11+p2+0] = cfa

        # Post-link: call sites (positive return addresses)
        for site in self._call_sites:
            words[da(site['ret_cell'])] = 11 + self.a._labels[site['ret_lbl']]

        # Post-link: bootstrap halt address
        bs = self._bootstrap
        words[da(bs['brc'])] = 11 + self.a._labels[bs['halt_lbl']]

        return words


# ════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ════════════════════════════════════════════════════════════════════════════

def compile_v1(src):
    return Compiler().compile(src)


def main():
    src = sys.stdin.read()
    if len(src) > MAX_SOURCE_BYTES:
        print(f"error: source too large ({len(src)} > {MAX_SOURCE_BYTES})", file=sys.stderr)
        sys.exit(1)
    try:
        words = compile_v1(src)
    except CompileError as e:
        print(f"compile error: {e}", file=sys.stderr)
        sys.exit(1)
    print(' '.join(str(w) for w in words))


if __name__ == '__main__':
    main()
