"""Reproduce advanced SQL, hypothesis tests, regression, and BI exports."""
import argparse
import csv
import hashlib
import json
import math
import platform
import re
import sqlite3
import statistics
import time
from contextlib import closing
from pathlib import Path

import numpy as np
import pandas as pd
import scipy
from scipy import stats
import statsmodels
import statsmodels.formula.api as smf
from statsmodels.stats.multitest import multipletests
from pipeline import DB,ROOT
from server import connect

def advanced_queries():
    parts=re.split(r'^-- name: (\w+)\n',(ROOT/'sql/advanced_analysis.sql').read_text(),flags=re.M)
    return dict(zip(parts[1::2],parts[2::2]))

def statistical_tests(sample):
    late=sample.loc[sample.is_late==1,'review_score'].to_numpy(dtype=float)
    ontime=sample.loc[sample.is_late==0,'review_score'].to_numpy(dtype=float)
    if min(len(late),len(ontime))<2:
        raise ValueError('Need at least two reviewed customers in each delivery group')
    result=stats.ttest_ind(late,ontime,equal_var=False,alternative='two-sided')
    interval=result.confidence_interval()
    pooled=np.sqrt(((len(late)-1)*late.var(ddof=1)+(len(ontime)-1)*ontime.var(ddof=1))/(len(sample)-2))
    d=(late.mean()-ontime.mean())/pooled if pooled else None
    table=pd.crosstab(sample.is_late,sample.low_review).reindex(index=[0,1],columns=[0,1],fill_value=0)
    observed=table.to_numpy()
    chi=stats.chi2_contingency(observed,correction=False)
    if (chi.expected_freq<5).any():
        raise ValueError('Expected contingency cell below 5; use Fisher exact for this sample')
    # Rank-based sensitivity analysis respects the ordinal review outcome.
    mw=stats.mannwhitneyu(late,ontime,alternative='two-sided',method='asymptotic')
    corrected=multipletests([result.pvalue,chi.pvalue,mw.pvalue],method='holm')[1]
    return {
      'sample_customers':len(sample),'late_customers':len(late),'on_time_customers':len(ontime),
      'welch':{'late_mean':float(late.mean()),'on_time_mean':float(ontime.mean()),
        'difference':float(late.mean()-ontime.mean()),'ci95':[float(interval.low),float(interval.high)],
        't':float(result.statistic),'df':float(result.df),'p':float(result.pvalue),
        'p_holm':float(corrected[0]),'cohens_d':float(d) if d is not None else None},
      'chi_squared':{'table':observed.tolist(),'row_labels':['On time','Late'],
        'column_labels':['3–5 stars','1–2 stars'],'chi2':float(chi.statistic),'df':int(chi.dof),
        'p':float(chi.pvalue),'p_holm':float(corrected[1]),
        'expected_min':float(chi.expected_freq.min()),
        'cramers_v':float(np.sqrt(chi.statistic/len(sample))),
        'late_low_review_pct':float(100*observed[1,1]/observed[1].sum()),
        'on_time_low_review_pct':float(100*observed[0,1]/observed[0].sum())},
      'mann_whitney':{'u':float(mw.statistic),'p':float(mw.pvalue),'p_holm':float(corrected[2])}}

def regression(sample):
    # Avoid unstable fixed effects for nearly empty boundary months. This
    # volume rule is fixed in advance and does not inspect review outcomes.
    month_n=sample.groupby('purchase_month').size()
    stable=sample.purchase_month.isin(month_n[month_n>=30].index)
    excluded=int((~stable).sum())
    sample=sample.loc[stable].copy()
    formula='review_score ~ is_late + np.log1p(merchandise_value) + promised_days + seller_count + C(customer_state) + C(purchase_month)'
    model=smf.ols(formula,data=sample,missing='raise').fit(cov_type='HC3')
    if np.linalg.matrix_rank(model.model.exog)!=model.model.exog.shape[1]:
        raise ValueError('Regression design matrix is rank deficient')
    ci=model.conf_int().loc['is_late']
    return model,{'formula':formula,'covariance':'HC3','n':int(model.nobs),
      'excluded_sparse_month_customers':excluded,'minimum_customers_per_month':30,
      'r_squared':float(model.rsquared),'late_coefficient':float(model.params['is_late']),
      'late_ci95':[float(ci.iloc[0]),float(ci.iloc[1])],
      'late_p':float(model.pvalues['is_late']),'design_rank':int(model.df_model+1),
      'condition_number':float(model.condition_number),
      'interpretation':'Adjusted historical association, not a causal effect or a validated prediction model.'}

