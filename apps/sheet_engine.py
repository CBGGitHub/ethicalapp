"""Spreadsheet data model + Excel-compatible formula engine (used by Ethical Sheets)."""
import datetime
import math
import random
import re
import statistics
from dataclasses import dataclass, field

MAX_ROWS, MAX_COLS = 1048576, 16384
EPOCH = datetime.datetime(1899, 12, 30)


# ====================================================================== addresses

def col_name(c):
    """0 -> 'A', 25 -> 'Z', 26 -> 'AA'."""
    s = ""
    c += 1
    while c:
        c, rem = divmod(c - 1, 26)
        s = chr(65 + rem) + s
    return s


def col_index(name):
    n = 0
    for ch in name.upper():
        n = n * 26 + ord(ch) - 64
    return n - 1


def cell_name(r, c):
    return f"{col_name(c)}{r + 1}"


_CELL = re.compile(r"^\$?([A-Za-z]{1,3})\$?(\d+)$")


def parse_cell(text):
    m = _CELL.match(text.strip())
    if not m:
        return None
    return int(m.group(2)) - 1, col_index(m.group(1))


def parse_range(text):
    """'A1' or 'A1:C5' -> (r1, c1, r2, c2) or None."""
    parts = text.strip().split(":")
    a = parse_cell(parts[0])
    if not a:
        return None
    b = parse_cell(parts[1]) if len(parts) == 2 else a
    if not b:
        return None
    return min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])


def quote_sheet(name):
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", name) else "'" + name.replace("'", "''") + "'"


# ====================================================================== values

class ExcelError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code

    def __eq__(self, other):
        return isinstance(other, ExcelError) and other.code == self.code

    def __hash__(self):
        return hash(self.code)

    def __repr__(self):
        return self.code

    __str__ = __repr__


DIV0, VALUE, REF, NAME, NA, NUM, CIRC = (ExcelError(c) for c in
                                         ("#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#N/A", "#NUM!",
                                          "#CIRC!"))
ERRORS = {e.code: e for e in (DIV0, VALUE, REF, NAME, NA, NUM, ExcelError("#NULL!"), CIRC)}


def to_serial(dt):
    if isinstance(dt, datetime.datetime):
        d = dt - EPOCH
    elif isinstance(dt, datetime.date):
        d = datetime.datetime(dt.year, dt.month, dt.day) - EPOCH
    elif isinstance(dt, datetime.time):
        return (dt.hour * 3600 + dt.minute * 60 + dt.second) / 86400
    else:
        return dt
    return d.days + d.seconds / 86400


def from_serial(v):
    return EPOCH + datetime.timedelta(days=float(v))


# ====================================================================== workbook model

@dataclass
class Cell:
    value: object = None          # raw input: None, number, bool, str (formulas start with '=')
    style: dict = field(default_factory=dict)
    cached: object = None         # value cached by Excel (used when we can't compute a formula)
    comment: str = ""

    def is_formula(self):
        return isinstance(self.value, str) and self.value.startswith("=") and len(self.value) > 1


class Sheet:
    def __init__(self, name):
        self.name = name
        self.cells = {}           # (row, col) -> Cell
        self.col_widths = {}      # col -> px
        self.row_heights = {}     # row -> px
        self.merges = []          # list of (r1, c1, r2, c2)
        self.freeze = None        # (row, col) of top-left unfrozen cell, or None
        self.charts = []          # dicts: type, ref, title, row, col, w, h
        self.images = []          # dicts: data (bytes), row, col, w, h

    def max_row(self):
        return max((r for r, _ in self.cells), default=-1)

    def max_col(self):
        return max((c for _, c in self.cells), default=-1)

    def get(self, r, c):
        return self.cells.get((r, c))

    def raw(self, r, c):
        cell = self.cells.get((r, c))
        return None if cell is None else cell.value


class Workbook:
    def __init__(self):
        self.sheets = [Sheet("Sheet1")]
        self.names = {}           # defined name (upper) -> "Sheet1!$A$1:$B$5"
        self.cache = {}
        self._evaluating = set()
        self.has_circular = False

    def sheet(self, name):
        lname = name.lower()
        return next((s for s in self.sheets if s.name.lower() == lname), None)

    def invalidate(self):
        self.cache.clear()
        self.has_circular = False

    # ---- evaluation
    def value(self, sheet, r, c):
        """Computed value of a cell (number, str, bool, None or ExcelError)."""
        key = (sheet.name, r, c)
        if key in self.cache:
            return self.cache[key]
        cell = sheet.cells.get((r, c))
        if cell is None:
            return None
        if not cell.is_formula():
            return cell.value
        if key in self._evaluating:
            self.has_circular = True
            return CIRC
        self._evaluating.add(key)
        try:
            v = Evaluator(self, sheet).run(cell.value)
            if v == NAME and cell.cached is not None:
                v = cell.cached   # function we don't know yet: trust Excel's saved result
        except RecursionError:
            v = CIRC
        except ExcelError as e:
            v = e
        except Exception:
            v = VALUE
        finally:
            self._evaluating.discard(key)
        self.cache[key] = v
        return v

    def recalc_all(self):
        """Evaluate every formula top-to-bottom so long chains never recurse deeply."""
        self.invalidate()
        for s in self.sheets:
            for (r, c) in sorted(k for k, cell in s.cells.items() if cell.is_formula()):
                self.value(s, r, c)


# ====================================================================== tokenizer

TOKEN_RE = re.compile(r"""
 (?P<ws>\s+)
|(?P<str>"(?:[^"]|"")*")
|(?P<err>\#(?:DIV/0!|VALUE!|REF!|NAME\?|N/A|NUM!|NULL!|CIRC!))
|(?P<ref>(?:(?:'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_.]*)!)?
     (?:\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?(?![A-Za-z0-9_(])
       |\$?[A-Za-z]{1,3}:\$?[A-Za-z]{1,3}(?![A-Za-z0-9_(])))
|(?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
|(?P<func>[A-Za-z_][A-Za-z0-9_.]*(?=\s*\())
|(?P<name>[A-Za-z_\\][A-Za-z0-9_.]*)
|(?P<op><=|>=|<>|[-+*/^&=<>%(),;:{}])
""", re.X)


def tokenize(text):
    out, pos = [], 0
    while pos < len(text):
        m = TOKEN_RE.match(text, pos)
        if not m:
            raise ExcelError("#VALUE!")
        kind = m.lastgroup
        out.append((kind, m.group(), m.start(), m.end()))
        pos = m.end()
    return out


_REF_PART = re.compile(r"^(\$?)([A-Za-z]{1,3})(\$?)(\d*)$")


def split_ref(tok):
    """'Sheet1!$A1:B$2' -> (sheet or None, [(colabs, col, rowabs, row|None), ...])"""
    sheet = None
    if "!" in tok:
        sheet, tok = tok.rsplit("!", 1)
        if sheet.startswith("'"):
            sheet = sheet[1:-1].replace("''", "'")
    parts = []
    for p in tok.split(":"):
        m = _REF_PART.match(p)
        parts.append((m.group(1) == "$", col_index(m.group(2)), m.group(3) == "$",
                      int(m.group(4)) - 1 if m.group(4) else None))
    return sheet, parts


