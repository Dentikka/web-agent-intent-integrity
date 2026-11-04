"""Inspect the recorded research artifact without models or application servers."""
from __future__ import annotations

import argparse
from contextlib import closing
from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
SECTIONS = ('paper', 'cart-replication')


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_registry(section: str) -> list[dict]:
    with (ROOT / 'data' / section / 'trials.csv').open(encoding='utf8', newline='') as stream:
        return list(csv.DictReader(stream))


def files(section: str) -> list[dict]:
    return json.loads((ROOT / 'data' / section / 'files.json').read_text(encoding='utf8'))


def support_files(section: str) -> list[dict]:
    path = ROOT / 'data' / section / 'support.json'
    if not path.exists():
        return []
    index = json.loads(path.read_text())
    if sha256((ROOT / index['path']).read_bytes()) != index['sha256']:
        raise ValueError('Recorded-analysis archive checksum mismatch')
    return [dict(item, shard=index['path']) for item in index['files']]


def records(section: str):
    indexed = {row['source']: row for row in read_registry(section)}
    grouped = defaultdict(list)
    for item in files(section):
        if item['path'] in indexed:
            grouped[item['shard']].append(item)
    for shard, items in sorted(grouped.items()):
        with zipfile.ZipFile(ROOT / shard) as archive:
            for item in items:
                yield indexed[item['path']], json.loads(archive.read(item['path']))


def verify(section: str, sqlite: bool = False) -> dict:
    index = json.loads((ROOT / 'data' / section / 'index.json').read_text())
    registry = read_registry(section)
    if len(registry) != index['episodes'] or len({row['source'] for row in registry}) != len(registry):
        raise ValueError('Assignment registry count or uniqueness mismatch')
    if dict(Counter(row['cohort'] for row in registry)) != index['cohorts']:
        raise ValueError('Cohort counts do not match the index')
    entries = files(section)
    grouped = defaultdict(dict)
    for item in entries:
        grouped[item['shard']][item['path']] = item
    result_hashes = {row['source']: row['artifact_sha256'] for row in registry}
    checked = 0
    checked_db = 0
    for shard in index['shards']:
        path = ROOT / shard['path']
        if sha256(path.read_bytes()) != shard['sha256']:
            raise ValueError(f'Archive checksum mismatch: {shard["path"]}')
        with zipfile.ZipFile(path) as archive:
            expected = grouped[shard['path']]
            if set(archive.namelist()) != set(expected) or len(archive.namelist()) != len(expected):
                raise ValueError(f'Archive file list mismatch: {shard["path"]}')
            for name, item in expected.items():
                data = archive.read(name)
                hashed = sha256(data)
                if len(data) != item['size'] or hashed != item['sha256']:
                    raise ValueError(f'File checksum mismatch: {name}')
                if name in result_hashes and hashed != result_hashes.pop(name):
                    raise ValueError(f'Registry checksum mismatch: {name}')
                if sqlite and Path(name).suffix in {'.sqlite', '.db'}:
                    with tempfile.TemporaryDirectory() as temp:
                        db_path = Path(temp) / 'record.sqlite'
                        db_path.write_bytes(data)
                        with closing(sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True)) as db:
                            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                                raise ValueError(f'SQLite integrity failure: {name}')
                        if sha256(db_path.read_bytes()) != hashed:
                            raise ValueError('Read-only database audit changed its input')
                    checked_db += 1
                checked += 1
    if result_hashes or checked != index['files']:
        raise ValueError('Missing result or evidence file')
    supporting = support_files(section)
    if supporting:
        with zipfile.ZipFile(ROOT / supporting[0]['shard']) as archive:
            if set(archive.namelist()) != {item['path'] for item in supporting}:
                raise ValueError('Recorded-analysis file list mismatch')
            for item in supporting:
                data = archive.read(item['path'])
                if sha256(data) != item['sha256'] or len(data) != item['size']:
                    raise ValueError('Recorded-analysis checksum mismatch')
    errors = sum(bool(result.get('error')) for _, result in records(section))
    if section == 'paper':
        cohorts = json.loads((ROOT / 'data/paper/cohorts.json').read_text())['cohorts']
        if sum(c['expected'] for c in cohorts) != len(registry):
            raise ValueError('Prospective cohort counts disagree with registered assignments')
        actual = Counter(row['cohort'] for row, result in records(section) if result.get('error'))
        for cohort in cohorts:
            if actual[cohort['cohort']] != cohort['technical_errors']:
                raise ValueError(f'Technical-error mismatch: {cohort["cohort"]}')
    return dict(section=section, assignments=len(registry), cohorts=len(index['cohorts']),
                technical_errors=errors, files_checked=checked, databases_checked=checked_db,
                supporting_files_checked=len(supporting), passed=True, model_calls=0)