def benchmark(db,repeats=15):
    # Separate in-memory copy; no mutation of the reporting database. Warm cache
    # timings are illustrative local measurements, not production guarantees.
    query='SELECT COUNT(*),SUM(merchandise_value) FROM mart_orders WHERE customer_state=? AND purchased_at>=? AND purchased_at<?'
    params=('SP','2018-01-01','2018-02-01')
    with connect(db) as source, closing(sqlite3.connect(':memory:')) as con:
        source.backup(con)
        for index in con.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='mart_orders'").fetchall():
            con.execute(f'DROP INDEX "{index[0]}"')
        output={}
        for label in ('without_index','with_index'):
            if label=='with_index':
                con.execute('CREATE INDEX bench_state_date ON mart_orders(customer_state,purchased_at)')
                con.execute('ANALYZE')
            output[label+'_plan']=[r[3] for r in con.execute('EXPLAIN QUERY PLAN '+query,params)]
            answer=con.execute(query,params).fetchone()
            times=[]
            for _ in range(repeats):
                start=time.perf_counter();con.execute(query,params).fetchone()
                times.append((time.perf_counter()-start)*1000)
            output[label+'_median_ms']=statistics.median(times)
            if label=='without_index': baseline=answer
            elif answer!=baseline: raise ValueError('Benchmark changed query result')
        output['repeats']=repeats
        output['query']=query
        output['parameters']=params
        output['speedup']=output['without_index_median_ms']/output['with_index_median_ms']
        return output