def join_ref(sheet, parts):
    s = ":".join(f"{'$' if ca else ''}{col_name(c)}" + ("" if r is None else f"{'$' if ra else ''}{r + 1}")
                 for ca, c, ra, r in parts)
    return (quote_sheet(sheet) + "!" if sheet else "") + s


def rewrite_refs(formula, fn):
    """Apply fn(sheet, parts) -> new ref text (or None to keep) to every reference in a formula."""
    try:
        toks = tokenize(formula[1:])
    except ExcelError:
        return formula
    out = ["="]
    for kind, text, _, _ in toks:
        if kind == "ref":
            sheet, parts = split_ref(text)
            new = fn(sheet, parts)
            out.append(text if new is None else new)
        else:
            out.append(text)
    return "".join(out)


def shift_formula(formula, dr, dc):
    """Adjust relative references when a formula is copied dr rows / dc cols away."""
    def fn(sheet, parts):
        new = []
        for ca, c, ra, r in parts:
            nc = c if ca else c + dc
            nr = r if (ra or r is None) else r + dr
            if nc < 0 or (nr is not None and nr < 0):
                return "#REF!"
            new.append((ca, nc, ra, nr))
        return join_ref(sheet, new)
    return rewrite_refs(formula, fn)


def adjust_for_structure(formula, formula_sheet, target_sheet, axis, at, n):
    """Fix references after inserting (n>0) or deleting (n<0) rows/cols at index `at`."""
    def fn(sheet, parts):
        if (sheet or formula_sheet).lower() != target_sheet.lower():
            return None
        idx = 3 if axis == "row" else 1
        vals = [p[idx] for p in parts]
        if None in vals:   # whole-column/row ranges: leave alone
            return None
        if n > 0:
            vals = [v + n if v >= at else v for v in vals]
        else:
            lo, hi = at, at - n - 1
            if len(vals) == 1:
                if lo <= vals[0] <= hi:
                    return "#REF!"
                vals = [vals[0] + n if vals[0] > hi else vals[0]]
            else:
                a, b = vals
                if lo <= a and b <= hi:
                    return "#REF!"
                a = a if a < lo else (lo if a <= hi else a + n)
                b = b if b < lo else (lo - 1 if b <= hi else b + n)
                vals = [a, b]
        new = []
        for p, v in zip(parts, vals):
            p = list(p)
            p[idx] = v
            new.append(tuple(p))
        return join_ref(sheet, new)
    return rewrite_refs(formula, fn)


# ====================================================================== parser

class Parser:
    def __init__(self, text):
        self.toks = [t for t in tokenize(text) if t[0] != "ws"]
        self.i = 0

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None, 0, 0)

    def take(self):
        t = self.peek()
        self.i += 1
        return t

    def expect(self, text):
        t = self.take()
        if t[1] != text:
            raise ExcelError("#VALUE!")

    def parse(self):
        node = self.compare()
        if self.i != len(self.toks):
            raise ExcelError("#VALUE!")
        return node

    def compare(self):
        a = self.concat()
        while self.peek()[1] in ("=", "<>", "<", ">", "<=", ">="):
            op = self.take()[1]
            a = ("bin", op, a, self.concat())
        return a

    def concat(self):
        a = self.additive()
        while self.peek()[1] == "&":
            self.take()
            a = ("bin", "&", a, self.additive())
        return a

    def additive(self):
        a = self.term()
        while self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            a = ("bin", op, a, self.term())
        return a

    def term(self):
        a = self.power()
        while self.peek()[1] in ("*", "/"):
            op = self.take()[1]
            a = ("bin", op, a, self.power())
        return a

    def power(self):
        a = self.unary()
        while self.peek()[1] == "^":
            self.take()
            a = ("bin", "^", a, self.unary())
        return a

    def unary(self):
        if self.peek()[1] in ("-", "+"):
            op = self.take()[1]
            v = self.unary()
            return ("neg", v) if op == "-" else v
        return self.postfix()

    def postfix(self):
        a = self.primary()
        while self.peek()[1] == "%":
            self.take()
            a = ("pct", a)
        return a

    def primary(self):
        kind, text, _, _ = self.take()
        if kind == "num":
            return ("lit", float(text) if any(ch in text for ch in ".eE") else int(text))
        if kind == "str":
            return ("lit", text[1:-1].replace('""', '"'))
        if kind == "err":
            return ("lit", ERRORS.get(text.upper(), VALUE))
        if kind == "ref":
            return ("ref", text)
        if kind == "func":
            name = text.upper()
            self.expect("(")
            args = []
            if self.peek()[1] != ")":
                while True:
                    if self.peek()[1] in (",", ";", ")"):
                        args.append(("lit", None))  # empty argument
                    else:
                        args.append(self.compare())
                    if self.peek()[1] in (",", ";"):
                        self.take()
                        continue
                    break
            self.expect(")")
            return ("func", name, args)
        if kind == "name":
            up = text.upper()
            if up in ("TRUE", "FALSE"):
                return ("lit", up == "TRUE")
            return ("name", up)
        if text == "(":
            node = self.compare()
            self.expect(")")
            return node
        if text == "{":
            rows, row = [], []
            while True:
                row.append(self.primary()[1])
                t = self.take()[1]
                if t == ",":
                    continue
                rows.append(row)
                row = []
                if t == ";":
                    continue
                if t == "}":
                    break
                raise ExcelError("#VALUE!")
            return ("array", rows)
        raise ExcelError("#VALUE!")


_PARSE_CACHE = {}


def parse_formula(text):
    node = _PARSE_CACHE.get(text)
    if node is None:
        node = Parser(text[1:]).parse()
        if len(_PARSE_CACHE) > 20000:
            _PARSE_CACHE.clear()
        _PARSE_CACHE[text] = node
    return node


# ====================================================================== evaluator

class Range:
    """A rectangular block of cells, read lazily."""

    def __init__(self, wb, sheet, r1, c1, r2, c2):
        self.wb, self.sheet = wb, sheet
        self.r1, self.c1, self.r2, self.c2 = r1, c1, r2, c2

    @property
    def rows(self):
        return self.r2 - self.r1 + 1

    @property
    def cols(self):
        return self.c2 - self.c1 + 1

    def get(self, i, j):
        return self.wb.value(self.sheet, self.r1 + i, self.c1 + j)

    def values(self):
        """Row-major values, skipping the empty area beyond the sheet's data."""
        r2 = min(self.r2, self.sheet.max_row())
        c2 = min(self.c2, self.sheet.max_col())
        for r in range(self.r1, r2 + 1):
            for c in range(self.c1, c2 + 1):
                yield self.wb.value(self.sheet, r, c)

    def matrix(self):
        return [[self.get(i, j) for j in range(self.cols)] for i in range(self.rows)]


