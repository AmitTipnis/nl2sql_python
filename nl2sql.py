from __future__ import annotations
import re
import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional


# -----------------------------
# Schema configuration (example)
# -----------------------------

@dataclass
class TableMeta:
    name: str
    columns: List[str]
    synonyms: List[str] = field(default_factory=list)


@dataclass
class ForeignKey:
    # simple FK mapping: table_a.col -> table_b.col
    left_table: str
    left_col: str
    right_table: str
    right_col: str


@dataclass
class SchemaMeta:
    tables: Dict[str, TableMeta]
    fks: List[ForeignKey]
    column_synonyms: Dict[str, List[str]] = field(default_factory=dict)  # col -> synonyms


def _make_default_schema() -> SchemaMeta:
    tables = {
        "customers": TableMeta(
            name="customers",
            columns=["id", "name", "city", "signup_date"],
            synonyms=["client", "buyer", "user", "customer"]
        ),
        "orders": TableMeta(

            name="orders",
            columns=["id", "customer_id", "amount", "status", "order_date"],
            synonyms=["purchase", "sale", "order"]
        ),
        "products": TableMeta(
            name="products",
            columns=["id", "name", "category", "price"],
            synonyms=["item", "sku", "product"]
        )
    }


    fks = [
        ForeignKey("orders", "customer_id", "customers", "id"),
    ]
    column_synonyms = {
        "amount": ["revenue", "sales", "value", "price", "bill"],
        "order_date": ["date", "ordered on", "purchase date"],
        "signup_date": ["joined on", "registered on", "sign up date"],
        "name": ["customer name", "client name", "username", "product name"],
        "city": ["location", "town"],
        "status": ["state"],
        "category": ["type", "segment"],
        "price": ["cost", "amount"],
      }
    return SchemaMeta(tables=tables, fks=fks, column_synonyms=column_synonyms)

DEFAULT_SCHEMA = _make_default_schema()

# -----------------------------
# Utility helpers
# -----------------------------

_WORD_SPLIT_RE = re.compile(r"[^\w%]+", re.UNICODE)


def normalize(text: str) -> str:


    return re.sub(r"\s+", " ", text.strip().lower())


def tokenize(text: str) -> List[str]:


    return [t for t in _WORD_SPLIT_RE.split(text.lower()) if t]


def find_numbers(text: str) -> List[float]:


    return [float(x) for x in re.findall(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])", text)]


def find_int(text: str, default: Optional[int] = None) -> Optional[int]:
     m = re.search(r"(?<![\w.])(\d+)(?![\w.])", text)
     return int(m.group(1)) if m else default


def pluralize(word: str) -> str:
    if word.endswith("y"):
       return word[:-1] + "ies"
    if word.endswith("s"):
       return word
    return word + "s"

# -----------------------------
# Core parser
# -----------------------------

AGG_KEYWORDS = {
    "count": "COUNT",
    "how many": "COUNT",
    "number of": "COUNT",
    "avg": "AVG",
    "average": "AVG",
    "sum": "SUM",
    "total": "SUM",
    "minimum": "MIN",
    "min": "MIN",
    "maximum": "MAX",
    "max": "MAX",
}

COMPARATORS = {
    "greater than": ">",
    "more than": ">",
    "over": ">",
    "less than": "<",
    "under": "<",
    "below": "<",
    "at least": ">=",
    "minimum of": ">=",
    "no less than": ">=",
    "at most": "<=",
    "maximum of": "<=",
    "no more than": "<=",
    "equal to": "=",
    "equals": "=",
    "not equal to": "!=",
}

TIME_UNITS = ["day", "week", "month", "year"]

ORDER_KEYWORDS = {
    "latest": ("desc", "date"),
    "newest": ("desc", "date"),
    "earliest": ("asc", "date"),
    "oldest": ("asc", "date"),
    "highest": ("desc", None),
    "largest": ("desc", None),
    "lowest": ("asc", None),
    "smallest": ("asc", None),
    "top": ("desc", None),
    "bottom": ("asc", None),
}


