#!/usr/bin/env python3
"""Emit the skip-scan differential matrix for orioledb/orioledb#1313.

Writes setup_matrix.sql (tables) and matrix.sql (cases) into the directory
given as the first argument.  Pass --heap-only to create every table on heap,
which dry-runs the harness on stock PostgreSQL (every case must then be OK).

Tables: s1 has 4000 rows, a = g % 8, b NULL for a in (1, 3, 6) when g % 11 = 0
else g % 10, c NULL when g % 13 = 0 else g % 997.  s2 is s1 plus 300 rows with
a NULL (b NULL every third row, c = g % 997, NULL every 13th).  h1 and h2 are
heap twins without an index.

Cases: 2 tables x 5 index orderings x 2 directions x 13 quals = 260.  Each
case reads the full row set of the ordered query, which the planner routes
through the one index that exists at that moment (seqscan and bitmapscan are
off), and compares it with the heap twin using EXCEPT ALL both ways.
"""
import os
import sys

VARIANTS = [
    # name, index columns, forward ORDER BY, backward ORDER BY
    ("ll", "(a, b, c)",
     "a, b, c",
     "a DESC, b DESC, c DESC"),
    ("ff", "(a NULLS FIRST, b NULLS FIRST, c)",
     "a NULLS FIRST, b NULLS FIRST, c",
     "a DESC NULLS LAST, b DESC NULLS LAST, c DESC"),
    ("lf", "(a, b NULLS FIRST, c)",
     "a, b NULLS FIRST, c",
     "a DESC, b DESC NULLS LAST, c DESC"),
    ("fl", "(a NULLS FIRST, b, c)",
     "a NULLS FIRST, b, c",
     "a DESC NULLS LAST, b DESC, c DESC"),
    ("dd", "(a DESC, b DESC, c)",
     "a DESC, b DESC, c",
     "a, b, c DESC"),
]

QUALS = [
    "c = 5",
    "c = 0",
    "c > 900",
    "c < 50",
    "c IN (3, 500, 996)",
    "c IS NULL",
    "c BETWEEN 100 AND 110",
    "b > 5 AND c < 100",
    "b IS NOT NULL AND c = 5",
    "a = 3 AND c = 5",
    "b IS NULL AND c > 900",
    "a > 2 AND c = 7",
    "c IS NOT NULL AND c < 20",
]


def setup_sql(heap_only):
    am = "" if heap_only else " USING orioledb"
    return f"""\
DROP TABLE IF EXISTS s1, s2, h1, h2;
CREATE TABLE s1 (a int, b int, c int){am};
INSERT INTO s1
	SELECT g % 8,
		   CASE WHEN g % 8 IN (1, 3, 6) AND g % 11 = 0 THEN NULL ELSE g % 10 END,
		   CASE WHEN g % 13 = 0 THEN NULL ELSE g % 997 END
	FROM generate_series(1, 4000) g;
CREATE TABLE s2 (a int, b int, c int){am};
INSERT INTO s2 SELECT * FROM s1;
INSERT INTO s2
	SELECT NULL,
		   CASE WHEN g % 3 = 0 THEN NULL ELSE g % 10 END,
		   CASE WHEN g % 13 = 0 THEN NULL ELSE g % 997 END
	FROM generate_series(1, 300) g;
CREATE TABLE h1 AS SELECT * FROM s1;
CREATE TABLE h2 AS SELECT * FROM s2;
SELECT 'ROWS s1=' || (SELECT count(*) FROM s1) || ' s2=' || (SELECT count(*) FROM s2)
	|| ' s1_null_b=' || (SELECT count(*) FROM s1 WHERE b IS NULL)
	|| ' s1_null_c=' || (SELECT count(*) FROM s1 WHERE c IS NULL)
	|| ' s2_null_a=' || (SELECT count(*) FROM s2 WHERE a IS NULL);
"""