def extract(section: str, out: Path, cohorts: list[str] | None = None) -> dict:
    if out.exists():
        raise ValueError('Output directory must be new; recorded files are never overwritten')
    index = json.loads((ROOT / 'data' / section / 'index.json').read_text())
    if cohorts and set(cohorts) - set(index['cohorts']):
        raise ValueError('Unknown cohort; see data index.json')
    registry = read_registry(section)
    allowed = {str(Path(row['source']).parent).replace('\\', '/') for row in registry
               if not cohorts or row['cohort'] in cohorts}
    # Full relative paths are preserved so original read-only database audits work.
    grouped = defaultdict(list)
    for item in files(section):
        if any(parent.as_posix() in allowed for parent in Path(item['path']).parents):
            grouped[item['shard']].append(item)
    if not cohorts:
        for item in support_files(section):
            grouped[item['shard']].append(item)
    out.mkdir(parents=True)
    written = 0
    for shard, entries in sorted(grouped.items()):
        with zipfile.ZipFile(ROOT / shard) as archive:
            for item in entries:
                target = (out / item['path']).resolve()
                if not target.is_relative_to(out.resolve()):
                    raise ValueError('Unsafe archive path')
                data = archive.read(item['path'])
                if sha256(data) != item['sha256']:
                    raise ValueError('Archive content checksum mismatch')
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as stream:
                    stream.write(data)
                written += 1
    return dict(section=section, files=written, output=str(out), model_calls=0)


def summarize(section: str, out: Path, by: list[str]) -> dict:
    if out.exists():
        raise ValueError('Output directory must be new')
    grouped = defaultdict(list)
    for row, result in records(section):
        spec = result.get('spec', {})
        model = result.get('model') or spec.get('model_id') or spec.get('model')
        if isinstance(model, dict):
            model = model.get('id')
        group = (row['cohort'], str(model or 'not_recorded')) + tuple(
            json.dumps(spec.get(key), sort_keys=True) for key in by)
        grouped[group].append(result)
    out.mkdir(parents=True)
    cells = []
    for group, results in sorted(grouped.items()):
        complete = [r for r in results if not r.get('error')]
        score_names = sorted({key for r in complete for key, val in r.get('scores', {}).items()
                              if isinstance(val, bool)})
        cell = dict(cohort=group[0], model=group[1],
                    factors=dict(zip(by, group[2:])), assigned=len(results),
                    complete=len(complete), technical_errors=len(results) - len(complete))
        cell['scores'] = {key: dict(k=sum(r.get('scores', {}).get(key) is True for r in complete),
                                   n=sum(isinstance(r.get('scores', {}).get(key), bool) for r in complete))
                          for key in score_names}
        cells.append(cell)
    (out / 'cells.json').write_text(json.dumps(cells, indent=2), encoding='utf8')
    text = io.StringIO(newline='')
    writer = csv.writer(text)
    writer.writerow(['cohort', 'model', *by, 'assigned', 'complete', 'technical_errors', 'metric', 'k', 'n'])
    for cell in cells:
        for metric, values in cell['scores'].items():
            writer.writerow([cell['cohort'], cell['model'], *cell['factors'].values(), cell['assigned'],
                             cell['complete'], cell['technical_errors'], metric, values['k'], values['n']])
    (out / 'cells.csv').write_text(text.getvalue(), encoding='utf8')
    return dict(section=section, cells=len(cells), output=str(out), model_calls=0)


def main() -> None:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('command', choices=['verify', 'summarize', 'extract'])
    parser.add_argument('--section', choices=SECTIONS, default='paper')
    parser.add_argument('--sqlite', action='store_true', help='Also check every stored SQLite database')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--cohorts', nargs='+')
    parser.add_argument('--group-by', nargs='*', default=['app', 'policy'])
    args = parser.parse_args()
    if args.command == 'verify':
        result = verify(args.section, args.sqlite)
    else:
        if args.out is None:
            parser.error('--out is required and must name a new directory')
        result = (extract(args.section, args.out, args.cohorts) if args.command == 'extract'
                  else summarize(args.section, args.out, args.group_by))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
