-- Monthly performance; rate uses eligible deliveries, NOT all orders.
WITH monthly AS (
 SELECT purchase_month,COUNT(*) AS orders,
   SUM(delivery_eligible) AS eligible_deliveries,
   SUM(CASE WHEN delivery_eligible=1 AND delay_days>0 THEN 1 ELSE 0 END) AS late_deliveries,
   SUM(merchandise_value) AS merchandise_value
 FROM mart_orders GROUP BY purchase_month
)
SELECT *, ROUND(100.0*late_deliveries/NULLIF(eligible_deliveries,0),2) AS late_rate_pct,
 ROUND(100.0*(merchandise_value/LAG(merchandise_value) OVER(ORDER BY purchase_month)-1),2)
 AS merchandise_value_mom_pct
FROM monthly ORDER BY purchase_month;

-- Association only: delivery timing does not establish causation.
SELECT CASE WHEN delay_days>0 THEN 'Late' ELSE 'On time' END AS delivery_group,
 COUNT(*) AS eligible_deliveries, COUNT(review_score) AS reviewed_orders,
 ROUND(AVG(review_score),2) AS average_review
FROM mart_orders WHERE delivery_eligible=1 GROUP BY delivery_group;

-- Prioritize investigation by late ORDER count, with a minimum sample.
SELECT seller_id,seller_state,COUNT(*) AS eligible_orders,
 SUM(CASE WHEN delay_days>0 THEN 1 ELSE 0 END) AS late_orders,
 ROUND(100.0*SUM(CASE WHEN delay_days>0 THEN 1 ELSE 0 END)/COUNT(*),2) AS late_rate_pct
FROM mart_seller_orders WHERE delivery_eligible=1
GROUP BY seller_id,seller_state HAVING COUNT(*)>=30
ORDER BY late_orders DESC,late_rate_pct DESC;
