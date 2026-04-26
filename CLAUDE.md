# CLAUDE.md — Project context for Claude Code

This file is long-lived context that Claude Code should load on every session in this repo.

## What this project is

A **local-first personal finance tracker** for a single user (India-first, multi-currency). Data lives in a local Postgres database; the app runs in a browser tab on `http://localhost:8000`.

## Canonical docs (read first, every session)

- `SPEC.md` — the buildable product spec. Prioritized MVP/v2/v3 lists, schema, screen-by-screen breakdown, user flows, risks.
- `DECISIONS.md` — the locked stack contract and rationale for each non-obvious choice.
- `screenshots/index.html` — hand-built HTML wireframes for every major screen, sharing one stylesheet. Visual reference for layout, field names, and interaction affordances. Open it in a browser.
- `screenshots/00-sitemap.svg` — IA diagram.

## Tech stack

The stack is locked. See `DECISIONS.md` for the full table and rationale. Summary:

- **Django 6 + Python 3.12** — server-rendered HTML with HTMX 2 + Alpine.js 3 for partial swaps; no JS build step.
- **Postgres 14+** — local instance via Homebrew. `JSONB` for breakdowns, `NUMERIC(20,4)` for money.
- **Tailwind CSS 3** — standalone CLI binary (no Node).
- **Chart.js 4** via CDN for all visualizations.
- **`pytest-django` + `pytest-cov`** for tests, `factory-boy` for fixtures, **Playwright** for one happy-path E2E.
- **`ruff`** for lint + format. **`uv`** for env + deps.
- **`django-q2`** for nightly snapshots and FX refresh.

## Non-negotiable conventions

1. **End-to-end type safety where the language allows.** Type hints on service-layer functions; no untyped `Any` boundaries except where Django itself is dynamic (e.g. form `cleaned_data`).
2. **Money discipline.** Every money value uses `Decimal` via `DecimalField(max_digits=20, decimal_places=4)`. **Never** `float`. Cross-currency arithmetic only goes through `core/money.py`. Totals re-base to the user's `baseCurrency` on read via the FX-rate cache.
3. **Multi-profile from day 1.** Every row carries `profile_id`. The MVP UI exposes only the default profile, but the schema supports multiple.
4. **Snapshots are immutable.** When the user (or a scheduled job) takes a snapshot, serialize the computed breakdown into the snapshot row. Never recompute historical snapshots from current data.
5. **Categories are rows, not enums.** Renaming/adding categories must not orphan transactions.
6. **Local-first, no telemetry.** No network calls except: FX rates (user-triggered or scheduled) and optional live-price fetch (off by default).
7. **Tests before merging a feature.** A feature isn't done until it has at least one service-level unit test against a throwaway DB and one UI test covering the happy path.
8. **Empty states are first-class.** Every screen must render correctly with zero rows.
9. **Write your own UI copy.** Don't copy any third-party app's text verbatim.

## Build status

Phases 0 – 6 are complete. The investments module (broker-agnostic core, generic statement import, lots, prices, XIRR) ships on top of Phase 6.

### Phase 7 — Polish (next up)

- Dark mode toggle (CSS + `prefers-color-scheme` fallback).
- Hide/show values toggle on the topbar.
- Keyboard shortcuts: Cmd-K global search across transactions / assets / liabilities.
- PWA manifest + service worker so the app installs as a standalone window.
- Weekly backup export to a user-chosen folder (e.g. iCloud Drive, Dropbox).
- One Playwright happy-path E2E: open → add asset → see on dashboard → take snapshot → log out.

### Beyond Phase 7 (v2 / v3 ideas in `SPEC.md §2`)

- Live price fetching (opt-in, rate-limited, free public endpoint per asset class).
- Multi-profile UI (schema already supports it).
- Recurring rules with a "confirm-on-date" queue.
- Inflation calculator + future-value goal projection.
- Backup-on-schedule to a user-selected folder.
- Shared access via a second local profile (read-only).
- Rule-based insights, optional local-LLM summary via Ollama.
- Scenario modeling, document vault (encrypted at rest), printable yearly PDF.

## Explicitly out of scope (for now)

- Bank account linking / account aggregator integration.
- Mobile-native apps (PWA only).
- Cloud auth or any multi-machine sync.
- Any LLM-generated insights (deferred to v3, opt-in only).

## Quality bar

- `pytest` passes with ≥70 % statement coverage on the service layer (`app/core/services/`).
- `ruff check` and `ruff format --check` pass.
- One happy-path Playwright test exists.
- No console errors or template warnings in dev.

## How to handle ambiguity

If a requirement is ambiguous or missing, ask the user before coding. Document any non-obvious decision as a one-liner in `DECISIONS.md`.

## When running the app

See `app/README.md` for full instructions. Quick reference:

- **Dev:** `make dev` (or `cd app && uv run python manage.py runserver`)
- **Migrate:** `cd app && uv run python manage.py migrate`
- **Seed:** `cd app && uv run python manage.py seed`
- **Tests:** `cd app && uv run pytest`
- **Background worker (snapshots / FX):** `cd app && uv run python manage.py qcluster`
