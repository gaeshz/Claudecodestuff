"""Print a one-screen summary of a built edition, for the daily run log.

Usage:
    python tools/edition_stats.py --date 2026-09-07
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from _lib import tmp_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--file", default=None)
    args = ap.parse_args()

    path = Path(args.file) if args.file else tmp_path(f"edition_{args.date}.json")
    if not path.exists():
        sys.exit(f"Not found: {path}")
    ed = json.loads(path.read_text(encoding="utf-8"))

    deep = briefs = 0
    per_section = []
    publishers = Counter()
    for sec in ed.get("sections", []):
        items = sec.get("items", [])
        d = sum(1 for it in items if it.get("type") == "deep")
        b = sum(1 for it in items if it.get("type") == "brief")
        deep += d
        briefs += b
        if items:
            per_section.append((sec.get("slug"), d, b))
        for it in items:
            for s in it.get("sources", []):
                if (s or {}).get("publisher"):
                    publishers[s["publisher"]] += 1

    threads = ed.get("threads", [])
    status = Counter(t.get("status") for t in threads)

    fh_path = tmp_path(f"feed_health_{args.date}.json")
    failed_feeds = []
    if fh_path.exists():
        failed_feeds = [h["feed"] for h in json.loads(fh_path.read_text(encoding="utf-8"))
                        if h.get("status") != "ok"]

    print(f"EDITION {ed.get('date')} - {ed.get('masthead', {}).get('edition_label', '')}")
    print(f"  {deep} deep dives, {briefs} briefs, {len(ed.get('need_to_know', []))} need-to-know bullets")
    print(f"  sections with content: {len(per_section)}")
    for slug, d, b in per_section:
        print(f"    {slug:28} {d} deep / {b} brief")
    print(f"  threads touched: {len(threads)}  "
          f"(new {status.get('new', 0)}, trend {status.get('trend', 0)}, one_day {status.get('one_day', 0)})")
    for t in threads:
        tl = t.get("timeline") or ([t["timeline_add"]] if t.get("timeline_add") else [])
        print(f"    [{t.get('status'):7}] {t.get('slug')}  (+{len(tl)} this edition)")
    print(f"  distinct publishers cited: {len(publishers)}")
    top = ", ".join(f"{p}({n})" for p, n in publishers.most_common(8))
    print(f"    top: {top}")
    if failed_feeds:
        print(f"  feeds failed today: {', '.join(failed_feeds)}")


if __name__ == "__main__":
    main()
