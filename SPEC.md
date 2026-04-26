# PersonalFinanceTracker — Build Spec

> A buildable, opinionated spec for a **local-first** personal finance tracker, implemented with Claude Code.
> All UI copy is written from scratch; no third-party app text is reproduced verbatim.

---

## 1. Product Summary

A single-user (optionally multi-profile) **wealth & money tracker** that runs entirely on the user's machine. One user records assets, liabilities, expenses, income, and goals via structured forms, and gets a dashboard of net worth, asset allocation, cashflow, a financial-health score, and goal progress.

**Design principles**

1. **Local-first.** Data never leaves the machine by default. Everything is a local SQLite file.
2. **Type-safe boring stack.** React + Vite + TypeScript on the front, a thin Node/Express (or Hono) service on the back, Prisma + SQLite for persistence.
3. **Hand-entered, not scraped.** No bank credentials. CSV import and broker CSV normalizers only.
4. **Deterministic computations.** Net worth, allocation, savings rate, SIP plan are all pure functions of stored rows — trivially testable.
5. **India-first defaults, currency-flexible.** INR default, NSE/BSE symbols, EPF/PPF/NPS/SSY/SGB in the taxonomy, but multi-currency built in from v1.
6. **PWA-ready.** Installable, offline, with an optional app-lock PIN.

**Non-goals (for v1):** bank account sync, Plaid/account-aggregator integration, real-time trading, tax filing, AI advisor.

## 2. Prioritized Feature List

### MVP (v1) — the minimum to ship a usable single-user tracker

- Auth: single local user with optional 4-digit app-lock PIN (no cloud auth).
- Assets CRUD with the full 8-category taxonomy (Stocks & Equity, Gold & Silver, Bonds & Debt, Real Estate, Retirement, Cash & Savings, Alternatives, Other) and per-category subtypes (see `core/subtypes.py`).
- Liabilities CRUD with the 9-category taxonomy.
- Transactions CRUD (expenses & income) with row-based multi-entry, categories, tags, notes, recurring toggle.
- Tags, custom categories, exempt categories.
- Net Worth time-series via **manual snapshots** + **nightly auto-snapshot** (local cron via a service worker or a tiny daemon).
- Asset Allocation donut: actual vs target (editable target preset). Monthly SIP plan calculation.
- Goals: create, target amount/date, link to asset classes or specific assets; progress & projection.
- Essentials health score: Emergency Fund (months covered), Savings Rate, Term Cover adequacy, Health Cover adequacy.
- Dashboard with KPI widgets: net worth, total assets, total liabilities, invested, financial health score, asset allocation donut, cashflow mini-chart, top holdings, insights, goals progress.
- Import: generic CSV (Assets, Liabilities, Transactions) with Append / Update-by-Name modes.
- Export: JSON full dump + CSV per table.
- Multi-currency: store per-row currency + base currency; FX rates via a local cache refreshed on demand (manual + scheduled).
- Dark/light theme, show/hide values, tags filter, date range presets.

### v2

- Broker CSV adapters for at least Zerodha, Groww, INDmoney (normalizers that emit canonical Transaction + Asset rows).
- Live price fetch for Direct Stock / ETFs (opt-in, with per-symbol caching, clearly rate-limited; use a free public endpoint).
- Multi-profile (Self / Spouse / Joint) with per-profile scoping of all tables.
- Recurring rules with cadences (monthly, weekly, yearly, custom cron) and automatic generation of upcoming transactions with "confirm on date" queue.
- Inflation calculator + "future value of goal" projection (FV = PV × (1 + r)^n).
- Search across transactions/assets/liabilities with a global spotlight (Cmd-K).
- Backup to a user-selected folder (e.g. Dropbox, iCloud Drive) — export on schedule.

### v3

- Shared access via a second local profile with read-only permissions (and an optional encrypted LAN-sync between two machines).
- Insights engine: rule-based first (e.g. "spend in Entertainment up 40% MoM"), with an opt-in local LLM summary using Ollama.
- Scenario modeling: "what if I add ₹X to SIPs for 5 years".
- Document vault: attach PDFs/images to assets/liabilities (policy docs, sale deeds, etc.), stored encrypted at rest.
- Reports: printable yearly PDF with charts.

