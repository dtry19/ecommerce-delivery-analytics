# Explaining the project in a BIE interview

## Business question

An operations manager wants to investigate delivery bottlenecks and understand
customer feedback. The outputs identify high-volume late routes/seller
associations and quantify the historical review difference. Recommendations
are proposed investigations; no actual operational intervention was run.

## Implementation evidence

| BIE requirement | What this project implements |
| --- | --- |
| SQL querying | Multi-table joins, nested/recursive CTEs, conditional aggregation, ROW_NUMBER, LAG, DENSE_RANK, weighted rolling windows and cumulative Pareto shares |
| DDL and data modeling | Three dimensions, order and item facts, declared primary/foreign keys, CHECK constraints and unique indexes in sql/warehouse.sql |
| ETL and scripting | Version-pinned acquisition, SHA-256 checks, Python CSV ingestion, validation and atomic reporting-database replacement |
| Statistics | Welch t-test, confidence intervals, Cohen's d, Pearson chi-squared, expected-count checks, Cramer's V, rank-based sensitivity and Holm correction |
| Regression | State/month categorical controls and continuous covariates, HC3 robust uncertainty, full coefficient export and rank validation |
| BI visualization | Filterable browser dashboard plus native Excel chart and monthly formulas; facts/dimensions exported for other BI tools |
| Optimization | Composite indexes, EXPLAIN QUERY PLAN, result equivalence and repeated warm-query timings |
| Reliability | Automated fixture tests, reconciliation, invalid-refresh preservation, report staleness checks and GitHub Actions workflow definition |
| Communication | Reproducible findings memo, exact source/sample counts, limitations and a proposed pilot measurement plan |

## Questions to be ready for

**Why not join everything directly?** One order can have several items and
reviews. Joining raw tables would multiply rows and money. Aggregate items and
rank/select reviews before joining; validate one row per order and reconcile
item prices to order totals.

**Why 112,650 rows but 99,441 orders?** The first is order-item grain and the
second is order grain. Five loaded source tables total 413,851 records.
Auxiliary downloaded geolocation data is not counted as analyzed observations.

**Why Welch?** Group sizes and variances differ. Welch compares mean star
scores without assuming equal variances. Stars are ordinal, so report a
Mann-Whitney rank-based sensitivity analysis as well, with its distinct null.

**Why chi-squared?** Late/on-time and low/not-low review are categorical. Show
the 2x2 table and confirm expected counts exceed five. Report Cramer's V so
sample size does not make a tiny p-value the entire story.

**What is the unit of inference?** One first eligible reviewed order per unique
customer. That reduces repeated-customer dependence. Shared sellers/routes and
time shocks can still correlate outcomes; HC3 is not cluster-robust inference.

**Why regression?** Examine whether the association persists conditional on
recorded order characteristics and state/month controls. It does not remove
unmeasured confounding. No causal reduction or out-of-sample accuracy is claimed.

**Why weighted rolling rates?** Sum late orders and eligible orders over the
same dense three-month calendar window, then divide. Averaging three monthly
percentages would give small and large months equal influence.

**How do you optimize SQL?** Use an equality state column followed by a purchase
timestamp range in the composite index. Inspect the query plan, verify identical
results, and measure repeated executions on the same disposable database copy.
The dashboard also indexes these columns; its date() wrappers may limit use of
the range part. The benchmark measures the explicit sargable research query,
not a blanket speedup for every dashboard endpoint.

**What would you improve next?** Carrier/product controls, seller/time cluster
sensitivity, richer review-selection modeling, a second dataset/time period,
and an actual controlled operational pilot. These are future work, not current
resume claims.
