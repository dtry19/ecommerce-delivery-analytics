from contextlib import closing
import csv
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from pipeline import build, make_demo, TABLES, ROOT
from server import get_data, make_handler

class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.directory=Path(self.temp.name)/'input'
        self.db=Path(self.temp.name)/'delivery.db'
        make_demo(self.directory,100)
        build(self.directory,self.db)

    def tearDown(self):
        self.temp.cleanup()

    def read(self,name):
        with (self.directory/TABLES[name][0]).open(newline='') as f:
            return list(csv.DictReader(f))

    def write(self,name,records):
        with (self.directory/TABLES[name][0]).open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=records[0].keys())
            writer.writeheader();writer.writerows(records)

    def test_grain_and_value_reconciliation(self):
        with closing(sqlite3.connect(self.db)) as c, c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM mart_orders').fetchone()[0],100)
            a=c.execute('SELECT SUM(price) FROM raw_items').fetchone()[0]
            b=c.execute('SELECT SUM(merchandise_value) FROM mart_orders').fetchone()[0]
            self.assertAlmostEqual(a,b)

    def test_latest_review_does_not_multiply_orders(self):
        records=self.read('reviews');existing=records[0]
        records.append({**existing,'review_id':'zz_new','review_score':'1','review_creation_date':'2030-01-01 00:00:00'})
        self.write('reviews',records);build(self.directory,self.db)
        with closing(sqlite3.connect(self.db)) as c, c:
            self.assertEqual(c.execute('SELECT review_score FROM mart_orders WHERE order_id=?',(existing['order_id'],)).fetchone()[0],1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM mart_orders').fetchone()[0],100)

    def test_same_calendar_date_on_time_and_missing_date_excluded(self):
        records=self.read('orders')
        records[0].update(order_status='delivered',order_purchase_timestamp='2024-01-01 10:00:00',
          order_estimated_delivery_date='2024-01-10 00:00:00',order_delivered_customer_date='2024-01-10 20:00:00')
        records[1].update(order_status='delivered',order_delivered_customer_date='')
        self.write('orders',records);info=build(self.directory,self.db)
        with closing(sqlite3.connect(self.db)) as c, c:
            self.assertEqual(c.execute('SELECT delay_days FROM mart_orders WHERE order_id=?',(records[0]['order_id'],)).fetchone()[0],0)
            self.assertEqual(c.execute('SELECT delivery_eligible FROM mart_orders WHERE order_id=?',(records[1]['order_id'],)).fetchone()[0],0)
        self.assertGreaterEqual(info['ineligible_delivered_orders'],1)

    def test_multi_seller_order_count_once_per_seller(self):
        records=self.read('items');oid=records[0]['order_id']
        first=records[0]['seller_id'];other=next(s['seller_id'] for s in self.read('sellers') if s['seller_id']!=first)
        itemid=max(int(r['order_item_id']) for r in records if r['order_id']==oid)
        records.extend([{**records[0],'order_item_id':str(itemid+1),'seller_id':other},
                        {**records[0],'order_item_id':str(itemid+2),'seller_id':other}])
        self.write('items',records);build(self.directory,self.db)
        with closing(sqlite3.connect(self.db)) as c, c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM mart_seller_orders WHERE order_id=? AND seller_id=?',(oid,other)).fetchone()[0],1)

    def test_invalid_reference_preserves_prior_database(self):
        prior=self.db.read_bytes();records=self.read('items');records[0]['seller_id']='unknown'
        self.write('items',records)
        with self.assertRaises(ValueError):build(self.directory,self.db)
        self.assertEqual(self.db.read_bytes(),prior)

    def test_filters_empty_cohort_and_sql(self):
        data=get_data(self.db,{'state':['SP'],'minimum':['1']})
        with closing(sqlite3.connect(self.db)) as c, c:
            count=c.execute("SELECT COUNT(*) FROM mart_orders WHERE customer_state='SP'").fetchone()[0]
            c.executescript((ROOT/'sql/analysis.sql').read_text())
        self.assertEqual(data['summary']['orders'],count)
        self.assertTrue(all(s['customer_state']=='SP' for s in data['states']))
        empty=get_data(self.db,{'start':['2035-01-01']})
        self.assertEqual(empty['summary']['orders'],0)
        self.assertEqual(empty['monthly'],[])
        with self.assertRaises(ValueError):get_data(self.db,{'minimum':['0']})

    def test_http_dashboard_metadata_and_export(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.db))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base+'/') as response:self.assertIn(b'Monthly late-delivery rate',response.read())
            with urlopen(base+'/api/meta') as response:self.assertEqual(json.load(response)['source'],'SYNTHETIC DEMO')
            with urlopen(base+'/api/data?state=SP') as response:self.assertGreater(json.load(response)['summary']['orders'],0)
            with urlopen(base+'/api/export?state=SP') as response:
                records=list(csv.DictReader(response.read().decode().splitlines()))
                self.assertTrue(records);self.assertTrue(all(r['customer_state']=='SP' for r in records))
        finally:
            server.shutdown();server.server_close();thread.join()

    def analytics_fixture(self):
        # Deliberate boundaries, missing reviews, excluded dates, and a gap
        # in calendar months make metric semantics independently checkable.
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute('DELETE FROM mart_seller_orders')
            c.execute('DELETE FROM mart_orders')
            for i,(month,delay,review,eligible,state) in enumerate([
                ('01',0,5,1,'SP'),('01',1,1,1,'SP'),
                ('02',3,None,1,'SP'),('02',4,2,1,'SP'),
                ('02',7,4,1,'SP'),('02',8,None,1,'SP'),
                ('02',99,1,0,'SP'),('04',0,5,1,'RJ')]):
                c.execute('''INSERT INTO mart_orders
                    (order_id,purchased_at,purchase_month,customer_state,delivery_eligible,
                     delay_days,delivery_days,merchandise_value,review_score,order_status)
                    VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (str(i),f'2024-{month}-01',f'2024-{month}',state,eligible,
                     delay,10+delay,100,review,'delivered'))
                # Two sellers from SP in the same order are ONE route/order.
                for seller,origin in [('a','SP'),('b','SP'),('c','MG')]:
                    c.execute('''INSERT INTO mart_seller_orders
                        (order_id,seller_id,seller_state,customer_state,delivery_eligible,
                         delay_days,delivery_days) VALUES (?,?,?,?,?,?,?)''',
                        (str(i),seller,origin,state,eligible,delay,10+delay))

    def test_severity_boundaries_reviews_and_value(self):
        self.analytics_fixture()
        data=get_data(self.db,{'minimum':['1']})
        buckets=data['severity']
        self.assertEqual([r['eligible_deliveries'] for r in buckets],[2,2,2,1])
        self.assertEqual(sum(r['eligible_deliveries'] for r in buckets),data['summary']['eligible_deliveries'])
        self.assertEqual([r['merchandise_value'] for r in buckets],[200,200,200,100])
        self.assertEqual(buckets[1]['reviewed_orders'],1)
        self.assertEqual(buckets[1]['low_reviews'],1)
        self.assertEqual(buckets[2]['average_review'],3)
        self.assertIsNone(buckets[3]['average_review'])
        empty=get_data(self.db,{'state':['XX']})
        self.assertEqual(empty['routes'],[])
        self.assertTrue(all(r['eligible_deliveries']==0 for r in empty['severity']))

    def test_routes_deduplicate_and_respect_filters_and_threshold(self):
        self.analytics_fixture()
        data=get_data(self.db,{'state':['SP'],'minimum':['6']})
        self.assertEqual(len(data['routes']),2)
        for route in data['routes']:
            self.assertEqual(route['eligible_orders'],6)
            self.assertEqual(route['late_orders'],5)
            self.assertAlmostEqual(route['average_late_days'],4.6)
            self.assertEqual(route['customer_state'],'SP')
        self.assertEqual(get_data(self.db,{'state':['SP'],'minimum':['7']})['routes'],[])
        dated=get_data(self.db,{'start':['2024-02-01'],'end':['2024-02-29'],'minimum':['1']})
        self.assertTrue(all(r['eligible_orders']==4 for r in dated['routes']))
        self.assertEqual(sum(r['eligible_deliveries'] for r in dated['severity']),4)

    def test_monthly_changes_require_consecutive_valid_cohorts(self):
        self.analytics_fixture()
        monthly=get_data(self.db,{})['monthly']
        self.assertEqual([r['late_rate_pct'] for r in monthly],[50,100,0])
        self.assertIsNone(monthly[0]['late_rate_change_pp'])
        self.assertEqual(monthly[1]['late_rate_change_pp'],50)
        self.assertIsNone(monthly[2]['late_rate_change_pp'])
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("UPDATE mart_orders SET delivery_eligible=0 WHERE purchase_month='2024-01'")
        monthly=get_data(self.db,{})['monthly']
        self.assertIsNone(monthly[0]['late_rate_pct'])
        self.assertIsNone(monthly[1]['late_rate_change_pp'])

if __name__=='__main__':unittest.main()
