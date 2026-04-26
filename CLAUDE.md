# CLAUDE.md — Project context for Claude Code

This file is long-lived context that Claude Code should load on every session in this repo.

## What this project is

A **local-first personal finance tracker** for a single user (India-first, multi-currency). Inspired by finboom.app but self-hosted, with data living in a local SQLite file.

## Canonical docs (read first, every session)

- `FEATURES.md` — full feature inventory derived from a walk-through of finboom.app. Categories, subtypes, every form field, every visualization, and a section (§7) listing open questions that are **not** verified.
- `SPEC.md` — the buildable product spec. Opinionated tech stack, prioritized MVP/v2/v3 lists, full Prisma schema, screen-by-screen breakdown, user flows, risks.
- `screenshots/index.html` — hand-built HTML wireframes for every major screen, sharing one stylesheet. Visual reference for layout, field names, and interaction affordances. Open it in a browser.
- `screenshots/00-sitemap.svg` — IA diagram.

When there is any disagreement, `SPEC.md` wins over `FEATURES.md` (SPEC is the "what we're building", FEATURES is "what finboom does").

## Stack — to be decided collaboratively

**The tech stack is NOT frozen.** `SPEC.md §3` lists one opinionated proposal (React + Vite + Hono + Prisma + SQLite + Recharts + dinero.js + Vitest + Playwright) — treat it as a starting straw-man, not a contract.

Before Phase 0 scaffolding, Claude Code must have an explicit stack conversation with the user covering:

- **Runtime:** web-only, desktop (Tauri/Electron), both, mobile (React Native), or native?
- **Front-end framework:** React vs. Svelte/SvelteKit vs. Solid vs. Vue vs. something else. Build tool (Vite / Next.js / Remix / Astro / SvelteKit).
- **UI primitives:** shadcn/ui, Radix, Mantine, Chakra, Park UI, raw Tailwind, or a custom kit.
- **Styling:** Tailwind vs. CSS Modules vs. vanilla-extract vs. Panda.
- **Charts:** Recharts vs. Chart.js vs. Visx vs. ECharts vs. D3-direct.
- **State / data:** TanStack Query + Zustand, Redux Toolkit, Jotai, Signals, or a single-store pattern. Forms: React Hook Form + Zod vs. Formik vs. TanStack Form vs. native.
- **Back-end shape:** separate API (Hono / Express / Fastify / NestJS) vs. embedded (Next.js Route Handlers, SvelteKit endpoints, Tauri commands) vs. SQLite-in-browser (no backend) via `sql.js` / `wa-sqlite` / `absurd-sql`.
- **Language runtime:** Node vs. Bun vs. Deno.
- **Database:** SQLite (file) vs. SQLite (browser via WASM) vs. Postgres (overkill for local-first?) vs. DuckDB. ORM: Prisma vs. Drizzle vs. Kysely vs. raw SQL.
- **Money library:** `dinero.js` vs. `big.js` vs. `decimal.js` vs. integer-minor-units convention.
- **Dates:** `date-fns` vs. `dayjs` vs. Luxon vs. Temporal polyfill.
- **Scheduling:** `node-cron` vs. a simple `setInterval` vs. OS scheduler integration.
- **Testing:** Vitest vs. Jest vs. Node:test. E2E: Playwright vs. Cypress. Component: React Testing Library vs. Testing Library alternatives.
- **Lint/format:** Biome vs. ESLint + Prettier.
- **Monorepo tooling:** pnpm + turborepo vs. Nx vs. single package vs. Deno workspaces.
- **Packaging:** Tauri vs. Electron vs. pure PWA vs. web-only.

Claude Code should propose a stack with trade-offs (complexity, ecosystem maturity, offline story, binary size, build time, learning curve), hear the user's constraints (familiarity, target machines, bundle size, battery concerns), and only then lock a choice. Write the final decision to `DECISIONS.md` as a short rationale — that decision then becomes the contract for subsequent phases.

## Non-negotiable conventions (stack-agnostic)

These survive regardless of which stack is chosen:

1. **End-to-end type safety.** Whatever language/DB layer is picked, types must flow from the source of truth (DB schema / API contract) to the client without hand-written duplicates. No `any`, no unchecked casts except at serialization boundaries (with a comment).
2. **Money discipline.** Every money value uses a decimal-safe representation (a decimal library, a minor-units integer, or equivalent) — **never** a JS `number` / float. Totals re-base to the user's `baseCurrency` on read via an FX rate cache.
3. **Multi-profile from day 1.** Every row carries `profileId`. Even though v1 exposes only one profile in the UI, the schema supports multiple.
4. **Snapshots are immutable.** When the user (or a scheduled job) takes a snapshot, serialize the computed breakdown into the snapshot row. Never recompute historical snapshots from current data.
5. **Categories are rows, not enums.** Renaming/adding categories must not orphan transactions.
6. **Local-first, no telemetry.** No network calls except: FX rates (user-triggered or scheduled) and optional live-price fetch (off by default).
7. **Tests before merging a feature.** A feature isn't done until it has at least one service-level unit test against a throwaway DB and one UI test covering the happy path.
8. **Empty states are first-class.** Every screen must render correctly with zero rows.
9. **Do not copy finboom's copy verbatim.** Use your own wording in UI strings.

