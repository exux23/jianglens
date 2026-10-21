#!/usr/bin/env python3
"""Validate an immutable stablecoin archive and collect reproducible API snapshots."""
import argparse
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import tempfile
import time
from urllib.request import Request, urlopen
import zipfile

API = 'https://stablecoins.llama.fi'
FIELDS = ('stablecoin_id', 'symbol', 'chain', 'date', 'peg_type', 'circulating',
          'circulating_usd', 'minted', 'unreleased', 'bridged_to')


def get_json(endpoint):
    url = API + endpoint
    for attempt in range(4):
        try:
            with urlopen(Request(url, headers={'User-Agent': 'jianglens-research/1.0'}), timeout=90) as response:
                return json.load(response)
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def day(value):
    if value is None or value == '':
        raise ValueError('missing date')
    if isinstance(value, (float, int)) or str(value).strip().lstrip('-').isdigit():
        timestamp = int(value)
        if abs(timestamp) > 10**11:
            timestamp //= 1000
        return dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).date().isoformat()
    return dt.date.fromisoformat(str(value)[:10]).isoformat()


def amount(value, peg):
    if isinstance(value, dict):
        value = value.get(peg)
    if value is None or value == '' or isinstance(value, (dict, list)):
        return ''
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'invalid amount {value!r}')
    return str(value)


def market_rows(history):
    for record in history:
        for peg in sorted(set().union(*(set(record.get(k) or {}) for k in
                                       ('totalCirculating', 'totalCirculatingUSD', 'totalMintedUSD',
                                        'totalBridgedToUSD', 'totalUnreleased')))):
            yield {'date': day(record['date']), 'peg_type': peg,
                   'circulating': amount(record.get('totalCirculating'), peg),
                   'circulating_usd': amount(record.get('totalCirculatingUSD'), peg),
                   'minted_usd': amount(record.get('totalMintedUSD'), peg),
                   'bridged_to_usd': amount(record.get('totalBridgedToUSD'), peg),
                   'unreleased': amount(record.get('totalUnreleased'), peg)}


def chain_rows(asset):
    balances = asset.get('chainBalances', {})
    if not isinstance(balances, dict):
        raise ValueError('chainBalances must be a mapping')
    for chain, detail in balances.items():
        if not isinstance(detail, dict):
            raise ValueError(f'invalid chain detail for {chain}')
        tokens = detail.get('tokens', [])
        if not isinstance(tokens, list):
            raise ValueError(f'invalid token history for {chain}')
        for observation in tokens:
            if not isinstance(observation, dict):
                raise ValueError(f'invalid observation on {chain}')
            types = set()
            for k in ('circulating', 'circulatingUSD', 'unreleased'):
                if isinstance(observation.get(k), dict):
                    types.update(p for p in observation[k] if p.startswith('pegged'))
            if not types:
                continue
            for peg in sorted(types):
                yield dict(stablecoin_id=str(asset['id']), symbol=asset.get('symbol', ''),
                           chain=chain, date=day(observation['date']), peg_type=peg,
                           circulating=amount(observation.get('circulating'), peg),
                           circulating_usd=amount(observation.get('circulatingUSD'), peg),
                           minted=amount(observation.get('minted'), peg),
                           unreleased=amount(observation.get('unreleased'), peg),
                           bridged_to=amount(observation.get('bridgedTo'), peg))


