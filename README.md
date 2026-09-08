# my work — WAT framework

A **WAT** (Workflows, Agents, Tools) project. Probabilistic AI handles reasoning;
deterministic code handles execution. See [CLAUDE.md](CLAUDE.md) for the full
architecture and operating rules.

## Layout

```
workflows/   Markdown SOPs — objective, inputs, tools to call, outputs, edge cases
tools/       Python scripts that do the actual work (APIs, transforms, file/db ops)
.tmp/        Disposable intermediates (scraped data, exports). Regenerated as needed.
.env         API keys and secrets (gitignored — never store secrets elsewhere)
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env          # then fill in real values
```

## How work happens

1. Agent reads the relevant file in `workflows/`.
2. Agent gathers required inputs, then calls the matching script in `tools/`.
3. Deliverables go to cloud services; everything in `.tmp/` is throwaway.

## Adding a workflow

Copy `workflows/_template.md`, fill it in. Don't overwrite existing workflows
without being asked.

## Adding a tool

Drop a script in `tools/`. Keep it deterministic, testable, and runnable
standalone (`python tools/your_tool.py --help`).

---

## The CMT Briefing — daily industry intelligence platform

A daily, curated, learning-oriented briefing for the communications, media,
technology and high-tech industries. Each morning a scheduled agent runs
[`workflows/daily_edition.md`](workflows/daily_edition.md), which discovers and
analyses the day's developments and publishes a new edition into a Claude Artifact.

- **Read it:** https://claude.ai/code/artifact/af38e52a-e04f-4904-ad6d-92ebdd13993e
  (also in [`.artifact_url`](.artifact_url))
- **No API keys required.** Discovery uses RSS + Google News RSS
  ([`tools/fetch_rss.py`](tools/fetch_rss.py)); synthesis is done by the agent
  itself; the Artifact stores editions, storylines and your own notes in its
  built-in database.

### Run an edition by hand

```bash
python tools/fetch_rss.py --date $(date +%F)           # -> .tmp/rss_<date>.json
python tools/normalize_dedupe.py --date $(date +%F)    # -> .tmp/candidates_<date>.json
# then ask Claude Code to execute workflows/daily_edition.md for that date:
#   reads the candidates, runs targeted web searches, writes .tmp/edition_<date>.json
python tools/validate_edition.py --date $(date +%F)    # gate before publish
# Claude writes the edition to the Artifact DB, then:
python tools/mark_published.py --date $(date +%F)
python tools/edition_stats.py --date $(date +%F)
```

### Config ([`config/`](config/))

| file | what it controls |
|---|---|
| `sections.yaml` | the ~13 edition sections, their scope and guiding questions |
| `sources.yaml`  | curated RSS/Atom feeds (Google News queries are the resilient backbone) |
| `queries.yaml`  | per-section Google News + WebSearch queries |
| `scoring.yaml`  | the agent's selection rubric and trend-promotion rules |

### Automation

The morning run is a **Claude Code cloud routine** (`/schedule`). It needs this
repo on GitHub. Cron: `0 12 * * *` UTC ≈ 5:00 AM Pacific during PDT (edition ready
by 7 AM); shift to `0 13 * * *` for PST, or accept the one-hour DST drift.