@dataclass
class ParseResult:


    tables: List[str] = field(default_factory=list)
columns: List[str] = field(default_factory=list)  # select columns
agg: Optional[Tuple[str, Optional[str]]] = None  # ("COUNT"|"SUM"|..., column or None for *)
where: List[str] = field(default_factory=list)
order_by: Optional[Tuple[str, str]] = None  # (column, asc|desc)
limit: Optional[int] = None
group_by: List[str] = field(default_factory=list)
joins: List[Tuple[str, str, str, str]] = field(default_factory=list)  # (ltab, lcol, rtab, rcol)


class NL2SQL:
     def __init__(self, schema: SchemaMeta):
         self.schema = schema
         self._table_aliases = {}  # simple auto aliases if needed


     # --------- Public API ---------
     def to_sql(self, text: str) -> str:
         text_norm = normalize(text)
         pr = self._parse(text_norm)
         return self._build_sql(pr)


     # --------- Parsing ---------
     def _parse(self, text: str) -> ParseResult:
       pr = ParseResult()
       toks = tokenize(text)

       # 1) Detect tables
       pr.tables = self._detect_tables(text)
       if not pr.tables:
         # guess a table by keywords
         # simple heuristic: if 'order' present → orders, if 'product' → products, else customers
         if re.search(r"\border", text):
             pr.tables = ["orders"]
         elif re.search(r"\bproduct|sku|item", text):
          pr.tables = ["products"]
         else:
          pr.tables = ["customers"]

       # 2) Detect aggregation intent
       agg = self._detect_agg(text)
       if agg:
           pr.agg = agg

       # 3) Columns (if mentioned)
       cols = self._detect_columns(text, pr.tables)
       pr.columns = cols

       # 4) Joins if multiple tables are present or referenced via column names
       pr.joins = self._detect_joins(pr.tables)

       # 5) Filters (where)
       pr.where.extend(self._detect_equality_filters(text, pr.tables))
       pr.where.extend(self._detect_comparison_filters(text, pr.tables))
       pr.where.extend(self._detect_like_filters(text, pr.tables))
       pr.where.extend(self._detect_date_filters(text, pr.tables))

       # 6) Order by + limit
       order_by, limit = self._detect_order_limit(text, pr.tables, pr.columns, pr.agg)
       pr.order_by = order_by
       pr.limit = limit

       # 7) Group by (if aggregate on a column and also selecting other columns)
       if pr.agg and pr.agg[0] not in ("COUNT",) and pr.columns:
          # simple: group by selected non-aggregated columns
          pr.group_by = pr.columns.copy()

       return pr


# --- detectors ---
def _detect_tables(self, text: str) -> List[str]:


    tables = []
for tname, meta in self.schema.tables.items():
    patterns = [tname] + [pluralize(tname)] + meta.synonyms
for p in patterns:
    if re.search(rf"\b{re.escape(p)}\b", text):
    tables.append(tname)
break
# de-dup
return list(dict.fromkeys(tables))


def _detect_agg(self, text: str) -> Optional[Tuple[str, Optional[str]]]:


# find keyword
for phrase, agg in AGG_KEYWORDS.items():
    if phrase in text:
# if a column follows the agg
col = self._find_any_column(text)
# for COUNT default to *
return (agg, None if agg == "COUNT" else col)
# handle "how many X" → COUNT(*)
if re.search(r"\bhow many\b|\bnumber of\b", text):
    return ("COUNT", None)
return None


def _detect_columns(self, text: str, tables: List[str]) -> List[str]:


    cols_found = set()
# direct mention of columns or synonyms
for t in tables:
    cols = self.schema.tables[t].columns
for c in cols:
    if re.search(rf"\b{re.escape(c)}\b", text):
    cols_found.add(f"{t}.{c}" if len(tables) > 1 else c)
else:
for syn in self.schema.column_synonyms.get(c, []):
    if re.search(rf"\b{re.escape(syn)}\b", text):
    cols_found.add(f"{t}.{c}" if len(tables) > 1 else c)
