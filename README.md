# E-commerce Delivery Performance Dashboard

A reproducible Python + SQLite analytics project with a browser dashboard.
Investigate late deliveries by purchase month, customer state, and seller;
compare customer reviews for late and on-time deliveries.

**Real-data edition:** 413,851 loaded source rows, including **112,650 order items
across 99,441 distinct orders**, from the Olist Brazilian marketplace dataset.
The complete archive also includes 1,000,163 geolocation rows; those are not part
of the pipeline's loaded-row claim. Statistical analyses use 92,747 unique
customers with eligible deliveries and reviews. See [measured findings](reports/findings.md)
and [resume bullets](reports/resume_bullets.md).

## Reproduce the real-data study

Requires Python 3.11+ for the pinned statistical dependencies. Use a virtual
environment, then run these commands from this repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python download_data.py
python pipeline.py
python research.py
python -m unittest discover -s tests -v
python server.py
```

`download_data.py` fetches Olist version 2 directly from its public Kaggle endpoint,
verifies the archive SHA-256, and records per-file checksums and logical CSV row
counts. It refuses to overwrite differing source files. For an existing archive,
use `python download_data.py --archive /path/to/archive.zip`.
A dataset/source change fails verification until intentionally reviewed.
Raw CSVs and generated databases stay local and are ignored by Git.

`research.py` writes reproducible results, SQL analysis CSVs, regression
coefficients, a findings memo, resume bullets, and star-schema BI exports under
`reports/`. The dashboard research panel checks the database build timestamp and
rejects stale results. Run `research.py` again after rebuilding the database.

## Run the lightweight synthetic demo

Requires Python 3.10+ with SQLite support. The demo pipeline and server use the Python standard library. Statistical research
requires `requirements.txt`; the real-data study above is the portfolio evidence. Windows users can substitute `py` for `python`.

```bash
python pipeline.py --demo
python server.py
```

Open http://localhost:8000 in your browser. Keep the terminal running; press
Ctrl+C to stop. The server binds to localhost and is intended for local use,
not production internet hosting. To use another port: `python server.py --port 8001`.

## Use real Olist data

Download the Brazilian E-Commerce Public Dataset by Olist from its publisher:
https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce

Check its current license and attribution requirements. Do not mistake a
notebook's license for the underlying dataset's license. Data download is manual;
this code does not scrape Kaggle or require a Kaggle API key.

Create `data/raw/` and place these CSV files inside it:

- `olist_orders_dataset.csv`
- `olist_customers_dataset.csv`
- `olist_sellers_dataset.csv`
- `olist_order_items_dataset.csv`
- `olist_order_reviews_dataset.csv`

Then run:

```bash
python pipeline.py
python server.py
```

Real data and demo data use separate input folders. Rebuilding replaces the
reporting database only after validation succeeds. Refresh the browser after
rebuilding. Additional columns in the CSVs are ignored; required columns are
defined in `pipeline.py`. Historical Olist data cannot support claims about
current Amazon operations.

## Dashboard features

- Purchase-date and customer-state filters.
- Order counts, late-delivery rate, delivery time, merchandise value, and reviews.
- Monthly late rates with denominators in a detail table.
- Customer-state late rates and sample counts.
- Seller investigation queue with a configurable minimum delivery count.
- Review comparison with reviewed-order counts.
- CSV export for the filtered order cohort.
- Visible source, refresh timestamp, and excluded-delivery counts.
- Delay severity buckets with order shares, associated merchandise value,
  review coverage, and the percentage of reviewed orders with 1–2 star scores.
- Shipping-route investigation by seller state and customer state, with a
  configurable minimum delivery count shared with the seller queue.
- Month-to-month late-rate changes in percentage points in the monthly detail table.

## Data model and metric definitions

| Table | Grain | Purpose |
| --- | --- | --- |
| `raw_orders` | One order | Status and delivery dates |
| `raw_items` | One order item | Seller, item price, freight |
| `raw_customers` | One customer ID | Customer state |
| `raw_sellers` | One seller | Seller state |
| `raw_reviews` | Review record | Review score and creation date |
| `mart_orders` | One order | Stable denominator for order KPIs |
| `mart_seller_orders` | One seller per order | Seller-associated delivery outcomes |

The SQL aggregates items and ranks reviews **before** joining to orders. This
prevents item/review joins from multiplying order counts and merchandise values.

- **Eligible delivery:** delivered status; parseable purchase, delivery, and
  estimated dates; delivery and estimated timestamps at or after purchase.
- **Late rate:** orders delivered after the estimated calendar date / eligible
  delivered orders. Same-day delivery is on time even if the estimate is midnight.
- **Delivery days:** elapsed timestamp days from purchase to customer delivery.
- **Merchandise value:** sum of recorded item prices across all selected orders,
  including canceled orders. Not recognized revenue, profit, or collected payments.
- **Average review:** latest available review per order. Ties use descending
  review ID. Missing reviews do not contribute to the average.
- **Seller queue:** eligible orders associated with each seller, sorted by late
  count, then late rate. A multi-seller order appears once per seller. These
  counts are not additive across sellers and do not establish responsibility.

All charts use purchase cohorts. Reviews and eventual delivery outcomes are
historical outcomes, not an as-of-date snapshot. Minimum seller volume affects
the seller and shipping-route tables. Filtering a state can change which groups meet it.
Recent or incomplete cohorts can be biased toward already delivered orders.
Delivery/review relationships are observational, not causal.

### Expanded operations analysis

Severity buckets are on time, 1–3 days late, 4–7 days late, and 8+ days late.
They partition eligible deliveries and exclude invalid delivery dates. Their
merchandise values describe associated order value, not financial losses.
Low-review percentages divide 1–2 star reviews by reviewed orders in the bucket;
orders without reviews do not enter this denominator.

Shipping routes count distinct order/origin-state/destination-state pairs.
Two sellers in the same origin state on one order contribute one route delivery.
An order with sellers in different origin states contributes to each route,
so route counts cannot be added to recover total orders. Delivery timing is
order-level and does not identify which seller or carrier caused a delay.
The top 20 routes are ranked by late count, then late rate.

Monthly changes use SQL `LAG` and compare consecutive calendar months only.
A missing month or a cohort without eligible deliveries produces no comparison.
For example, moving from 10% to 15% is a +5 percentage-point change.
All new panels follow the purchase-date and customer-state filters.

## Validation and tests

```bash
python -m unittest discover -s tests -v
```

Validation fails for missing files/columns, invalid numbers, duplicate primary
keys, missing identities/states, orphan items/reviews, invalid purchase dates,
negative amounts, and invalid review scores. Delivered orders with missing or
illogical delivery/estimated dates are retained but excluded from delivery KPIs.
Order counts and item-price totals are reconciled after model creation.

Tests cover order grain, multiple reviews, multiple sellers, same-day deadlines,
missing delivery dates, invalid references, refresh preservation, API filtering,
empty cohorts, SQL analyses, and HTTP dashboard/export responses. Additional
fixtures verify severity boundaries, missing reviews, route deduplication,
route thresholds, and monthly comparisons across gaps or excluded cohorts.

## Repository guide

| File | Role |
| --- | --- |
| `pipeline.py` | CSV loading, demo generation, validation, database build |
| `sql/models.sql` | Reporting tables and review selection |
| `sql/analysis.sql` | Monthly growth, review comparison, seller investigation |
| `server.py` | Read-only reporting API and local HTTP server |
| `dashboard/index.html` | Responsive dashboard, charts, filters, export |
| `tests/test_project.py` | Business-rule and integration tests |
| `docs/analysis_memo.md` | Template for your own evidence-backed findings |

## Advanced SQL, statistics, and BI

- `sql/warehouse.sql`: explicit star-schema DDL, primary/foreign keys, CHECK
  constraints, and a customer-level statistical sample selected with ROW_NUMBER.
- `sql/advanced_analysis.sql`: recursive date spine, weighted rolling rates,
  LAG comparisons, DENSE_RANK seller ranking, cumulative Pareto shares, SQL
  Wilson intervals, and observed repeat-purchase cohorts.
- `research.py`: Welch's unequal-variance t-test with 95% CI and Cohen's d,
  Pearson chi-squared with expected-cell checks and Cramer's V, Mann-Whitney
  sensitivity test, Holm correction, and OLS with HC3 robust standard errors.
- Composite state/date indexes and `EXPLAIN QUERY PLAN` benchmarking compare
  identical query results before and after indexing on a disposable copy.
- Native [Excel report](reports/ecommerce_analysis.xlsx). It contains formula-driven monthly rates and a native line chart.
  Monthly source counts are a saved SQL export, not a live database connection.
- `reports/bi/`: order and item facts plus date/customer/seller dimensions for
  Excel, Power BI or Tableau import. See [BI model guide](docs/bi_model.md).
  Import files and model instructions are provided; this is not a claim that a
  Power BI or Tableau dashboard has been built or deployed.
- [Interview guide](docs/interview_guide.md) maps the implementation to the BIE
  job requirements and explains the analytical choices.
- `.github/workflows/tests.yml` defines automated fixture validation on pushes
  and pull requests. Local checks have been run; hosted CI has not run until
  the branch is pushed.

## Publish to GitHub

This project is cloned from `dtry19/ecommerce-delivery-analytics`. Changes are
local on `codex/operations-analytics-expansion`. Review before committing and
pushing; do not initialize another repository or replace the existing remote.

The `.gitignore` excludes generated databases, raw data, and demo CSVs. The demo
can be regenerated from code. GitHub Pages cannot run the Python server: use
screenshots in the README or a separately hosted application for a live demo.

## Source and interpretation

Olist publishes the dataset at
[its Kaggle data card](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce).
The publisher's metadata identifies version 2, updated October 1, 2021, under
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).
See [data provenance](docs/data_provenance.md) for hashes and exact row counts.
Preserve source attribution and the stated dataset terms when sharing derived
materials. This repository's pipeline does not publish the raw files.

The review gap is an observational association in historical Olist data.
It does not establish that lateness caused the entire difference or that a
proposed operational intervention improved business outcomes. The findings
memo records review selection, customer dependence, date exclusions, regression
assumptions and cohort censoring. Read it before using the resume entry.
