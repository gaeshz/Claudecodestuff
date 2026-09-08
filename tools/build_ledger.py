"""Build .tmp/seen_urls.json from recently published editions.

The dedup ledger lives in .tmp/ (disposable), so a fresh checkout - notably the
scheduled cloud run - starts with no memory of what was already published. This
tool rebuilds it from the Artifact database's own recent editions.

Workflow: at step 4 of workflows/daily_edition.md, dump recent editions to a
directory with `Artifact read_db ... out_dir=.tmp/recent`, then run this.

    python tools/build_ledger.py --dir .tmp/recent
    python tools/build_ledger.py --dir .tmp/recent --cap 4000

It scans every *.json under --dir for objects carrying a `sources` list (edition
docs and story docs both do) and writes the union of their URLs to
.tmp/seen_urls.json. Safe to run repeatedly; merges with any existing ledger.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _lib import tmp_path


def urls_in(obj, acc: set) -> None:
    if isinstance(obj, dict):
        if isinstance(obj.get("sources"), list):
            for s in obj["sources"]:
                u = (s or {}).get("url") if isinstance(s, dict) else None
                if isinstance(u, str) and u.startswith("http"):
                    acc.add(u)
        for v in obj.values():
            urls_in(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            urls_in(v, acc)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=".tmp/recent", help="Directory of dumped edition/story JSON.")
    ap.add_argument("--cap", type=int, default=4000)
    args = ap.parse_args()

    root = Path(args.dir)
    if not root.exists():
        sys.exit(f"Not found: {root} (dump recent editions there first)")

    found: set[str] = set()
    n = 0
    for f in root.rglob("*.json"):
        try:
            urls_in(json.loads(f.read_text(encoding="utf-8")), found)
            n += 1
        except (json.JSONDecodeError, OSError):
            continue

    ledger_path = tmp_path("seen_urls.json")
    existing: list[str] = []
    if ledger_path.exists():
        try:
            existing = json.loads(ledger_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, TypeError):
            existing = []

    merged = existing + [u for u in sorted(found) if u not in set(existing)]
    if len(merged) > args.cap:
        merged = merged[-args.cap:]
    ledger_path.write_text(json.dumps(merged, indent=0, ensure_ascii=False), encoding="utf-8")
    print(f"scanned {n} files, {len(found)} URLs found -> ledger now {len(merged)} entries\nwrote {ledger_path}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