# fallback: if "list/show/get" with no specific agg, default to *
return sorted(cols_found)


def _find_any_column(self, text: str) -> Optional[str]:


    for t, meta in self.schema.tables.items():
    for c in meta.columns:
    if re.search(rf"\b{re.escape(c)}\b", text):
    return c
for syn in self.schema.column_synonyms.get(c, []):
    if re.search(rf"\b{re.escape(syn)}\b", text):
    return c
return None


def _detect_joins(self, tables: List[str]) -> List[Tuple[str, str, str, str]]:


    joins = []
if len(tables) <= 1:
    return joins
# try to chain tables via known FKs
used = set([tables[0]])
for t in tables[1:]:
    link = None
for fk in self.schema.fks:
    if (fk.left_table in used and fk.right_table == t) or (fk.right_table in used and fk.left_table == t):
    link = fk
break
if link:
    if link.left_table in used:
    joins.append((link.left_table, link.left_col, link.right_table, link.right_col))
used.add(link.right_table)
else:
joins.append((link.right_table, link.right_col, link.left_table, link.left_col))
used.add(link.left_table)
return joins


def _detect_equality_filters(self, text: str, tables: List[str]) -> List[str]:


    filters = []
# pattern: "status open", "city mumbai", "name like 'john'"
for t in tables:
    for c in self.schema.tables[t].columns:
# equals via "c = value" or "c is value" or "c value"
# capture quoted strings first
pattern = rf"(?:\b{re.escape(c)}\b|\b{'|'.join(map(re.escape, self.schema.column_synonyms.get(c, [])))}\b)\s*(?:=|is|equal to|equals)?\s*'([^']+)'"
for m in re.finditer(pattern, text):
    val = m.group(1)
col = f"{t}.{c}" if len(tables) > 1 else c
filters.append(f"{col} = '{val}'")
# unquoted single token
pattern2 = rf"(?:\b{re.escape(c)}\b|\b{'|'.join(map(re.escape, self.schema.column_synonyms.get(c, [])))}\b)\s*(?:=|is|equal to|equals)?\s*\b([a-z0-9_%-]+)\b"
for m in re.finditer(pattern2, text):
    val = m.group(1)
if val in {'greater', 'less', 'over', 'under', 'before', 'after', 'between', 'on', 'latest', 'highest', 'lowest', 'top',
           'bottom'}:
    continue
col = f"{t}.{c}" if len(tables) > 1 else c
# don't duplicate date/number comparisons handled elsewhere
if not re.match(r"^\d{4}-\d{2}-\d{2}$", val):
    filters.append(f"{col} = '{val}'")
return list(dict.fromkeys(filters))


def _detect_comparison_filters(self, text: str, tables: List[str]) -> List[str]:


    filters = []
# comparators like "amount > 100", "price at least 50"
for phrase, op in COMPARATORS.items():
    if phrase in text:
# find nearest number and column
num = self._nearest_number(text, phrase)
col = self._nearest_column(text, phrase, tables)
if num is not None and col is not None:
    filters.append(f"{col} {op} {num}")
# direct "amount > 100"
m = re.finditer(r"\b([a-z_][a-z0-9_]*)\s*(>=|<=|>|<|=)\s*(\d+(?:\.\d+)?)", text)
for g in m:
    col, op, num = g.groups()
col_full = self._qualify_column(col, tables)
if col_full:
    filters.append(f"{col_full} {op} {num}")
return list(dict.fromkeys(filters))


def _detect_like_filters(self, text: str, tables: List[str]) -> List[str]:


    filters = []
# "containing/contains/like 'john' in name"
like_match = re.search(r"(containing|contains|like)\s+'([^']+)'(?:\s+in\s+([a-z_][a-z0-9_]*))?", text)
if like_match:
    val = like_match.group(2)
col = like_match.group(3)
if col:
    qcol = self._qualify_column(col, tables) or col