## How to handle ambiguity

If a requirement is ambiguous or missing, check `FEATURES.md §7 Open Questions` first. If the question is listed there, make a pragmatic choice and document it in a new `DECISIONS.md` file (one-liner per decision). If it isn't, ask the user in chat before coding.

## Build phases (MVP)

Follow these phases in order. Do not jump ahead. Each phase ends with a runnable demo + tests. Tool names mentioned below (cron, form libraries, etc.) should be replaced with whatever equivalents the chosen stack uses — the **work** per phase is fixed, the **tools** are not.

- **Phase 0 — Stack decision + scaffolding:** (a) Have the stack conversation per the "Stack" section above; write the decision to `DECISIONS.md`. (b) Scaffold the chosen repo shape (monorepo if needed, or single package). (c) Configure the chosen lint/format/test tools. (d) Wire up the chosen back-end (or prove the no-back-end path) with a trivial "hello" round-trip. Verify with one command that runs the dev environment end-to-end.
- **Phase 1 — DB + Auth:** Implement the data model from `SPEC.md §4` (the Prisma syntax there is illustrative — translate it faithfully to whatever ORM / schema tool was chosen). Migrations + a seed script: 1 default User + 1 default Profile + system Categories + a Default AllocationTarget. App-lock PIN hashing (Argon2 or the chosen stack's equivalent). No external auth.
- **Phase 2 — Assets + Liabilities CRUD:** Wizard (category grid → form), list page with search and tag/currency filters, edit, delete. Service layer + API (or equivalent) + pages. Match the field list in `FEATURES.md §3.2 / §3.3`. Reference wireframes `03-asset-wizard.html` and `04-liability-wizard.html`.
- **Phase 3 — Transactions (Expenses + Income):** Multi-row add form, period-chip filters, list, edit, delete. Categories in Settings → Preferences (exempt toggles). Recurring *rules* UI can be Phase-2 v2 — in MVP just show the flag on transactions. Reference `07-expenses.html` and `08-expense-form.html`.
- **Phase 4 — Net worth, allocation, dashboard:** Compute net worth and allocation from assets/liabilities in base currency via the FX-rate cache. Snapshots (manual + nightly auto via the chosen scheduling primitive). Dashboard widgets (KPI cards, donut, cashflow mini, top holdings, rule-based insights). Reference `01-dashboard.html`, `05-allocation.html`, `06-snapshots.html`.
- **Phase 5 — Goals + Essentials:** Goal CRUD with linked asset classes and optional specific-asset linkage. Projection math (FV = PV × (1+r)^n, where `r` is assumed real return; allow user override). Essentials 4 cards with user-settable targets. Reference `09-goals.html` and `10-essentials.html`.
- **Phase 6 — Import/Export + Settings:** Generic CSV import for Assets/Transactions (Append vs Update-by-Name). Full JSON export. Settings tabs: Account, Preferences, Recurring, Data, Plan & Billing (placeholder). Reference `12-import.html` and `11-settings.html`.
- **Phase 7 — Polish:** Dark mode, hide/show values toggle, keyboard shortcuts (Cmd-K search), PWA manifest + service worker (if a web-deliverable was chosen), weekly backup export to a user-chosen folder.

## Explicitly out of scope for MVP

- Bank account linking / account aggregator integration
- Broker-specific CSV adapters (deferred to v2)
- Live price fetching (deferred to v2)
- Multi-profile UI (schema supports it; UI exposes only default profile)
- Shared access, collaborative features
- Mobile-native apps (PWA only)
- Any LLM-generated insights (deferred to v3, opt-in only)

## Quality bar

Command names below are placeholders — the chosen package manager / task runner will define the actual scripts. What matters is that equivalents exist and pass.

- Unit + service tests pass with ≥70% statement coverage on the DB-facing service layer.
- Strict type-checking passes (TypeScript strict, or the chosen language's equivalent).
- Lint passes; `any`/unsafe escape hatches are banned outside explicitly justified boundaries.
- One happy-path end-to-end test exists: open app, add asset, see it on dashboard, take snapshot, log out.
- No console errors or UI-framework warnings in dev.

## When running the app

The chosen stack will define the exact scripts. Whatever they are, ensure these capabilities exist and are documented in the root README:

- **Dev:** one command that starts the full dev environment (front-end, back-end if any, DB tools).
- **Migrate:** one command to apply schema changes.
- **Seed:** one command to seed defaults.
- **Build:** one command for a production build.
- **Desktop shell (Phase 7+):** one command if a desktop packaging was chosen.