class Array(Range):
    """Literal array constant {1,2;3,4}."""

    def __init__(self, rows):
        self.data = rows
        self.r1 = self.c1 = 0
        self.r2, self.c2 = len(rows) - 1, len(rows[0]) - 1

    def get(self, i, j):
        return self.data[i][j]

    def values(self):
        for row in self.data:
            yield from row


def to_number(v):
    if isinstance(v, ExcelError):
        raise v
    if v is None or v == "":
        return 0
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return float(v.replace(",", "").replace("$", "").strip().rstrip("%")) / (
                100 if v.strip().endswith("%") else 1)
        except ValueError:
            raise ExcelError("#VALUE!")
    return to_serial(v)


def to_text(v):
    if isinstance(v, ExcelError):
        raise v
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        if v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return f"{v:.15g}"
    return str(v)


def to_bool(v):
    if isinstance(v, ExcelError):
        raise v
    if isinstance(v, str):
        if v.upper() in ("TRUE", "FALSE"):
            return v.upper() == "TRUE"
        raise ExcelError("#VALUE!")
    return bool(v)


def _cmp_key(v):
    # Excel ordering: numbers < text < booleans; text compares case-insensitively
    if v is None:
        return (0, 0)
    if isinstance(v, bool):
        return (2, int(v))
    if isinstance(v, (int, float)):
        return (0, v)
    return (1, str(v).lower())


def compare(a, b, op):
    if a is None:
        a = "" if isinstance(b, str) else 0
    if b is None:
        b = "" if isinstance(a, str) else 0
    ka, kb = _cmp_key(a), _cmp_key(b)
    return {"=": ka == kb, "<>": ka != kb, "<": ka < kb, ">": ka > kb,
            "<=": ka <= kb, ">=": ka >= kb}[op]


def criteria_fn(crit):
    """Build a predicate for SUMIF/COUNTIF-style criteria like '>5', 'abc*', '<>x'."""
    if isinstance(crit, ExcelError):
        raise crit
    if not isinstance(crit, str):
        return lambda v: v is not None and not isinstance(v, str) and compare(v, crit, "=")
    m = re.match(r"^(<=|>=|<>|=|<|>)?(.*)$", crit, re.S)
    op, rest = m.group(1) or "=", m.group(2)
    try:
        target = float(rest)
        return lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and compare(v, target, op)
    except ValueError:
        pass
    if op in ("=", "<>") and any(ch in rest for ch in "*?"):
        pat = re.compile("^" + re.escape(rest).replace(r"\*", ".*").replace(r"\?", ".") + "$", re.I | re.S)
        return (lambda v: bool(pat.match(to_text(v)))) if op == "=" else (lambda v: not pat.match(to_text(v)))
    if rest == "" and op == "=":
        return lambda v: v is None or v == ""
    if rest == "" and op == "<>":
        return lambda v: v is not None and v != ""
    up = rest.upper()
    if up in ("TRUE", "FALSE"):
        return lambda v: isinstance(v, bool) and compare(v, up == "TRUE", op)
    return lambda v: isinstance(v, str) and compare(v, rest, op)


class Evaluator:
    def __init__(self, wb, sheet):
        self.wb, self.sheet = wb, sheet

    def run(self, formula):
        v = self.ev(parse_formula(formula))
        return self.scalar(v)

    def scalar(self, v):
        if isinstance(v, Range):
            if v.rows == 1 and v.cols == 1:
                return v.get(0, 0)
            return VALUE
        return v

    def resolve_ref(self, text):
        sheet_name, parts = split_ref(text)
        sheet = self.wb.sheet(sheet_name) if sheet_name else self.sheet
        if sheet is None:
            raise ExcelError("#REF!")
        (_, c1, _, r1) = parts[0]
        (_, c2, _, r2) = parts[-1]
        if r1 is None:   # whole columns
            r1, r2 = 0, max(sheet.max_row(), 0)
        return Range(self.wb, sheet, min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2))

    def ev(self, node):
        kind = node[0]
        if kind == "lit":
            return node[1]
        if kind == "ref":
            return self.resolve_ref(node[1])
        if kind == "array":
            return Array(node[1])
        if kind == "name":
            target = self.wb.names.get(node[1])
            if target is None:
                raise ExcelError("#NAME?")
            return self.ev(parse_formula("=" + target.lstrip("=")))
        if kind == "neg":
            return -to_number(self.scalar(self.ev(node[1])))
        if kind == "pct":
            return to_number(self.scalar(self.ev(node[1]))) / 100
        if kind == "bin":
            op = node[1]
            a = self.scalar(self.ev(node[2]))
            b = self.scalar(self.ev(node[3]))
            if isinstance(a, ExcelError):
                return a
            if isinstance(b, ExcelError):
                return b
            if op == "&":
                return to_text(a) + to_text(b)
            if op in ("=", "<>", "<", ">", "<=", ">="):
                return compare(a, b, op)
            x, y = to_number(a), to_number(b)
            if op == "+":
                return x + y
            if op == "-":
                return x - y
            if op == "*":
                return x * y
            if op == "/":
                if y == 0:
                    return DIV0
                return x / y
            if op == "^":
                try:
                    r = x ** y
                except (OverflowError, ZeroDivisionError):
                    return NUM
                return NUM if isinstance(r, complex) else r
        if kind == "func":
            fn = FUNCTIONS.get(node[1].replace("_XLFN.", "").replace("_XLWS.", ""))
            if fn is None:
                return NAME
            lazy = getattr(fn, "lazy", False)
            args = node[2] if lazy else [self.ev(a) for a in node[2]]
            return fn(self, *args)
        raise ExcelError("#VALUE!")


# ====================================================================== functions

FUNCTIONS = {}


def fn(name, lazy=False):
    def deco(f):
        f.lazy = lazy
        for n in name.split():
            FUNCTIONS[n] = f
        return f
    return deco


def _iter_args(args):
    """Yield (value, from_range) for each argument value, expanding ranges."""
    for a in args:
        if isinstance(a, Range):
            for v in a.values():
                yield v, True
        else:
            yield a, False


def _numbers(args, count_text=False):
    out = []
    for v, from_range in _iter_args(args):
        if isinstance(v, ExcelError):
            raise v
        if from_range:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append(v)
        elif v is not None:
            out.append(to_number(v))
    return out


def _scalar(ev, v):
    v = ev.scalar(v)
    if isinstance(v, ExcelError):
        raise v
    return v


@fn("SUM")
def f_sum(ev, *a): return sum(_numbers(a))


@fn("AVERAGE")
def f_avg(ev, *a):
    n = _numbers(a)
    return sum(n) / len(n) if n else DIV0


@fn("MIN")
def f_min(ev, *a):
    n = _numbers(a)
    return min(n) if n else 0


@fn("MAX")
def f_max(ev, *a):
    n = _numbers(a)
    return max(n) if n else 0


@fn("COUNT")
def f_count(ev, *a):
    return sum(1 for v, _ in _iter_args(a) if isinstance(v, (int, float)) and not isinstance(v, bool))