filters.append(f"{qcol} LIKE '%{val}%'")
else:
# try name-like columns
for t in tables:
    for c in self.schema.tables[t].columns:
    if c in ("name", "city", "category", "status"):
    qcol = f"{t}.{c}" if len(tables) > 1 else c
filters.append(f"{qcol} LIKE '%{val}%'")
return list(dict.fromkeys(filters))


def _detect_date_filters(self, text: str, tables: List[str]) -> List[str]:


    filters = []
# before/after/on column date
date_cols = []
for t in tables:
    for c in self.schema.tables[t].columns:
    if "date" in c:
    date_cols.append(f"{t}.{c}" if len(tables) > 1 else c)
# "before 2024-01-01" / "after 2023-12-01" / "on 2024-02-20"
for kw, op in [("before", "<"), ("after", ">"), ("on", "=")]:
    for m in re.finditer(rf"\b{kw}\s+(\d{{4}}-\d{{2}}-\d{{2}})\b", text):
    date = m.group(1)
if date_cols:
    filters.append(f"{date_cols[0]} {op} DATE '{date}'")

# "between 2024-01-01 and 2024-02-01"
m = re.search(r"between\s+(\d{4}-\d{2}-\d{2})\s+and\s+(\d{4}-\d{2}-\d{2})", text)
if m and date_cols:
    a, b = m.group(1), m.group(2)
col = date_cols[0]
filters.append(f"{col} BETWEEN DATE '{a}' AND DATE '{b}'")

# "last N days/weeks/months/years"
m = re.search(r"\blast\s+(\d+)\s+(day|week|month|year)s?\b", text)
if m and date_cols:
    n = int(m.group(1));
unit = m.group(2)
col = date_cols[0]
# portable-ish SQL using CURRENT_DATE - INTERVAL:
# many dialects accept INTERVAL 'N unit' but names vary; this is a best-effort
unit_sql = unit.upper()
if unit_sql.endswith("H"):
    unit_sql += "S"
filters.append(f"{col} >= CURRENT_DATE - INTERVAL '{n} {unit_sql}'")

# relative keywords "today", "yesterday", "this week/month/year", "last month"
rel_map = {
    "today": ("=", "CURRENT_DATE"),
    "yesterday": ("=", "CURRENT_DATE - INTERVAL '1 DAY'"),
    "this week": (">=", "DATE_TRUNC('week', CURRENT_DATE)"),
    "this month": (">=", "DATE_TRUNC('month', CURRENT_DATE)"),
    "this year": (">=", "DATE_TRUNC('year', CURRENT_DATE)"),
    "last week": (">=", "DATE_TRUNC('week', CURRENT_DATE - INTERVAL '1 WEEK')"),
    "last month": (">=", "DATE_TRUNC('month', CURRENT_DATE - INTERVAL '1 MONTH')"),
    "last year": (">=", "DATE_TRUNC('year', CURRENT_DATE - INTERVAL '1 YEAR')"),
}
for phrase, (op, expr) in rel_map.items():
    if phrase in text and date_cols:
    col = date_cols[0]
filters.append(f"{col} {op} {expr}")
return list(dict.fromkeys(filters))


def _detect_order_limit(self, text: str, tables: List[str], cols: List[str], agg: Optional[Tuple[str, Optional[str]]]):


# ORDER BY determination
order_by = None
limit = None

# top/bottom N
m = re.search(r"\b(top|bottom|first|last)\s+(\d+)\b", text)
if m:
    keyword, n = m.group(1), int(m.group(2))
limit = n
direction = "desc" if keyword in ("top", "last") else "asc" if keyword in ("bottom", "first") else "desc"
# choose a sensible column
candidate = self._find_numeric_or_date_column(tables, cols, agg)
if candidate:
    order_by = (candidate, direction)

# highest/lowest/latest/earliest
for key, (direction, domain) in ORDER_KEYWORDS.items():
    if key in text:
    if domain == "date":
    candidate = self._find_date_column(tables)
else:
candidate = self._find_numeric_or_date_column(tables, cols, agg)
if candidate:
    order_by = (candidate, direction)