## 3. Proposed Tech Stack

- **Front end:** React 19 + Vite + TypeScript + **Tailwind CSS** (+ shadcn/ui for primitives).
- **Charts:** **Recharts** (simple donut/line/bar primitives, SSR-safe). Fall back to Plotly for anything advanced in v2.
- **State:** TanStack Query for server cache, Zustand for UI-local state, React Hook Form + Zod for forms and validation.
- **Back end:** **Hono** on Node (lightweight, typed, easy to bundle) exposing a REST+RPC API on `localhost`.
- **DB:** **SQLite** file in the app's data directory. Accessed via **Prisma**.
- **Auth:** none for single-user; optional app-lock PIN stored hashed (Argon2) in the DB; biometrics via WebAuthn for v2.
- **Scheduling:** a node-cron inside the back end for auto-snapshots, recurring rule generation, and FX refresh.
- **Packaging:** **Tauri** (preferred) or Electron for a single desktop app; PWA build as a fallback.
- **Testing:** Vitest + React Testing Library for UI, Vitest + Prisma SQLite in-memory for services. Playwright for one happy-path E2E.
- **Lint/format:** Biome (single tool, fast) or ESLint + Prettier.
- **Money math:** **dinero.js** for multi-currency arithmetic; never use JS `number` for money.
- **Dates:** date-fns + date-fns-tz.

Why this stack: it's boring, local-first-friendly, type-safe end-to-end (Prisma types flow into the client via an RPC layer), and every dependency is permissively licensed and actively maintained.

## 4. Schema (Prisma pseudocode)

