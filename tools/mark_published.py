"""Append every source URL in a published edition to the rolling seen-URLs ledger.

Run this immediately AFTER a successful publish. normalize_dedupe.py reads
.tmp/seen_urls.json and drops candidates whose URL is already there, so this is
what stops the same story resurfacing in tomorrow's edition.

The ledger is capped (default 4000 most-recent URLs) so it cannot grow forever.

Usage:
    python tools/mark_published.py                  # today
    python tools/mark_published.py --date 2026-09-07
    python tools/mark_published.py --file .tmp/edition_2026-09-07.json --cap 5000
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from _lib import tmp_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--file", default=None)
    ap.add_argument("--cap", type=int, default=4000)
    args = ap.parse_args()

    path = Path(args.file) if args.file else tmp_path(f"edition_{args.date}.json")
    if not path.exists():
        sys.exit(f"Not found: {path}")
    ed = json.loads(path.read_text(encoding="utf-8"))

    new_urls: list[str] = []
    for sec in ed.get("sections", []):
        for it in sec.get("items", []):
            for s in it.get("sources", []):
                u = (s or {}).get("url")
                if isinstance(u, str) and u.startswith("http"):
                    new_urls.append(u)

    ledger_path = tmp_path("seen_urls.json")
    existing: list[str] = []
    if ledger_path.exists():
        try:
            existing = json.loads(ledger_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, TypeError):
            existing = []

    # newest last; dedupe preserving order
    merged = existing + [u for u in new_urls if u not in set(existing)]
    if len(merged) > args.cap:
        merged = merged[-args.cap:]

    ledger_path.write_text(json.dumps(merged, indent=0, ensure_ascii=False), encoding="utf-8")
    print(
        f"ledger: +{len(set(new_urls) - set(existing))} new URLs, {len(merged)} total "
        f"(cap {args.cap})\nwrote {ledger_path}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
