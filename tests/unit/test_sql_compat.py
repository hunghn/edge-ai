"""The device runs SQLite 3.22 (Ubuntu 18.04). Guard against newer syntax.

Only real SQL is scanned: .sql files with their `--` comments stripped, and Python
string literals that contain a SQL verb. Prose in a docstring that merely names a
feature ("no RETURNING (3.35)") must not trip the guard.
"""
import glob
import io
import os
import re
import tokenize

import edgeface

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(edgeface.__file__)))
PY_FILES = (glob.glob(os.path.join(ROOT, "edgeface", "storage", "*.py"))
            + glob.glob(os.path.join(ROOT, "edgeface", "gallery", "*.py")))
SQL_FILES = glob.glob(os.path.join(ROOT, "edgeface", "storage", "schema", "*.sql"))
SCHEMA = os.path.join(ROOT, "edgeface", "storage", "schema", "001_init.sql")

SQL_VERB = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE|PRAGMA|REPLACE)\b", re.I)

FORBIDDEN = [
    (re.compile(r"ON\s+CONFLICT\s*\(", re.I), "UPSERT needs SQLite 3.24; use UPDATE then INSERT"),
    (re.compile(r"\bRETURNING\b", re.I), "RETURNING needs SQLite 3.35"),
    (re.compile(r"\bOVER\s*\(", re.I), "window functions need SQLite 3.25"),
    (re.compile(r"DROP\s+COLUMN", re.I), "DROP COLUMN needs SQLite 3.35"),
    (re.compile(r"\bGENERATED\s+ALWAYS\b", re.I), "generated columns need SQLite 3.31"),
    (re.compile(r"\bIIF\s*\(", re.I), "IIF needs SQLite 3.32"),
]


def sql_snippets():
    """[(file, line, sql)] — every piece of SQL the storage layer can execute."""
    out = []
    for path in SQL_FILES:
        with open(path) as f:
            for lineno, line in enumerate(f, 1):
                statement = line.split("--", 1)[0]
                if statement.strip():
                    out.append((path, lineno, statement))
    for path in PY_FILES:
        with open(path, "rb") as f:
            for token in tokenize.tokenize(f.readline):
                if token.type == tokenize.STRING and SQL_VERB.search(token.string):
                    out.append((path, token.start[0], token.string))
    return out


def test_no_sql_newer_than_3_22():
    snippets = sql_snippets()
    assert snippets, "no SQL found to scan"
    problems = []
    for path, lineno, sql in snippets:
        for pattern, reason in FORBIDDEN:
            if pattern.search(sql):
                problems.append("{}:{}: {}".format(os.path.basename(path), lineno, reason))
    assert not problems, "\n".join(problems)


def test_schema_statements_are_rerunnable():
    """executescript is not transactional, so a migration must survive being re-run."""
    with open(SCHEMA) as f:
        text = "\n".join(line.split("--", 1)[0] for line in f)
    bad_create = re.findall(r"CREATE\s+(?:TABLE|INDEX)\s+(?!IF\s+NOT\s+EXISTS)(\w+)", text, re.I)
    assert not bad_create, "missing IF NOT EXISTS: {}".format(bad_create)
    bad_insert = re.findall(r"INSERT\s+(?!OR\s+IGNORE)(\w+)", text, re.I)
    assert not bad_insert, "plain INSERT in a migration is not re-runnable: {}".format(bad_insert)


def test_guard_catches_a_real_violation():
    """The guard itself must work — otherwise it silently passes forever."""
    sql = "INSERT INTO patients (patient_code) VALUES (?) ON CONFLICT (patient_code) DO NOTHING"
    assert any(pattern.search(sql) for pattern, _ in FORBIDDEN)