```prisma
// schema.prisma
datasource db { provider = "sqlite"; url = "file:./finance.db" }
generator client { provider = "prisma-client-js" }

model User {
  id               String   @id @default(cuid())
  displayName      String
  email            String?  @unique
  baseCurrency     String   @default("INR")   // ISO-4217
  theme            String   @default("light") // light | dark | system
  appLockHash      String?                     // Argon2 of 4-digit PIN
  createdAt        DateTime @default(now())
  profiles         Profile[]
  fxRates          FxRate[]
}

model Profile {
  id            String   @id @default(cuid())
  userId        String
  name          String
  isDefault     Boolean  @default(false)
  user          User     @relation(fields: [userId], references: [id])
  assets        Asset[]
  liabilities   Liability[]
  transactions  Transaction[]
  categories    Category[]
  tags          Tag[]
  recurring     RecurringRule[]
  snapshots     Snapshot[]
  goals         Goal[]
  allocations   AllocationTarget[]
  essentials    EssentialsState?
  importJobs    ImportJob[]
  @@unique([userId, name])
}

enum AssetCategory { EQUITY GOLD BONDS_DEBT REAL_ESTATE RETIREMENT CASH ALTERNATIVES OTHER }

model Asset {
  id                  String   @id @default(cuid())
  profileId           String
  category            AssetCategory
  subtype             String            // e.g. "DIRECT_STOCK", "FD", "PPF"
  name                String
  currency            String   @default("INR")
  currentValue        Decimal           // in `currency`
  costBasis           Decimal?
  quantity            Decimal?
  unitPrice           Decimal?
  startDate           DateTime?
  maturityDate        DateTime?
  interestRate        Decimal?
  geography           String?           // "IN" | "INTL" | "MIXED"
  subClass            String?           // "LARGE_CAP" etc.
  weight              Decimal?          // user-specified sub-allocation weight
  livePriceEnabled    Boolean  @default(false)
  instrumentSymbol    String?           // e.g. "INFY.NSE"
  notes               String?
  excludeFromAllocation Boolean @default(false)
  createdAt           DateTime @default(now())
  updatedAt           DateTime @updatedAt
  profile             Profile  @relation(fields: [profileId], references: [id])
  tags                TagOnAsset[]
  @@index([profileId, category])
}

enum LiabilityCategory { HOME_LOAN VEHICLE_LOAN PERSONAL_LOAN EDUCATION_LOAN CREDIT_CARD GOLD_LOAN BUSINESS_LOAN FRIENDS_FAMILY OTHER }

model Liability {
  id                 String   @id @default(cuid())
  profileId          String
  category           LiabilityCategory
  name               String
  currency           String   @default("INR")
  outstandingAmount  Decimal
  interestRate       Decimal?
  monthlyEmi         Decimal?
  startDate          DateTime?
  notes              String?
  createdAt          DateTime @default(now())
  updatedAt          DateTime @updatedAt
  profile            Profile  @relation(fields: [profileId], references: [id])
  tags               TagOnLiability[]
}

enum TxType { EXPENSE INCOME }

model Category {
  id           String  @id @default(cuid())
  profileId    String?            // null = system default
  type         TxType
  name         String
  isExempt     Boolean @default(false) // excludes from totals (e.g. Investment)
  isCustom     Boolean @default(false)
  profile      Profile? @relation(fields: [profileId], references: [id])
  transactions Transaction[]
  @@unique([profileId, type, name])
}

model Transaction {
  id              String   @id @default(cuid())
  profileId       String
  type            TxType
  date            DateTime
  categoryId      String
  description     String
  amount          Decimal
  currency        String   @default("INR")
  notes           String?
  recurringRuleId String?
  createdAt       DateTime @default(now())
  profile         Profile  @relation(fields: [profileId], references: [id])
  category        Category @relation(fields: [categoryId], references: [id])
  tags            TagOnTransaction[]
  recurringRule   RecurringRule? @relation(fields: [recurringRuleId], references: [id])
  @@index([profileId, date])
  @@index([profileId, categoryId])
}

model Tag {
  id        String @id @default(cuid())
  profileId String
  label     String
  profile   Profile @relation(fields: [profileId], references: [id])
  assets       TagOnAsset[]
  liabilities  TagOnLiability[]
  transactions TagOnTransaction[]
  @@unique([profileId, label])
}

model TagOnAsset        { tagId String; assetId String;     @@id([tagId, assetId]);     tag Tag @relation(fields:[tagId], references:[id]); asset Asset @relation(fields:[assetId], references:[id]) }
model TagOnLiability    { tagId String; liabilityId String; @@id([tagId, liabilityId]); tag Tag @relation(fields:[tagId], references:[id]); liability Liability @relation(fields:[liabilityId], references:[id]) }
model TagOnTransaction  { tagId String; transactionId String; @@id([tagId, transactionId]); tag Tag @relation(fields:[tagId], references:[id]); transaction Transaction @relation(fields:[transactionId], references:[id]) }

model RecurringRule {
  id           String   @id @default(cuid())
  profileId    String
  templateJson Json                 // serialized Transaction template
  cadence      String               // "monthly" | "weekly" | "yearly" | CRON
  startDate    DateTime
  endDate      DateTime?
  lastGenerated DateTime?
  profile      Profile  @relation(fields: [profileId], references: [id])
  transactions Transaction[]
}

model Snapshot {
  id               String   @id @default(cuid())
  profileId        String
  takenAt          DateTime @default(now())
  source           String   @default("manual") // "manual" | "auto"
  baseCurrency     String
  netWorth         Decimal
  totalAssets      Decimal
  totalLiabilities Decimal
  breakdownJson    Json
  profile          Profile  @relation(fields: [profileId], references: [id])
  @@index([profileId, takenAt])
}

model Goal {
  id                String   @id @default(cuid())
  profileId         String
  name              String
  templateId        String?           // e.g. "RETIREMENT" | "HOME" | "EMERGENCY"
  targetAmount      Decimal
  currency          String   @default("INR")
  targetDate        DateTime
  linkedAssetClass  String            // "NET_WORTH" | AssetCategory | custom class id
  linkedAssetIds    Json?             // optional list of Asset.id
  createdAt         DateTime @default(now())
  profile           Profile  @relation(fields: [profileId], references: [id])
}

model AllocationTarget {
  id         String   @id @default(cuid())
  profileId  String
  presetName String   @default("Default")
  percentByClass Json  // { "EQUITY":55, "BONDS_DEBT":20, "GOLD":10, "ALTERNATIVES":10, "REAL_ESTATE":5 }
  profile    Profile  @relation(fields: [profileId], references: [id])
}

model EssentialsState {
  id                      String  @id @default(cuid())
  profileId               String  @unique
  emergencyFundTargetMonths Int   @default(6)
  termCoverAmount         Decimal?
  termCoverTargetMultiplier Int   @default(10)   // target = annualIncome * N
  healthCoverAmount       Decimal?
  healthCoverTarget       Decimal @default(1_000_000)
  profile                 Profile @relation(fields: [profileId], references: [id])
}

model FxRate {
  id           String   @id @default(cuid())
  userId       String
  from         String
  to           String
  rate         Decimal
  fetchedAt    DateTime @default(now())
  user         User     @relation(fields: [userId], references: [id])
  @@unique([userId, from, to])
}

model ImportJob {
  id         String   @id @default(cuid())
  profileId  String
  source     String             // "zerodha" | "groww" | "generic_csv"
  scope      String             // "assets" | "transactions"
  mode       String             // "append" | "update_by_name"
  filename   String
  rowsImported Int
  status     String             // "running" | "ok" | "error"
  log        String?
  createdAt  DateTime @default(now())
  profile    Profile  @relation(fields: [profileId], references: [id])
}
```

