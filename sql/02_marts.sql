-- Step 4: marts (build.py writes each block to results/<name>.csv). Medians are across institutions or programs.

-- name: measure_availability
-- Which measures exist in which annual file: they arrive sparsely, so each question uses a year where its measures meet.
SELECT year, count(*) AS institutions, count(undergrad_enrollment) AS enrollment, count(tuition_in_state) AS tuition,
       count(avg_net_price) AS net_price, count(median_debt_completers) AS debt, count(median_earnings_10yr) AS earnings_10yr,
       count(completion_rate) AS completion
  FROM fact_institution_year GROUP BY 1 ORDER BY 1;

-- name: enrollment_by_control
SELECT c.year, d.label AS control, c.institutions, c.undergrads
  FROM agg_enrollment_cube c JOIN dim_control d USING (control)
 WHERE c.grouping_id = 1                                       -- year and control kept, region rolled up
 ORDER BY 1, 2;

-- name: outcomes_by_control_2020
-- 2020-21 file (the latest with earnings), predominantly bachelor's-degree institutions only: most for-profits are
-- certificate schools, so mixing degree levels would compare different things.
SELECT d.label AS control, count(*) AS institutions, count(f.median_earnings_10yr) AS with_earnings,
       median(f.avg_net_price) AS median_net_price, median(f.median_debt_completers) AS median_debt,
       median(f.median_earnings_10yr) AS median_earnings_10yr, round(median(f.completion_rate), 3) AS median_completion,
       round(median(f.median_debt_completers / f.median_earnings_10yr), 3) AS median_debt_to_earnings
  FROM fact_institution_year f JOIN dim_institution i USING (unitid) JOIN dim_control d USING (control)
 WHERE f.year = 2020 AND i.predominant_degree = 3        -- predominantly bachelor's: compare like with like
 GROUP BY 1 ORDER BY median_earnings_10yr DESC;

-- name: tuition_trend
SELECT f.year, d.label AS control, count(f.tuition_in_state) AS institutions, median(f.tuition_in_state) AS median_in_state_tuition
  FROM fact_institution_year f JOIN dim_institution i USING (unitid) JOIN dim_control d USING (control)
 WHERE i.predominant_degree = 3 AND f.tuition_in_state IS NOT NULL GROUP BY 1, 2 ORDER BY 1, 2;

-- name: bachelors_by_field
-- Bachelor's programs in the 2018-20 completer cohort file, the one file with earnings and debt together.
SELECT fam.family, fam.family_title, count(*) AS programs, count(p.median_earnings_4yr) AS with_earnings,
       median(p.median_earnings_1yr) AS earnings_1yr, median(p.median_earnings_4yr) AS earnings_4yr, median(p.median_debt) AS debt,
       round(median(p.median_debt / p.median_earnings_4yr), 2) AS debt_to_earnings
  FROM fact_program p JOIN dim_field f USING (cip) JOIN dim_cip_family fam ON fam.family = f.family
 WHERE p.cohort = '1819_1920' AND p.credential_level = 3
 GROUP BY 1, 2 HAVING count(p.median_earnings_4yr) >= 100 ORDER BY earnings_4yr DESC;

-- name: closures
-- "No longer appears" includes closures but also mergers and branch campuses folded into a parent's reporting.
SELECT d.label AS control, count(*) FILTER (WHERE i.first_year <= 2010) AS present_by_2010,
       count(*) FILTER (WHERE i.first_year <= 2010 AND i.last_year < 2025) AS not_in_2025_file,
       round(100.0 * count(*) FILTER (WHERE i.first_year <= 2010 AND i.last_year < 2025) / count(*) FILTER (WHERE i.first_year <= 2010), 1) AS pct_not_in_2025
  FROM dim_institution i JOIN dim_control d USING (control) GROUP BY 1 ORDER BY 1;

-- name: suppression
SELECT "column", sum("rows") AS "rows", sum(privacy_suppressed) AS privacy_suppressed, sum("null") AS missing
  FROM read_csv('{results}/suppression.csv') GROUP BY 1 ORDER BY 3 DESC, 4 DESC;
