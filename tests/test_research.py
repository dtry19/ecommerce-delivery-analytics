from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from pipeline import build,make_demo,TABLES
from download_data import acquire
from research import advanced_queries,statistical_tests
from server import research_results


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.directory=Path(self.temp.name)/'raw'
        self.db=Path(self.temp.name)/'report.db'
        make_demo(self.directory,150)
        self.info=build(self.directory,self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_star_schema_keys_grains_and_reconciliation(self):
        with closing(sqlite3.connect(self.db)) as con, con:
            self.assertEqual(con.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(con.execute('SELECT COUNT(*) FROM fact_orders').fetchone()[0],150)
            raw=con.execute('SELECT COUNT(*),SUM(price) FROM raw_items').fetchone()
            fact=con.execute('SELECT COUNT(*),SUM(price) FROM fact_order_items').fetchone()
            self.assertEqual(raw,fact)
            self.assertAlmostEqual(raw[1],con.execute('SELECT SUM(merchandise_value) FROM fact_orders').fetchone()[0])
            con.execute('PRAGMA foreign_keys=ON')
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("INSERT INTO fact_order_items VALUES ('missing',1,'missing',10,0)")

    def test_customer_sample_deduplicates_before_tests(self):
        with closing(sqlite3.connect(self.db)) as con, con:
            # Make every eligible reviewed order belong to a single customer.
            con.execute("UPDATE mart_orders SET customer_unique_id='one_person'")
            sample=con.execute('SELECT order_id FROM analysis_customer_sample').fetchall()
            expected=con.execute('''SELECT order_id FROM mart_orders WHERE delivery_eligible=1
              AND review_score IS NOT NULL ORDER BY purchased_at,order_id LIMIT 1''').fetchone()
            self.assertEqual(sample,[expected])

    def test_sql_calendar_and_wilson_bounds(self):
        with closing(sqlite3.connect(self.db)) as con, con:
            con.row_factory=sqlite3.Row
            queries=advanced_queries()
            self.assertEqual(len(queries),4)
            for query in queries.values(): con.execute(query).fetchall()
            for r in con.execute(queries['route_intervals']):
                self.assertLessEqual(r['wilson_low_pct'],r['late_rate_pct']+1e-9)
                self.assertGreaterEqual(r['wilson_high_pct'],r['late_rate_pct']-1e-9)
                self.assertGreaterEqual(r['wilson_low_pct'],-1e-9)
                self.assertLessEqual(r['wilson_high_pct'],100+1e-9)
            # Two orders separated by a gap: recursive calendar fills February.
            con.execute('DELETE FROM mart_orders')
            for month,late in [('01',0),('03',1)]:
                con.execute('''INSERT INTO mart_orders(order_id,purchased_at,purchase_month,
                  delivery_eligible,delay_days) VALUES (?,?,?,1,?)''',
                  (month,f'2024-{month}-01',f'2024-{month}',late))
            result=con.execute(queries['monthly_trends']).fetchall()
            self.assertEqual([r['orders'] for r in result],[1,0,1])
            self.assertIsNone(result[1]['late_rate_pct'])
            self.assertIsNone(result[2]['change_pp'])
            self.assertEqual(result[2]['rolling_3m_late_rate_pct'],50)

    def test_hypothesis_tests_against_independent_formulas(self):
        a=np.tile([1,2,3,4,5],20).astype(float)
        b=np.tile([1,2,4,5,5],20).astype(float)
        scores=np.r_[a,b]
        sample=pd.DataFrame({'review_score':scores,'is_late':[1]*100+[0]*100,
                             'low_review':(scores<=2).astype(int)})
        result=statistical_tests(sample)
        expected_t=(a.mean()-b.mean())/np.sqrt(a.var(ddof=1)/100+b.var(ddof=1)/100)
        self.assertAlmostEqual(result['welch']['t'],expected_t)
        observed=np.array(result['chi_squared']['table'])
        expected=observed.sum(axis=1)[:,None]*observed.sum(axis=0)[None,:]/200
        self.assertAlmostEqual(result['chi_squared']['chi2'],float(((observed-expected)**2/expected).sum()))
        self.assertLess(result['welch']['ci95'][0],result['welch']['difference'])
        self.assertGreater(result['welch']['ci95'][1],result['welch']['difference'])
        for name in ('welch','chi_squared','mann_whitney'):
            self.assertGreaterEqual(result[name]['p_holm'],result[name]['p'])
        sample.low_review=0
        with self.assertRaises(ValueError):statistical_tests(sample)

    def test_research_staleness_and_checksum_failure(self):
        report=Path(self.temp.name)/'results.json'
        report.write_text(json.dumps({'source':self.info}))
        self.assertEqual(research_results(self.db,report)['source'],self.info)
        report.write_text(json.dumps({'source':{'built_at_utc':'old'}}))
        with self.assertRaisesRegex(ValueError,'stale'):research_results(self.db,report)
        bad=Path(self.temp.name)/'archive.zip';bad.write_bytes(b'not an archive')
        with self.assertRaisesRegex(ValueError,'differs'):acquire(self.directory,bad)

    def test_nonfinite_numbers_rejected(self):
        item=self.directory/TABLES['items'][0]
        import csv
        with item.open() as f: rows=list(csv.DictReader(f))
        rows[0]['price']='inf'
        with item.open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
        with self.assertRaisesRegex(ValueError,'invalid price'):build(self.directory,self.db)


if __name__=='__main__':unittest.main()
