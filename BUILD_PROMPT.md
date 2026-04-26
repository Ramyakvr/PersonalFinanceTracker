# Kick-off prompt for Claude Code

Copy the block below and paste it into Claude Code as your first message. Claude Code will automatically pick up `CLAUDE.md` on every subsequent turn.

---

## Prompt to paste

> I want you to build a local-first personal finance tracker for me. The full spec, feature inventory, and visual wireframes are already in this folder.
>
> **Before writing any code, do the following in order:**
>
> 1. Read `CLAUDE.md` in full. It defines the build phases, the conventions, and the quality bar. Everything below is a summary — `CLAUDE.md` is the source of truth.
> 2. Read `SPEC.md` end-to-end. Pay special attention to §3 (stack proposal — this is a **starting straw-man only, not locked**), §4 (Prisma-syntax schema — the *data model* is canonical, but the ORM/DB choice is open), §5 (user flows), §6 (screen-by-screen), and §8 (risks).
> 3. Read `FEATURES.md`, especially §3 (feature inventory with all field names and category enumerations), §5 (data model rationale), and §7 (open questions that are NOT verified and need judgement calls).
> 4. Open `screenshots/index.html` and walk through every wireframe. Those are the layout references for each screen. Copy layouts and field lists from them — but write your own UI copy (do not reproduce finboom.app text verbatim).
>
> **Then, before scaffolding anything, have a stack conversation with me.** Walk through the decision categories listed in `CLAUDE.md` "Stack — to be decided collaboratively": runtime target (web/desktop/both), front-end framework + build tool, UI kit, charts library, state/data layer, back-end shape (separate API vs. embedded vs. browser-only SQLite via WASM), runtime (Node/Bun/Deno), database + ORM, money library, dates, scheduling, testing, lint/format, monorepo tooling, packaging. For each category, **propose 2–3 options with one-line trade-offs** (ecosystem maturity, complexity, offline story, bundle size, learning curve) and tell me what you'd pick and why. Ask me about my constraints (what I'm comfortable with, what machines this runs on, how offline it needs to be, whether I want a desktop binary). Do not decide unilaterally and do not decide silently.
>
> Once we have agreement, write the decisions to a new file `DECISIONS.md` as a short list — one line per category — with a brief rationale. That file then becomes the stack contract. If later phases need a decision we skipped, come back and amend `DECISIONS.md`.
>
> Only after `DECISIONS.md` exists should you start **Phase 0** (scaffolding against the agreed stack). Proceed phase by phase as laid out in `CLAUDE.md` "Build phases (MVP)". Do not jump ahead. At the end of each phase:
>
> - Give me a one-line demo instruction (e.g. "run the dev command, open the app, click X").
> - Confirm tests / typecheck / lint pass.
> - Stop and wait for me to say "next phase" before starting the next one.
>
> **Ground rules (stack-agnostic)**
>
> - Money uses a decimal-safe representation (library of your choice or integer minor units). **Never** JS `number` / float for money.
> - Every table has `profileId` from day 1. The MVP UI exposes only one profile, but the schema supports multiple.
> - Snapshots are immutable: store the computed breakdown when taken; never recompute history from current data.
> - Categories are rows, not enums — renaming a category must not orphan transactions.
> - Empty states are first-class — every screen must render with zero rows.
> - When a requirement is ambiguous: first check `FEATURES.md §7 Open Questions`; if it's listed there, make a pragmatic choice and log it as a one-liner in `DECISIONS.md`. If it isn't listed there, ask me.
> - No network calls except the FX-rate refresh (user-triggered or scheduled) and an **off-by-default** live-price fetch. No telemetry.
> - Write tests as you go, not at the end. A feature isn't done without a service-level test + a UI test covering the happy path.
> - Commit after each phase with a clear message; do not bundle phases into one commit.
>
> Start with the stack conversation. Do not create any code or config files before `DECISIONS.md` is written.
>
> The repo root holds the spec docs; once the stack is agreed, create a subfolder `app/` for the codebase so the spec docs stay separate from the source.

---

## If the first phase goes well

Once Phase 0 is done and you've said "next phase", subsequent prompts can be as short as:

> Proceed with Phase N per `CLAUDE.md`. Reference `FEATURES.md §3.X` and `screenshots/0X-*.html` for the specific screen. Stop at the end of the phase.

---

## If you already know what you want

If you don't want to have the open-ended stack conversation, you can pre-seed it:

> Override: I want to use [stack here, e.g. "Next.js 15 App Router + Drizzle + SQLite, desktop packaging with Tauri"]. Skip the stack conversation for those categories — confirm the others (charts, forms, money lib, testing) briefly, then write `DECISIONS.md` and proceed.

Or you can invert the flow and ask Claude Code to strongly recommend one stack instead of presenting options:

> Recommend one opinionated stack that best fits this spec, defend it in 5 bullets, and proceed unless I push back. Still write `DECISIONS.md` before scaffolding.
