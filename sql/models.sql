-- Order grain: aggregate items and select one review BEFORE joining.
DROP TABLE IF EXISTS mart_orders;
CREATE TABLE mart_orders AS
WITH item_totals AS (
 SELECT order_id, COUNT(*) AS item_count, COUNT(DISTINCT seller_id) AS seller_count,
        SUM(price) AS merchandise_value, SUM(freight_value) AS freight_value
 FROM raw_items GROUP BY order_id
), ranked_reviews AS (
 SELECT *, ROW_NUMBER() OVER (
   PARTITION BY order_id ORDER BY review_creation_date DESC, review_id DESC
 ) AS review_rank FROM raw_reviews
)
SELECT o.order_id, o.customer_id, c.customer_unique_id, c.customer_state,
       o.order_status, o.order_purchase_timestamp AS purchased_at,
       o.order_delivered_customer_date AS delivered_at,
       o.order_estimated_delivery_date AS estimated_at,
       SUBSTR(o.order_purchase_timestamp,1,7) AS purchase_month,
       COALESCE(i.item_count,0) AS item_count,
       COALESCE(i.seller_count,0) AS seller_count,
       COALESCE(i.merchandise_value,0) AS merchandise_value,
       COALESCE(i.freight_value,0) AS freight_value,
       r.review_score,
       CASE WHEN o.order_status='delivered'
         AND julianday(o.order_delivered_customer_date) IS NOT NULL
         AND julianday(o.order_estimated_delivery_date) IS NOT NULL
         AND julianday(o.order_purchase_timestamp) IS NOT NULL
         AND julianday(o.order_delivered_customer_date)>=julianday(o.order_purchase_timestamp)
         AND julianday(o.order_estimated_delivery_date)>=julianday(o.order_purchase_timestamp)
       THEN 1 ELSE 0 END AS delivery_eligible,
       julianday(o.order_delivered_customer_date)-julianday(o.order_purchase_timestamp) AS delivery_days,
       julianday(date(o.order_delivered_customer_date))-julianday(date(o.order_estimated_delivery_date)) AS delay_days
FROM raw_orders o
LEFT JOIN raw_customers c ON o.customer_id=c.customer_id
LEFT JOIN item_totals i ON o.order_id=i.order_id
LEFT JOIN ranked_reviews r ON o.order_id=r.order_id AND r.review_rank=1;

-- Seller-order grain: each seller appears once per order regardless of item count.
DROP TABLE IF EXISTS mart_seller_orders;
CREATE TABLE mart_seller_orders AS
WITH seller_items AS (
 SELECT order_id,seller_id,COUNT(*) AS item_count,
        SUM(price) AS merchandise_value,SUM(freight_value) AS freight_value
 FROM raw_items GROUP BY order_id,seller_id
)
SELECT i.*,s.seller_state,m.customer_state,m.purchase_month,m.purchased_at,
       m.delivery_eligible,m.delivery_days,m.delay_days,m.review_score
FROM seller_items i
JOIN mart_orders m USING(order_id)
JOIN raw_sellers s USING(seller_id);
CREATE UNIQUE INDEX idx_mart_order ON mart_orders(order_id);
CREATE UNIQUE INDEX idx_mart_seller_order ON mart_seller_orders(order_id,seller_id);
CREATE INDEX idx_orders_state_purchase ON mart_orders(customer_state,purchased_at);
CREATE INDEX idx_orders_purchase ON mart_orders(purchased_at);
CREATE INDEX idx_seller_orders_seller ON mart_seller_orders(seller_id,order_id);
