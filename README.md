# E-commerce Delivery Performance Dashboard

A reproducible Python + SQLite analytics project with a browser dashboard.
Investigate late deliveries by purchase month, customer state, and seller;
compare customer reviews for late and on-time deliveries.

**Status:** working portfolio starter. The included generator produces synthetic
data, not empirical findings. Replace it with sourced data and write your own
analysis before describing this as a completed business study.

## Run locally

Requires Python 3.10+ with SQLite support. No pip installs, credentials, or paid
services are needed. Windows users can substitute `py` for `python`.

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
only the seller table. Filtering a state can change which sellers meet it.
Recent or incomplete cohorts can be biased toward already delivered orders.
Delivery/review relationships are observational, not causal.

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
empty cohorts, SQL analyses, and HTTP dashboard/export responses.

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

## Publish to GitHub

Create an empty GitHub repository named `delivery-performance-dashboard`, then
run these commands from this project folder. Replace the placeholder URL with
your actual repository URL before the final commands.

```bash
git init
git add .
git commit -m "Build delivery performance pipeline and dashboard"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/delivery-performance-dashboard.git
git push -u origin main
```

The `.gitignore` excludes generated databases, raw data, and demo CSVs. The demo
can be regenerated from code. GitHub Pages cannot run the Python server: use
screenshots in the README or a separately hosted application for a live demo.

## Make this your portfolio work

1. Run it on sourced data, document the source and access date, and inspect warnings.
2. Add dashboard screenshots to `docs/` and embed them in this README.
3. Complete `docs/analysis_memo.md` with measured results and limitations.
4. Add an original question, such as whether late rates persist across months.
5. Be able to explain the join grain, denominators, review selection, and checks.

Suggested truthful resume structure after completing your analysis:
"Built a Python/SQL delivery analytics pipeline for [actual N] orders, validated
order-level counts and merchandise totals, and developed an interactive dashboard
to identify [measured finding]." Do not claim reduced delays or improved business
outcomes unless the recommendations were implemented and evaluated.