@fn("COUNTA")
def f_counta(ev, *a): return sum(1 for v, _ in _iter_args(a) if v is not None and v != "")


@fn("COUNTBLANK")
def f_countblank(ev, r):
    return sum(1 for i in range(r.rows) for j in range(r.cols) if r.get(i, j) in (None, ""))


@fn("PRODUCT")
def f_product(ev, *a): return math.prod(_numbers(a))


@fn("MEDIAN")
def f_median(ev, *a):
    n = _numbers(a)
    return statistics.median(n) if n else NUM


@fn("MODE MODE.SNGL")
def f_mode(ev, *a):
    n = _numbers(a)
    counts = {}
    for x in n:
        counts[x] = counts.get(x, 0) + 1
    best = max(counts.values(), default=0)
    if best < 2:
        return NA
    return next(x for x in n if counts[x] == best)


@fn("STDEV STDEV.S")
def f_stdev(ev, *a):
    n = _numbers(a)
    return statistics.stdev(n) if len(n) > 1 else DIV0


@fn("STDEVP STDEV.P")
def f_stdevp(ev, *a):
    n = _numbers(a)
    return statistics.pstdev(n) if n else DIV0


@fn("VAR VAR.S")
def f_var(ev, *a):
    n = _numbers(a)
    return statistics.variance(n) if len(n) > 1 else DIV0


@fn("VARP VAR.P")
def f_varp(ev, *a):
    n = _numbers(a)
    return statistics.pvariance(n) if n else DIV0


@fn("LARGE")
def f_large(ev, r, k):
    n = sorted(_numbers([r]), reverse=True)
    k = int(to_number(_scalar(ev, k)))
    return n[k - 1] if 1 <= k <= len(n) else NUM


@fn("SMALL")
def f_small(ev, r, k):
    n = sorted(_numbers([r]))
    k = int(to_number(_scalar(ev, k)))
    return n[k - 1] if 1 <= k <= len(n) else NUM


@fn("RANK RANK.EQ")
def f_rank(ev, x, r, order=0):
    x = to_number(_scalar(ev, x))
    n = _numbers([r])
    if x not in n:
        return NA
    asc = bool(to_number(_scalar(ev, order)))
    return 1 + sum(1 for v in n if (v < x if asc else v > x))


@fn("SUMPRODUCT")
def f_sumproduct(ev, *arrays):
    rs = [a if isinstance(a, Range) else Array([[a]]) for a in arrays]
    if any(r.rows != rs[0].rows or r.cols != rs[0].cols for r in rs):
        return VALUE
    total = 0
    for i in range(rs[0].rows):
        for j in range(rs[0].cols):
            p = 1
            for r in rs:
                v = r.get(i, j)
                if isinstance(v, ExcelError):
                    return v
                p *= v if isinstance(v, (int, float)) else 0
            total += p
    return total


def _num1(f):
    def wrapper(ev, x, *rest):
        return f(to_number(_scalar(ev, x)), *[to_number(_scalar(ev, r)) for r in rest])
    return wrapper


def _round(x, d, mode):
    d = int(d)
    m = 10 ** d
    if mode == "half":
        v = math.floor(abs(x) * m + 0.5 + 1e-9) / m
    elif mode == "up":
        v = math.ceil(abs(x) * m - 1e-9) / m
    else:
        v = math.floor(abs(x) * m + 1e-9) / m
    return math.copysign(v, x) if v else 0


FUNCTIONS.update({
    "ABS": _num1(abs),
    "ROUND": _num1(lambda x, d=0: _round(x, d, "half")),
    "ROUNDUP": _num1(lambda x, d=0: _round(x, d, "up")),
    "ROUNDDOWN": _num1(lambda x, d=0: _round(x, d, "down")),
    "TRUNC": _num1(lambda x, d=0: _round(x, d, "down")),
    "INT": _num1(lambda x: math.floor(x)),
    "SQRT": _num1(lambda x: math.sqrt(x) if x >= 0 else NUM),
    "POWER": _num1(lambda x, y: x ** y),
    "MOD": _num1(lambda x, y: DIV0 if y == 0 else x - y * math.floor(x / y)),
    "EXP": _num1(math.exp),
    "LN": _num1(lambda x: math.log(x) if x > 0 else NUM),
    "LOG10": _num1(lambda x: math.log10(x) if x > 0 else NUM),
    "LOG": _num1(lambda x, b=10: math.log(x, b) if x > 0 and b > 0 and b != 1 else NUM),
    "SIGN": _num1(lambda x: (x > 0) - (x < 0)),
    "PI": lambda ev: math.pi,
    "RAND": lambda ev: random.random(),
    "RANDBETWEEN": _num1(lambda a, b: random.randint(math.ceil(a), math.floor(b))),
    "CEILING": _num1(lambda x, s=1: 0 if s == 0 else math.ceil(x / s - 1e-12) * s),
    "CEILING.MATH": _num1(lambda x, s=1: 0 if s == 0 else math.ceil(x / s - 1e-12) * s),
    "FLOOR": _num1(lambda x, s=1: DIV0 if s == 0 else math.floor(x / s + 1e-12) * s),
    "FLOOR.MATH": _num1(lambda x, s=1: DIV0 if s == 0 else math.floor(x / s + 1e-12) * s),
    "EVEN": _num1(lambda x: math.copysign(math.ceil(abs(x) / 2) * 2, x)),
    "ODD": _num1(lambda x: math.copysign(math.ceil((abs(x) - 1) / 2) * 2 + 1, x)),
    "FACT": _num1(lambda x: math.factorial(int(x)) if x >= 0 else NUM),
    "DEGREES": _num1(math.degrees),
    "RADIANS": _num1(math.radians),
    "SIN": _num1(math.sin), "COS": _num1(math.cos), "TAN": _num1(math.tan),
    "ASIN": _num1(math.asin), "ACOS": _num1(math.acos), "ATAN": _num1(math.atan),
    "ATAN2": _num1(lambda x, y: math.atan2(y, x)),
})


# ---- logic
@fn("IF", lazy=True)
def f_if(ev, cond, yes=("lit", True), no=("lit", False)):
    c = ev.scalar(ev.ev(cond))
    if isinstance(c, ExcelError):
        return c
    return ev.ev(yes if to_bool(c) else no)


@fn("IFS", lazy=True)
def f_ifs(ev, *pairs):
    for i in range(0, len(pairs) - 1, 2):
        c = ev.scalar(ev.ev(pairs[i]))
        if isinstance(c, ExcelError):
            return c
        if to_bool(c):
            return ev.ev(pairs[i + 1])
    return NA


@fn("IFERROR", lazy=True)
def f_iferror(ev, v, alt):
    try:
        r = ev.scalar(ev.ev(v))
    except ExcelError as e:
        r = e
    return ev.ev(alt) if isinstance(r, ExcelError) else r


@fn("IFNA", lazy=True)
def f_ifna(ev, v, alt):
    try:
        r = ev.scalar(ev.ev(v))
    except ExcelError as e:
        r = e
    return ev.ev(alt) if r == NA else r


