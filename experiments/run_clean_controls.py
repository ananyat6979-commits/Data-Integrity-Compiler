from __future__ import annotations
import hashlib, json, subprocess, sys
from pathlib import Path
root=Path.cwd().resolve()
data=root/'data'
manifest=json.loads((data/'source-manifest.json').read_text(encoding='utf-8'))['months']
lookup=data/'raw/taxi_zone_lookup.csv'
months=['2024-02','2025-01','2024-01']

def digest(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()

before={lookup.name:digest(lookup)}
for month in months:
    path=data/'raw'/f'yellow_tripdata_{month}.parquet'
    before[path.name]=digest(path)
    if manifest[month]['schema_classification']!='compatible':
        raise SystemExit(f'{month} schema is not compatible: {manifest[month]["schema_classification"]}')
    result=subprocess.run([sys.executable,'-m','dic.cli','run','--month',month],cwd=root,capture_output=True,text=True,check=True)
    report=json.loads(result.stdout)
    if report['outcome']!='passed':
        raise SystemExit(f'{month} clean control blocked: {report["checks"]}')
    out=data/'clean-controls'/f'{month}.json'
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'month':month,'run_id':report['run_id'],'outcome':report['outcome'],
      'schema_classification':manifest[month]['schema_classification'],'added_columns':manifest[month]['added_columns'],
      'row_counts':report['row_counts'],'runtimes_seconds':report['runtimes_seconds'],'hashes':report['logical_output_hashes']},indent=2))
    if month=='2024-01':
        previous=json.loads((data/'clean_report.json').read_text(encoding='utf-8-sig'))
        if previous['logical_output_hashes']!=report['logical_output_hashes']:
            raise SystemExit('January logical fingerprints differ from the saved baseline')
for name,expected in before.items():
    path=lookup if name==lookup.name else data/'raw'/name
    if digest(path)!=expected:
        raise SystemExit(f'Immutable input changed: {path}')
print('Input SHA-256 checks unchanged. January logical fingerprints match the saved baseline.')
