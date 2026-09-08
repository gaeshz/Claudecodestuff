# Workflow: Daily Edition

## Objective

Produce today's edition of the personalized **CMT & High-Tech Industry Intelligence**
platform: a curated, analyzed, learning-oriented briefing published into the Artifact
database. The reader is a management consultant building deep industry knowledge and a
differentiated point of view. This is a **learning system, not a link list** - every deep
dive must teach: what happened, why it matters, what is structurally changing, the business
implications, and the questions executives should be asking. Related stories must be
connected over time so a one-day event is distinguishable from an emerging trend.

## Required inputs

None. The workflow is self-contained. It needs only the tools in `tools/`, the config in
`config/`, the built-in `WebSearch` / `WebFetch` tools, and the `Artifact` tool bound to
the platform Artifact (see `## Artifact` below for the URL).

## Artifact

- **URL:** https://claude.ai/code/artifact/af38e52a-e04f-4904-ad6d-92ebdd13993e
  (also in the `.artifact_url` file at the repo root)
- Capabilities: `db` (edition + thread + POV storage) and `sample` (in-page "ask Claude").
- The daily run only calls `Artifact` `read_db` / `write_db`. It does **not** republish the
  HTML - the page reads everything live from the database.

## Where this runs

- **Locally (manual):** all tools work. Follow every step.
- **In the scheduled cloud routine (CCR):** the egress proxy **blocks RSS** - all feed
  hosts and Google News return `403`, so `fetch_rss.py` produces nothing. `WebSearch` and
  `WebFetch` work normally (they route through the Anthropic API). Also **do not pass
  `out_dir` to `Artifact read_db`** - the file-save triggers a permission prompt the routine
  cannot answer. Read continuity data inline instead. The cloud path is: skip step 1, do a
  thorough step 2, read the DB inline in step 3, then continue normally.

## Steps

### 1. Fetch discovery feeds  *(local only - skip in the cloud routine)*
```
python tools/fetch_rss.py --date <YYYY-MM-DD> --window 2d
```
Writes `.tmp/rss_<date>.json` and `.tmp/feed_health_<date>.json`. Note any feeds that
failed for the lessons-learned log, but do not stop. If this returns almost nothing
(cloud), that is expected - rely entirely on step 2.

### 2. Targeted web search per section
For each section in `config/sections.yaml`, run the `web_search` queries from
`config/queries.yaml`. **In the cloud this is the only discovery mechanism**, so be
thorough: run all of a section's `web_search` queries plus its `google_news` queries
reworded as WebSearch queries (e.g. `semiconductor foundry capacity investment news
this week`), plus 3-5 free-form searches for what is clearly breaking today
(`biggest technology news today`, `major AI announcement this week`, etc.). Aim for
80-150 distinct candidate items.

Collect results as `{title, url, source, published, summary}` and write them to
`.tmp/search_hits_<date>.json` (shape: a bare list, or `{"items": [...]}`).

Aim for genuine breadth: primary announcements, analyst/consulting research, and
serious independent analysis - not just wire copy.

### 3. Load continuity context from the Artifact
- `Artifact` `read_db` `get` `meta/latest` -> last edition date.
- `read_db` `list` on `threads` (`query.limit` 200) -> open storylines with their
  timelines and summaries. Keep these in context; you match today's stories against them
  in step 8.
- `read_db` `list` on `editions` (`query.limit` 7) -> recent edition docs. `list` does
  **not** accept `order_by`; it returns docs by id (which is the date), so the last
  entries are the most recent. Read their `sections[].items[].headline` and `.sources`
  inline to see what was already covered.
- Build the dedup ledger:
  - **Local:** `read_db` those editions with `out_dir=.tmp/recent`, then
    `python tools/build_ledger.py --dir .tmp/recent`.
  - **Cloud (no `out_dir`):** for each recent edition doc, save its JSON yourself with the
    `Write` tool to `.tmp/recent/<date>.json`, then run `build_ledger.py` the same way.
    Or skip the ledger and dedupe against the recent headlines by judgment in step 5.

### 4. Normalize & de-duplicate
```
python tools/normalize_dedupe.py --date <YYYY-MM-DD>
```
Reads `.tmp/rss_<date>.json` + `.tmp/search_hits_<date>.json` + the ledger from step 3.
Writes `.tmp/candidates_<date>.json` with:
- `shortlist` - compact, de-duplicated, section-capped, already-published stories removed.
  **Start here.**
- `clusters` - the full ranked set. Drill in when the shortlist is thin for a section.

