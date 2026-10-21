#!/usr/bin/env python3
"""Join downloaded historical stablecoin CSV.gz parts into one gzip CSV."""
import csv, gzip, glob, os, sys
files=sorted(glob.glob(sys.argv[1] if len(sys.argv)>1 else "supply/*.csv.gz"))
if not files:
 raise SystemExit("Download all .csv.gz files and pass glob pattern, e.g. python join.py 'supply/*.csv.gz'")
out="stablecoin_asset_supply_daily_all.csv.gz"
rows=0
with gzip.open(out,"wt",newline="",encoding="utf8") as dst:
 writer=csv.writer(dst)
 for i,filename in enumerate(files):
  with gzip.open(filename,"rt",newline="",encoding="utf8") as src:
   reader=csv.reader(src);header=next(reader)
   if i==0: writer.writerow(header)
   for row in reader:
    writer.writerow(row);rows+=1
print(f"Wrote {out} with {rows:,} rows from {len(files)} files")
