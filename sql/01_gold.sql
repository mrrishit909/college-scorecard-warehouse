-- Step 3: silver -> gold. Two fact tables at different grains sharing conformed dimensions ({lake} filled in by build.py).
--   fact_institution_year   one row per institution per academic year (1996-97 .. 2025-26)
--   fact_program            one row per institution x field (4-digit CIP) x credential x cohort file
CREATE OR REPLACE VIEW silver_inst AS SELECT * FROM read_parquet('{lake}/institution_year/*/*.parquet', hive_partitioning = true);
CREATE OR REPLACE VIEW silver_prog AS SELECT * FROM read_parquet('{lake}/program/*.parquet');

CREATE OR REPLACE TABLE dim_control (control TINYINT PRIMARY KEY, label VARCHAR NOT NULL);
INSERT INTO dim_control VALUES (1, 'Public'), (2, 'Private nonprofit'), (3, 'Private for-profit');

CREATE OR REPLACE TABLE dim_year AS
SELECT DISTINCT year::SMALLINT AS year, year || '-' || right((year + 1)::VARCHAR, 2) AS academic_year FROM silver_inst ORDER BY 1;

-- Institution attributes from each institution's most recent file (Type 1: latest values, the "as-is" view).
-- Sector and degree mix also go on the fact as reported each year (the "as-was" view): 369 institutions changed
-- sector, and filing their whole history under today's sector rewrites the past.
CREATE OR REPLACE TABLE dim_institution AS
SELECT unitid, arg_max(instnm, year) AS name, arg_max(city, year) AS city, arg_max(stabbr, year) AS state,
       arg_max(control, year) AS control, arg_max(preddeg, year) AS predominant_degree, arg_max(region, year) AS region,
       arg_max(locale, year) AS locale, arg_max(hbcu, year) AS hbcu, arg_max(main, year) AS main_campus,
       arg_max(latitude, year) FILTER (WHERE latitude IS NOT NULL) AS latitude,
       arg_max(longitude, year) FILTER (WHERE longitude IS NOT NULL) AS longitude,
       min(year) AS first_year, max(year) AS last_year
  FROM silver_inst GROUP BY unitid;

CREATE OR REPLACE TABLE dim_cip_family AS SELECT code AS family, rtrim(title, '.') AS family_title FROM read_parquet('{lake}/cip_family.parquet');
CREATE OR REPLACE TABLE dim_field AS
SELECT cipcode AS cip, any_value(cipdesc) AS field, left(cipcode, 2) AS family FROM silver_prog WHERE cipcode IS NOT NULL GROUP BY 1;
CREATE OR REPLACE TABLE dim_credential AS SELECT DISTINCT credlev AS credential_level, creddesc AS credential FROM silver_prog WHERE credlev IS NOT NULL;

CREATE OR REPLACE TABLE fact_institution_year AS
SELECT unitid, year::SMALLINT AS year, control, preddeg AS predominant_degree, ugds AS undergrad_enrollment, adm_rate AS admission_rate, costt4_a AS cost_of_attendance,
       coalesce(npt4_pub, npt4_priv) AS avg_net_price, tuitionfee_in AS tuition_in_state, tuitionfee_out AS tuition_out_of_state,
       pctpell AS pell_share, coalesce(c150_4, c150_l4) AS completion_rate, grad_debt_mdn AS median_debt_completers,
       md_earn_wne_p10 AS median_earnings_10yr, cdr3 AS default_rate_3yr, curroper AS operating_flag
  FROM silver_inst;

CREATE OR REPLACE TABLE fact_program AS
SELECT cohort, unitid, cipcode AS cip, credlev AS credential_level, ipedscount1 AS completers_year1, ipedscount2 AS completers_year2,
       debt_all_stgp_eval_mdn AS median_debt, earn_mdn_1yr AS median_earnings_1yr, earn_mdn_4yr AS median_earnings_4yr
  FROM silver_prog;

-- A pre-aggregated cube for dashboards: every combination of year x sector (as reported that year) x region, plus subtotals.
CREATE OR REPLACE TABLE agg_enrollment_cube AS
SELECT f.year, f.control, i.region, GROUPING(f.year, f.control, i.region) AS grouping_id,
       count(*) AS institutions, sum(f.undergrad_enrollment) AS undergrads
  FROM fact_institution_year f JOIN dim_institution i USING (unitid)
 GROUP BY CUBE (f.year, f.control, i.region);
