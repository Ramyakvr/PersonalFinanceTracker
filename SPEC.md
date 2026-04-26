# PersonalFinanceTracker — Product Spec

> Product framing, scope, flows, and risks for a **local-first** personal finance tracker.
> Tech stack lives in `DECISIONS.md`. Schema lives in `app/core/models.py`. Phase status lives in `CLAUDE.md`.
> All UI copy is written from scratch; no third-party app text is reproduced verbatim.

---

## 1. Product Summary

A single-user (optionally multi-profile) **wealth & money tracker** that runs entirely on the user's machine. One user records assets, liabilities, expenses, income, and goals via structured forms, and gets a dashboard of net worth, asset allocation, cashflow, a financial-health score, and goal progress.

**Design principles**

1. **Local-first.** Data never leaves the machine by default. Local Postgres database; no cloud calls except opt-in FX/price fetches.
2. **Type-safe boring stack.** Server-rendered HTML with progressive enhancement; no JS build step. Decimal money math throughout.
3. **Hand-entered, not scraped.** No bank credentials. CSV import and broker statement normalizers only.
4. **Deterministic computations.** Net worth, allocation, savings rate, SIP plan are all pure functions of stored rows — trivially testable.
5. **India-first defaults, currency-flexible.** INR default, NSE/BSE symbols, EPF/PPF/NPS/SSY/SGB in the taxonomy, but multi-currency built in from day 1.
6. **PWA-ready.** Installable, offline, with an optional app-lock PIN (Phase 7).

**Non-goals:** bank account sync, Plaid/account-aggregator integration, real-time trading, tax filing, AI advisor.

## 2. Scope

### MVP — shipped (Phases 0–6)

- Single local user with profile-scoped data; multi-profile schema in place from day 1.
- Assets CRUD with the full 8-category taxonomy (Stocks & Equity, Gold & Silver, Bonds & Debt, Real Estate, Retirement, Cash & Savings, Alternatives, Other) and per-category subtypes (`core/subtypes.py`).
- Liabilities CRUD with the 9-category taxonomy.
- Transactions CRUD (expenses & income) with row-based multi-entry, categories, tags, notes.
- Tags, custom categories, exempt categories.
- Net Worth time-series via **manual snapshots** + **nightly auto-snapshot** (`django-q2`).
- Asset Allocation donut: actual vs target (editable target preset). Monthly SIP plan calculation.
- Goals: create, target amount/date, link to asset classes or specific assets; progress & projection.
- Essentials health score: Emergency Fund (months covered), Savings Rate, Term Cover adequacy, Health Cover adequacy.
- Dashboard with KPI widgets: net worth, total assets, total liabilities, invested, financial health score, asset allocation donut, cashflow mini-chart, top holdings, goals progress.
- Investments module on top of Phase 6: broker-agnostic core, generic statement import, lots, prices, XIRR.
- Import: generic CSV (Assets, Liabilities, Transactions) with Append / Update-by-Name modes, and broker statement adapters under `core/services/imports/`.
- Export: JSON full dump + CSV per table.
- Multi-currency: per-row currency + base currency; FX rates via local cache refreshed on demand (manual + scheduled).
- Inflation calculator.

### v2 (planned)

- Live price fetch for Direct Stock / ETFs (opt-in, with per-symbol caching, clearly rate-limited; use a free public endpoint).
- Multi-profile UI (Self / Spouse / Joint) — schema already supports it.
- Recurring rules with cadences (monthly, weekly, yearly, custom cron) and automatic generation of upcoming transactions with "confirm on date" queue.
- Search across transactions / assets / liabilities with a global spotlight (Cmd-K).
- Backup to a user-selected folder (e.g. Dropbox, iCloud Drive) — export on schedule.
- Dark/light theme toggle and show/hide values toggle (Phase 7 polish).

### v3

- Shared access via a second local profile with read-only permissions (and an optional encrypted LAN-sync between two machines).
- Insights engine: rule-based first (e.g. "spend in Entertainment up 40% MoM"), with an opt-in local LLM summary using Ollama.
- Scenario modeling: "what if I add ₹X to SIPs for 5 years".
- Document vault: attach PDFs/images to assets/liabilities (policy docs, sale deeds, etc.), stored encrypted at rest.
- Reports: printable yearly PDF with charts.

## 3. Top User Flows

1. **First-run onboarding** — create local user → set display name → choose base currency → (optional) set 4-digit PIN → create default Profile ("Self") → land on empty dashboard with "Add your first asset" CTA.
2. **Add an asset (Direct Stock)** — Wealth → Assets → Add Asset → pick Stocks & Equity → pick Direct Stock → fill symbol / quantity / avg buy / current value → save → redirected to Assets list with the new row and an updated Net Worth KPI.
3. **Add a liability & link EMI** — Wealth → Liabilities → Add Liability → Home Loan → fill name / outstanding / EMI / rate / start date → save → an entry appears in Recurring (v2) that will prompt the user each month to log the EMI as an expense.
4. **Record a month's expenses (multi-row)** — Money → Add → toggle Expense → add 5 rows with date/category/amount → mark rent as Recurring → Save → see Cashflow widget refresh.
5. **Take a net-worth snapshot** — Wealth → Net Worth → Take New Snapshot → a point is appended to the time-series chart. Auto-snapshot also fires nightly.
6. **Create a goal and track progress** — Essentials → Goals → + New Goal → "Retirement 2045", ₹5 Cr, Net Worth (all assets) → goal card shows % complete, required monthly SIP, and projected shortfall/surplus.
7. **Set target allocation & see SIP plan** — Wealth → Allocation → Edit target → e.g. 60/20/10/5/5 → the SIP plan widget recomputes how much to add to each class this month to converge.
8. **Bulk import from broker statement** — Import → choose source → upload → preview canonicalized rows → Append vs Update-by-Name → commit → import job logged.

## 4. Risks & Mitigations

- **Multi-currency correctness.** JS-style float for money would bite; all money goes through `Decimal` and `core/money.py`, with property tests for round-trip conversions.
- **FX rate staleness.** Totals shift when base currency toggles. Mitigation: cache rates per day in `FxRate`, show "as of" timestamp under any base-currency total.
- **Live prices.** Free endpoints break/ratelimit. Mitigation: opt-in per symbol, cache aggressively, fall back to last manual `unitPrice`.
- **Snapshot drift.** If users change historical data, old snapshots disagree with new computations. Mitigation: snapshots are immutable records of the computed state at `takenAt`; `breakdownJson` is serialized so charts don't re-compute.
- **Schema drift as features land.** Free-form enums (subtype, linkedAssetClass) are string-typed; migrations + service-layer tests guard against regressions.
- **Single-user assumption vs. multi-profile.** `profileId` is on every table from day 1 — retrofitting later would have been expensive.
- **Data loss.** Local DB without backups is risky. Mitigation: full JSON export + per-table CSV export; weekly auto-export to a user-chosen folder is on the v2 list.
- **Security of PIN/app-lock.** Argon2-hash the PIN; rate-limit attempts; optional wipe on N failures.
- **Scope creep on Insights.** Keep insights purely rule-based (e.g. "spend up 20% MoM", "emergency fund < 3 months"). Anything LLM-shaped is v3 and opt-in.
- **Category migration.** Renaming a default category must not orphan transactions. Categories are rows (not enums) — already handled.
