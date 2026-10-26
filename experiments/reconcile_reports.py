from __future__ import annotations
import argparse
import json
from decimal import Decimal
from pathlib import Path
import duckdb


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, default=Path.cwd())
    args = p.parse_args()
    root = args.root.resolve()
    data = root / 'data'
    clean_report = json.loads((data / 'clean_report.json').read_text(encoding='utf-8-sig'))
    fault_report = json.loads((data / 'fault_report.json').read_text(encoding='utf-8-sig'))
    clean_run = data / 'runs' / clean_report['run_id']
    fault_run = data / 'runs' / fault_report['run_id']
    con = duckdb.connect(':memory:')
    def parquet(path: Path) -> str:
        return path.resolve().as_posix().replace("'", "''")
    cdiag = parquet(clean_run / 'diagnostic_join.parquet')
    fdiag = parquet(fault_run / 'diagnostic_join.parquet')
    cdaily = parquet(clean_run / 'daily_zone_metrics.parquet')
    fdaily = parquet(fault_run / 'daily_zone_metrics.parquet')
    clean_rows = con.execute(f"SELECT count(*) FROM read_parquet('{cdiag}')").fetchone()[0]
    fault_rows = con.execute(f"SELECT count(*) FROM read_parquet('{fdiag}')").fetchone()[0]
    nk = con.execute(f"SELECT count(*) FROM read_parquet('{cdiag}') WHERE pickup_zone=1").fetchone()[0]
    direct = con.execute(f"""SELECT coalesce(c.pickup_date,f.pickup_date), coalesce(c.pickup_zone,f.pickup_zone),
        coalesce(c.trip_count,0), coalesce(f.trip_count,0), coalesce(c.revenue,0), coalesce(f.revenue,0),
        coalesce(c.average_fare,0), coalesce(f.average_fare,0)
      FROM read_parquet('{cdaily}') c FULL OUTER JOIN read_parquet('{fdaily}') f USING(pickup_date,pickup_zone)
      WHERE c.trip_count IS DISTINCT FROM f.trip_count OR c.revenue IS DISTINCT FROM f.revenue
        OR c.average_fare IS DISTINCT FROM f.average_fare ORDER BY 1,2""").fetchall()
    saved = {(x['pickup_date'], int(x['pickup_zone'])): x for x in fault_report['downstream_aggregate_deltas']}
    assert len(saved) == len(direct)
    total_trip_delta = 0
    total_revenue_delta = Decimal(0)
    all_averages_unchanged = True
    for row in direct:
        date, zone, expected_n, observed_n, expected_rev, observed_rev, expected_avg, observed_avg = row
        key = (str(date), int(zone))
        item = saved[key]
        trip_delta = int(observed_n) - int(expected_n)
        revenue_delta = Decimal(observed_rev) - Decimal(expected_rev)
        assert item['trip_count_delta'] == trip_delta
        assert Decimal(item['revenue_delta']) == revenue_delta
        assert Decimal(item['expected_revenue']) == Decimal(expected_rev)
        assert Decimal(item['observed_revenue']) == Decimal(observed_rev)
        assert Decimal(item['expected_average_fare']) == Decimal(expected_avg)
        assert Decimal(item['observed_average_fare']) == Decimal(observed_avg)
        total_trip_delta += trip_delta
        total_revenue_delta += revenue_delta
        all_averages_unchanged &= expected_avg == observed_avg
    expected_inflation = nk * 1
    observed_inflation = fault_rows - clean_rows
    assert observed_inflation == expected_inflation
    assert fault_report['expected_observed']['row_inflation'] == observed_inflation
    manifest = json.loads((data / 'source-manifest.json').read_text(encoding='utf-8'))
    jan = manifest['months']['2024-01']
    assert jan['schema_classification'] == 'compatible'
    clean_manifest_path = clean_run / 'manifest.json'
    fault_manifest_path = fault_run / 'manifest.json'
    clean_manifest = json.loads(clean_manifest_path.read_text(encoding='utf-8'))
    fault_manifest = json.loads(fault_manifest_path.read_text(encoding='utf-8'))
    contract_hash = clean_report['contract_hash']
    assert contract_hash == fault_report['contract_hash']
    assert contract_hash == clean_manifest['contract_sha256'] == fault_manifest['contract_sha256']
    assert clean_report['logical_output_hashes']['clean_trips'] == 'rows=2870188;logical_hash=26490451740393269596323632'
    assert fault_report['expected_observed']['row_inflation'] == 50
    result = {
      'reconciliation_version':'jan-2024-parquet-reconciliation-v1',
      'clean_run_id':clean_report['run_id'], 'fault_run_id':fault_report['run_id'],
      'clean_manifest':str(clean_manifest_path.relative_to(root)),
      'fault_manifest':str(fault_manifest_path.relative_to(root)),
      'contract_sha256':contract_hash,
      'clean_diagnostic_rows':clean_rows, 'fault_diagnostic_rows':fault_rows,
      'matching_input_rows_for_M1':nk, 'expected_row_inflation':expected_inflation,
      'observed_row_inflation':observed_inflation,
      'affected_daily_zone_groups':len(direct), 'total_trip_count_delta':total_trip_delta,
      'total_revenue_delta':str(total_revenue_delta),
      'average_fares_unchanged_in_all_affected_groups':all_averages_unchanged,
      'report_aggregate_deltas_match_parquet':True,
      'publication_pointer_preserved':fault_report['publication']['pointer_before']==fault_report['publication']['pointer_after'],
      'limitations':['One injected join fault is a plumbing and attribution test, not a recall or false-positive estimate.',
                     'Peak memory is measured for each dedicated experiment subprocess and may be unavailable on unsupported platforms.']
    }
    out = data / 'jan-2024-reconciliation.json'
    out.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    con.close()


if __name__ == '__main__':
    main()