if limit is None and ("top" not in text and "bottom" not in text):
# default to top 10 in these cases
limit = 10
break

# explicit "order by <col> asc|desc"
m = re.search(r"order by\s+([a-z_][a-z0-9_\.]*)\s*(asc|desc)?", text)
if m:
    col = m.group(1)
direction = (m.group(2) or "asc").lower()
qcol = self._qualify_column(col, tables) or col
order_by = (qcol, direction)

return order_by, limit


# --- helpers ---
def _nearest_number(self, text: str, phrase: str) -> Optional[float]:


# find a number within ~20 chars to the right
idx = text.find(phrase)
if idx == -1: return None
window = text[idx: idx + 60]
m = re.search(r"(\d+(?:\.\d+)?)", window)
return float(m.group(1)) if m else None


def _nearest_column(self, text: str, phrase: str, tables: List[str]) -> Optional[str]:


    idx = text.find(phrase)
if idx == -1: return None
window = text[max(0, idx - 60): idx + 60]
# search any known column in the window
for t in tables:
    for c in self.schema.tables[t].columns:
    if re.search(rf"\b{re.escape(c)}\b", window):
    return f"{t}.{c}" if len(tables) > 1 else c
# fallback to numeric/date-ish column
return self._find_numeric_or_date_column(tables, [], None)


def _qualify_column(self, col: str, tables: List[str]) -> Optional[str]:


# if col exists in one of the tables
hits = []
for t in tables:
    if col in self.schema.tables[t].columns:
    hits.append(f"{t}.{col}" if len(tables) > 1 else col)
return hits[0] if hits else None


def _find_date_column(self, tables: List[str]) -> Optional[str]:


    for t in tables:
    for c in self.schema.tables[t].columns:
    if "date" in c:
    return f"{t}.{c}" if len(tables) > 1 else c
return None


def _find_numeric_or_date_column(self, tables: List[str], cols: List[str], agg: Optional[Tuple[str, Optional[str]]]):


# prefer amount/price, else date, else first column after id
pref = ["amount", "price", "order_date", "signup_date"]
for p in pref:
    q = self._qualify_column(p, tables)
if q:
    return q
# if agg includes a column, use it
if agg and agg[1]:
    q = self._qualify_column(agg[1], tables)
if q:
    return q
# else any date column
d = self._find_date_column(tables)
if d:
    return d
# else the first numeric-sounding
for t in tables:
    for c in self.schema.tables[t].columns:
    if c not in ("id", "name", "city", "status", "category"):
    return f"{t}.{c}" if len(tables) > 1 else c
return None


# --------- SQL builder ---------
def _build_sql(self, pr: ParseResult) -> str:


    tables = pr.tables or ["customers"]
select_clause = "*"
if pr.agg:
    func, col = pr.agg
select_clause = f"{func}({col or '*'}) AS {func.lower()}"
if pr.columns:
# include extra columns for grouping
select_clause = ", ".join(pr.columns + [select_clause])
elif pr.columns:
select_clause = ", ".join(pr.columns)

from_clause = tables[0]
join_clause = ""
for (ltab, lcol, rtab, rcol) in pr.joins:
    join_clause += f" JOIN {rtab} ON {ltab}.{lcol} = {rtab}.{rcol}"

where_clause = ""
if pr.where:
    where_clause = " WHERE " + " AND ".join(dict.fromkeys(pr.where))

group_by_clause = ""
if pr.group_by:
    group_by_clause = " GROUP BY " + ", ".join(pr.group_by)

order_by_clause = ""
if pr.order_by:
    order_by_clause = f" ORDER BY {pr.order_by[0]} {pr.order_by[1].upper()}"

limit_clause = ""
if pr.limit is not None:
    limit_clause = f" LIMIT {pr.limit}"

sql = f"SELECT {select_clause} FROM {from_clause}{join_clause}{where_clause}{group_by_clause}{order_by_clause}{limit_clause};"
return sql


# -----------------------------
# Demo
# -----------------------------
def _demo():


    parser = NL2SQL(DEFAULT_SCHEMA)