def case_sql(table, variant, direction, qual, order):
    heap = "h" + table[1]
    case = f"CASE {table} {variant} {direction} [{qual}]"
    return f"""\
WITH o AS (SELECT a, b, c FROM {table} WHERE {qual} ORDER BY {order}),
	 h AS (SELECT a, b, c FROM {heap} WHERE {qual})
SELECT '{case} ' || CASE WHEN missing = 0 AND extra = 0 THEN 'OK' ELSE 'WRONG' END
	|| ' missing=' || missing || ' extra=' || extra || ' got=' || got || ' want=' || want
FROM (SELECT (SELECT count(*) FROM (SELECT * FROM h EXCEPT ALL SELECT * FROM o) x) AS missing,
			 (SELECT count(*) FROM (SELECT * FROM o EXCEPT ALL SELECT * FROM h) y) AS extra,
			 (SELECT count(*) FROM o) AS got,
			 (SELECT count(*) FROM h) AS want) r;
"""


def matrix_sql():
    out = []
    out.append("\\pset tuples_only on\n\\pset format unaligned\n")
    out.append("SET statement_timeout = '120s';\n")
    out.append("SET enable_seqscan = off;\nSET enable_bitmapscan = off;\n")
    for table in ("s1", "s2"):
        for name, cols, fwd, bwd in VARIANTS:
            idx = f"{table}_{name}_idx"
            out.append(f"CREATE INDEX {idx} ON {table} {cols};\n")
            for direction, order in (("fwd", fwd), ("bwd", bwd)):
                out.append(f"\\echo PLAN {table} {name} {direction}\n")
                out.append(f"EXPLAIN (COSTS OFF) SELECT a, b, c FROM {table} "
                           f"WHERE {QUALS[2]} ORDER BY {order};\n")
                for qual in QUALS:
                    out.append(case_sql(table, name, direction, qual, order))
            out.append(f"DROP INDEX {idx};\n")
    # Exploratory, report only: a parallel index scan over skip-shaped quals.
    out.append("\\echo PARALLEL-PROBE\n")
    out.append("SET max_parallel_workers_per_gather = 2;\n"
               "SET parallel_setup_cost = 0;\nSET parallel_tuple_cost = 0;\n"
               "SET min_parallel_index_scan_size = 0;\n"
               "SET min_parallel_table_scan_size = 0;\n")
    for name, cols, fwd, bwd in VARIANTS[:2]:
        idx = f"s2_{name}_idx"
        out.append(f"CREATE INDEX {idx} ON s2 {cols};\n")
        for qual in ("c > 900", "c = 5", "b IS NULL AND c > 900"):
            out.append(f"\\echo PARALLEL-PLAN s2 {name} [{qual}]\n")
            out.append(f"EXPLAIN (COSTS OFF) SELECT count(*) FROM s2 WHERE {qual};\n")
            out.append(f"SELECT 'PARALLEL s2 {name} [{qual}] ' || CASE WHEN g = w THEN 'OK' ELSE 'WRONG' END "
                       f"|| ' got=' || g || ' want=' || w FROM (SELECT (SELECT count(*) FROM s2 WHERE {qual}) g, "
                       f"(SELECT count(*) FROM h2 WHERE {qual}) w) r;\n")
        out.append(f"DROP INDEX {idx};\n")
    out.append("RESET max_parallel_workers_per_gather;\n")
    return "".join(out)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    heap_only = "--heap-only" in sys.argv
    outdir = args[0] if args else "."
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "setup_matrix.sql"), "w") as f:
        f.write(setup_sql(heap_only))
    with open(os.path.join(outdir, "matrix.sql"), "w") as f:
        f.write(matrix_sql())
    ncases = 2 * len(VARIANTS) * 2 * len(QUALS)
    print(f"wrote {outdir}/setup_matrix.sql and {outdir}/matrix.sql ({ncases} cases)")


if __name__ == "__main__":
    main()