@fn("SWITCH", lazy=True)
def f_switch(ev, expr, *rest):
    v = ev.scalar(ev.ev(expr))
    for i in range(0, len(rest) - 1, 2):
        if compare(v, ev.scalar(ev.ev(rest[i])), "="):
            return ev.ev(rest[i + 1])
    return ev.ev(rest[-1]) if len(rest) % 2 else NA


@fn("CHOOSE", lazy=True)
def f_choose(ev, idx, *opts):
    i = int(to_number(ev.scalar(ev.ev(idx))))
    return ev.ev(opts[i - 1]) if 1 <= i <= len(opts) else VALUE


@fn("AND")
def f_and(ev, *a):
    vals = [v for v, _ in _iter_args(a) if v is not None and not isinstance(v, str)]
    return all(to_bool(v) for v in vals) if vals else VALUE


@fn("OR")
def f_or(ev, *a):
    vals = [v for v, _ in _iter_args(a) if v is not None and not isinstance(v, str)]
    return any(to_bool(v) for v in vals) if vals else VALUE


@fn("XOR")
def f_xor(ev, *a):
    return sum(bool(to_bool(v)) for v, _ in _iter_args(a) if v is not None) % 2 == 1


FUNCTIONS.update({
    "NOT": lambda ev, x: not to_bool(_scalar(ev, x)),
    "TRUE": lambda ev: True,
    "FALSE": lambda ev: False,
    "NA": lambda ev: NA,
})


def _is(pred):
    def f(ev, x):
        try:
            v = ev.scalar(x)
        except ExcelError as e:
            v = e
        return pred(v)
    f.lazy = False
    return f


FUNCTIONS.update({
    "ISBLANK": _is(lambda v: v is None),
    "ISNUMBER": _is(lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)),
    "ISTEXT": _is(lambda v: isinstance(v, str)),
    "ISNONTEXT": _is(lambda v: not isinstance(v, str)),
    "ISLOGICAL": _is(lambda v: isinstance(v, bool)),
    "ISERROR": _is(lambda v: isinstance(v, ExcelError)),
    "ISERR": _is(lambda v: isinstance(v, ExcelError) and v != NA),
    "ISNA": _is(lambda v: v == NA),
    "ISEVEN": _is(lambda v: int(to_number(v)) % 2 == 0),
    "ISODD": _is(lambda v: int(to_number(v)) % 2 == 1),
})


# ---- conditional aggregates
def _pairs(ev, args):
    """[(range, predicate), ...] from criteria_range1, criteria1, ..."""
    return [(args[i], criteria_fn(_scalar(ev, args[i + 1]))) for i in range(0, len(args) - 1, 2)]


def _matching(pairs, size_from):
    rows, cols = size_from.rows, size_from.cols
    for i in range(rows):
        for j in range(cols):
            if all(p(r.get(i, j)) for r, p in pairs):
                yield i, j


@fn("SUMIF")
def f_sumif(ev, r, crit, sum_r=None):
    sum_r = sum_r if isinstance(sum_r, Range) else r
    p = criteria_fn(_scalar(ev, crit))
    rows = min(r.rows, r.sheet.max_row() - r.r1 + 1)
    return sum(v for i in range(max(rows, 0)) for j in range(r.cols)
               if p(r.get(i, j)) and isinstance(v := sum_r.get(i, j), (int, float)) and not isinstance(v, bool))


@fn("SUMIFS")
def f_sumifs(ev, sum_r, *args):
    out = 0
    for i, j in _matching(_pairs(ev, args), _clip(sum_r)):
        v = sum_r.get(i, j)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out += v
    return out


def _clip(r):
    """Limit whole-column ranges to the used rows for iteration."""
    if not isinstance(r, Range) or isinstance(r, Array):
        return r
    return Range(r.wb, r.sheet, r.r1, r.c1, max(r.r1, min(r.r2, r.sheet.max_row())), r.c2)


@fn("COUNTIF")
def f_countif(ev, r, crit):
    p = criteria_fn(_scalar(ev, crit))
    c = _clip(r)
    n = sum(1 for i in range(c.rows) for j in range(c.cols) if p(c.get(i, j)))
    if r.rows > c.rows and p(None):  # blank cells beyond the data also match
        n += (r.rows - c.rows) * r.cols
    return n


@fn("COUNTIFS")
def f_countifs(ev, *args):
    return sum(1 for _ in _matching(_pairs(ev, args), _clip(args[0])))


@fn("AVERAGEIF")
def f_averageif(ev, r, crit, avg_r=None):
    avg_r = avg_r if isinstance(avg_r, Range) else r
    p = criteria_fn(_scalar(ev, crit))
    c = _clip(r)
    vals = [v for i in range(c.rows) for j in range(c.cols)
            if p(c.get(i, j)) and isinstance(v := avg_r.get(i, j), (int, float)) and not isinstance(v, bool)]
    return sum(vals) / len(vals) if vals else DIV0


@fn("AVERAGEIFS")
def f_averageifs(ev, avg_r, *args):
    vals = [v for i, j in _matching(_pairs(ev, args), _clip(avg_r))
            if isinstance(v := avg_r.get(i, j), (int, float)) and not isinstance(v, bool)]
    return sum(vals) / len(vals) if vals else DIV0


@fn("MAXIFS")
def f_maxifs(ev, r, *args):
    vals = [v for i, j in _matching(_pairs(ev, args), _clip(r)) if isinstance(v := r.get(i, j), (int, float))]
    return max(vals) if vals else 0


@fn("MINIFS")
def f_minifs(ev, r, *args):
    vals = [v for i, j in _matching(_pairs(ev, args), _clip(r)) if isinstance(v := r.get(i, j), (int, float))]
    return min(vals) if vals else 0


# ---- lookup
def _match_pos(value, cells, mode):
    """mode 0 exact (with wildcards), 1 largest <= value (sorted asc), -1 smallest >= value."""
    if mode == 0:
        p = criteria_fn(value) if isinstance(value, str) else (lambda v: compare(v, value, "="))
        for i, v in enumerate(cells):
            if v is not None and p(v):
                return i
        return None
    best = None
    for i, v in enumerate(cells):
        if v is None:
            continue
        if mode == 1:
            if compare(v, value, "<="):
                best = i
            else:
                break
        else:
            if compare(v, value, ">="):
                best = i
            else:
                break
    return best


@fn("VLOOKUP")
def f_vlookup(ev, value, table, col, approx=True):
    value = _scalar(ev, value)
    col = int(to_number(_scalar(ev, col)))
    if col < 1 or col > table.cols:
        return REF
    t = _clip(table)
    pos = _match_pos(value, [t.get(i, 0) for i in range(t.rows)],
                     1 if to_bool(_scalar(ev, approx) if approx is not None else True) else 0)
    return NA if pos is None else table.get(pos, col - 1)


