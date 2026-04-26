# PersonalFinanceTracker

Local-first personal finance tracker. Django 6 + PostgreSQL + HTMX + Tailwind CSS.

See the repo root for the canonical product docs (`CLAUDE.md`, `SPEC.md`, `DECISIONS.md`).

## Prerequisites (one-time)

```bash
# Python 3.12 and uv
# uv: https://docs.astral.sh/uv/getting-started/installation/
curl -LsSf https://astral.sh/uv/install.sh | sh

# Postgres (any recent version; 14+ tested)
brew install postgresql@14
brew services start postgresql@14
createdb personal_finance
```

Copy `.env.example` to `.env` and adjust the connection string to match your local Postgres role.

```bash
cp .env.example .env
```

## Install dependencies

```bash
uv sync
```

## Commands

| Task | Command |
|---|---|
| **dev** (Django + Tailwind watcher) | `./scripts/dev.sh` |
| **dev (Django only)** | `uv run python manage.py runserver` |
| **migrate** | `uv run python manage.py migrate` |
| **seed** | `uv run python manage.py seed` |
| **build** (compile Tailwind once) | `./bin/tailwindcss -i static/css/tailwind.css -o static/css/tailwind.out.css --minify` |
| **test** | `uv run pytest` |
| **lint** | `uv run ruff check . && uv run ruff format --check .` |
| **check** (Django system checks) | `uv run python manage.py check` |
| **scheduler** (nightly snapshots, FX refresh — Phase 4+) | `uv run python manage.py qcluster` |

## First run

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py seed
./bin/tailwindcss -i static/css/tailwind.css -o static/css/tailwind.out.css
uv run python manage.py runserver
```

Open http://localhost:8000/ — you should see "Finance is running" with DB: ok, base currency INR, profile "Self".

Admin (optional): `uv run python manage.py createsuperuser`, then visit http://localhost:8000/admin/.

## Layout

```
app/
  finance/         Django project settings
  core/            First app: User, Profile, FxRate, money helper, hello view
  templates/       Global templates (base.html) and app-scoped subdirs
  static/css/      Tailwind source + compiled output
  bin/tailwindcss  Standalone Tailwind CLI binary (gitignored)
  scripts/dev.sh   Runs Django + Tailwind watcher in parallel
  pyproject.toml   uv-managed deps
  pytest.ini       Test config with 70% coverage gate on core/
  .ruff.toml       Lint + format config
```

## Phase status

Phases 0–6 are complete (MVP + investments). Phase 7 (polish: dark mode, hide-values toggle, Cmd-K search, PWA, scheduled backups, one Playwright E2E) is next. See the root `CLAUDE.md` for the live status.
