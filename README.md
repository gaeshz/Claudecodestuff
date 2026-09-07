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
