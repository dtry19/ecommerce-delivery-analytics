# BI model and refresh

`python research.py` exports five tables to `reports/bi/` as CSV. These are
local, complete facts and dimensions rather than a sample.

| Table | Grain | Key |
| --- | --- | --- |
| dim_date | Observed purchase date | date_key |
| dim_customer | Order-associated customer ID | customer_id |
| dim_seller | Seller | seller_id |
| fact_orders | Order | order_id |
| fact_order_items | Item within order | order_id + order_item_id |

The customer dimension also carries customer_unique_id: Olist customer_id is
order-associated and is not a stable person identifier. Statistical samples
and repeat-purchase queries use customer_unique_id.

## Import into Excel, Power BI or Tableau

Import the CSVs as UTF-8. Keep IDs and date_key as text initially; set dates to
date type consistently on both sides of a relationship. Numeric columns must
be numeric. Establish these one-to-many relationships:

- dim_date.date_key to fact_orders.purchase_date_key
- dim_customer.customer_id to fact_orders.customer_id
- fact_orders.order_id to fact_order_items.order_id
- dim_seller.seller_id to fact_order_items.seller_id

Use single-direction dimension-to-fact filtering. Order KPIs come from
fact_orders; item/seller value comes from fact_order_items. A seller slice does
not automatically filter orders backward in this model. For seller delivery
KPIs use the deduplicated seller-order export/query; do not turn on ambiguous
bidirectional filtering or sum item-joined order values.

Suggested measures are count of fact_orders, sum of delivery_eligible, count
of eligible orders where delay_days > 0, and late count / eligible count.
Reviews average non-null review_score. Date slicing is purchase date.

## Excel deliverable

The local workbook at `reports/ecommerce_analysis.xlsx` has an
Overview sheet with coverage and statistical estimates and a Monthly sheet
with SQL-exported counts, Excel rate/rolling formulas, and a native line chart.
It is a saved analysis, not a live database connection or PivotTable.
Source counts can be refreshed from `reports/monthly_trends.csv`; keep the
row alignment and extend formulas/chart ranges when adding months. Rerun the
research script to refresh statistical estimates, which are imported results
and are not recalculated by editing monthly counts in Excel.

The SQL/Python study and CSV exports reproduce with the public project
dependencies. The workbook was authored using the Codex spreadsheet runtime;
its formula logic is visible in Excel and the source counts are public-script
outputs. Power BI and Tableau import instructions have not been validated in
those applications, and no PBIX/TWB deployment is claimed.