def write_narrative(result,output):
    t=result['tests'];w=t['welch'];c=t['chi_squared'];g=result['regression'];b=result['benchmark']
    s=result['summary'];counts=result['row_counts'];total=sum(counts.values())
    def pvalue(p):return '< 1e-300 (numerical underflow)' if p==0 else f'{p:.3g}'
    memo=f'''# Olist delivery performance: findings and methods

## Decision and data

Question: where should marketplace operations investigate delivery delays, and
how strongly are delays associated with customer reviews?

Source: [Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce),
version 2, CC BY-NC-SA 4.0. Archive SHA-256:
`{result['source']['provenance']['archive_sha256'] if result['source'].get('provenance') else 'Synthetic/user-supplied input; see results.json'}`.
Source mode: **{result['source']['source']}**. Build: {result['source']['built_at_utc']}.
This report concerns historical Brazilian marketplace data, not Amazon data.

The pipeline loads **{total:,} rows across five source tables**, including
**{counts['items']:,} order items and {counts['orders']:,} distinct orders**.
Downloaded auxiliary tables are counted in the provenance manifest but are not
part of this loaded-row claim. Purchase dates: {s['start']} through {s['end']}.
There are {int(s['eligible']):,} eligible delivered orders and {int(s['late']):,}
late deliveries ({100*s['late']/s['eligible']:.2f}%).
{result['source']['ineligible_delivered_orders']} delivered orders with invalid/missing dates are excluded from delivery metrics.

## Hypotheses and sample

The analysis sample is the first eligible reviewed order per customer_unique_id,
ordered by purchase timestamp and order ID. This produces {t['sample_customers']:,}
unique customers: {t['late_customers']:,} late and {t['on_time_customers']:,} on time.
The SQL selects the latest review per order before this customer-level selection.
The sample is conditional on observed delivery and review, not all customers.

1. Welch's two-sided t-test: H0 is equal mean review scores for late and on-time
   deliveries. Unequal population variances are allowed.
2. Pearson chi-squared test without Yates correction: H0 is independence of
   late status and low review (1-2 stars versus 3-5 stars).
3. Two-sided Mann-Whitney U provides a rank-based sensitivity check because
   review scores are bounded and ordinal. It tests distributions/ranks, not
   an interchangeable claim about mean differences.

These are exploratory analyses. Holm correction covers the family of these
three tests; the separate adjusted regression is also exploratory.

## Measured results

| Measure | Result |
| --- | --- |
| Late / on-time mean review | {w['late_mean']:.3f} / {w['on_time_mean']:.3f} stars |
| Mean difference, late minus on time | {w['difference']:.3f} stars |
| Welch 95% confidence interval | [{w['ci95'][0]:.3f}, {w['ci95'][1]:.3f}] |
| Welch t / degrees of freedom | {w['t']:.3f} / {w['df']:.2f} |
| Welch Holm-adjusted p | {pvalue(w['p_holm'])} |
| Cohen's d, pooled-SD descriptive effect size | {w['cohens_d']:.3f} |
| Low-review share, late / on time | {c['late_low_review_pct']:.2f}% / {c['on_time_low_review_pct']:.2f}% |
| Chi-squared / degrees of freedom | {c['chi2']:.3f} / {c['df']} |
| Minimum expected contingency count | {c['expected_min']:.2f} (all exceed 5) |
| Chi-squared Holm-adjusted p | {pvalue(c['p_holm'])} |
| Cramer's V | {c['cramers_v']:.3f} |
| Mann-Whitney Holm-adjusted p | {pvalue(t['mann_whitney']['p_holm'])} |

Contingency rows are on time, late; columns are 3-5 stars, 1-2 stars:
`{c['table']}`. JSON retains floating-point underflow as 0; this is not a
claim that the mathematical p-value is exactly zero.

## Adjusted regression

Formula: `{g['formula']}`.
OLS estimates an adjusted mean association with HC3 heteroskedasticity-robust
standard errors. States and purchase months enter as categorical fixed effects.
Months with fewer than {g['minimum_customers_per_month']} reviewed customers
are excluded to avoid unstable month effects ({g['excluded_sparse_month_customers']}
customers excluded). This volume rule does not select on review score.

N = {g['n']:,}; late coefficient = {g['late_coefficient']:.3f} stars,
95% CI [{g['late_ci95'][0]:.3f}, {g['late_ci95'][1]:.3f}],
p {pvalue(g['late_p'])}, R-squared = {g['r_squared']:.3f}.
Full coefficients and robust intervals are in regression_coefficients.csv.
The matrix has full column rank ({g['design_rank']}) and condition number
{g['condition_number']:.1f}; coefficient estimates should be interpreted with
the sparse states, feature scale differences, and residual confounding in mind.
OLS treats stars as numeric. It is an explanatory sensitivity analysis, not a
validated forecasting model; no train/test accuracy claim is made.

## SQL engineering and performance

Explicit DDL models date, customer and seller dimensions, order facts and
order-item facts. Primary/foreign keys, unique grain checks and monetary
reconciliations defend against join fanout. Advanced analyses use recursive
calendar CTEs, ROW_NUMBER, DENSE_RANK, LAG, cumulative SUM and rolling ROWS windows.
Shipping-route Wilson intervals expose uncertainty; seller Pareto shares use
seller-associated orders, which are non-additive to distinct order totals.

EXPLAIN QUERY PLAN changes a state/date query from a table scan to a composite
index search. On this local in-memory copy, median warm timings over
{b['repeats']} runs were {b['without_index_median_ms']:.3f} ms without the index
and {b['with_index_median_ms']:.3f} ms with it ({b['speedup']:.2f}x).
Results match between query plans. Timing is environment-specific and is not
a production latency or business-impact claim.

## Recommended investigation and next measurement

Operations should investigate high-volume late routes and seller associations
in route_intervals.csv and seller_pareto.csv, using counts and intervals rather
than the largest raw percentage. Inspect carrier handoffs and exception logs
before assigning responsibility; those causal details are not in this model.
Customer experience teams can review communications around missed estimates,
given the measured low-review association.

A proposed pilot would compare late-delivery rate, 1-2 star review share and
freight cost against a contemporaneous randomized or carefully matched control
over complete purchase cohorts. No pilot was run and no improvement is claimed.

## Limits

Review nonresponse, surviving delivered orders, incomplete end cohorts,
unmeasured product/carrier factors, and residual seller/time correlation limit
inference. One order per customer reduces repeated-customer dependence but does
not guarantee independence across shared sellers, routes or dates. HC3 handles
heteroskedasticity, not all clustering. Multiple sellers cannot be assigned the
order's delay causally. Large samples make tiny p-values unsurprising; effect
sizes, uncertainty and practical relevance carry the interpretation. Repeat
purchase cohorts describe observed activity, not subscription retention.

Method references: [SciPy Welch test](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_ind.html),
[SciPy contingency test](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.chi2_contingency.html),
[statsmodels robust covariance](https://www.statsmodels.org/stable/generated/statsmodels.regression.linear_model.OLSResults.get_robustcov_results.html).
'''
    (output/'findings.md').write_text(memo)
    (output/'resume_bullets.md').write_text(f'''# Resume project entry

**E-commerce Delivery & Customer Experience Analytics | SQL, Python, SQLite, SciPy, statsmodels, Excel**

- Engineered a reproducible Python/SQL ETL pipeline processing {total:,} source records, including {counts['items']:,} order items across {counts['orders']:,} orders; implemented a star schema, referential-integrity checks, and order/value reconciliations.
- Developed recursive CTEs and window functions (ROW_NUMBER, LAG, DENSE_RANK, rolling and cumulative SUM) for delivery cohorts, seller Pareto analysis, and route-level confidence intervals.
- Applied Welch's t-test, chi-squared testing, and HC3-robust regression to {t['sample_customers']:,} unique customers; measured a {abs(w['difference']):.2f}-star review gap between late and on-time deliveries (95% CI: {abs(w['ci95'][1]):.2f}-{abs(w['ci95'][0]):.2f} stars).

For a tighter two-bullet entry, use the first bullet and combine the SQL techniques
with the statistical finding. The Excel workbook contains a native chart and
formula-driven monthly rates; inspect it before discussing it in interviews.
Use the full project report to explain the sample and observational limitations.
Do not claim 100,000+ distinct orders, reduced delivery delays, Amazon data,
production deployment, or Power BI/Tableau experience from this implementation.
''')

