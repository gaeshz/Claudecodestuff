"""Merge, canonicalize, and de-duplicate the day's raw items into candidate clusters.

Inputs (from .tmp/, by date):
    rss_<date>.json           required  -- output of fetch_rss.py
    search_hits_<date>.json    optional  -- items the agent gathered via WebSearch,
                                            same item shape (title/url/source/...);
                                            a bare list or {"items": [...]}.

Also reads (optional):
    .tmp/seen_urls.json       a list of canonical URLs already used in past
                              editions; matching candidates are dropped. Updated
                              by tools/mark_published.py at publish time, not here.

Output:
    .tmp/candidates_<date>.json  -- clusters sorted by a rough salience score:
        {cluster_id, headline, section_hint, urls[], sources[], titles[],
         published (earliest ISO), summary, corroboration (int), age_hours,
         already_seen (bool, always false in output), score}

The agent does final selection and section placement; this step only reduces
noise and surfaces which stories multiple outlets are carrying.

Usage:
    python tools/normalize_dedupe.py
    python tools/normalize_dedupe.py --date 2026-09-07 --max-age-days 3
    python tools/normalize_dedupe.py --similarity 88
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone

try:
    from rapidfuzz import fuzz
except ImportError:
    sys.exit("Missing dependency: rapidfuzz. Run: pip install -r requirements.txt")

from _lib import tmp_path

STOP_TITLE_TAIL = re.compile(r"\s+[-|–—]\s+[^-|–—]{1,40}$")  # " - Publisher"


def norm_title(title: str) -> str:
    t = STOP_TITLE_TAIL.sub("", title)
    t = re.sub(r"[^a-z0-9 ]+", " ", t.lower())
    t = re.sub(r"\s+", " ", t).strip()
    return t


def load_items(date: str) -> list[dict]:
    rss_path = tmp_path(f"rss_{date}.json")
    hits_path = tmp_path(f"search_hits_{date}.json")
    if not rss_path.exists() and not hits_path.exists():
        sys.exit(
            f"No input: need {rss_path.name} (run tools/fetch_rss.py) or "
            f"{hits_path.name} (agent-written WebSearch hits). In the cloud routine, "
            f"RSS is blocked - write search_hits_<date>.json from WebSearch results."
        )
    items = []
    if rss_path.exists():
        items = json.loads(rss_path.read_text(encoding="utf-8")).get("items", [])

    if hits_path.exists():
        blob = json.loads(hits_path.read_text(encoding="utf-8"))
        hits = blob.get("items", blob) if isinstance(blob, dict) else blob
        for h in hits or []:
            if h.get("url") and h.get("title"):
                h.setdefault("source", "web_search")
                h.setdefault("section_hint", None)
                h.setdefault("published", None)
                h.setdefault("summary", "")
                h.setdefault("via", "web_search")
                items.append(h)
    return items


def age_hours(published: str | None, now: datetime) -> float | None:
    if not published:
        return None
    try:
        return round((now - datetime.fromisoformat(published)).total_seconds() / 3600, 1)
    except ValueError:
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--max-age-days", type=int, default=4,
                    help="Drop dated items older than this. Undated items are kept.")
    ap.add_argument("--similarity", type=int, default=82,
                    help="rapidfuzz token_set_ratio threshold for merging titles (0-100).")
    ap.add_argument("--limit", type=int, default=70,
                    help="Max clusters in the compact shortlist (multi-source clusters are always kept).")
    ap.add_argument("--per-section", type=int, default=10,
                    help="Max single-source clusters per section_hint in the shortlist.")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    max_age_h = args.max_age_days * 24

    seen_path = tmp_path("seen_urls.json")
    seen: set[str] = set()
    if seen_path.exists():
        try:
            seen = set(json.loads(seen_path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError):
            seen = set()

    items = load_items(args.date)

    # Pre-filter: by URL (already seen), by age.
    kept: list[dict] = []
    dropped_seen = dropped_age = 0
    for it in items:
        if it["url"] in seen:
            dropped_seen += 1
            continue
        ah = age_hours(it.get("published"), now)
        if ah is not None and ah > max_age_h:
            dropped_age += 1
            continue
        it["_norm"] = norm_title(it["title"])
        it["_age_h"] = ah
        if len(it["_norm"]) >= 8:
            kept.append(it)

    # Greedy clustering on normalized titles.
    clusters: list[list[dict]] = []
    for it in sorted(kept, key=lambda x: len(x["_norm"]), reverse=True):
        placed = False
        for cl in clusters:
            if fuzz.token_set_ratio(it["_norm"], cl[0]["_norm"]) >= args.similarity:
                cl.append(it)
                placed = True
                break
        if not placed:
            clusters.append([it])

    out_clusters = []
    for i, cl in enumerate(clusters):
        urls, sources, titles = [], [], []
        for m in cl:
            if m["url"] not in urls:
                urls.append(m["url"])
            if m["source"] and m["source"] not in sources:
                sources.append(m["source"])
            titles.append(m["title"])
        dated = [m["_age_h"] for m in cl if m["_age_h"] is not None]
        hints = [m["section_hint"] for m in cl if m.get("section_hint")]
        section_hint = max(set(hints), key=hints.count) if hints else None
        summary = max((m["summary"] for m in cl), key=len, default="")
        published = min(
            (m["published"] for m in cl if m.get("published")), default=None
        )
        corroboration = len(sources)
        age_h = min(dated) if dated else None

        recency_score = 0.0 if age_h is None else max(0.0, 1.0 - age_h / max_age_h)
        score = round(2.0 * corroboration + 3.0 * recency_score + 0.5 * len(cl), 3)

        out_clusters.append({
            "cluster_id": f"{args.date}-c{i:03d}",
            "headline": sorted(cl, key=lambda m: len(m["title"]))[len(cl) // 2]["title"],
            "section_hint": section_hint,
            "urls": urls,
            "sources": sources,
            "titles": titles,
            "published": published,
            "age_hours": age_h,
            "summary": summary,
            "corroboration": corroboration,
            "cluster_size": len(cl),
            "score": score,
        })

    out_clusters.sort(key=lambda c: c["score"], reverse=True)

    # Compact shortlist for the agent: every multi-source cluster + the top N
    # overall, with per-section caps so no single beat dominates. The agent
    # reads this first and drills into `clusters` only when it needs more.
    def compact(c: dict) -> dict:
        return {k: c[k] for k in (
            "cluster_id", "headline", "section_hint", "sources",
            "corroboration", "age_hours", "score", "summary", "urls",
        )}

    shortlist, per_section = [], {}
    for c in out_clusters:
        sec = c["section_hint"] or "_none"
        is_ms = c["corroboration"] > 1
        if is_ms or (per_section.get(sec, 0) < args.per_section and len(shortlist) < args.limit):
            shortlist.append(compact(c))
            per_section[sec] = per_section.get(sec, 0) + 1

    out = {
        "date": args.date,
        "generated_at": now.isoformat(),
        "params": {
            "similarity": args.similarity, "max_age_days": args.max_age_days,
            "limit": args.limit, "per_section": args.per_section,
        },
        "counts": {
            "input_items": len(items),
            "kept_items": len(kept),
            "clusters": len(out_clusters),
            "shortlist": len(shortlist),
            "dropped_already_seen": dropped_seen,
            "dropped_too_old": dropped_age,
            "multi_source_clusters": sum(1 for c in out_clusters if c["corroboration"] > 1),
        },
        "shortlist": shortlist,
        "clusters": out_clusters,
    }
    out_path = tmp_path(f"candidates_{args.date}.json")
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"{len(items)} items -> {len(out_clusters)} clusters "
        f"({out['counts']['multi_source_clusters']} multi-source) | "
        f"dropped {dropped_seen} seen, {dropped_age} old\nwrote {out_path}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
