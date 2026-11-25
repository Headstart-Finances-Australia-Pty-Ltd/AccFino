"""
backfill_sessions.py  -  run once from the Accfino/ root.

Repairs two problems in existing session folders:
  1. Missing accounts.json  - creates one (bank/account from pickle, files from disk)
  2. accounts.json with empty "files" arrays  - fills them from input/files/ on disk

    python backfill_sessions.py

Safe to re-run: already-correct sessions are skipped.
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT     = Path(__file__).parent          # Accfino/
DATA_DIR = ROOT / "main_app" / "data"

if not DATA_DIR.exists():
    print(f"ERROR: {DATA_DIR} not found - run from the Accfino/ root.")
    sys.exit(1)


def get_disk_files(sess_root: Path) -> list:
    files_dir = sess_root / "input" / "files"
    if not files_dir.exists():
        return []
    return sorted(f.name for f in files_dir.iterdir() if f.is_file())


def distribute_files(accs: list, disk_names: list) -> list:
    n_acc   = len(accs)
    n_files = len(disk_names)
    if n_acc == 0:
        return accs
    if n_files >= n_acc:
        chunk = n_files // n_acc
        for idx, a in enumerate(accs):
            start      = idx * chunk
            end        = start + chunk if idx < n_acc - 1 else n_files
            a["files"] = disk_names[start:end]
    else:
        for a in accs:
            a["files"] = disk_names
    return accs


fixed_missing = 0
fixed_empty   = 0
skipped       = 0

for results_pkl in sorted(DATA_DIR.rglob("output/results/results.pkl")):
    sess_root  = results_pkl.parent.parent.parent
    input_dir  = sess_root / "input"
    acct_file  = input_dir / "accounts.json"
    disk_names = get_disk_files(sess_root)
    username   = sess_root.parent.name
    session_id = sess_root.name

    if acct_file.exists():
        accs = json.loads(acct_file.read_text(encoding="utf-8"))
        if all(len(a.get("files", [])) == 0 for a in accs) and disk_names:
            accs = distribute_files(accs, disk_names)
            acct_file.write_text(json.dumps(accs, indent=2), encoding="utf-8")
            print(f"  Repaired files: {username}/{session_id}  -  "
                  f"{sum(len(a['files']) for a in accs)} file(s) across {len(accs)} account(s)")
            fixed_empty += 1
        else:
            skipped += 1
        continue

    accs = []
    try:
        df = pd.read_pickle(results_pkl)
        if isinstance(df, pd.DataFrame):
            col_map     = {c.lower(): c for c in df.columns}
            bank_col    = col_map.get("bank")
            account_col = col_map.get("account")
            if bank_col and account_col:
                seen = {}
                for _, row in df.iterrows():
                    b = str(row[bank_col]).strip()
                    a = str(row[account_col]).strip()
                    if b and a and (b, a) not in seen:
                        seen[(b, a)] = True
                accs = [{"bank_name": b, "account_number": a, "files": []}
                        for (b, a) in seen]
    except Exception as e:
        print(f"  WARNING: could not read pickle {results_pkl}: {e}")

    if disk_names and accs:
        accs = distribute_files(accs, disk_names)

    input_dir.mkdir(parents=True, exist_ok=True)
    acct_file.write_text(json.dumps(accs, indent=2), encoding="utf-8")
    print(f"  Created:  {username}/{session_id}  -  "
          f"{len(accs)} account(s), {sum(len(a.get('files',[]))for a in accs)} file(s)")
    fixed_missing += 1

print(f"\nDone.  Created {fixed_missing} missing  |  "
      f"Repaired {fixed_empty} empty-files  |  Skipped {skipped} already-correct.")