def run(db=DB,output=ROOT/'reports'):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    bi=output/'bi';bi.mkdir(exist_ok=True)
    with connect(db) as con:
        metadata=json.loads(con.execute('SELECT payload FROM metadata').fetchone()[0])
        sample=pd.read_sql_query('SELECT * FROM analysis_customer_sample ORDER BY customer_unique_id',con)
        tests=statistical_tests(sample)
        model,reg=regression(sample)
        row_counts={name:con.execute(f'SELECT COUNT(*) FROM raw_{name}').fetchone()[0]
                    for name in ('orders','items','reviews','customers','sellers')}
        queries=advanced_queries()
        for name,query in queries.items():
            pd.read_sql_query(query,con).to_csv(output/(name+'.csv'),index=False)
        for table in ('dim_date','dim_customer','dim_seller','fact_orders','fact_order_items'):
            pd.read_sql_query(f'SELECT * FROM {table}',con).to_csv(bi/(table+'.csv'),index=False)
        summary=pd.read_sql_query('''SELECT COUNT(*) AS orders,SUM(delivery_eligible) AS eligible,
          SUM(CASE WHEN delivery_eligible=1 AND delay_days>0 THEN 1 ELSE 0 END) AS late,
          COUNT(review_score) AS reviewed_orders,MIN(date(purchased_at)) AS start,
          MAX(date(purchased_at)) AS end FROM mart_orders''',con).iloc[0].to_dict()
    results={'source':metadata,'row_counts':row_counts,'summary':summary,
      'tests':tests,'regression':reg,'benchmark':benchmark(db),
      'versions':{'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,
        'numpy':np.__version__,'pandas':pd.__version__,'scipy':scipy.__version__,
        'statsmodels':statsmodels.__version__},
      'analysis_sample_sha256':hashlib.sha256(sample.to_csv(index=False).encode()).hexdigest()}
    (output/'results.json').write_text(json.dumps(results,indent=2,allow_nan=False)+'\n')
    coefficients=pd.DataFrame({'term':model.params.index,'coefficient':model.params.values,
      'robust_se':model.bse.values,'p':model.pvalues.values,
      'ci95_low':model.conf_int().iloc[:,0].values,'ci95_high':model.conf_int().iloc[:,1].values})
    coefficients.to_csv(output/'regression_coefficients.csv',index=False)
    (output/'regression_summary.txt').write_text('\n'.join(
        line.rstrip() for line in model.summary().as_text().splitlines())+'\n')
    write_narrative(results,output)
    with connect(db) as con:
        monthly=pd.read_sql_query(queries['monthly_trends'],con)
    (output/'workbook_inputs.json').write_text(json.dumps({
      'months':json.loads(monthly.to_json(orient='records'))},allow_nan=False)+'\n')
    return results

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,default=DB)
    parser.add_argument('--output',type=Path,default=ROOT/'reports')
    args=parser.parse_args()
    result=run(args.db,args.output)
    print(json.dumps({'row_counts':result['row_counts'],'tests':result['tests'],
      'regression':result['regression'],'benchmark':result['benchmark']},indent=2))
