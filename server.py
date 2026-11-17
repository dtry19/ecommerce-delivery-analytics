"""Local dashboard and read-only API. Run: python server.py"""
import argparse
import csv
import io
import json
import sqlite3
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from pipeline import DB, ROOT

@contextmanager
def connect(db):
    con = sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()

def rows(con,query,params=()):
    return [dict(r) for r in con.execute(query,params).fetchall()]

def where_clause(filters):
    clauses,params=[],[]
    for key,expression in [('start','date(purchased_at)>=date(?)'),
        ('end','date(purchased_at)<=date(?)'),('state','customer_state=?')]:
        value=filters.get(key,[''])[0]
        if value:
            if key in ('start','end'):
                from datetime import date
                date.fromisoformat(value)
            clauses.append(expression)
            params.append(value)
    return (' WHERE '+' AND '.join(clauses) if clauses else ''),params

def get_data(db,filters):
    where,params=where_clause(filters)
    with connect(db) as con:
        # Filter purchase cohort consistently across charts and metrics.
        con.execute('CREATE TEMP TABLE filtered AS SELECT * FROM mart_orders'+where,params)
        summary=rows(con,"""SELECT COUNT(*) AS orders,SUM(merchandise_value) AS merchandise_value,
          SUM(freight_value) AS freight_value,SUM(delivery_eligible) AS eligible_deliveries,
          SUM(CASE WHEN delivery_eligible=1 AND delay_days>0 THEN 1 ELSE 0 END) AS late_deliveries,
          AVG(CASE WHEN delivery_eligible=1 THEN delivery_days END) AS average_delivery_days,
          AVG(review_score) AS average_review,COUNT(review_score) AS reviewed_orders,
          SUM(CASE WHEN order_status='canceled' THEN 1 ELSE 0 END) AS canceled_orders,
          SUM(CASE WHEN order_status='delivered' AND delivery_eligible=0 THEN 1 ELSE 0 END) AS excluded_deliveries
          FROM filtered""")[0]
        monthly=rows(con,"""WITH cohorts AS (SELECT purchase_month,COUNT(*) AS orders,
          SUM(delivery_eligible) AS eligible_deliveries,
          SUM(CASE WHEN delivery_eligible=1 AND delay_days>0 THEN 1 ELSE 0 END) AS late_deliveries,
          SUM(merchandise_value) AS merchandise_value FROM filtered GROUP BY purchase_month)
          SELECT *,100.0*late_deliveries/NULLIF(eligible_deliveries,0) AS late_rate_pct,
          CASE WHEN date(purchase_month||'-01','-1 month') =
            LAG(purchase_month) OVER (ORDER BY purchase_month)||'-01'
          THEN 100.0*late_deliveries/NULLIF(eligible_deliveries,0) -
            LAG(100.0*late_deliveries/NULLIF(eligible_deliveries,0)) OVER (ORDER BY purchase_month)
          END AS late_rate_change_pp
          FROM cohorts ORDER BY purchase_month""")
        states=rows(con,"""SELECT customer_state,COUNT(*) AS orders,SUM(delivery_eligible) AS eligible_deliveries,
          SUM(CASE WHEN delivery_eligible=1 AND delay_days>0 THEN 1 ELSE 0 END) AS late_deliveries
          FROM filtered GROUP BY customer_state ORDER BY late_deliveries DESC""")
        reviews=rows(con,"""SELECT CASE WHEN delay_days>0 THEN 'Late' ELSE 'On time' END AS delivery_group,
          COUNT(*) AS eligible_deliveries,COUNT(review_score) AS reviewed_orders,AVG(review_score) AS average_review
          FROM filtered WHERE delivery_eligible=1 GROUP BY delivery_group ORDER BY delivery_group""")
        minimum=int(filters.get('minimum',['30'])[0])
        if not 1<=minimum<=100000:
            raise ValueError('Minimum must be between 1 and 100000')
        sellers=rows(con,"""SELECT s.seller_id,s.seller_state,COUNT(*) AS eligible_orders,
          SUM(CASE WHEN s.delay_days>0 THEN 1 ELSE 0 END) AS late_orders,
          AVG(s.delivery_days) AS average_delivery_days,
          100.0*SUM(CASE WHEN s.delay_days>0 THEN 1 ELSE 0 END)/COUNT(*) AS late_rate_pct
          FROM mart_seller_orders s JOIN filtered f USING(order_id) WHERE s.delivery_eligible=1
          GROUP BY s.seller_id,s.seller_state HAVING COUNT(*)>=?
          ORDER BY late_orders DESC,late_rate_pct DESC,s.seller_id LIMIT 20""",[minimum])
        severity=rows(con,"""WITH classified AS (
          SELECT *,CASE WHEN delay_days<=0 THEN 0 WHEN delay_days<=3 THEN 1
            WHEN delay_days<=7 THEN 2 ELSE 3 END AS severity_rank
          FROM filtered WHERE delivery_eligible=1
        ), buckets(severity_rank,delivery_group) AS (
          VALUES (0,'On time'),(1,'1–3 days late'),(2,'4–7 days late'),(3,'8+ days late')
        ) SELECT b.delivery_group,COUNT(c.order_id) AS eligible_deliveries,
          COALESCE(SUM(c.merchandise_value),0) AS merchandise_value,
          COUNT(c.review_score) AS reviewed_orders,AVG(c.review_score) AS average_review,
          SUM(CASE WHEN c.review_score<=2 THEN 1 ELSE 0 END) AS low_reviews
        FROM buckets b LEFT JOIN classified c USING(severity_rank)
        GROUP BY b.severity_rank,b.delivery_group ORDER BY b.severity_rank""")
        # Deduplicate route/order pairs before aggregation: multiple sellers in
        # the same origin state must never inflate the route denominator.
        routes=rows(con,"""WITH route_orders AS (
          SELECT DISTINCT s.order_id,s.seller_state,f.customer_state,
            f.delay_days,f.delivery_days
          FROM mart_seller_orders s JOIN filtered f USING(order_id)
          WHERE f.delivery_eligible=1
        ) SELECT seller_state,customer_state,COUNT(*) AS eligible_orders,
          SUM(CASE WHEN delay_days>0 THEN 1 ELSE 0 END) AS late_orders,
          100.0*SUM(CASE WHEN delay_days>0 THEN 1 ELSE 0 END)/COUNT(*) AS late_rate_pct,
          AVG(CASE WHEN delay_days>0 THEN delay_days END) AS average_late_days
        FROM route_orders GROUP BY seller_state,customer_state
        HAVING COUNT(*)>=? ORDER BY late_orders DESC,late_rate_pct DESC,
          seller_state,customer_state LIMIT 20""",[minimum])
        return {'summary':summary,'monthly':monthly,'states':states,'reviews':reviews,
                'sellers':sellers,'severity':severity,'routes':routes}

