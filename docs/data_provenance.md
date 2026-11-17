# Data provenance

Publisher: **Olist**. Dataset: [Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce).

Version 2. Retrieved UTC: 2026-11-17T02:07:12.633042+00:00.
Publisher metadata lists **CC BY-NC-SA 4.0** ([license](https://creativecommons.org/licenses/by-nc-sa/4.0/)).

Verified archive SHA-256: `967e41e04fc306fe604e2a693f488995a8b41e5047418f8a5c8e4abd6deca784`.

| Original file | Logical CSV rows | Loaded by pipeline |
| --- | ---: | --- |
| olist_customers_dataset.csv | 99,441 | Yes |
| olist_geolocation_dataset.csv | 1,000,163 | No; auxiliary download |
| olist_order_items_dataset.csv | 112,650 | Yes |
| olist_order_payments_dataset.csv | 103,886 | No; auxiliary download |
| olist_order_reviews_dataset.csv | 99,224 | Yes |
| olist_orders_dataset.csv | 99,441 | Yes |
| olist_products_dataset.csv | 32,951 | No; auxiliary download |
| olist_sellers_dataset.csv | 3,095 | Yes |
| product_category_name_translation.csv | 71 | No; auxiliary download |

Loaded total: **413,851 source rows**, including **112,650 order items** and
**99,441 distinct orders**. Counts exclude headers and use a CSV parser so
embedded newlines in review text do not inflate the result. Auxiliary tables
are retained locally, but geolocation, payment and product rows are not claimed
as observations analyzed by this delivery model.

Original data are kept unchanged. Transformations: required-column selection,
numeric conversion, reference validation, item aggregation, latest-review
selection, date eligibility rules, and fact/dimension creation. Source hashes
are validated before publication of the reporting database.

[Machine-readable source manifest](source_manifest.json) records all file
hashes. Raw files/database are ignored by Git; rerun `download_data.py` to
retrieve them. The archive hash protects reproducibility even if the endpoint
changes. Source terms are separate from any future license for the code.
