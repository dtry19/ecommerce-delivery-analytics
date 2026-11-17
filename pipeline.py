"""CSV -> SQLite -> validated reporting tables. Python standard library only."""
import argparse
import csv
import json
import hashlib
import math
import random
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / 'data' / 'raw'
DB = ROOT / 'data' / 'processed' / 'delivery.db'
TABLES = {
 'orders': ('olist_orders_dataset.csv', {
  'order_id':'TEXT PRIMARY KEY','customer_id':'TEXT','order_status':'TEXT',
  'order_purchase_timestamp':'TEXT','order_delivered_customer_date':'TEXT',
  'order_estimated_delivery_date':'TEXT'}),
 'customers': ('olist_customers_dataset.csv', {'customer_id':'TEXT PRIMARY KEY','customer_unique_id':'TEXT','customer_state':'TEXT'}),
 'sellers': ('olist_sellers_dataset.csv', {'seller_id':'TEXT PRIMARY KEY','seller_state':'TEXT'}),
 'items': ('olist_order_items_dataset.csv', {'order_id':'TEXT','order_item_id':'INTEGER',
  'seller_id':'TEXT','price':'REAL','freight_value':'REAL'}),
 'reviews': ('olist_order_reviews_dataset.csv', {'review_id':'TEXT','order_id':'TEXT',
  'review_score':'INTEGER','review_creation_date':'TEXT'})
}

def write_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

def make_demo(directory, n=1500):
    """Deterministic synthetic data for functionality checks, NOT portfolio findings."""
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.glob('olist_*.csv')):
        raise ValueError('Demo destination already contains CSVs. Use a new directory.')
    rng = random.Random(42)
    states = ['SP','RJ','MG','BA','PR']
    sellers = [{'seller_id':f's{i:03}', 'seller_state':rng.choice(states)} for i in range(20)]
    customers, orders, items, reviews = [], [], [], []
    for i in range(n):
        oid, cid = f'o{i:06}', f'c{i:06}'
        state = rng.choice(states)
        customers.append({'customer_id':cid,'customer_unique_id':cid,'customer_state':state})
        purchase = datetime(2024,1,1)+timedelta(days=rng.randrange(365),hours=rng.randrange(24))
        estimated = (purchase+timedelta(days=rng.randint(8,16))).replace(hour=0)
        late = rng.random() < (0.32 if state=='BA' else 0.13)
        delivered = estimated+timedelta(days=rng.randint(1,8) if late else -rng.randint(0,5),hours=12)
        status = 'canceled' if rng.random()<0.04 else 'delivered'
        fmt = lambda d: d.strftime('%Y-%m-%d %H:%M:%S')
        orders.append({'order_id':oid,'customer_id':cid,'order_status':status,
          'order_purchase_timestamp':fmt(purchase),
          'order_delivered_customer_date':fmt(delivered) if status=='delivered' else '',
          'order_estimated_delivery_date':fmt(estimated)})
        first_seller = rng.choice(sellers)['seller_id']
        for j in range(rng.randint(1,3)):
            seller = rng.choice(sellers)['seller_id'] if j>0 and rng.random()<0.15 else first_seller
            items.append({'order_id':oid,'order_item_id':j+1,'seller_id':seller,
              'price':round(rng.uniform(20,500),2),'freight_value':round(rng.uniform(8,45),2)})
        if status=='delivered' and rng.random()<0.85:
            reviews.append({'review_id':f'r{i:06}','order_id':oid,
              'review_score':rng.choice([1,2,3,4] if late else [3,4,5,5]),
              'review_creation_date':fmt(delivered+timedelta(days=2))})
    for name, rows in [('orders',orders),('customers',customers),('sellers',sellers),('items',items),('reviews',reviews)]:
        write_csv(directory/TABLES[name][0],rows)
    (directory/'demo_marker.json').write_text(json.dumps({'synthetic':True,'seed':42,'orders':n}))

def load_csv(con, directory):
    for name, (filename, columns) in TABLES.items():
        path = directory / filename
        if not path.exists():
            raise ValueError(f'Missing required file: {path}')
        definitions = ','.join(f'{key} {kind}' for key,kind in columns.items())
        if name=='items':
            definitions += ', PRIMARY KEY(order_id,order_item_id)'
        con.execute(f'CREATE TABLE raw_{name} ({definitions})')
        with path.open(encoding='utf-8-sig',newline='') as f:
            reader = csv.DictReader(f)
            # Legacy demo/input files may omit the stable customer identity.
            missing = set(columns)-set(reader.fieldnames or [])-{'customer_unique_id'}
            if missing:
                raise ValueError(f'{filename}: missing columns {sorted(missing)}')
            rows=[]
            for line,row in enumerate(reader,2):
                values=[]
                for key,kind in columns.items():
                    value=(row.get(key) or (row.get('customer_id') if key=='customer_unique_id' else '')).strip()
                    if value and kind in ('REAL','INTEGER'):
                        try:
                            value=float(value) if kind=='REAL' else int(value)
                            if not math.isfinite(value):
                                raise ValueError('Non-finite number')
                        except ValueError as e:
                            raise ValueError(f'{filename}:{line}: invalid {key}') from e
                    values.append(value if value!='' else None)
                rows.append(values)
            con.executemany(f'INSERT INTO raw_{name} VALUES ({",".join("?" for _ in columns)})',rows)