def metadata(db):
    with connect(db) as con:
        info=json.loads(con.execute('SELECT payload FROM metadata').fetchone()[0])
        info.update(rows(con,'SELECT MIN(date(purchased_at)) AS start,MAX(date(purchased_at)) AS end FROM mart_orders')[0])
        info['states']=[r[0] for r in con.execute('SELECT DISTINCT customer_state FROM mart_orders ORDER BY customer_state')]
        return info

def research_results(db,report=None):
    report=report or ROOT/'reports/results.json'
    if not report.exists():
        raise ValueError('Research report missing. Run: python research.py')
    result=json.loads(report.read_text())
    if result['source']['built_at_utc']!=metadata(db)['built_at_utc']:
        raise ValueError('Research report is stale. Run: python research.py')
    return result

def make_handler(db):
    class Handler(BaseHTTPRequestHandler):
        def send(self,content,mime='application/json',status=200):
            self.send_response(status)
            self.send_header('Content-Type',mime+'; charset=utf-8')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            parsed=urlparse(self.path)
            try:
                if parsed.path in ('/','/index.html'):
                    return self.send((ROOT/'dashboard/index.html').read_bytes(),'text/html')
                if parsed.path=='/api/meta':
                    return self.send(json.dumps(metadata(db)).encode())
                if parsed.path=='/api/data':
                    return self.send(json.dumps(get_data(db,parse_qs(parsed.query))).encode())
                if parsed.path=='/api/research':
                    return self.send(json.dumps(research_results(db)).encode())
                if parsed.path=='/api/export':
                    where,params=where_clause(parse_qs(parsed.query))
                    with connect(db) as con:
                        records=rows(con,'SELECT * FROM mart_orders'+where+' ORDER BY purchased_at',params)
                        cols=[r[1] for r in con.execute('PRAGMA table_info(mart_orders)')]
                    output=io.StringIO(newline='')
                    writer=csv.DictWriter(output,fieldnames=cols)
                    writer.writeheader()
                    writer.writerows(records)
                    return self.send(output.getvalue().encode(),'text/csv')
                self.send(b'{"error":"Not found"}',status=404)
            except (ValueError,sqlite3.Error) as error:
                self.send(json.dumps({'error':str(error)}).encode(),status=400)
    return Handler

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=__import__('pathlib').Path,default=DB)
    parser.add_argument('--port',type=int,default=8000)
    args=parser.parse_args()
    if not args.db.exists():
        parser.error('Database missing. First run: python pipeline.py --demo')
    server=ThreadingHTTPServer(('127.0.0.1',args.port),make_handler(args.db))
    print(f'Open http://localhost:{args.port} (Ctrl+C to stop)',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
