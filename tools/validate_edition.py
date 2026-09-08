"""Schema + completeness gate for a finished edition, run before publishing.

Reads .tmp/edition_<date>.json and checks it against the contract the Artifact
page expects. Exits 0 if clean, 1 with a numbered list of problems otherwise so
the agent can fix and re-run.

Edition JSON contract
---------------------
{
  "date": "YYYY-MM-DD",
  "generated_at": "<ISO8601>",
  "masthead": {"title": str, "edition_label": str},
  "need_to_know": [str, ...],                 # 3-8 bullets
  "sections": [
    {
      "slug": str,                            # from config/sections.yaml
      "title": str,
      "items": [
        {
          "story_id": str,                    # unique across the edition
          "type": "deep" | "brief",
          "headline": str,
          "dek": str,                         # one sentence
          "thread_ref": str | null,           # thread slug; if set, must be in "threads"
          "thread_status": "new" | "one_day" | "trend",
          "sources": [{"title": str, "publisher": str, "url": str}, ...],  # >= 1
          "analysis": {                       # REQUIRED for type "deep", omit for "brief"
            "what_happened": str,
            "why_it_matters": str,
            "whats_changing": str,
            "business_implications": str,
            "operational_supply_chain": str,  # "" allowed when not applicable
            "ai_tech_disruption": str,
            "opportunities_risks": str,
            "exec_questions": [str, ...],      # 3-5
            "develop_your_pov": [str, ...],    # >= 3 prompts
            "trend_note": str                 # "" allowed when the story is new
          }
        }
      ]
    }
  ],
  "threads": [
    {
      "slug": str, "title": str, "section": str,
      "status": "new" | "one_day" | "trend",
      "first_seen": "YYYY-MM-DD", "last_seen": "YYYY-MM-DD",
      "summary": str,
      "timeline_add": {"date": "YYYY-MM-DD", "edition_date": "YYYY-MM-DD",
                       "note": str, "story_id": str}
    }
  ]
}

Usage:
    python tools/validate_edition.py                 # today
    python tools/validate_edition.py --date 2026-09-07
    python tools/validate_edition.py --file .tmp/edition_2026-09-07.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency: pyyaml. Run: pip install -r requirements.txt")

from _lib import ROOT, tmp_path

ANALYSIS_KEYS = [
    "what_happened", "why_it_matters", "whats_changing", "business_implications",
    "operational_supply_chain", "ai_tech_disruption", "opportunities_risks",
    "exec_questions", "develop_your_pov", "trend_note",
]
MAY_BE_EMPTY = {"operational_supply_chain", "trend_note"}
THREAD_STATUS = {"new", "one_day", "trend"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DEEP_BAND = (6, 10)


def load_section_slugs() -> list[str]:
    cfg = yaml.safe_load((ROOT / "config" / "sections.yaml").read_text(encoding="utf-8"))
    return [s["slug"] for s in cfg.get("sections", [])]


def is_url(v) -> bool:
    return isinstance(v, str) and v.startswith(("http://", "https://"))


def nonempty_str(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--file", default=None, help="Explicit path; overrides --date.")
    args = ap.parse_args()

    path = Path(args.file) if args.file else tmp_path(f"edition_{args.date}.json")
    if not path.exists():
        sys.exit(f"Not found: {path}")

    try:
        ed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"Invalid JSON: {exc}")

    problems: list[str] = []
    warnings: list[str] = []
    known_slugs = set(load_section_slugs())

    # ---- top level ----
    if not DATE_RE.match(str(ed.get("date", ""))):
        problems.append("top-level 'date' missing or not YYYY-MM-DD")
    mast = ed.get("masthead") or {}
    if not nonempty_str(mast.get("title")):
        problems.append("masthead.title missing")
    if not nonempty_str(mast.get("edition_label")):
        problems.append("masthead.edition_label missing")

    ntk = ed.get("need_to_know")
    if not isinstance(ntk, list) or not (3 <= len(ntk) <= 8):
        problems.append("need_to_know must be a list of 3-8 bullets")
    elif not all(nonempty_str(b) for b in ntk):
        problems.append("need_to_know has empty bullets")

    sections = ed.get("sections")
    if not isinstance(sections, list) or not sections:
        sys.exit("sections missing or empty - nothing to validate")

    # ---- threads index ----
    threads = ed.get("threads") or []
    thread_slugs = set()
    for i, th in enumerate(threads):
        loc = f"threads[{i}]"
        slug = th.get("slug")
        if not nonempty_str(slug):
            problems.append(f"{loc}.slug missing")
            continue
        if slug in thread_slugs:
            problems.append(f"{loc}.slug '{slug}' duplicated")
        thread_slugs.add(slug)
        if th.get("status") not in THREAD_STATUS:
            problems.append(f"{loc}.status must be one of {sorted(THREAD_STATUS)}")
        for k in ("title", "section", "summary"):
            if not nonempty_str(th.get(k)):
                problems.append(f"{loc}.{k} missing")
        if th.get("section") not in known_slugs:
            warnings.append(f"{loc}.section '{th.get('section')}' is not a known section slug")
        for k in ("first_seen", "last_seen"):
            if not DATE_RE.match(str(th.get(k, ""))):
                problems.append(f"{loc}.{k} not YYYY-MM-DD")
        add = th.get("timeline_add") or {}
        if not nonempty_str(add.get("note")) or not nonempty_str(add.get("story_id")):
            problems.append(f"{loc}.timeline_add needs 'note' and 'story_id'")

    # ---- sections & items ----
    seen_ids: set[str] = set()
    deep_count = 0
    seen_slugs: set[str] = set()

    for si, sec in enumerate(sections):
        loc = f"sections[{si}]"
        slug = sec.get("slug")
        if not nonempty_str(slug):
            problems.append(f"{loc}.slug missing")
            continue
        seen_slugs.add(slug)
        if slug not in known_slugs:
            warnings.append(f"{loc}.slug '{slug}' is not in config/sections.yaml")
        if not nonempty_str(sec.get("title")):
            problems.append(f"{loc}.title missing")
        items = sec.get("items")
        if not isinstance(items, list):
            problems.append(f"{loc}.items must be a list")
            continue
        if slug == "need_to_know":
            continue  # narrative-only section, bullets live in need_to_know

        for ii, it in enumerate(items):
            iloc = f"{loc}.items[{ii}]"
            sid = it.get("story_id")
            if not nonempty_str(sid):
                problems.append(f"{iloc}.story_id missing")
            elif sid in seen_ids:
                problems.append(f"{iloc}.story_id '{sid}' duplicated")
            else:
                seen_ids.add(sid)

            if it.get("type") not in {"deep", "brief"}:
                problems.append(f"{iloc}.type must be 'deep' or 'brief'")
            for k in ("headline", "dek"):
                if not nonempty_str(it.get(k)):
                    problems.append(f"{iloc}.{k} missing")

            srcs = it.get("sources")
            if not isinstance(srcs, list) or not srcs:
                problems.append(f"{iloc}.sources must be a non-empty list")
            else:
                for sj, s in enumerate(srcs):
                    if not is_url((s or {}).get("url")):
                        problems.append(f"{iloc}.sources[{sj}].url invalid")
                    if not nonempty_str((s or {}).get("publisher")):
                        warnings.append(f"{iloc}.sources[{sj}].publisher missing")

            tref = it.get("thread_ref")
            if tref is not None:
                if not nonempty_str(tref):
                    problems.append(f"{iloc}.thread_ref must be a slug string or null")
                elif tref not in thread_slugs:
                    problems.append(
                        f"{iloc}.thread_ref '{tref}' has no matching entry in 'threads' "
                        f"(a referenced thread must be updated in this edition)"
                    )
            if it.get("thread_status") not in THREAD_STATUS:
                problems.append(f"{iloc}.thread_status must be one of {sorted(THREAD_STATUS)}")

            if it.get("type") == "deep":
                deep_count += 1
                an = it.get("analysis")
                if not isinstance(an, dict):
                    problems.append(f"{iloc}.analysis missing (required for deep dives)")
                    continue
                for k in ANALYSIS_KEYS:
                    if k not in an:
                        problems.append(f"{iloc}.analysis.{k} missing")
                        continue
                    v = an[k]
                    if k in ("exec_questions", "develop_your_pov"):
                        if not isinstance(v, list):
                            problems.append(f"{iloc}.analysis.{k} must be a list")
                        elif k == "exec_questions" and not (3 <= len(v) <= 5):
                            problems.append(f"{iloc}.analysis.exec_questions needs 3-5 items")
                        elif k == "develop_your_pov" and len(v) < 3:
                            problems.append(f"{iloc}.analysis.develop_your_pov needs >= 3 prompts")
                        elif not all(nonempty_str(x) for x in v):
                            problems.append(f"{iloc}.analysis.{k} has empty entries")
                    elif k in MAY_BE_EMPTY:
                        if not isinstance(v, str):
                            problems.append(f"{iloc}.analysis.{k} must be a string")
                    elif not nonempty_str(v):
                        problems.append(f"{iloc}.analysis.{k} is empty")
            elif it.get("type") == "brief" and "analysis" in it:
                warnings.append(f"{iloc} is a brief but carries an 'analysis' block")

    # ---- edition-level checks ----
    for required in ("top_stories", "need_to_know", "consultant_lens"):
        if required not in seen_slugs:
            problems.append(f"required section '{required}' is missing from the edition")

    if not (DEEP_BAND[0] <= deep_count <= DEEP_BAND[1]):
        problems.append(
            f"deep-dive count is {deep_count}; expected {DEEP_BAND[0]}-{DEEP_BAND[1]} "
            f"(edit DEEP_BAND / config/scoring.yaml if the target changed)"
        )

    # ---- report ----
    for w in warnings:
        print(f"  warning: {w}", file=sys.stderr)
    if problems:
        print(f"\nFAILED - {len(problems)} problem(s):", file=sys.stderr)
        for n, p in enumerate(problems, 1):
            print(f"  {n:2d}. {p}", file=sys.stderr)
        sys.exit(1)

    print(
        f"OK - {len(sections)} sections, {len(seen_ids)} stories "
        f"({deep_count} deep dives), {len(threads)} threads updated. "
        f"{len(warnings)} warning(s).",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
