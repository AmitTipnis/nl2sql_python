# nl2sql_python
Convert simple English requests into SQL queries using lightweight NLP heuristics.

"""
nl2sql.py — Minimal, dependency-free NL → SQL converter (rule-based)

Purpose
-------
Convert simple English requests into SQL queries using lightweight NLP heuristics.
This is NOT a full semantic parser; it's a practical starting point you can adapt.

Key features supported
----------------------
- SELECT (default), COUNT, SUM, AVG, MIN, MAX
- Simple WHERE filters: equality, contains/like, >, <, >=, <=
- Date filters: before/after/on, between, "last N days/weeks/months/years"
- ORDER BY: highest/lowest/top N, latest/earliest
- LIMIT: "top N", "first N", "last N"
- Very simple JOIN when two tables are detected and a foreign key mapping exists
- Synonym mapping for columns and tables
- Configurable schema metadata

Limitations
-----------
- English-only, simple sentence structures
- No complex nested logic or subqueries
- Limited join inference (one-hop via provided FKs)
- Ambiguity is resolved with heuristics; validate generated SQL before executing

Usage
-----
Run directly to see demo examples:
pip install -r requirements.txt
python nl2sql.py

Import and use:
from nl2sql import NL2SQL, DEFAULT_SCHEMA
parser = NL2SQL(DEFAULT_SCHEMA)
sql = parser.to_sql("show top 5 customers from mumbai signed up last month")

Security
--------
 This tool outputs literal SQL for demonstration. No security aspect covered.


from __future__ import annotations