Notes: all money columns use `Decimal` (Prisma → SQLite stores as `DECIMAL` text) and are materialized to `dinero.js` at the boundary. FX normalization is done on read, not on write, so you can always regenerate totals if base currency or rates change.

## 5. Top User Flows

1. **First-run onboarding** — create local user → set display name → choose base currency → (optional) set 4-digit PIN → create default Profile ("Self") → land on empty dashboard with "Add your first asset" CTA.
2. **Add an asset (Direct Stock)** — Wealth → Assets → Add Asset → pick Stocks & Equity → pick Direct Stock → fill symbol / quantity / avg buy / current value → save → redirected to Assets list with the new row and an updated Net Worth KPI.
3. **Add a liability & link EMI** — Wealth → Liabilities → Add Liability → Home Loan → fill name / outstanding / EMI / rate / start date → save → an entry appears in Recurring (v2) that will prompt the user each month to log the EMI as an expense.
4. **Record a month's expenses (multi-row)** — Money → Add → toggle Expense → add 5 rows with date/category/amount → mark rent as Recurring → Save → see Cashflow widget refresh.
5. **Take a net-worth snapshot** — Wealth → Net Worth → Take New Snapshot → a point is appended to the time-series chart. Auto-snapshot also fires nightly.
6. **Create a goal and track progress** — Essentials → Goals → + New Goal → "Retirement 2045", ₹5 Cr, Net Worth (all assets) → goal card shows % complete, required monthly SIP, and projected shortfall/surplus.
7. **Set target allocation & see SIP plan** — Wealth → Allocation → Edit target → e.g. 60/20/10/5/5 → the SIP plan widget recomputes how much to add to each class this month to converge.
8. **Bulk import from Zerodha CSV (v2)** — Import → Import from Broker → Zerodha → upload → preview table with canonicalized rows → choose Append vs Update-by-Name → commit → jobs log entry appears.

## 6. Screen-by-Screen MVP Breakdown