def write_csv(path, rows, fields, zipped=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if zipped else open
    with opener(path, 'wt', encoding='utf-8', newline='') as output:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        count = 0
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def sha256_file(path):
    hash_ = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            hash_.update(chunk)
    return hash_.hexdigest()


def collect(output, ids, all_assets=False, market=False):
    if output.exists():
        raise FileExistsError(f'snapshot already exists: {output}')
    output.parent.mkdir(parents=True, exist_ok=True)
    catalog = get_json('/stablecoins?includePrices=true')
    listing = catalog.get('peggedAssets')
    if not isinstance(listing, list):
        raise ValueError('invalid DefiLlama asset catalog')
    by_id = {str(x['id']): x for x in listing}
    if len(by_id) != len(listing):
        raise ValueError('duplicate asset IDs in catalog')
    wanted = sorted(by_id, key=int) if all_assets else list(dict.fromkeys(ids))
    if not wanted or any(k not in by_id for k in wanted):
        raise ValueError('select valid --assets or --all-assets')
    with tempfile.TemporaryDirectory(prefix='.stablecoin-', dir=output.parent) as tmpname:
        tmp = Path(tmpname)
        sources = {}
        def preserve(name, endpoint, payload):
            dest = tmp / 'raw' / f'{name}.json.gz'
            dest.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(dest, 'wt', encoding='utf-8') as writer:
                json.dump(payload, writer, sort_keys=True, separators=(',', ':'))
            sources[name] = {'url': API + endpoint, 'sha256': sha256_file(dest)}
        preserve('catalog', '/stablecoins?includePrices=true', catalog)
        all_rows = []
        for id_ in wanted:
            endpoint = f'/stablecoin/{id_}'
            record = get_json(endpoint)
            if str(record.get('id')) != id_:
                raise ValueError(f'asset mismatch for {id_}')
            preserve(f'asset_{id_}', endpoint, record)
            all_rows.extend(chain_rows(record))
        all_rows.sort(key=lambda x: (int(x['stablecoin_id']), x['chain'], x['date'], x['peg_type']))
        keys = [(x['stablecoin_id'], x['chain'], x['date'], x['peg_type']) for x in all_rows]
        if len(keys) != len(set(keys)):
            raise ValueError('duplicate asset-chain-date-peg observations')
        count = write_csv(tmp / 'asset_chain_daily.csv.gz', all_rows, FIELDS, zipped=True)
        if market:
            responses = {}
            for name, endpoint in (('market', '/stablecoincharts/all'),
                                   ('chain_catalog', '/stablecoinchains'),
                                   ('prices', '/stablecoinprices')):
                payload = get_json(endpoint)
                preserve(name, endpoint, payload)
                responses[name] = payload
            write_csv(tmp / 'market_daily.csv.gz', market_rows(responses['market']),
                      ('date', 'peg_type', 'circulating', 'circulating_usd', 'minted_usd',
                       'bridged_to_usd', 'unreleased'), zipped=True)
            price_keys = {key for record in responses['prices'] for key in record.get('prices', {})}
            price_ids = {}
            for item in listing:
                key = item.get('gecko_id')
                if key:
                    price_ids.setdefault(key, []).append(str(item['id']))
            mapping = [{'price_key': k, 'stablecoin_id_if_unique': matches[0] if len(matches) == 1 else '',
                        'status': 'unique' if len(matches) == 1 else ('ambiguous' if matches else 'unmatched')}
                       for k in sorted(price_keys) for matches in [price_ids.get(k, [])]]
            write_csv(tmp / 'price_key_mapping.csv', mapping,
                      ('price_key', 'stablecoin_id_if_unique', 'status'))
            index = {item['price_key']: item for item in mapping}
            write_csv(tmp / 'price_daily.csv.gz',
                      ({'date': day(record['date']), 'price_key': key,
                        'stablecoin_id_if_unique': index[key]['stablecoin_id_if_unique'],
                        'mapping_status': index[key]['status'],
                        'price_usd': amount(value, '')}
                       for record in responses['prices'] for key, value in record['prices'].items()),
                      ('date', 'price_key', 'stablecoin_id_if_unique', 'mapping_status', 'price_usd'),
                      zipped=True)
        manifest = {'retrieved_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                    'source': API, 'asset_ids': wanted, 'asset_chain_daily_rows': count,
                    'historical_chain_data': True, 'market_included': market, 'raw_sources': sources,
                    'note': 'Daily history is provider-derived, not a point-in-time backtest vintage.'}
        (tmp / 'snapshot.json').write_text(json.dumps(manifest, indent=2) + '\n')
        os.rename(tmp, output)
    print(json.dumps({'path': str(output), 'asset_chain_daily_rows': count, 'assets': len(wanted)}, indent=2))


def verify(root):
    manifest = json.loads((root / 'manifest.json').read_text())
    problems, report = [], []
    headers = {}
    seen_by_category = {}
    for spec in manifest['files']:
        rel = Path(spec['path'])
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError(f'unsafe manifest path {rel}')
        path = root / rel
        entry = {'file': str(rel), 'expected_rows': spec.get('rows')}
        if not path.is_file():
            problems.append(f'missing file: {rel}')
            report.append(entry)
            continue
        contents = path.read_bytes()
        git_sha = hashlib.sha1(b'blob ' + str(len(contents)).encode() + b'\0' + contents).hexdigest()
        entry['sha_verified'] = git_sha == spec['sha']
        entry['sha256'] = hashlib.sha256(contents).hexdigest()
        if not entry['sha_verified']:
            problems.append(f'SHA mismatch: {rel}')
        if path.suffix == '.zip':
            with zipfile.ZipFile(path) as archive:
                bad = archive.testzip()
                if bad:
                    problems.append(f'corrupt ZIP member: {bad}')
        elif path.name.endswith('.csv.gz'):
            n, invalid, dupe = 0, 0, 0
            seen = seen_by_category.setdefault(spec['category'], set())
            with gzip.open(path, 'rt', encoding='utf-8', newline='') as source:
                reader = csv.DictReader(source)
                fields = reader.fieldnames
                if not fields or len(fields) != len(set(fields)):
                    problems.append(f'invalid CSV header: {rel}')
                    continue
                category = spec['category']
                if category in headers and headers[category] != fields:
                    problems.append(f'schema mismatch: {rel}')
                headers.setdefault(category, fields)
                date_col = next((k for k in ('date', 'datetime', 'timestamp') if k in fields), None)
                id_cols = [k for k in ('stablecoin_id', 'asset_id', 'id', 'price_key', 'chain', 'peg_type', 'pegType') if k in fields]
                for row in reader:
                    n += 1
                    if None in row or any(v is None for v in row.values()):
                        invalid += 1
                        continue
                    if date_col:
                        try:
                            date_ = day(row[date_col])
                            if id_cols:
                                key = tuple(row[k] for k in id_cols) + (date_,)
                                if key in seen:
                                    dupe += 1
                                seen.add(key)
                        except (ValueError, OverflowError, OSError):
                            invalid += 1
            entry.update(actual_rows=n, malformed_rows=invalid, duplicate_keys=dupe)
            if n != spec['rows']:
                problems.append(f'row count mismatch: {rel}: {n} != {spec["rows"]}')
            if invalid or dupe:
                problems.append(f'invalid or duplicate records: {rel}: {invalid} malformed, {dupe} duplicates')
        report.append(entry)
    result = {'files': report, 'checked_files': len(report), 'errors': problems,
              'note': 'ZIP integrity checked; ZIP interior market row count and upstream correctness not asserted.'}
    print(json.dumps(result, indent=2))
    return not problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    validation = sub.add_parser('verify', help='Check archive hashes, schemas and row counts')
    validation.add_argument('root', type=Path, help='Directory containing manifest.json and downloaded files')
    capture = sub.add_parser('collect', help='Create immutable DefiLlama snapshot')
    capture.add_argument('output', type=Path, help='NEW output directory, never overwritten')
    choice = capture.add_mutually_exclusive_group(required=True)
    choice.add_argument('--assets', help='Comma-separated DefiLlama asset IDs')
    choice.add_argument('--all-assets', action='store_true', help='Collect every catalog asset, many API requests')
    capture.add_argument('--market', action='store_true', help='Also preserve market, chain catalog, and price history')
    args = parser.parse_args()
    if args.command == 'verify':
        raise SystemExit(0 if verify(args.root) else 1)
    ids = [x.strip() for x in args.assets.split(',')] if args.assets else []
    collect(args.output, ids, args.all_assets, args.market)


if __name__ == '__main__':
    main()
