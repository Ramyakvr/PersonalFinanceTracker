# DECISIONS

> The stack contract. Every non-obvious choice made for this project lives here as a one-liner. If a later phase needs to amend an entry, amend it in the same commit that uses the new decision — do not let this file drift.

## Stack (Phase 0)

| Category | Decision | Why |
|---|---|---|
| Language | Python 3.12 | User's primary comfort language. |
| Web framework | Django 6.0 (latest stable as of scaffold) | Batteries-included: ORM, migrations, forms, free admin panel for CRUD debugging, best fit for a 15-screen CRUD app. |
| Frontend interactivity | HTMX 2 + Alpine.js 3 | Server-rendered HTML with partial swaps. No JS build step needed for any wireframe in `screenshots/`. |
| Styling | Tailwind CSS 3 via standalone CLI | Same utility-class vocabulary as `screenshots/_shell.css`. No Node required — the standalone binary does JIT. |
| Database | PostgreSQL 14+ (localhost) | Native `JSONB` for `breakdownJson` / `percentByClass` / `templateJson`. Exact `NUMERIC(20,4)` for money. User already has 14.18 via Homebrew. |
| ORM | Django ORM | Schema in `SPEC.md §4` maps 1:1. |
| Charts | Chart.js 4 via CDN | Covers every viz the dashboard needs (donut, line, bar). No build step. |
| Forms | Django Forms + `django-crispy-forms` + `crispy-tailwind` | Server-validated; Tailwind-rendered fields. |
| Money | `DecimalField(max_digits=20, decimal_places=4)` in every money column | Python `Decimal` is exact. Never use `float`. `core/money.py` is the only path for cross-currency arithmetic. |
| Dates | `datetime` stdlib + `zoneinfo` | No third-party date library needed. |
| Scheduling | `django-q2` (Django-native task queue, DB-backed broker) | For nightly snapshots + FX refresh. Runs as `python manage.py qcluster`. Phase 7 wraps it in `launchd`. |
| Testing | `pytest-django` + `pytest-cov`; `factory-boy` for fixtures; Playwright for one happy-path E2E | ≥70% coverage gate on the service layer per `CLAUDE.md` quality bar. |
| Lint/format | `ruff` (lint + format) | One tool, fast. |
| Dep + env mgmt | `uv` (astral.sh) | Fast, modern pyproject.toml workflow. |
| Runtime target | Local web app in a browser tab at `http://localhost:8000` | User's answer: Mac-only, no desktop shell. |
| Packaging | None for Phase 0. PWA manifest + service worker in Phase 7. | Matches user's answer. |
| Monorepo tooling | None — single Django project in `app/`. | Lowest-complexity shape that fits. |

## Resolutions of open questions

Pragmatic calls made on ambiguous requirements get appended here as one-liners.

## Ambiguity policy

When a requirement is ambiguous during a phase, ask the user before coding. Append a one-liner to this file documenting any non-obvious decision.