@fn("HLOOKUP")
def f_hlookup(ev, value, table, row, approx=True):
    value = _scalar(ev, value)
    row = int(to_number(_scalar(ev, row)))
    if row < 1 or row > table.rows:
        return REF
    pos = _match_pos(value, [table.get(0, j) for j in range(table.cols)],
                     1 if to_bool(_scalar(ev, approx) if approx is not None else True) else 0)
    return NA if pos is None else table.get(row - 1, pos)


@fn("MATCH")
def f_match(ev, value, r, mode=1):
    value = _scalar(ev, value)
    mode = int(to_number(_scalar(ev, mode))) if mode is not None else 1
    c = _clip(r)
    cells = [c.get(i, 0) for i in range(c.rows)] if c.cols == 1 else [c.get(0, j) for j in range(c.cols)]
    pos = _match_pos(value, cells, max(-1, min(1, mode)))
    return NA if pos is None else pos + 1


@fn("XLOOKUP")
def f_xlookup(ev, value, look, ret, not_found=None, mode=0):
    value = _scalar(ev, value)
    lc = _clip(look)
    cells = [lc.get(i, 0) for i in range(lc.rows)] if look.cols == 1 else [look.get(0, j) for j in range(look.cols)]
    pos = _match_pos(value, cells, 0)
    if pos is None:
        return not_found if not_found is not None else NA
    return ret.get(pos, 0) if look.cols == 1 else ret.get(0, pos)


@fn("INDEX")
def f_index(ev, r, row, col=None):
    row = int(to_number(_scalar(ev, row)))
    col = int(to_number(_scalar(ev, col))) if col is not None else 1
    if r.rows == 1 and col == 1 and row > 1:
        row, col = 1, row
    if not (1 <= row <= r.rows and 1 <= col <= r.cols):
        return REF
    return r.get(row - 1, col - 1)


@fn("ROWS")
def f_rows(ev, r): return r.rows


@fn("COLUMNS")
def f_columns(ev, r): return r.cols


@fn("ROW", lazy=True)
def f_row(ev, ref=None):
    if ref is None:
        raise ExcelError("#VALUE!")
    return ev.ev(ref).r1 + 1


@fn("COLUMN", lazy=True)
def f_column(ev, ref=None):
    if ref is None:
        raise ExcelError("#VALUE!")
    return ev.ev(ref).c1 + 1


# ---- text
def _t(ev, x):
    return to_text(_scalar(ev, x))


FUNCTIONS.update({
    "LEN": lambda ev, x: len(_t(ev, x)),
    "UPPER": lambda ev, x: _t(ev, x).upper(),
    "LOWER": lambda ev, x: _t(ev, x).lower(),
    "PROPER": lambda ev, x: _t(ev, x).title(),
    "TRIM": lambda ev, x: " ".join(_t(ev, x).split()),
    "LEFT": lambda ev, x, n=1: _t(ev, x)[:int(to_number(_scalar(ev, n)))],
    "RIGHT": lambda ev, x, n=1: (lambda s, k: s[-k:] if k else "")(_t(ev, x), int(to_number(_scalar(ev, n)))),
    "MID": lambda ev, x, s, n: _t(ev, x)[int(to_number(_scalar(ev, s))) - 1:
                                         int(to_number(_scalar(ev, s))) - 1 + int(to_number(_scalar(ev, n)))],
    "REPT": lambda ev, x, n: _t(ev, x) * int(to_number(_scalar(ev, n))),
    "EXACT": lambda ev, a, b: _t(ev, a) == _t(ev, b),
    "CHAR": lambda ev, n: chr(int(to_number(_scalar(ev, n)))),
    "CODE": lambda ev, x: ord(_t(ev, x)[0]) if _t(ev, x) else VALUE,
    "CLEAN": lambda ev, x: "".join(ch for ch in _t(ev, x) if ord(ch) >= 32),
    "T": lambda ev, x: v if isinstance(v := _scalar(ev, x), str) else "",
    "N": lambda ev, x: v if isinstance(v := _scalar(ev, x), (int, float)) else 0,
})


@fn("CONCATENATE CONCAT")
def f_concat(ev, *a):
    return "".join(to_text(v) for v, _ in _iter_args(a))


@fn("TEXTJOIN")
def f_textjoin(ev, delim, ignore_empty, *a):
    d = _t(ev, delim)
    skip = to_bool(_scalar(ev, ignore_empty))
    return d.join(to_text(v) for v, _ in _iter_args(a) if not (skip and (v is None or v == "")))


@fn("FIND")
def f_find(ev, needle, hay, start=1):
    i = _t(ev, hay).find(_t(ev, needle), int(to_number(_scalar(ev, start))) - 1)
    return VALUE if i < 0 else i + 1


@fn("SEARCH")
def f_search(ev, needle, hay, start=1):
    pat = re.escape(_t(ev, needle)).replace(r"\*", ".*").replace(r"\?", ".")
    m = re.compile(pat, re.I).search(_t(ev, hay), int(to_number(_scalar(ev, start))) - 1)
    return VALUE if not m else m.start() + 1


@fn("SUBSTITUTE")
def f_substitute(ev, text, old, new, inst=None):
    s, o, n = _t(ev, text), _t(ev, old), _t(ev, new)
    if inst is None:
        return s.replace(o, n)
    k = int(to_number(_scalar(ev, inst)))
    idx = -1
    for _ in range(k):
        idx = s.find(o, idx + 1)
        if idx < 0:
            return s
    return s[:idx] + n + s[idx + len(o):]


@fn("REPLACE")
def f_replace(ev, text, start, n, new):
    s = _t(ev, text)
    st = int(to_number(_scalar(ev, start))) - 1
    return s[:st] + _t(ev, new) + s[st + int(to_number(_scalar(ev, n))):]


@fn("VALUE")
def f_value(ev, x):
    v = _scalar(ev, x)
    if isinstance(v, str):
        p = parse_input(v)
        if isinstance(p[0], (int, float)) and not isinstance(p[0], bool):
            return p[0]
        raise ExcelError("#VALUE!")
    return to_number(v)


@fn("TEXT")
def f_text(ev, x, fmt):
    return format_value(_scalar(ev, x), _t(ev, fmt))


@fn("FIXED")
def f_fixed(ev, x, d=2, no_commas=False):
    d = int(to_number(_scalar(ev, d)))
    return format_value(to_number(_scalar(ev, x)),
                        ("0" if to_bool(_scalar(ev, no_commas)) else "#,##0") + ("." + "0" * d if d > 0 else ""))


@fn("DOLLAR")
def f_dollar(ev, x, d=2):
    d = int(to_number(_scalar(ev, d)))
    return format_value(to_number(_scalar(ev, x)), "$#,##0" + ("." + "0" * d if d > 0 else ""))


# ---- dates
def _date(ev, x):
    return from_serial(to_number(_scalar(ev, x)))


