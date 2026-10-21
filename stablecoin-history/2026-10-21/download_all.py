#!/usr/bin/env python3
"""Download the stablecoin historical dataset from pinned GitHub blob IDs. Python 3 stdlib."""
import base64, json, pathlib, urllib.request, time, hashlib, gzip, zipfile, sys
REPO="exux23/jianglens"
BASE="https://raw.githubusercontent.com/exux23/jianglens/datasets/stablecoin-history-2026-10-21/stablecoin-history/2026-10-21/"
OUT=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else "stablecoin_history_2026_10_21")
OUT.mkdir(parents=True,exist_ok=True)
def get(url):
 for attempt in range(4):
  try:
   with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"stablecoin-research-downloader"}),timeout=90) as r:return r.read()
  except Exception:
   if attempt==3:raise
   time.sleep(2**attempt)
manifest=json.loads(get(BASE+"manifest.json"))
for i,item in enumerate(manifest["files"],1):
 rel=item["path"]
 target=OUT/rel
 target.parent.mkdir(parents=True,exist_ok=True)
 if target.exists():
  b=target.read_bytes()
 else:
  sha=item["sha"]
  api=f"https://api.github.com/repos/{REPO}/git/blobs/{sha}"
  obj=json.loads(get(api))
  b=base64.b64decode(obj["content"]) if obj.get("encoding")=="base64" else get(BASE+rel)
  target.write_bytes(b)
 expected=item["sha"]
 actual=hashlib.sha1(("blob "+str(len(b))+"\0").encode()+b).hexdigest()
 if actual!=expected:raise RuntimeError(f"Git object hash mismatch on {rel}: {actual} expected {expected}")
 print(f"{i}/{len(manifest['files'])} OK {rel}: {len(b):,} bytes")
(OUT/"manifest.json").write_text(json.dumps(manifest,indent=2))
print(f"Downloaded {len(manifest['files'])} verified files to {OUT.resolve()}")
