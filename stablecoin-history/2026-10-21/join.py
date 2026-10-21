#!/usr/bin/env python3
"""Losslessly join compatible CSV.gz shards, with schema checks and atomic output."""
import argparse
import csv
import glob
import gzip
import os
from pathlib import Path
import tempfile


def join(pattern, target):
    paths = sorted(Path(p) for p in glob.glob(pattern))
    if not paths:
        raise ValueError(f'no input files match {pattern!r}')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix='.join-', suffix='.csv.gz', dir=target.parent,
                                     delete=False) as buffer:
        temp = Path(buffer.name)
    try:
        with gzip.open(temp, 'wt', encoding='utf-8', newline='') as dest:
            writer = csv.writer(dest)
            header = None
            count = 0
            for path in paths:
                if path.resolve() == target.resolve():
                    raise ValueError('output would be included among input files')
                with gzip.open(path, 'rt', encoding='utf-8', newline='') as source:
                    reader = csv.reader(source)
                    new_header = next(reader, None)
                    if not new_header or len(new_header) != len(set(new_header)):
                        raise ValueError(f'invalid header in {path}')
                    if header is None:
                        header = new_header
                        writer.writerow(header)
                    elif header != new_header:
                        raise ValueError(f'conflicting columns in {path}')
                    for row in reader:
                        if len(row) != len(header):
                            raise ValueError(f'malformed CSV row in {path}')
                        writer.writerow(row)
                        count += 1
        os.replace(temp, target)
        return count
    finally:
        temp.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pattern', nargs='?', default='supply/*.csv.gz')
    parser.add_argument('--output', type=Path, default=Path('stablecoin_asset_supply_daily_all.csv.gz'))
    args = parser.parse_args()
    print(f'Joined {join(args.pattern, args.output):,} rows into {args.output}')