FUNCTIONS.update({
    "TODAY": lambda ev: float(to_serial(datetime.date.today())),
    "NOW": lambda ev: to_serial(datetime.datetime.now()),
    "DATE": lambda ev, y, m, d: _make_date(*(int(to_number(_scalar(ev, v))) for v in (y, m, d))),
    "TIME": lambda ev, h, m, s: (to_number(_scalar(ev, h)) * 3600 + to_number(_scalar(ev, m)) * 60
                                 + to_number(_scalar(ev, s))) / 86400 % 1,
    "YEAR": lambda ev, x: _date(ev, x).year,
    "MONTH": lambda ev, x: _date(ev, x).month,
    "DAY": lambda ev, x: _date(ev, x).day,
    "HOUR": lambda ev, x: _date(ev, x).hour,
    "MINUTE": lambda ev, x: _date(ev, x).minute,
    "SECOND": lambda ev, x: _date(ev, x).second,
    "WEEKDAY": lambda ev, x, t=1: _weekday(_date(ev, x), int(to_number(_scalar(ev, t)))),
    "DAYS": lambda ev, a, b: math.floor(to_number(_scalar(ev, a))) - math.floor(to_number(_scalar(ev, b))),
    "EDATE": lambda ev, x, m: _add_months(_date(ev, x), int(to_number(_scalar(ev, m))), False),
    "EOMONTH": lambda ev, x, m: _add_months(_date(ev, x), int(to_number(_scalar(ev, m))), True),
    "DATEVALUE": lambda ev, x: v if isinstance(v := parse_input(_t(ev, x))[0], float) else VALUE,
})


def _make_date(y, m, d):
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return float(to_serial(datetime.date(y, m, 1)) + d - 1)


def _weekday(dt, t):
    wd = dt.isoweekday() % 7  # Sunday=0
    return wd + 1 if t == 1 else (dt.isoweekday() if t == 2 else dt.weekday())


def _add_months(dt, n, end):
    y, m = dt.year + (dt.month - 1 + n) // 12, (dt.month - 1 + n) % 12 + 1
    if end:
        return _make_date(y, m + 1, 1) - 1
    import calendar
    return float(to_serial(datetime.date(y, m, min(dt.day, calendar.monthrange(y, m)[1]))))


@fn("DATEDIF")
def f_datedif(ev, a, b, unit):
    d1, d2, u = _date(ev, a), _date(ev, b), _t(ev, unit).upper()
    if d2 < d1:
        return NUM
    if u == "D":
        return (d2 - d1).days
    months = (d2.year - d1.year) * 12 + d2.month - d1.month - (d2.day < d1.day)
    if u == "M":
        return months
    if u == "Y":
        return months // 12
    return VALUE


# ---- finance basics
@fn("PMT")
def f_pmt(ev, rate, n, pv, fv=0, typ=0):
    r, n, pv, fv, typ = (to_number(_scalar(ev, v)) for v in (rate, n, pv, fv, typ))
    if r == 0:
        return -(pv + fv) / n
    return -(r * (fv + pv * (1 + r) ** n)) / ((1 + r * typ) * ((1 + r) ** n - 1))


@fn("FV")
def f_fv(ev, rate, n, pmt, pv=0, typ=0):
    r, n, pmt, pv, typ = (to_number(_scalar(ev, v)) for v in (rate, n, pmt, pv, typ))
    if r == 0:
        return -(pv + pmt * n)
    return -(pv * (1 + r) ** n + pmt * (1 + r * typ) * ((1 + r) ** n - 1) / r)


@fn("PV")
def f_pv(ev, rate, n, pmt, fv=0, typ=0):
    r, n, pmt, fv, typ = (to_number(_scalar(ev, v)) for v in (rate, n, pmt, fv, typ))
    if r == 0:
        return -(fv + pmt * n)
    return -(fv + pmt * (1 + r * typ) * ((1 + r) ** n - 1) / r) / (1 + r) ** n


@fn("NPV")
def f_npv(ev, rate, *vals):
    r = to_number(_scalar(ev, rate))
    return sum(v / (1 + r) ** (i + 1) for i, v in enumerate(_numbers(vals)))


# ====================================================================== input parsing

_DATE_FORMATS = [("%Y-%m-%d", "yyyy-mm-dd"), ("%m/%d/%Y", "m/d/yyyy"), ("%m/%d/%y", "m/d/yy"),
                 ("%d-%b-%Y", "d-mmm-yyyy"), ("%d %b %Y", "d mmm yyyy"), ("%b %d, %Y", "mmm d, yyyy"),
                 ("%B %d, %Y", "mmmm d, yyyy"), ("%Y-%m-%d %H:%M", "yyyy-mm-dd h:mm"),
                 ("%H:%M", "h:mm"), ("%H:%M:%S", "h:mm:ss"), ("%I:%M %p", "h:mm AM/PM")]


def parse_input(text):
    """What the user typed -> (value, suggested number format or None)."""
    if text is None:
        return None, None
    if not isinstance(text, str):
        return text, None
    s = text.strip()
    if s == "":
        return None, None
    if text.startswith("'"):
        return text[1:], "@"
    if s.startswith("=") and len(s) > 1:
        return s, None
    up = s.upper()
    if up in ("TRUE", "FALSE"):
        return up == "TRUE", None
    if up in ERRORS:
        return ERRORS[up], None
    m = re.fullmatch(r"([-+]?)(\$|€|£)?\s*([\d,]*\.?\d+(?:[eE][-+]?\d+)?)\s*(%?)", s)
    if m and ("," not in m.group(3) or re.fullmatch(r"\d{1,3}(,\d{3})*(\.\d+)?", m.group(3))):
        num = float(m.group(3).replace(",", ""))
        if m.group(1) == "-":
            num = -num
        fmt = None
        if m.group(4):
            num /= 100
            fmt = "0%" if num * 100 == int(num * 100) else "0.00%"
        elif m.group(2):
            fmt = f"{m.group(2)}#,##0.00"
        elif "," in m.group(3):
            fmt = "#,##0" if num == int(num) else "#,##0.00"
        if num == int(num) and abs(num) < 1e15 and "." not in m.group(3) and "e" not in m.group(3).lower():
            num = int(num)
        return num, fmt
    for pyfmt, xlfmt in _DATE_FORMATS:
        try:
            dt = datetime.datetime.strptime(s, pyfmt)
        except ValueError:
            continue
        if pyfmt.startswith("%H") or pyfmt.startswith("%I"):
            return (dt.hour * 3600 + dt.minute * 60 + dt.second) / 86400, xlfmt
        return float(to_serial(dt)), xlfmt
    return text, None


# ====================================================================== number formats

def _split_sections(fmt):
    out, cur, q = [], "", False
    for ch in fmt:
        if ch == '"':
            q = not q
        if ch == ";" and not q:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


_DATE_TOKEN = re.compile(r'(yyyy|yy|mmmmm|mmmm|mmm|mm|m|dddd|ddd|dd|d|hh|h|ss|s|AM/PM|am/pm|A/P|"[^"]*"|\\.|.)', re.I)


