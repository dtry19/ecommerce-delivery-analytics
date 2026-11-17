-- name: monthly_trends
-- Dense calendar prevents ROWS windows from treating missing months as adjacent
-- observations. The 3-month rate divides rolling counts, not mean percentages.
WITH RECURSIVE calendar(month) AS (
 SELECT date(MIN(purchased_at),'start of month') FROM mart_orders
 UNION ALL SELECT date(month,'+1 month') FROM calendar
 WHERE month<(SELECT date(MAX(purchased_at),'start of month') FROM mart_orders)
), monthly AS (
 SELECT purchase_month,COUNT(*) AS orders,SUM(delivery_eligible) AS eligible,
  SUM(CASE WHEN delivery_eligible=1 AND delay_days>0 THEN 1 ELSE 0 END) AS late
 FROM mart_orders GROUP BY purchase_month
), dense AS (
 SELECT substr(c.month,1,7) AS purchase_month,COALESCE(m.orders,0) AS orders,
  COALESCE(m.eligible,0) AS eligible_deliveries,COALESCE(m.late,0) AS late_deliveries
 FROM calendar c LEFT JOIN monthly m ON m.purchase_month=substr(c.month,1,7)
), rates AS (
 SELECT *,100.0*late_deliveries/NULLIF(eligible_deliveries,0) AS late_rate_pct,
  SUM(late_deliveries) OVER w AS rolling_late,
  SUM(eligible_deliveries) OVER w AS rolling_eligible,
  ROW_NUMBER() OVER (ORDER BY purchase_month) AS month_number
 FROM dense WINDOW w AS (ORDER BY purchase_month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)
)
SELECT *,late_rate_pct-LAG(late_rate_pct) OVER (ORDER BY purchase_month) AS change_pp,
 CASE WHEN month_number>=3 THEN 100.0*rolling_late/NULLIF(rolling_eligible,0) END AS rolling_3m_late_rate_pct
FROM rates ORDER BY purchase_month;

-- name: seller_pareto
-- Cumulative share uses seller-associated late orders (non-additive to order
-- totals); this denominator is explicit rather than incorrectly global orders.
WITH sellers AS (
 SELECT seller_id,seller_state,COUNT(*) AS eligible_orders,
  SUM(CASE WHEN delay_days>0 THEN 1 ELSE 0 END) AS late_orders
 FROM mart_seller_orders WHERE delivery_eligible=1 GROUP BY seller_id,seller_state
), ranked AS (
 SELECT *,DENSE_RANK() OVER (ORDER BY late_orders DESC) AS late_count_rank,
  100.0*late_orders/NULLIF(eligible_orders,0) AS late_rate_pct,
  100.0*SUM(late_orders) OVER (ORDER BY late_orders DESC,seller_id ROWS UNBOUNDED PRECEDING)
   /NULLIF(SUM(late_orders) OVER (),0) AS cumulative_late_association_pct
 FROM sellers
)
SELECT * FROM ranked ORDER BY late_orders DESC,seller_id;

-- name: route_intervals
-- Wilson 95% binomial intervals expose uncertainty in small route samples.
WITH pairs AS (
 SELECT DISTINCT order_id,seller_state,customer_state,delay_days
 FROM mart_seller_orders WHERE delivery_eligible=1
), totals AS (
 SELECT seller_state,customer_state,COUNT(*) AS n,
  SUM(CASE WHEN delay_days>0 THEN 1 ELSE 0 END) AS late FROM pairs
 GROUP BY seller_state,customer_state
), rates AS (SELECT *,1.0*late/n AS p FROM totals)
SELECT seller_state,customer_state,n AS eligible_orders,late AS late_orders,100*p AS late_rate_pct,
 100*(p+1.96*1.96/(2*n)-1.96*sqrt(p*(1-p)/n+1.96*1.96/(4*n*n)))/(1+1.96*1.96/n) AS wilson_low_pct,
 100*(p+1.96*1.96/(2*n)+1.96*sqrt(p*(1-p)/n+1.96*1.96/(4*n*n)))/(1+1.96*1.96/n) AS wilson_high_pct
FROM rates ORDER BY late DESC,seller_state,customer_state;

-- name: repeat_purchase_cohorts
-- Observed repeat purchase, NOT subscription retention. Incomplete later
-- follow-up periods are omitted; even complete calendar months may be censored
-- at the dataset boundary and are not a customer-lifetime measure.
WITH purchases AS (
 SELECT DISTINCT customer_unique_id,purchase_month FROM mart_orders
), firsts AS (
 SELECT customer_unique_id,MIN(purchase_month) AS cohort FROM purchases GROUP BY customer_unique_id
), activity AS (
 SELECT f.cohort,p.purchase_month,COUNT(*) AS active_customers
 FROM firsts f JOIN purchases p USING(customer_unique_id) GROUP BY f.cohort,p.purchase_month
), sizes AS (SELECT cohort,COUNT(*) AS cohort_customers FROM firsts GROUP BY cohort)
SELECT a.*,s.cohort_customers,
 (CAST(substr(a.purchase_month,1,4) AS INTEGER)-CAST(substr(a.cohort,1,4) AS INTEGER))*12
  +CAST(substr(a.purchase_month,6,2) AS INTEGER)-CAST(substr(a.cohort,6,2) AS INTEGER) AS months_since_first,
 100.0*a.active_customers/s.cohort_customers AS observed_purchase_pct
FROM activity a JOIN sizes s USING(cohort)
WHERE date(a.purchase_month||'-01','+1 month') <= (SELECT MAX(date(purchased_at)) FROM mart_orders)
ORDER BY a.cohort,a.purchase_month;
