"""Steps 3-4: build the gold star schema from the silver lake, run the marts, and time raw CSV vs Parquet.

    ./venv/bin/python build.py     -> data/warehouse.duckdb, results/*.csv, results/benchmark.json, results/warehouse_counts.json
"""
import json
import re
import time
from pathlib import Path

import duckdb

HERE = Path(__file__).parent
DB = HERE / "data" / "warehouse.duckdb"
LAKE = HERE / "data" / "lake"
BRONZE = HERE / "data" / "raw" / "College_Scorecard_Raw_Data_06032026"


def blocks(path):
    text = path.read_text()
    return [(m.group(1).strip(), m.group(2).strip().rstrip(";")) for m in re.finditer(r"-- name: ([^\n]+)\n(.*?)(?=\n-- name:|\Z)", text, re.S)]


def timed(con, sql, runs=3):
    t = []
    for _ in range(runs):
        t0 = time.perf_counter()
        result = con.execute(sql).fetchall()
        t.append(time.perf_counter() - t0)
    return sorted(t)[runs // 2], result


def main():
    if DB.exists():
        DB.unlink()
    con = duckdb.connect(str(DB))
    con.execute((HERE / "sql" / "01_gold.sql").read_text().replace("{lake}", str(LAKE)))
    (HERE / "results").mkdir(exist_ok=True)
    for name, sql in blocks(HERE / "sql" / "02_marts.sql"):
        sql = sql.replace("{results}", str(HERE / "results"))
        con.execute(f"COPY ({sql}) TO '{HERE / 'results' / (name + '.csv')}' (HEADER)")

    q = "SELECT CONTROL, sum(TRY_CAST(UGDS AS BIGINT)) FROM {src} GROUP BY 1 ORDER BY 1"
    raw = f"read_csv('{BRONZE}/MERGED*_PP.csv', all_varchar = true, header = true, union_by_name = true)"
    t_raw, r_raw = timed(con, q.format(src=raw), runs=1)
    t_pq, r_pq = timed(con, q.format(src=f"read_parquet('{LAKE}/institution_year/*/*.parquet', hive_partitioning = true)"))
    t_gold, r_gold = timed(con, "SELECT control, sum(undergrad_enrollment) FROM fact_institution_year GROUP BY 1 ORDER BY 1")
    bench = {"query": "total undergraduate enrollment by control, all 30 years",
             "raw_csv_seconds": round(t_raw, 2), "silver_parquet_seconds": round(t_pq, 3), "gold_table_seconds": round(t_gold, 3),
             "raw_parquet_and_gold_agree": [list(map(str, x)) for x in r_raw if x[0] in ("1", "2", "3")] == [[str(a), str(b)] for a, b in r_pq if a is not None]
                                           == [[str(a), str(b)] for a, b in r_gold if a is not None]}
    (HERE / "results" / "benchmark.json").write_text(json.dumps(bench, indent=2) + "\n")
    print(bench)
    counts = dict(zip(["institutions", "institution_years", "program_rows", "fields"], con.execute(
        "SELECT (SELECT count(*) FROM dim_institution), (SELECT count(*) FROM fact_institution_year), (SELECT count(*) FROM fact_program), (SELECT count(*) FROM dim_field)").fetchone()))
    widths = {len(con.execute(f"DESCRIBE SELECT * FROM read_csv('{f}', all_varchar = true, header = true)").fetchall()) for f in BRONZE.glob("MERGED*_PP.csv")}
    counts.update(institution_files=len(list(BRONZE.glob("MERGED*_PP.csv"))), columns_per_institution_file=sorted(widths))
    (HERE / "results" / "warehouse_counts.json").write_text(json.dumps(counts, indent=2) + "\n")
    print(counts)


if __name__ == "__main__":
    main()
