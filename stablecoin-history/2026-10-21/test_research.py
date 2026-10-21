"""Run with: python -m unittest discover -s stablecoin-history/2026-10-21 -p test_*.py"""
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import research
import join


class ResearchTests(unittest.TestCase):
    def test_chain_rows_keep_missing_distinct_from_zero(self):
        asset = {'id': '1', 'symbol': 'USDT', 'chainBalances': {
            'Ethereum': {'tokens': [{'date': 1609459200, 'circulating': {'peggedUSD': 100},
                                      'circulatingUSD': {'peggedUSD': 101},
                                      'unreleased': {'peggedUSD': 0}}]}}}
        row, = list(research.chain_rows(asset))
        self.assertEqual((row['date'], row['circulating'], row['circulating_usd']),
                         ('2021-01-01', '100', '101'))
        self.assertEqual(row['unreleased'], '0')
        self.assertEqual(row['bridged_to'], '')

    def test_nested_bridge_metadata_not_treated_as_peg(self):
        asset = {'id': 1, 'chainBalances': {'Tron': {'tokens': [
            {'date': 1735689600, 'circulating': {'peggedUSD': 50},
             'bridgedTo': {'not-found': {'not-found': {'amount': 5583011}}}}
        ]}}}
        row, = list(research.chain_rows(asset))
        self.assertEqual(row['peg_type'], 'peggedUSD')
        self.assertEqual(row['bridged_to'], '')

    def test_reject_invalid_chain_history(self):
        with self.assertRaises(ValueError):
            list(research.chain_rows({'id': '1', 'chainBalances': {'Ethereum': {'tokens': {}}}}))

    @patch.object(research, 'get_json')
    def test_collect_writes_unambiguous_mapping_and_preserves_raw(self, get):
        catalog = {'peggedAssets': [{'id': '1', 'gecko_id': 'one', 'symbol': 'ONE'},
                                    {'id': '2', 'gecko_id': 'shared', 'symbol': 'TWO'},
                                    {'id': '3', 'gecko_id': 'shared', 'symbol': 'THREE'}]}
        asset = {'id': '1', 'symbol': 'ONE', 'chainBalances': {'Base': {
            'tokens': [{'date': '1735689600', 'circulating': {'peggedUSD': 0}}]}}}
        def fake(endpoint):
            return {'/stablecoins?includePrices=true': catalog, '/stablecoin/1': asset,
                    '/stablecoincharts/all': [], '/stablecoinchains': [],
                    '/stablecoinprices': [{'date': 1735689600,
                                          'prices': {'one': 1, 'shared': 1, 'unknown': 1}}]}[endpoint]
        get.side_effect = fake
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'snapshot'
            research.collect(out, ['1'], market=True)
            with gzip.open(out / 'asset_chain_daily.csv.gz', 'rt') as stream:
                row, = list(csv.DictReader(stream))
            self.assertEqual((row['chain'], row['circulating'], row['bridged_to']), ('Base', '0', ''))
            with (out / 'price_key_mapping.csv').open() as stream:
                mapping = {row['price_key']: row for row in csv.DictReader(stream)}
            self.assertEqual(mapping['one']['stablecoin_id_if_unique'], '1')
            self.assertEqual(mapping['shared']['status'], 'ambiguous')
            self.assertEqual(mapping['unknown']['status'], 'unmatched')
            self.assertTrue((out / 'raw' / 'asset_1.json.gz').is_file())
            with self.assertRaises(FileExistsError):
                research.collect(out, ['1'])

    @patch.object(research, 'get_json')
    def test_collection_failure_does_not_publish_partial_snapshot(self, get):
        get.side_effect = [{'peggedAssets': [{'id': '1'}]}, {'id': '2'}]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'bad'
            with self.assertRaises(ValueError):
                research.collect(path, ['1'])
            self.assertFalse(path.exists())

    def test_verify_detects_corrupted_blob_and_row_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            body = gzip.compress(b'date,asset_id,value\n2024-01-01,1,12\n')
            (root / 'part.csv.gz').write_bytes(body)
            sha = hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest()
            entry = {'path': 'part.csv.gz', 'rows': 1, 'sha': sha, 'category': 'daily_asset_supply'}
            (root / 'manifest.json').write_text(json.dumps({'files': [entry]}))
            with patch('builtins.print'):
                self.assertTrue(research.verify(root))
                entry['rows'] = 2
                (root / 'manifest.json').write_text(json.dumps({'files': [entry]}))
                self.assertFalse(research.verify(root))
                (root / 'part.csv.gz').write_bytes(b'changed')
                with self.assertRaises((gzip.BadGzipFile, OSError)):
                    research.verify(root)

    def test_join_rejects_schema_drift_without_overwriting_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, text in [('a.csv.gz', 'date,id\n2025-01-01,1\n'),
                               ('b.csv.gz', 'timestamp,id\n2025-01-02,1\n')]:
                with gzip.open(root / name, 'wt') as stream:
                    stream.write(text)
            target = root / 'combined.csv.gz'
            target.write_bytes(b'keep me')
            with self.assertRaises(ValueError):
                join.join(str(root / '[ab].csv.gz'), target)
            self.assertEqual(target.read_bytes(), b'keep me')
            with gzip.open(root / 'b.csv.gz', 'wt') as stream:
                stream.write('date,id\n2025-01-02,1\n')
            self.assertEqual(join.join(str(root / '[ab].csv.gz'), target), 2)
            with gzip.open(target, 'rt') as stream:
                self.assertEqual(len(list(csv.reader(stream))), 3)

    def test_market_rows_do_not_treat_missing_as_zero(self):
        series = [{'date': 1735689600, 'totalCirculating': {'peggedUSD': 22},
                   'totalCirculatingUSD': {'peggedUSD': 21}}]
        record, = list(research.market_rows(series))
        self.assertEqual(record['circulating_usd'], '21')
        self.assertEqual(record['bridged_to_usd'], '')

    def test_date_support_and_reject_nonfinite(self):
        self.assertEqual(research.amount('1.1017182', ''), '1.1017182')
        self.assertEqual(research.day('2026-10-21'), '2026-10-21')
        self.assertEqual(research.day('1761004800000'), '2025-10-21')
        with self.assertRaises(ValueError):
            research.amount(float('nan'), 'peggedUSD')


if __name__ == '__main__':
    unittest.main()