examples = [
    "show top 5 customers from mumbai signed up last month",
    "how many orders after 2024-01-01 with status shipped",
    "total revenue by customers in mumbai",
    "list orders containing 'john' in name before 2024-06-01 order by amount desc",
    "average amount of orders for status completed last 7 days",
    "latest 3 orders for customer id 42",
    "products with price greater than 1000 in category electronics top 10",
    "count orders between 2024-01-01 and 2024-01-31",
    "sum amount for orders from mumbai",
    "lowest 5 products in price",
]
for q in examples:
    print("NL:", q)
print("SQL:", parser.to_sql(q))
print("-" * 80)

if __name__ == "__main__":
    _demo()


# -----------------------------
# Runtime patches for better heuristics
# -----------------------------
def _patched_detect_equality_filters(self, text: str, tables: list) -> list:


    filters = []
# 0) Common prepositional patterns
m_from = re.search(r"\bfrom\s+'?([a-z][a-z\s\-]+)'?", text)
if m_from and any('city' in self.schema.tables[t].columns for t in tables):
    city = m_from.group(1).strip()
for t in tables:
    if 'city' in self.schema.tables[t].columns:
    col = f"{t}.city" if len(tables) > 1 else "city"
filters.append(f"{col} = '{city}'")
break

# 1) Explicit ID patterns like "customer id 42" / "order id = 99"
for t in tables:
    id_col = None
for c in self.schema.tables[t].columns:
    if c == 'id' or c.endswith('_id'):
    id_col = c
break
if id_col:
    patt = rf"(?:\b{t}\s+id\b|\b{id_col}\b)\s*(?:=|is)?\s*(\d+)"
for m in re.finditer(patt, text):
    col = f"{t}.{id_col}" if len(tables) > 1 else id_col
filters.append(f"{col} = {m.group(1)}")

# 2) Quoted equality for string columns
for t in tables:
    for c in self.schema.tables[t].columns:
    patt_q = rf"(?:\b{re.escape(c)}\b|\b{'|'.join(map(re.escape, self.schema.column_synonyms.get(c, [])))}\b)\s*(?:=|is|equal to|equals)?\s*'([^']+)'"
for m in re.finditer(patt_q, text):
    col = f"{t}.{c}" if len(tables) > 1 else c
filters.append(f"{col} = '{m.group(1)}'")

# 3) Unquoted equality only for clearly stringy columns (name, city, status, category)
stringy = {'name', 'city', 'status', 'category'}
for t in tables:
    for c in self.schema.tables[t].columns:
    if c not in stringy:
    continue
patt_u = rf"(?:\b{re.escape(c)}\b|\b{'|'.join(map(re.escape, self.schema.column_synonyms.get(c, [])))}\b)\s*(?:=|is|equal to|equals)?\s*\b([a-z][a-z0-9_\-]+)\b"
for m in re.finditer(patt_u, text):
    val = m.group(1)
if val in {'greater', 'less', 'over', 'under', 'before', 'after', 'between', 'on', 'latest', 'highest', 'lowest', 'top',
           'bottom'}:
    continue
col = f"{t}.{c}" if len(tables) > 1 else c
filters.append(f"{col} = '{val}'")

# 4) "with status shipped" style
m_status = re.search(r"\bwith\s+status\s+'?([a-z][a-z0-9_\-]+)'?", text)
if m_status:
    val = m_status.group(1)
for t in tables:
    if 'status' in self.schema.tables[t].columns:
    col = f"{t}.status" if len(tables) > 1 else "status"
filters.append(f"{col} = '{val}'")
break

# dedupe
return list(dict.fromkeys(filters))


def _patched_detect_order_limit(self, text: str, tables: list, cols: list, agg):


    order_by, limit = None, None
# top/bottom/first/last N rows — but ignore time expressions like "last 7 days"
m = re.search(r"\b(top|bottom|first|last)\s+(\d+)\b(?!\s+(day|days|week|weeks|month|months|year|years))", text)
if m:
    keyword, n = m.group(1), int(m.group(2))
