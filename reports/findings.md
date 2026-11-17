# Olist delivery performance: findings and methods

## Decision and data

Question: where should marketplace operations investigate delivery delays, and
how strongly are delays associated with customer reviews?

Source: [Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce),
version 2, CC BY-NC-SA 4.0. Archive SHA-256:
`967e41e04fc306fe604e2a693f488995a8b41e5047418f8a5c8e4abd6deca784`.
Source mode: **OLIST PUBLIC DATASET**. Build: 2026-11-17T02:07:22.025448+00:00.
This report concerns historical Brazilian marketplace data, not Amazon data.

The pipeline loads **413,851 rows across five source tables**, including
**112,650 order items and 99,441 distinct orders**.
Downloaded auxiliary tables are counted in the provenance manifest but are not
part of this loaded-row claim. Purchase dates: 2016-09-04 through 2018-10-17.
There are 96,470 eligible delivered orders and 6,534
late deliveries (6.77%).
8 delivered orders with invalid/missing dates are excluded from delivery metrics.

## Hypotheses and sample

The analysis sample is the first eligible reviewed order per customer_unique_id,
ordered by purchase timestamp and order ID. This produces 92,747
unique customers: 6,211 late and 86,536 on time.
The SQL selects the latest review per order before this customer-level selection.
The sample is conditional on observed delivery and review, not all customers.

1. Welch's two-sided t-test: H0 is equal mean review scores for late and on-time
   deliveries. Unequal population variances are allowed.
2. Pearson chi-squared test without Yates correction: H0 is independence of
   late status and low review (1-2 stars versus 3-5 stars).
3. Two-sided Mann-Whitney U provides a rank-based sensitivity check because
   review scores are bounded and ordinal. It tests distributions/ranks, not
   an interchangeable claim about mean differences.

These are exploratory analyses. Holm correction covers the family of these
three tests; the separate adjusted regression is also exploratory.

## Measured results

| Measure | Result |
| --- | --- |
| Late / on-time mean review | 2.266 / 4.289 stars |
| Mean difference, late minus on time | -2.023 stars |
| Welch 95% confidence interval | [-2.063, -1.983] |
| Welch t / degrees of freedom | -99.696 / 6697.18 |
| Welch Holm-adjusted p | < 1e-300 (numerical underflow) |
| Cohen's d, pooled-SD descriptive effect size | -1.711 |
| Low-review share, late / on time | 62.55% / 9.28% |
| Chi-squared / degrees of freedom | 14681.212 / 1 |
| Minimum expected contingency count | 798.18 (all exceed 5) |
| Chi-squared Holm-adjusted p | < 1e-300 (numerical underflow) |
| Cramer's V | 0.398 |
| Mann-Whitney Holm-adjusted p | < 1e-300 (numerical underflow) |

Contingency rows are on time, late; columns are 3-5 stars, 1-2 stars:
`[[78502, 8034], [2326, 3885]]`. JSON retains floating-point underflow as 0; this is not a
claim that the mathematical p-value is exactly zero.

## Adjusted regression

Formula: `review_score ~ is_late + np.log1p(merchandise_value) + promised_days + seller_count + C(customer_state) + C(purchase_month)`.
OLS estimates an adjusted mean association with HC3 heteroskedasticity-robust
standard errors. States and purchase months enter as categorical fixed effects.
Months with fewer than 30 reviewed customers
are excluded to avoid unstable month effects (2
customers excluded). This volume rule does not select on review score.

N = 92,745; late coefficient = -1.995 stars,
95% CI [-2.036, -1.955],
p < 1e-300 (numerical underflow), R-squared = 0.178.
Full coefficients and robust intervals are in regression_coefficients.csv.
The matrix has full column rank (51) and condition number
4687.9; coefficient estimates should be interpreted with
the sparse states, feature scale differences, and residual confounding in mind.
OLS treats stars as numeric. It is an explanatory sensitivity analysis, not a
validated forecasting model; no train/test accuracy claim is made.

## SQL engineering and performance

Explicit DDL models date, customer and seller dimensions, order facts and
order-item facts. Primary/foreign keys, unique grain checks and monetary
reconciliations defend against join fanout. Advanced analyses use recursive
calendar CTEs, ROW_NUMBER, DENSE_RANK, LAG, cumulative SUM and rolling ROWS windows.
Shipping-route Wilson intervals expose uncertainty; seller Pareto shares use
seller-associated orders, which are non-additive to distinct order totals.

EXPLAIN QUERY PLAN changes a state/date query from a table scan to a composite
index search. On this local in-memory copy, median warm timings over
15 runs were 6.090 ms without the index
and 0.904 ms with it (6.73x).
Results match between query plans. Timing is environment-specific and is not
a production latency or business-impact claim.

## Recommended investigation and next measurement

Operations should investigate high-volume late routes and seller associations
in route_intervals.csv and seller_pareto.csv, using counts and intervals rather
than the largest raw percentage. Inspect carrier handoffs and exception logs
before assigning responsibility; those causal details are not in this model.
Customer experience teams can review communications around missed estimates,
given the measured low-review association.

A proposed pilot would compare late-delivery rate, 1-2 star review share and
freight cost against a contemporaneous randomized or carefully matched control
over complete purchase cohorts. No pilot was run and no improvement is claimed.

## Limits

Review nonresponse, surviving delivered orders, incomplete end cohorts,
unmeasured product/carrier factors, and residual seller/time correlation limit
inference. One order per customer reduces repeated-customer dependence but does
not guarantee independence across shared sellers, routes or dates. HC3 handles
heteroskedasticity, not all clustering. Multiple sellers cannot be assigned the
order's delay causally. Large samples make tiny p-values unsurprising; effect
sizes, uncertainty and practical relevance carry the interpretation. Repeat
purchase cohorts describe observed activity, not subscription retention.

Method references: [SciPy Welch test](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_ind.html),
[SciPy contingency test](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.chi2_contingency.html),
[statsmodels robust covariance](https://www.statsmodels.org/stable/generated/statsmodels.regression.linear_model.OLSResults.get_robustcov_results.html).