def validate_raw(con):
    checks = {
      'orders_without_customers': 'SELECT COUNT(*) FROM raw_orders o LEFT JOIN raw_customers c USING(customer_id) WHERE c.customer_id IS NULL',
      'items_without_orders': 'SELECT COUNT(*) FROM raw_items i LEFT JOIN raw_orders o USING(order_id) WHERE o.order_id IS NULL',
      'items_without_sellers': 'SELECT COUNT(*) FROM raw_items i LEFT JOIN raw_sellers s USING(seller_id) WHERE s.seller_id IS NULL',
      'reviews_without_orders': 'SELECT COUNT(*) FROM raw_reviews r LEFT JOIN raw_orders o USING(order_id) WHERE o.order_id IS NULL',
      'invalid_item_amounts': 'SELECT COUNT(*) FROM raw_items WHERE price IS NULL OR freight_value IS NULL OR price<0 OR freight_value<0',
      'invalid_review_scores': 'SELECT COUNT(*) FROM raw_reviews WHERE review_score IS NULL OR review_score NOT BETWEEN 1 AND 5',
      'invalid_purchase_dates': 'SELECT COUNT(*) FROM raw_orders WHERE julianday(order_purchase_timestamp) IS NULL',
      'missing_states': 'SELECT (SELECT COUNT(*) FROM raw_customers WHERE customer_state IS NULL)+(SELECT COUNT(*) FROM raw_sellers WHERE seller_state IS NULL)',
      'missing_review_identity': 'SELECT COUNT(*) FROM raw_reviews WHERE review_id IS NULL OR julianday(review_creation_date) IS NULL',
    }
    for table, keys in {'orders':['order_id','customer_id','order_status'],
      'customers':['customer_id'],'sellers':['seller_id'],'items':['order_id','order_item_id','seller_id']}.items():
        checks[f'{table}_missing_keys'] = f'SELECT COUNT(*) FROM raw_{table} WHERE '+ ' OR '.join(f'{k} IS NULL' for k in keys)
    result = {key:con.execute(query).fetchone()[0] for key,query in checks.items()}
    failures = {key:value for key,value in result.items() if value}
    if failures:
        raise ValueError(f'Data quality checks failed: {failures}')
    if con.execute('SELECT COUNT(*) FROM raw_orders').fetchone()[0]==0:
        raise ValueError('Orders file is empty')
    return result

def build(directory=RAW, db=DB):
    directory, db = Path(directory), Path(db)
    db.parent.mkdir(parents=True,exist_ok=True)
    # Validate in memory so a failed refresh never replaces the last valid DB.
    con = sqlite3.connect(':memory:')
    try:
        load_csv(con,directory)
        checks = validate_raw(con)
        con.executescript((ROOT/'sql/models.sql').read_text())
        con.executescript((ROOT/'sql/warehouse.sql').read_text())
        if con.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Warehouse foreign key validation failed')
        raw_count = con.execute('SELECT COUNT(*) FROM raw_orders').fetchone()[0]
        mart_count = con.execute('SELECT COUNT(*) FROM mart_orders').fetchone()[0]
        if raw_count!=mart_count:
            raise ValueError('Order grain check failed')
        raw_value = con.execute('SELECT COALESCE(SUM(price),0) FROM raw_items').fetchone()[0]
        mart_value = con.execute('SELECT SUM(merchandise_value) FROM mart_orders').fetchone()[0]
        if abs(raw_value-mart_value)>0.01:
            raise ValueError('Merchandise value reconciliation failed')
        warning_count = con.execute("SELECT COUNT(*) FROM mart_orders WHERE order_status='delivered' AND delivery_eligible=0").fetchone()[0]
        source = 'SYNTHETIC DEMO' if (directory/'demo_marker.json').exists() else 'USER-SUPPLIED CSV'
        provenance=None
        manifest=directory/'source_manifest.json'
        if source!='SYNTHETIC DEMO' and manifest.exists():
            provenance=json.loads(manifest.read_text())
            for filename,record in provenance['files'].items():
                if hashlib.sha256((directory/filename).read_bytes()).hexdigest()!=record['sha256']:
                    raise ValueError(f'Source checksum mismatch: {filename}')
            source='OLIST PUBLIC DATASET'
        metadata = {'source':source,'built_at_utc':datetime.now(timezone.utc).isoformat(),
          'order_count':raw_count,'ineligible_delivered_orders':warning_count,'checks':checks,
          'raw_row_counts':{name:con.execute(f'SELECT COUNT(*) FROM raw_{name}').fetchone()[0] for name in TABLES},
          'provenance':provenance}
        con.execute('CREATE TABLE metadata (payload TEXT)')
        con.execute('INSERT INTO metadata VALUES (?)',(json.dumps(metadata),))
        con.commit()
        temporary = db.with_suffix('.tmp')
        with closing(sqlite3.connect(temporary)) as target, target:
            con.backup(target)
        temporary.replace(db)
        return metadata
    finally:
        con.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo',action='store_true',help='Generate separate synthetic input')
    parser.add_argument('--raw-dir',type=Path,default=RAW)
    parser.add_argument('--db',type=Path,default=DB)
    args=parser.parse_args()
    directory = ROOT/'data/demo' if args.demo else args.raw_dir
    if args.demo and not (directory/'demo_marker.json').exists():
        make_demo(directory)
    print(json.dumps(build(directory,args.db),indent=2))
