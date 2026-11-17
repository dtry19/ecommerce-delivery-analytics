-- Explicit DDL with declared grains and referential integrity. Reporting marts
-- retain descriptive columns for convenient API use; facts have dimension keys.
CREATE TABLE dim_date (
 date_key TEXT PRIMARY KEY, calendar_year INTEGER NOT NULL,
 calendar_month INTEGER NOT NULL CHECK(calendar_month BETWEEN 1 AND 12),
 purchase_month TEXT NOT NULL
);
INSERT INTO dim_date
SELECT DISTINCT date(purchased_at),CAST(strftime('%Y',purchased_at) AS INTEGER),
 CAST(strftime('%m',purchased_at) AS INTEGER),purchase_month FROM mart_orders;

CREATE TABLE dim_customer (
 customer_id TEXT PRIMARY KEY, customer_unique_id TEXT NOT NULL,
 customer_state TEXT NOT NULL
);
INSERT INTO dim_customer SELECT customer_id,customer_unique_id,customer_state FROM raw_customers;
CREATE INDEX idx_customer_unique ON dim_customer(customer_unique_id);

CREATE TABLE dim_seller (seller_id TEXT PRIMARY KEY,seller_state TEXT NOT NULL);
INSERT INTO dim_seller SELECT seller_id,seller_state FROM raw_sellers;

CREATE TABLE fact_orders (
 order_id TEXT PRIMARY KEY,
 customer_id TEXT NOT NULL REFERENCES dim_customer(customer_id),
 purchase_date_key TEXT NOT NULL REFERENCES dim_date(date_key),
 order_status TEXT NOT NULL, delivery_eligible INTEGER NOT NULL CHECK(delivery_eligible IN (0,1)),
 delay_days REAL,delivery_days REAL,review_score INTEGER CHECK(review_score BETWEEN 1 AND 5),
 merchandise_value REAL NOT NULL CHECK(merchandise_value>=0),
 freight_value REAL NOT NULL CHECK(freight_value>=0),
 item_count INTEGER NOT NULL,seller_count INTEGER NOT NULL
);
INSERT INTO fact_orders SELECT order_id,customer_id,date(purchased_at),order_status,
 delivery_eligible,delay_days,delivery_days,review_score,merchandise_value,
 freight_value,item_count,seller_count FROM mart_orders;

CREATE TABLE fact_order_items (
 order_id TEXT NOT NULL REFERENCES fact_orders(order_id),order_item_id INTEGER NOT NULL,
 seller_id TEXT NOT NULL REFERENCES dim_seller(seller_id),
 price REAL NOT NULL CHECK(price>=0),freight_value REAL NOT NULL CHECK(freight_value>=0),
 PRIMARY KEY(order_id,order_item_id)
);
INSERT INTO fact_order_items SELECT order_id,order_item_id,seller_id,price,freight_value FROM raw_items;
CREATE INDEX idx_fact_items_seller ON fact_order_items(seller_id,order_id);

-- First eligible reviewed order per stable customer. Selection uses timestamp
-- then order_id, never the size/direction of the observed outcome.
CREATE VIEW analysis_customer_sample AS
WITH ranked AS (
 SELECT m.*,CASE WHEN delay_days>0 THEN 1 ELSE 0 END AS is_late,
  CASE WHEN review_score<=2 THEN 1 ELSE 0 END AS low_review,
  julianday(estimated_at)-julianday(purchased_at) AS promised_days,
  ROW_NUMBER() OVER (PARTITION BY customer_unique_id ORDER BY purchased_at,order_id) AS customer_rank
 FROM mart_orders m WHERE delivery_eligible=1 AND review_score IS NOT NULL
)
SELECT * FROM ranked WHERE customer_rank=1;
