"""Merge one database into another by hand (nothing is deleted in the target).

    python -m db_app.sync_standby --from 0 --to 1     # main -> first standby (also creates its tables)
    python -m db_app.sync_standby --from 1 --to 0     # standby -> main

Numbers: 0 = DATABASE_URL, 1 = first DATABASE_STANDBY_URLS address, 2 = second ...
Run it once after adding a standby so it starts out as a full copy.
"""
import argparse
import json
import sys

from db_app import dbsync
from db_app.database import failover

p = argparse.ArgumentParser()
p.add_argument("--from", dest="src", type=int, required=True)
p.add_argument("--to", dest="dst", type=int, required=True)
a = p.parse_args()
n = failover.count
if not (0 <= a.src < n and 0 <= a.dst < n) or a.src == a.dst:
    sys.exit(f"Pick two different database numbers between 0 and {n - 1} ({n} configured).")
print(f"Merging database {a.src} -> {a.dst} ...")
r = dbsync.merge(a.src, a.dst)
print(json.dumps(r, indent=2))
sys.exit(0 if r["ok"] else 1)