`corroboration` = number of distinct publishers carrying the story. Higher = more likely
real and important. Press-wire pile-ons (many low-tier outlets, identical copy) are **not**
corroboration - judge source quality, see `config/scoring.yaml`.

### 5. Select and place stories
Apply the rubric in `config/scoring.yaml`. Targets (see `config/sections.yaml`
`deep_dive_target` per section):
- **6-10 deep dives total** across the edition (hard band - `validate_edition.py` enforces).
- **20-30 briefs** total.
- Every section present. Keep each section to <= 6 items.
- Prioritize: new + important + relevant + corroborated. Drop rumor, pure PR, and
  already-covered-nothing-new (per `drop_when`).
- A story already in an open thread should usually become a **deep dive** if today
  materially advances it.

### 6. Read the primary sources
For every deep dive, `WebFetch` the best 1-3 sources (prefer the primary announcement +
one analytical source). For briefs, the cluster summary usually suffices; `WebFetch` if the
headline is ambiguous or the claim is surprising. If key sources are paywalled and you
cannot verify, lower `confidence` and say so.

### 7. Write the analysis
Every **deep dive** gets the full scaffold below. Every **brief** gets `headline`, `dek`
(one sharp sentence), `sources`, `thread_ref`/`thread_status`, and nothing else.

**Deep-dive `analysis` object (all keys required; see contract in `tools/validate_edition.py`):**

| key | what to write |
|---|---|
| `what_happened` | The facts, plainly. 2-4 sentences. No spin. |
| `why_it_matters` | Significance for the industry - the "so what". |
| `whats_changing` | The underlying shift, not the event. What is different now vs. 12 months ago? |
| `business_implications` | Concretely: revenue, cost, margin, competitive position, operating model. Name who wins and who is squeezed. |
| `operational_supply_chain` | Operations / manufacturing / supply-chain angle. `""` only if genuinely none. |
| `ai_tech_disruption` | Could AI or an adjacent technology change the economics or the business model here? Be specific, not hand-wavy. |
| `opportunities_risks` | The openings this creates and the exposures it opens up. |
| `exec_questions` | 3-5 sharp questions a board or C-suite should be asking. Not generic. |
| `develop_your_pov` | 4-6 prompts addressed to the reader to build their own view. Always include a variant of: *what would I tell a client about this?* |
| `trend_note` | How today connects to earlier entries in the thread. `""` only if the story is brand new. |

Writing standard: specific, falsifiable, and useful in a client conversation. Prefer
numbers and named companies. Cut hedging. If you are uncertain, say what would change your
read.

### 8. Thread matching (connect developments over time)
For every story (deep and brief):
- Search existing threads (`slug`, `title`, `summary`) for a match. **Reuse the thread** if
  the story is the same storyline. Only open a new thread for a genuinely new storyline.
- Set `thread_ref` to the thread slug (kebab-case, stable, e.g. `taiwan-chip-diplomacy`).
- Set `thread_status`:
  - `new` - thread created today.
  - `one_day` - isolated; no clear follow-through yet.
  - `trend` - promote per `config/scoring.yaml` `trend_detection` (3+ entries across
    editions, or multiple independent developments pointing the same way, or a visible
    structural driver).
- **Every `thread_ref` you use must have a matching entry in the edition's `threads` array**
  with a `timeline_add` (validator enforces this). For reused threads, also update
  `status`, `last_seen`, and `summary` to reflect today.
- The `consultant_lens` section should explicitly call out which threads are now trends and
  what pattern connects them.

### 9. Assemble the edition JSON
Write `.tmp/edition_<date>.json` per the contract in `tools/validate_edition.py` (docstring
has the full shape). Key points:
- `need_to_know`: 4-6 terse, high-signal bullets - the "could I speak to this in a meeting"
  layer. This is the only content of the `need_to_know` section.
- `masthead.edition_label`: e.g. `"Monday, September 8, 2026"`.
- `story_id`: `"<date>-NNN"`, unique, stable within the edition.
- Order sections per `config/sections.yaml`. Order items within a section by importance.

### 10. Validate
```
python tools/validate_edition.py --date <YYYY-MM-DD>
```
Fix every problem and re-run until it exits `OK`. Warnings are advisory but check them.

### 11. Publish to the Artifact database
Use `Artifact` `write_db` (`batch` where possible). Write, in this order:
1. For each deep dive: `editions/<date>/stories/<story_id>` = the full item object
   (headline, dek, sources, thread info, `analysis`).
2. `editions/<date>` = the edition minus the deep-dive `analysis` blobs: masthead,
   `need_to_know`, and `sections[]` where each item carries
   `{story_id, type, headline, dek, thread_ref, thread_status, sources}` (briefs carry
   everything; deep dives reference their story doc). Include `date`, `generated_at`.