limit = n
direction = "desc" if keyword in ("top", "last") else "asc"
candidate = self._find_numeric_or_date_column(tables, cols, agg)
if candidate:
    order_by = (candidate, direction)

for key, (direction, domain) in ORDER_KEYWORDS.items():
    if key in text:
    candidate = self._find_date_column(tables) if domain == "date" else self._find_numeric_or_date_column(tables, cols,
                                                                                                          agg)
if candidate:
    order_by = (candidate, direction)
if limit is None and ("top" not in text and "bottom" not in text and not re.search(r"\b(first|last)\s+\d+\b", text)):
    limit = 10
break

m2 = re.search(r"order by\s+([a-z_][a-z0-9_\.]*)\s*(asc|desc)?", text)
if m2:
    col = m2.group(1)
direction = (m2.group(2) or "asc").lower()
qcol = self._qualify_column(col, tables) or col
order_by = (qcol, direction)

return order_by, limit


def _patched_find_date_column(self, tables: list) -> str | None:


# prefer the first table's date column if available
for t in tables:
    for c in self.schema.tables[t].columns:
    if "date" in c:
    return f"{t}.{c}" if len(tables) > 1 else c
return None

# Bind patches
NL2SQL._detect_equality_filters = _patched_detect_equality_filters
NL2SQL._detect_order_limit = _patched_detect_order_limit
NL2SQL._find_date_column = _patched_find_date_column


def _patched_detect_tables(self, text: str) -> list:


# order tables by first occurrence in text
hits = []
for tname, meta in self.schema.tables.items():
    patterns = [tname, f"{tname}s"] + meta.synonyms
best_idx = None
for p in patterns:
    m = re.search(rf"\b{re.escape(p)}\b", text)
if m:
    idx = m.start()
if best_idx is None or idx < best_idx:
    best_idx = idx
if best_idx is not None:
    hits.append((best_idx, tname))
hits.sort(key=lambda x: x[0])
return [t for _, t in hits]


def _better_city_from(text: str) -> str | None:


# extract after 'from' but stop at common boundary words
m = re.search(r"\bfrom\s+([a-z][a-z\s\-]+)", text)
if not m:
    return None
seg = m.group(1)
stop_words = ['signed', 'signup', 'sign', 'last', 'this', 'with', 'where', 'and', 'or', 'before', 'after', 'between',
              'on', 'in', 'for', 'order', 'orders', 'customers', 'products']
# cut at first stop word
tokens = seg.split()
out = []
for tok in tokens:
    if tok in stop_words:
    break
out.append(tok)
city = " ".join(out).strip()
return city or None


def _patched_detect_equality_filters_v2(self, text: str, tables: list) -> list:


# reuse previous patched but with better 'from <city>' and FK-aware "customer id"
filters = []
city = _better_city_from(text)
if city and any('city' in self.schema.tables[t].columns for t in tables):
    for t in tables:
    if 'city' in self.schema.tables[t].columns:
    col = f"{t}.city" if len(tables) > 1 else "city"
filters.append(f"{col} = '{city}'")
break

# FK-aware "customer id N" -> prefer orders.customer_id when orders present and FK exists
if re.search(r"\bcustomer\s+id\s+(\d+)", text) and 'orders' in tables:
    m = re.search(r"\bcustomer\s+id\s+(\d+)", text)
cid = m.group(1)
filters.append(f"{'orders.customer_id' if len(tables) > 1 else 'customer_id'} = {cid}")

# then call the previous patched one for the rest (but skip generic customer id since we handled above)
# Temporarily remove that phrase to avoid duplicate
text2 = re.sub(r"\bcustomer\s+id\s+\d+\b", "", text)
base = _patched_detect_equality_filters(self, text2, tables)
# merge with de-dupe
for f in base:
    if f not in filters:
    filters.append(f)
return filters

# Bind new patches
NL2SQL._detect_tables = _patched_detect_tables
NL2SQL._detect_equality_filters = _patched_detect_equality_filters_v2
