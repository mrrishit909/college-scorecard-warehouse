"""Steps 1-2: download, then bronze -> silver.

    ./venv/bin/python lake.py      -> data/lake/institution_year/year=YYYY/*.parquet, data/lake/program/*.parquet,
                                      data/lake/cip_family.parquet, results/suppression.csv, results/lake_sizes.json

Bronze is the raw College Scorecard download (US Department of Education, released 10 June 2026): 30 annual
institution files of 3,308 columns each, plus field-of-study files. Silver keeps only the columns the warehouse needs,
typed, with the dictionary's null tokens (NULL, PrivacySuppressed, NA, PS) turned into real NULLs and counted first.
"""
import json
import re
import ssl
import urllib.request
import zipfile
from pathlib import Path

import duckdb

HERE = Path(__file__).parent
RAW = HERE / "data" / "raw"
BRONZE = RAW / "College_Scorecard_Raw_Data_06032026"
LAKE = HERE / "data" / "lake"
ZIP = "https://ed-public-download.scorecard.network/downloads/College_Scorecard_Raw_Data_06102026.zip"
CIP = "https://nces.ed.gov/ipeds/cipcode/Files/CIPCode2020.csv"
NULLS = ["NULL", "PrivacySuppressed", "NA", "PS"]
INST = {  # column -> type in silver
    "UNITID": "INTEGER", "OPEID6": "VARCHAR", "INSTNM": "VARCHAR", "CITY": "VARCHAR", "STABBR": "VARCHAR", "CONTROL": "TINYINT",
    "PREDDEG": "TINYINT", "REGION": "TINYINT", "LOCALE": "SMALLINT", "HBCU": "TINYINT", "MAIN": "TINYINT", "CURROPER": "TINYINT",
    "LATITUDE": "DOUBLE", "LONGITUDE": "DOUBLE", "UGDS": "INTEGER", "ADM_RATE": "DOUBLE", "COSTT4_A": "INTEGER",
    "NPT4_PUB": "INTEGER", "NPT4_PRIV": "INTEGER", "TUITIONFEE_IN": "INTEGER", "TUITIONFEE_OUT": "INTEGER", "PCTPELL": "DOUBLE",
    "C150_4": "DOUBLE", "C150_L4": "DOUBLE", "GRAD_DEBT_MDN": "DOUBLE", "MD_EARN_WNE_P10": "INTEGER", "CDR3": "DOUBLE",
}
PROG = {"UNITID": "INTEGER", "CIPCODE": "VARCHAR", "CIPDESC": "VARCHAR", "CREDLEV": "TINYINT", "CREDDESC": "VARCHAR",
        "IPEDSCOUNT1": "INTEGER", "IPEDSCOUNT2": "INTEGER", "DEBT_ALL_STGP_EVAL_MDN": "DOUBLE", "EARN_MDN_1YR": "INTEGER",
        "EARN_MDN_4YR": "INTEGER"}


def download():
    ctx = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
    RAW.mkdir(parents=True, exist_ok=True)
    z = RAW / Path(ZIP).name
    if not z.exists():
        z.write_bytes(urllib.request.urlopen(ZIP, context=ctx, timeout=3600).read())
    if not BRONZE.exists():
        with zipfile.ZipFile(z) as zf:
            zf.extractall(RAW, [n for n in zf.namelist() if "__MACOSX" not in n and not n.endswith(".DS_Store")])
    if not (RAW / "CIPCode2020.csv").exists():
        (RAW / "CIPCode2020.csv").write_bytes(urllib.request.urlopen(CIP, context=ctx, timeout=120).read())


def select(cols):
    """Typed columns with every null token mapped to NULL."""
    return ", ".join(f"TRY_CAST(CASE WHEN \"{c}\" IN ({', '.join(repr(n) for n in NULLS)}) THEN NULL ELSE \"{c}\" END AS {t}) AS {c.lower()}"
                     for c, t in cols.items())


def main():
    download()
    con = duckdb.connect()
    supp = []
    for f in sorted(BRONZE.glob("MERGED*_PP.csv")):
        year = int(re.search(r"MERGED(\d{4})", f.name).group(1))
        src = f"read_csv('{f}', all_varchar = true, header = true)"
        counts = con.execute("SELECT " + ", ".join(
            f"count(*) FILTER (WHERE \"{c}\" IN ('PS', 'PrivacySuppressed')), count(*) FILTER (WHERE \"{c}\" IN ('NULL', 'NA') OR \"{c}\" IS NULL)"
            for c in INST) + f", count(*) FROM {src}").fetchone()
        for i, c in enumerate(INST):
            supp.append({"year": year, "column": c, "rows": counts[-1], "privacy_suppressed": counts[2 * i], "null": counts[2 * i + 1]})
        out = LAKE / "institution_year" / f"year={year}"
        out.mkdir(parents=True, exist_ok=True)
        con.execute(f"COPY (SELECT {year} AS year, {select(INST)} FROM {src}) TO '{out / 'part.parquet'}' (FORMAT parquet)")
        print(year, counts[-1], "institutions")
    (LAKE / "program").mkdir(parents=True, exist_ok=True)
    for f in sorted(BRONZE.glob("FieldOfStudyData*_PP.csv")):
        cohort = re.search(r"FieldOfStudyData(\d{4}_\d{4})", f.name).group(1)
        con.execute(f"COPY (SELECT '{cohort}' AS cohort, {select(PROG)} FROM read_csv('{f}', all_varchar = true, header = true)) "
                    f"TO '{LAKE / 'program' / (cohort + '.parquet')}' (FORMAT parquet)")
        print("program", cohort)
    import pandas as pd
    cip = pd.read_csv(RAW / "CIPCode2020.csv", dtype=str)            # codes are written Excel-style: ="01"
    cip["code"] = cip["CIPCode"].str.replace(r'[="]', "", regex=True)
    cip[cip["code"].str.len() == 2][["code", "CIPTitle"]].rename(columns={"CIPTitle": "title"}).to_parquet(LAKE / "cip_family.parquet", index=False)
    (HERE / "results").mkdir(exist_ok=True)
    pd.DataFrame(supp).to_csv(HERE / "results" / "suppression.csv", index=False)
    size = lambda p: sum(x.stat().st_size for x in p.rglob("*") if x.is_file())
    # fair comparison: the same 27 columns as CSV vs Parquet (column pruning and file format are separate wins)
    tmp = HERE / "data" / "same_columns.csv"
    con.execute(f"COPY (SELECT * FROM read_parquet('{LAKE / 'institution_year' / '*' / '*.parquet'}', hive_partitioning = true)) TO '{tmp}' (HEADER)")
    same_cols_csv = tmp.stat().st_size
    tmp.unlink()
    sizes = {"bronze_institution_csv_mb": round(sum(f.stat().st_size for f in BRONZE.glob("MERGED*_PP.csv")) / 1e6),
             "same_27_columns_as_csv_mb": round(same_cols_csv / 1e6, 1),
             "silver_institution_parquet_mb": round(size(LAKE / "institution_year") / 1e6, 1),
             "bronze_program_csv_mb": round(sum(f.stat().st_size for f in BRONZE.glob("FieldOfStudyData*_PP.csv")) / 1e6),
             "silver_program_parquet_mb": round(size(LAKE / "program") / 1e6, 1)}
    (HERE / "results" / "lake_sizes.json").write_text(json.dumps(sizes, indent=2) + "\n")
    print(sizes)


if __name__ == "__main__":
    main()