3. For each thread in `threads[]`: `read_db` `threads/<slug>`; merge - append
   `timeline_add` to `timeline`, update `status` / `last_seen` / `summary`; if absent,
   create with `first_seen = today` and `timeline = [timeline_add]`. `write_db` `set`.
4. `meta/latest` = `{ "date": "<date>", "updated_at": "<ISO>" }`  (write LAST - the page
   keys off this).

### 12. Update the seen-URL ledger
```
python tools/mark_published.py --date <YYYY-MM-DD>
```

### 13. Log a run summary
```
python tools/edition_stats.py --date <YYYY-MM-DD>
```
Report: sections, deep-dive and brief counts, new vs. continuing threads, feeds that
failed, anything notable. Append durable lessons to `## Edge cases & lessons learned`.

## Expected output

In the Artifact database:
- `editions/<date>` and `editions/<date>/stories/*`
- `threads/*` created or updated
- `meta/latest` pointing at `<date>`

The reader opens the Artifact and sees today's edition, can drill into any deep dive,
follow any thread's timeline, answer the `develop_your_pov` prompts (saved to `pov/<slug>`),
and ask Claude in-page to pressure-test their thinking.

## Selection rubric (quick reference)

Keep if: materially new **and** consequential for CMT / high-tech **and** useful to a
consultant. Corroborated by credible sources. Advances a thread or opens a real new one.

Drop if: rumor without sourcing; PR republication with no consequence; already covered with
nothing to add; consumer/culture news with no industry-structure angle.

When two stories compete for the last deep-dive slot, pick the one that (a) advances an
existing trend, or (b) a client is more likely to raise this month.

## Edge cases & lessons learned

- **The scheduled cloud routine (CCR) cannot fetch RSS.** Verified on the 2026-09-08 test
  run: the egress proxy `403`s every feed host and Google News; only pypi/npm/GitHub/the
  Anthropic API are allowlisted. `fetch_rss.py` returns ~nothing there. `WebSearch` /
  `WebFetch` work. So in the cloud, discovery is WebSearch-only - see "Where this runs".
- **`Artifact read_db` with `out_dir` prompts for permission** and stalls the routine
  (it has no way to answer). Never use `out_dir` in the cloud path; read inline or
  `Write` the JSON yourself. Plain `read_db` / `write_db` (incl. `batch`) do **not** prompt.
- **`read_db` `list` rejects `order_by`** - that is `query`-only. `list` returns docs by
  id; since edition ids are dates, the tail of the list is the most recent.
- **Google News RSS is the discovery backbone.** Static feeds in `config/sources.yaml` are
  a supplement; several are low-yield or dead. `AnandTech` was removed (shut down 2025).
  Feeds that failed on the 2026-09-07 build: `AI News` (SSL failure), `Fierce Wireless`,
  `Telecoms.com`, `IndustryWeek`, `Knowledge at Wharton` (may be transient - recheck).
  Feeds returning 0 items are usually fine (age cutoff), but `SemiAnalysis` and
  `IEEE Spectrum AI` have been persistently empty - verify the URLs. Re-check
  `feed_health_<date>.json` each run and prune monthly.
- **Google News item summaries are useless** (just "{title} &nbsp; {publisher}"). Rely on
  the headline, the corroboration count, and `WebSearch`/`WebFetch` for substance - not the
  `summary` field on google_news-sourced clusters.
- **Brief source URLs from clusters are often `news.google.com/rss/articles/...` redirect
  links.** They resolve, but a URL-resolution step in `normalize_dedupe.py` (follow the
  redirect, keep the publisher's canonical URL) would materially improve link quality.
  Until then, prefer `WebSearch` result URLs for anything you make a deep dive.
- **Google News emits `U+FFFD` in place of smart quotes** in some titles; `fetch_rss.py`
  repairs the common `word<?>word` case. Occasional artifacts survive - clean them when
  quoting a headline verbatim.
- **`when:2d` is noisy** - lots of press-wire and regional-outlet pile-ons (especially
  Indian IT trade blogs). Lean on `corroboration` by *credible* publisher and on your own
  judgment, not raw cluster size.
- **Thin sections** (`comms_media`, `challenges_opportunities` were thin on the first run) -
  supplement aggressively with `WebSearch` in step 2.
- **`write_db` from a scheduled cloud run** is the one link not yet proven end-to-end. If it
  fails, capture the exact error and fall back to committing `.tmp/edition_<date>.json` to
  the repo for a manual publish.