- **`/` Dashboard** — widgets: NetWorth, Assets, Liabilities, Invested, HealthScore, AllocationDonutMini, CashflowMini, TopHoldings, Insights, GoalsMini. Show/hide values toggle, theme toggle.
- **`/assets`** — table (name, category, subtype, currency, currentValue, tags, updatedAt). Search, tag filter, currency filter, Export, Import, Add Asset.
- **`/assets/new`** — 2-step wizard: CategoryGrid (8 cards) → AssetForm (dynamic per subtype). Asset↔Liability segment at top.
- **`/assets/:id/edit`** — same form as new, prefilled.
- **`/liabilities`** — table; same toolbar; Add Liability.
- **`/liabilities/new`** — single form (categories are labels; same fields across all subtypes).
- **`/snapshots`** — line chart of NetWorth / Assets / Liabilities with toggle; "Take New Snapshot" button; list of past snapshots with delete.
- **`/allocation`** — donut (actual) + donut (target) side-by-side; table of deltas; Monthly SIP Plan list; Edit Target modal.
- **`/expenses`** — table with period chips (Week / 30d / Month / LastMonth / 6M / 12M / Custom). Search, Export, Import, Add.
- **`/expenses/new`** — multi-row form with Expense/Income toggle, category combobox, date, amount, currency, recurring toggle, notes, tags.
- **`/insights`** — cashflow line, top-category bar, savings-rate KPI, spend-by-tag treemap.
- **`/essentials`** — 4 cards (Emergency Fund, Savings Rate, Term Insurance, Health Insurance) + summary donut. Clicking a card opens a small form to set targets.
- **`/goals`** — list of goals (progress bar each) + Create New Goal form inline.
- **`/goals/:id`** — detail view with projection chart and linked-assets list.
- **`/import`** — 2-tab UI (Assets | Transactions) × 2-mode (Generic CSV | Broker CSV placeholder). Drop zone, preview table, commit button.
- **`/settings`** — tabs: Account, Preferences, Recurring, Profiles (v2), Shared Access (v3), Data (export/import/wipe), Plan & Billing (placeholder, free self-hosted).
- **`/whats-new`** — markdown changelog rendered from a local file (optional).

Common shell: persistent left sidebar (primary + tools), header with hide-values toggle + theme toggle + profile picker (v2), top promo strip suppressed for self-hosted.

## 7. Out of Scope (v1)

- Bank account linking or account aggregator integration.
- Real brokerage integrations (only CSV imports).
- Cloud sync, multi-device sync, or social features.
- Tax computation or tax-loss harvesting.
- Automated investment advice.
- SMS/email notifications.
- Mobile native apps (PWA-only for v1).
- LLM-generated insights (deferred to v3, opt-in only).

## 8. Risks & Mitigations

- **Multi-currency correctness.** Using JS `number` for money will bite; mandate `dinero.js` at every boundary and add property tests for round-trip conversions.
- **FX rate staleness.** Totals shift when base currency toggles. Mitigation: cache rates per day in `FxRate`, show "as of" timestamp under any base-currency total.
- **Live prices.** Free endpoints break/ratelimit. Mitigation: make it opt-in per symbol, cache aggressively, fall back to last manual `unitPrice`.
- **Snapshot drift.** If users change historical data, old snapshots disagree with new computations. Mitigation: snapshots are immutable records of the computed state at `takenAt`; store `breakdownJson` so charts don't re-compute.
- **Schema drift as features land.** Free-form enums (subtype, linkedAssetClass) are string-typed; write a migration script + zod schema shared client-side.
- **Single-user assumption vs. multi-profile.** Designing `profileId` into every table from day 1 is cheap; retrofitting is expensive. Prisma schema above already does this.
- **Data loss.** Local SQLite without backups is risky. Mitigation: weekly auto-export (JSON) to `~/finance-backups/` + "Export all" button on Settings → Data.
- **Security of PIN/app-lock.** Argon2-hash the PIN; rate-limit attempts; wipe on N failures is optional (user choice).
- **Scope creep on Insights.** Keep v1 insights purely rule-based (e.g. "spend up 20% MoM", "emergency fund < 3 months"). Postpone anything that needs an LLM.
- **Decimal math in SQLite.** SQLite stores DECIMAL as TEXT; watch out for ordering/sorting. Use integer-paise/cents columns internally if this becomes an issue.
- **Category migration.** Renaming a default category shouldn't orphan transactions. Categories are rows (not enums) — already handled.
