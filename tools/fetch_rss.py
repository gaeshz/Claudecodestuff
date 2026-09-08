"""Fetch the day's candidate stories from RSS/Atom feeds and Google News queries.

Deterministic discovery layer for the daily edition. No API keys required.

  - Static feeds come from config/sources.yaml
  - Query-based discovery hits Google News RSS (no key) using config/queries.yaml

Output: .tmp/rss_<date>.json  -- a flat list of normalized items:
    {title, url, source, section_hint, published (ISO or null), summary, via}

Feeds that are dead, moved, or return junk are logged and skipped; the run
still succeeds. Feed health is written to .tmp/feed_health_<date>.json so the
daily workflow can track which feeds to prune.

Usage:
    python tools/fetch_rss.py                 # today, all sections
    python tools/fetch_rss.py --date 2026-09-07
    python tools/fetch_rss.py --section semiconductors --section ai_emerging
    python tools/fetch_rss.py --window 1d     # tighter Google News recency window
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus, urlparse, urlunparse, parse_qsl, urlencode

try:
    import feedparser
except ImportError:
    sys.exit("Missing dependency: feedparser. Run: pip install -r requirements.txt")

try:
    import httpx
except ImportError:
    sys.exit("Missing dependency: httpx. Run: pip install -r requirements.txt")

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: pyyaml. Run: pip install -r requirements.txt")

from _lib import ROOT, tmp_path

CONFIG = ROOT / "config"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36 IndustryIntel/1.0"
)
GOOGLE_NEWS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_name", "utm_reader", "guccounter", "guce_referrer",
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "cmpid", "ncid", "oc",
}


def load_yaml(name: str) -> dict:
    path = CONFIG / name
    if not path.exists():
        sys.exit(f"Config not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def canonical_url(url: str) -> str:
    """Strip tracking params and fragments; lowercase host. Best-effort."""
    if not url:
        return url
    try:
        parts = urlparse(url.strip())
        query = [(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in TRACKING_PARAMS]
        cleaned = parts._replace(
            netloc=parts.netloc.lower(),
            query=urlencode(query),
            fragment="",
        )
        out = urlunparse(cleaned)
        return out.rstrip("/") if out.count("/") > 2 else out
    except ValueError:
        return url


def parse_date(entry) -> str | None:
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc).isoformat()
            except (TypeError, ValueError):
                continue
    return None


def fix_text(text: str) -> str:
    """Repair the U+FFFD that Google News RSS emits in place of smart quotes,
    and normalize whitespace."""
    if not text:
        return ""
    text = re.sub(r"(?<=\w)�(?=\w)", "'", text)   # China<?>s -> China's
    text = text.replace("�", "'")
    text = re.sub(r"\s+", " ", text).strip()
    return text


TITLE_TAIL = re.compile(r"\s+-\s+[^-]{2,40}$")


def clean_title(raw: str) -> str:
    """Strip the ' - Publisher' tail Google News appends, then repair text."""
    return fix_text(TITLE_TAIL.sub("", raw or ""))


def entry_source(entry, configured: str | None, feed_title: str, feed_url: str) -> str:
    src = entry.get("source") or {}
    if isinstance(src, dict) and src.get("title"):
        return fix_text(src["title"])
    if configured:
        return configured
    m = re.search(r"\s+-\s+([^-]{2,40})$", entry.get("title", "") or "")
    if m:
        return fix_text(m.group(1))
    return feed_title or urlparse(feed_url).netloc


def clean_summary(entry) -> str:
    raw = entry.get("summary", "") or ""
    # feedparser gives HTML; strip tags crudely and collapse whitespace.
    text = re.sub(r"<[^>]+>", " ", raw)
    return fix_text(text)[:600]


def fetch_one(client: httpx.Client, url: str) -> tuple[bytes | None, str]:
    try:
        resp = client.get(url, follow_redirects=True, timeout=20.0)
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}"
        if not resp.content or len(resp.content) < 200:
            return None, "empty body"
        return resp.content, "ok"
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def collect_feed(client, url, source, section_hint, via, cutoff, health):
    raw, status = fetch_one(client, url)
    if raw is None:
        health.append({"feed": source or url, "url": url, "status": status, "items": 0})
        print(f"  [skip] {source or url}: {status}", file=sys.stderr)
        return []
    parsed = feedparser.parse(raw)
    entries = parsed.entries or []
    items = []
    feed_title = parsed.feed.get("title", "") if parsed.feed else ""
    for e in entries:
        link = canonical_url(e.get("link", ""))
        title = clean_title(e.get("title", ""))
        if not link or not title:
            continue
        published = parse_date(e)
        if published and cutoff and datetime.fromisoformat(published) < cutoff:
            continue
        items.append({
            "title": title,
            "url": link,
            "source": entry_source(e, source, feed_title, url),
            "section_hint": section_hint,
            "published": published,
            "summary": clean_summary(e),
            "via": via,
        })
    health.append({"feed": source or url, "url": url, "status": "ok", "items": len(items)})
    print(f"  [ok]   {source or url}: {len(items)} items", file=sys.stderr)
    return items


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                    help="Edition date, YYYY-MM-DD (default: today)")
    ap.add_argument("--section", action="append", dest="sections",
                    help="Limit to these section slugs (repeatable). Default: all.")
    ap.add_argument("--window", default=None,
                    help="Google News recency window (1d/2d/7d). Default: from queries.yaml.")
    ap.add_argument("--max-age-days", type=int, default=4,
                    help="Drop items older than this many days when a date is available.")
    args = ap.parse_args()

    sources_cfg = load_yaml("sources.yaml")
    queries_cfg = load_yaml("queries.yaml")
    window = args.window or queries_cfg.get("default_window", "2d")
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.max_age_days)

    wanted = set(args.sections) if args.sections else None
    health: list[dict] = []
    items: list[dict] = []

    with httpx.Client(headers={"User-Agent": USER_AGENT}) as client:
        print("Static feeds:", file=sys.stderr)
        for feed in sources_cfg.get("feeds", []):
            hint = feed.get("section_hint")
            if wanted and hint not in wanted:
                continue
            items += collect_feed(
                client, feed["url"], feed.get("source"), hint, "feed", cutoff, health
            )
            time.sleep(0.3)

        print("Google News queries:", file=sys.stderr)
        for slug, block in (queries_cfg.get("sections") or {}).items():
            if wanted and slug not in wanted:
                continue
            for query in (block or {}).get("google_news", []):
                q = quote_plus(f"{query} when:{window}")
                url = GOOGLE_NEWS.format(q=q)
                items += collect_feed(
                    client, url, None, slug, f"google_news:{query}", None, health
                )
                time.sleep(0.4)

    # Dedupe within this fetch by canonical URL, keeping the richest record.
    by_url: dict[str, dict] = {}
    for it in items:
        cur = by_url.get(it["url"])
        if cur is None or (len(it["summary"]) > len(cur["summary"])):
            by_url[it["url"]] = it
    deduped = list(by_url.values())

    out = {
        "date": args.date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": window,
        "counts": {
            "raw": len(items),
            "deduped": len(deduped),
            "feeds_ok": sum(1 for h in health if h["status"] == "ok"),
            "feeds_failed": sum(1 for h in health if h["status"] != "ok"),
        },
        "items": deduped,
    }
    out_path = tmp_path(f"rss_{args.date}.json")
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path(f"feed_health_{args.date}.json").write_text(
        json.dumps(health, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(
        f"\n{out['counts']['raw']} raw -> {out['counts']['deduped']} deduped items | "
        f"feeds ok {out['counts']['feeds_ok']}, failed {out['counts']['feeds_failed']}\n"
        f"wrote {out_path}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