def _format_date(v, fmt):
    try:
        dt = from_serial(v)
    except (OverflowError, ValueError):
        return "#" * 6
    toks = _DATE_TOKEN.findall(fmt)
    ampm = any(t.upper() in ("AM/PM", "A/P") for t in toks)
    out = []
    for i, t in enumerate(toks):
        lt = t.lower()
        if lt in ("mm", "m"):
            prev = next((x.lower() for x in reversed(toks[:i]) if x.strip() and x.lower()[0] in "hdys"), "")
            nxt = next((x.lower() for x in toks[i + 1:] if x.strip() and x.lower()[0] in "hdys"), "")
            minutes = prev.startswith("h") or nxt.startswith("s")
            val = dt.minute if minutes else dt.month
            out.append(f"{val:02d}" if lt == "mm" else str(val))
        elif lt == "yyyy":
            out.append(f"{dt.year:04d}")
        elif lt == "yy":
            out.append(f"{dt.year % 100:02d}")
        elif lt == "mmmmm":
            out.append(dt.strftime("%B")[0])
        elif lt == "mmmm":
            out.append(dt.strftime("%B"))
        elif lt == "mmm":
            out.append(dt.strftime("%b"))
        elif lt == "dddd":
            out.append(dt.strftime("%A"))
        elif lt == "ddd":
            out.append(dt.strftime("%a"))
        elif lt == "dd":
            out.append(f"{dt.day:02d}")
        elif lt == "d":
            out.append(str(dt.day))
        elif lt in ("hh", "h"):
            h = dt.hour % 12 or 12 if ampm else dt.hour
            out.append(f"{h:02d}" if lt == "hh" else str(h))
        elif lt in ("ss", "s"):
            out.append(f"{dt.second:02d}" if lt == "ss" else str(dt.second))
        elif lt in ("am/pm", "a/p"):
            s = "AM" if dt.hour < 12 else "PM"
            out.append(s if lt == "am/pm" else s[0])
        elif t.startswith('"'):
            out.append(t[1:-1])
        elif t.startswith("\\"):
            out.append(t[1:])
        else:
            out.append(t)
    return "".join(out)


def general(v):
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if v == int(v) and abs(v) < 1e11:
        return str(int(v))
    if abs(v) >= 1e11 or (abs(v) < 1e-9 and v != 0):
        return f"{v:.5E}".replace("E+0", "E+").replace("E-0", "E-")
    s = f"{v:.10g}"
    return s


def format_value(v, fmt="General"):
    """Display text for a value using an Excel number format code."""
    if v is None:
        return ""
    if isinstance(v, ExcelError):
        return v.code
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, str):
        sections = _split_sections(fmt or "General")
        if len(sections) >= 4 and "@" in sections[3]:
            return sections[3].replace('"', "").replace("@", v)
        return v
    if isinstance(v, (datetime.date, datetime.datetime, datetime.time)):
        v = to_serial(v)
    if not fmt or fmt.lower() == "general" or fmt == "@":
        return general(v)
    sections = _split_sections(fmt)
    sec = sections[0]
    neg_own = False
    if v < 0 and len(sections) > 1 and sections[1]:
        sec, neg_own = sections[1], True
    elif v == 0 and len(sections) > 2 and sections[2]:
        sec = sections[2]
    sec = re.sub(r"\[(Red|Black|Blue|Green|White|Yellow|Cyan|Magenta|Color\d+)\]", "", sec, flags=re.I)
    sec = re.sub(r"\[\$([^\]-]*)(-[^\]]*)?\]", r'"\1"', sec)
    sec = re.sub(r"\[[<>=][^\]]*\]", "", sec)
    if sec.lower() == "general":
        return ("-" if v < 0 and not neg_own else "") + general(abs(v))
    stripped = re.sub(r'"[^"]*"|\\.', "", sec)
    if re.search(r"[ydhs]|m(?![^\[]*\])", stripped, re.I) and not re.search(r"[0#?]", stripped):
        return _format_date(v, sec)
    x = abs(v) if (neg_own or v >= 0) else -v
    sign = "-" if v < 0 and not neg_own else ""
    pct = stripped.count("%")
    x *= 100 ** pct
    # scientific
    m = re.search(r"([0#?.,]+)[eE]([+-])(0+)", sec)
    if m:
        mant = m.group(1)
        dec = len(mant.split(".")[1]) if "." in mant else 0
        s = f"{x:.{dec}E}"
        base, exp = s.split("E")
        e = int(exp)
        return sign + base + "E" + ("+" if e >= 0 or m.group(2) == "-" else "") + \
            (f"{e:0{len(m.group(3))}d}" if e >= 0 else "-" + f"{-e:0{len(m.group(3))}d}")
    # find the numeric placeholder run
    m = re.search(r"[0#?][0#?,]*(\.[0#?]*)?|\.[0#?]+", stripped)
    if not m:
        return sign + _literal(sec)
    num_part = m.group()
    dec_part = num_part.split(".")[1] if "." in num_part else ""
    int_part = num_part.split(".")[0]
    thousands = "," in int_part
    trailing_commas = len(int_part) - len(int_part.rstrip(","))
    x /= 1000 ** trailing_commas
    decimals = len(dec_part)
    txt = f"{x:,.{decimals}f}" if thousands else f"{x:.{decimals}f}"
    min_int = int_part.replace(",", "").count("0")
    ip, _, dp = txt.partition(".")
    if min_int == 0 and ip in ("0", "-0"):
        ip = ""
    elif not thousands and len(ip) < min_int:
        ip = ip.zfill(min_int)  # e.g. format 000 shows 12 as 012
    if dec_part:
        keep = len(dec_part.rstrip("#?"))
        dp = dp.rstrip("0") if keep < len(dp) else dp
        dp = dp.ljust(keep, "0")
    number = ip + ("." + dp if dp or (dec_part and dec_part.replace("#", "") != dec_part) else "")
    if dec_part == "" and "." in num_part:
        number = ip + "."
    # rebuild with literal text around the placeholder run (in the original section)
    idx = _locate(sec, num_part)
    pre, post = sec[:idx], sec[idx + len(num_part):]
    return _literal(pre) + sign + number + _literal(post) if not pre.strip("_ (") else \
        sign + _literal(pre) + number + _literal(post)


def _locate(sec, part):
    pos, q = 0, False
    while pos < len(sec):
        if sec[pos] == '"':
            q = not q
        elif not q and sec.startswith(part, pos):
            return pos
        pos += 1
    return 0


def _literal(s):
    out, i, q = [], 0, False
    while i < len(s):
        ch = s[i]
        if ch == '"':
            q = not q
        elif q:
            out.append(ch)
        elif ch == "\\" and i + 1 < len(s):
            out.append(s[i + 1])
            i += 1
        elif ch == "_" and i + 1 < len(s):
            out.append(" ")
            i += 1
        elif ch == "*" and i + 1 < len(s):
            i += 1
        elif ch not in "#0?,":
            out.append(ch)
        i += 1
    return "".join(out)


def is_date_format(fmt):
    if not fmt or fmt.lower() == "general":
        return False
    sec = re.sub(r'"[^"]*"|\\.|\[[^\]]*\]', "", _split_sections(fmt)[0])
    return bool(re.search(r"[ydhs]|m", sec, re.I)) and not re.search(r"[0#?]", sec)
