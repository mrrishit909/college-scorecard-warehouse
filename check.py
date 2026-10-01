"""The project's check: run after lake.py and build.py. Fails loudly if a layer stops agreeing with the one below it.

    ./venv/bin/python check.py

1. bronze -> silver: for three years, row counts, enrollment totals and suppressed-value counts recompute from the raw
   CSVs; no suppression token survives as a value
2. silver -> gold: one fact row per institution-year, every fact has its institution, the dimension holds each
   institution's latest attributes, and the CUBE's subtotals add up
3. marts: the 2020 sector medians and one field-of-study row recompute in pandas straight from the silver Parquet
"""
import json
from pathlib import Path

import duckdb
import pandas as pd

import build as B

HERE = Path(__file__).parent
R = HERE / "results"


def main():
    raw = duckdb.connect()
    con = duckdb.connect(str(B.DB), read_only=True)
    q = lambda c, sql: c.execute(sql).fetchone()
    supp = pd.read_csv(R / "suppression_by_year.csv").set_index(["year", "column"])
    for year in (2000, 2012, 2020):
        f = next(B.BRONZE.glob(f"MERGED{year}_*_PP.csv"))
        n, ugds, ps = q(raw, f"""SELECT count(*), sum(TRY_CAST(UGDS AS BIGINT)), count(*) FILTER (WHERE GRAD_DEBT_MDN IN ('PS', 'PrivacySuppressed'))
                                  FROM read_csv('{f}', all_varchar = true, header = true)""")
        gn, gugds = q(con, f"SELECT count(*), sum(undergrad_enrollment) FROM fact_institution_year WHERE year = {year}")
        assert (n, ugds) == (gn, gugds), (year, n, gn, ugds, gugds)
        assert ps == supp.loc[(year, "GRAD_DEBT_MDN"), "privacy_suppressed"]
    lake = f"read_parquet('{B.LAKE}/institution_year/*/*.parquet', hive_partitioning = true)"
    assert q(raw, f"SELECT count(*) FROM {lake} WHERE instnm IN ('PS', 'NULL', 'PrivacySuppressed')")[0] == 0

    assert q(con, "SELECT count(*) - count(DISTINCT (unitid, year)) FROM fact_institution_year")[0] == 0
    assert q(con, "SELECT count(*) FROM fact_institution_year f WHERE NOT EXISTS (SELECT 1 FROM dim_institution i WHERE i.unitid = f.unitid)")[0] == 0
    assert q(con, "SELECT count(*) - count(DISTINCT unitid) FROM dim_institution")[0] == 0
    latest = q(con, f"""SELECT count(*) FROM dim_institution i JOIN {lake} s ON s.unitid = i.unitid AND s.year = i.last_year
                         WHERE s.instnm <> i.name OR s.stabbr <> i.state""")[0]
    assert latest == 0
    by_year = con.execute("""SELECT year, control, undergrads FROM agg_enrollment_cube WHERE grouping_id = 1""").df()
    base = con.execute("""SELECT f.year, i.control, sum(f.undergrad_enrollment) AS u FROM fact_institution_year f
                           JOIN dim_institution i USING (unitid) GROUP BY 1, 2""").df()
    m = by_year.merge(base, on=["year", "control"])
    assert len(m) == len(base) and (m["undergrads"].fillna(-1) == m["u"].fillna(-1)).all()
    grand = q(con, "SELECT undergrads FROM agg_enrollment_cube WHERE year IS NULL AND control IS NULL AND region IS NULL")[0]
    assert grand == q(con, "SELECT sum(undergrad_enrollment) FROM fact_institution_year")[0]

    s = raw.execute(f"SELECT * FROM {lake} WHERE year = 2020").df()
    dim = con.execute("SELECT unitid, control, predominant_degree FROM dim_institution").df()
    s = s.drop(columns=["control", "preddeg"]).merge(dim, on="unitid")
    s = s[s["predominant_degree"] == 3]
    s["net"] = s["npt4_pub"].fillna(s["npt4_priv"])
    mart = pd.read_csv(R / "outcomes_by_control_2020.csv").set_index("control")
    label = {1: "Public", 2: "Private nonprofit", 3: "Private for-profit"}
    for code, g in s.groupby("control"):
        row = mart.loc[label[code]]
        assert len(g) == row["institutions"]
        assert g["md_earn_wne_p10"].median() == row["median_earnings_10yr"] and g["net"].median() == row["median_net_price"]
        assert g["grad_debt_mdn"].median() == row["median_debt"]
    prog = raw.execute(f"SELECT * FROM read_parquet('{B.LAKE}/program/1819_1920.parquet') WHERE credlev = 3 AND left(cipcode, 2) = '14'").df()
    eng = pd.read_csv(R / "bachelors_by_field.csv", dtype={"family": str}).set_index("family").loc["14"]
    assert prog["earn_mdn_4yr"].median() == eng["earnings_4yr"] and prog["debt_all_stgp_eval_mdn"].median() == eng["debt"]

    bench = json.loads((R / "benchmark.json").read_text())
    assert bench["raw_and_parquet_agree"] and bench["silver_parquet_seconds"] * 100 < bench["raw_csv_seconds"]
    print(f"OK: three years of raw CSV recompute in silver and gold (counts, enrollment, suppression); no suppression token left; "
          f"one fact per institution-year, all with an institution; latest attributes; CUBE subtotals add up; 2020 sector medians "
          f"and engineering's medians recompute from Parquet; raw CSV and Parquet agree ({bench['raw_csv_seconds']} s vs {bench['silver_parquet_seconds']} s)")


if __name__ == "__main__":
    main()
