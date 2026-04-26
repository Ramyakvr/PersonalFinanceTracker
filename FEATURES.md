# FinBoom — Feature Inventory

> Research notes from a hands-on walk-through of https://www.finboom.app as a signed-in free-tier user (INR base currency).
> Research date: 2026-04-18. Account was empty (0 assets, 0 liabilities, 0 expenses, 0 goals), so some widgets were inspected in their "empty state" form and annotated.
> Copy is **paraphrased** throughout; original FinBoom strings are not reproduced verbatim.

---

## 1. Executive Summary

FinBoom is a privacy-first, India-centric personal wealth tracker. A single user logs a curated list of assets (stocks, MFs, PF/PPF/NPS, real estate, gold, crypto, alternatives, cash) and liabilities (home/vehicle/personal loans, credit cards, etc.), layers on expenses and income, and sees their **net worth**, **asset allocation**, **cash-flow**, **financial health score**, and **progress toward goals** through a dashboard of widgets.

Key product decisions that stand out:

- **Form-driven, not statement-parsed.** Data lives in hand-entered records; CSV/broker imports exist but are opt-in per broker.
- **Multi-currency by design** with an INR default. Each asset carries its own currency; a base display currency is configurable in settings.
- **Plan gating is mild.** Free tier lets you track the full taxonomy; Pro (promo code "TRACK15") gates what appear to be advanced features (snapshots history, live prices BETA, etc.).
- **Offline/PWA friendly.** The side-nav includes "Install App" and an optional 4-digit app-lock PIN in settings.
- **Indian-market vocabulary.** SIP, EPF/PPF/NPS, SSY, ULIP, endowment, PMS/AIF, EMI, CDSL, Zerodha/Groww/INDmoney imports, ₹ default.

Top-level IA is 4 primary sections (Overview, Wealth, Money, Essentials) + 5 utility items (Import, What's New, Settings, Install App, Feedback). Data-entry is consistent: a two-step wizard (pick category → fill form) with common "Add details" expandables for tags, notes, geography, sub-class, and an "exclude from allocation" flag.

## 2. Information Architecture

Primary nav (left sidebar, in this order):

- **Overview** — `/dashboard` — the main landing page (widgets & insights)
- **Wealth** — `/assets` (default) with tab set: Assets, Liabilities, Net Worth, Allocation. Tabs correspond to routes `/assets`, `/liabilities`, `/snapshots` (for Net Worth), `/allocation`
- **Money** — `/expenses` (default) with tab set: Expenses, Income, Insights
- **Essentials** — `/essentials` with tab set: Essentials, Goals (`/goals`)

Secondary "Tools" nav:

- **Import** — `/import` — broker file upload
- **What's New** — `/whats-new` — changelog
- **Settings** — `/settings` — tabs: Account, Preferences, Recurring, Profiles, Shared Access, Data, Plan & Billing
- **Install App** — PWA install trigger
- **Feedback** — in-app feedback

Top bar: hide-values toggle, light/dark theme toggle, user avatar menu, notifications bell (shows a red dot when new items are present).

Persistent promo strip: "Limited time offer! Save 15% on Pro with code TRACK15" — dismissible.

## 3. Feature Inventory by Section

### 3.1 Overview (Dashboard)

Widgets observed on `/dashboard`:

- **Net Worth** KPI card with trend indicator
- **Total Assets** KPI card
- **Total Liabilities** KPI card
- **Invested** KPI (sum of invested value of positions)
- **Financial Health Score** card (ties into Essentials checks)
- **Asset Allocation** mini donut chart
- **Cashflow** mini chart (income vs. expenses this month)
- **Top Holdings** list
- **Insights** card (automated observations — e.g. empty-state prompts)
- **Goals** progress snippet
- **Suggestions** section (empty-state shows onboarding CTAs such as "Add your first asset")

Global actions available from Overview: hide/show values (eye-off icon), light/dark toggle, notifications.

### 3.2 Wealth → Assets (`/assets`)

- Assets list with: name, category chip, current value, tags, last-updated
- Page actions: Search, Export (CSV), Import, **Add Asset** button
- Filters: tags filter, currency filter, "More" overflow
- Add Asset wizard (`/assets/new`) — two-step:

#### Asset taxonomy (top-level categories and subtypes)

| Category | Subtypes observed |
|---|---|
| Stocks & Equity | Direct Stock, Equity Mutual Fund, Employer Stock/ESOP, ETF |
| Gold & Silver | Physical Gold, Digital Gold, Sovereign Gold Bond, Gold ETF, Silver |
| Bonds & Debt | Bond, Debenture, Debt Mutual Fund, Corporate FD, Govt Security |
| Real Estate | Residential Property, Commercial Property, Land, REIT |
| Retirement | EPF, PPF, NPS, SSY (Sukanya Samriddhi) |
| Cash & Savings | Savings Account, Fixed Deposit, Recurring Deposit, Liquid Fund, Arbitrage Fund |
| Alternatives | P2P Lending, PMS / AIF |
| Other | (catch-all; user-definable) |

(Sub-type list reflects what was observed in the wizard — the actual app may include additional minor items behind scrolls.)

#### Common asset form fields

All forms share a core block:

- **Name** (required) — free text
- **Currency** — defaults to INR; select widget, single select
- **Current Value** (required) — numeric
- **Sub-class** (optional) — e.g. Large-cap / Mid-cap / Small-cap for equities
- **Tags** (optional) — free text, comma-chipped
- **Notes** (optional) — longer text
- **Geography** (optional) — India / International / Mixed
- **Exclude from Allocation** (toggle) — keeps asset in net worth but out of allocation %s

Type-specific fields (inferred from forms we opened):

- **Direct Stock:** Symbol/Name, Quantity, Avg Buy Price (derives Invested), live-price toggle labeled "BETA"
- **Mutual Fund / ETF:** Scheme/ticker, Units, NAV, (live-price BETA where supported)
- **Fixed Deposit / Recurring Deposit:** Principal, Interest Rate (%), Start Date, Maturity Date
- **EPF / PPF / NPS / SSY:** Principal/Balance, Employee contribution, Employer contribution, Interest rate, Weight (allocation weighting inside retirement sub-class)
- **Real Estate:** Purchase price, Current value, Location, Property type
- **Gold (physical/digital):** Weight (grams), Purity, Purchase rate
- **SGB / Gold ETF:** Units, NAV/Price
- **P2P / PMS / AIF:** Principal, Expected rate, Maturity
- **Savings Account:** Bank, Balance (current value)

Form actions: **Save**, **Save & Add Another**, **Cancel**, and "Back to Assets" breadcrumb.

### 3.3 Wealth → Liabilities (`/liabilities`)

List page with Assets/Liabilities/Net Worth/Allocation tabs, Export, Import, **Add Liability** button.

Liability categories (wizard at `/assets/new` with Liability tab):

- Home Loan
- Vehicle Loan
- Personal Loan
- Education Loan
- Credit Card
- Gold Loan
- Business Loan
- Friends / Family
- Other

Shared liability form fields (form was identical across subtypes):

- **Name** (required) — e.g. "Home Loan — SBI"
- **Currency** (default INR)
- **Outstanding Amount** (required)
- **Interest Rate (%)** — numeric, e.g. 8.5
- **Monthly EMI**
- **Start Date** — date picker

Plus the standard "Add details" block (Notes, Tags, Exclude flag).

### 3.4 Wealth → Net Worth (`/snapshots`)

- "Take New Snapshot" button (snapshots count is displayed; "0 snapshots" in empty state)
- Toggle between **Net Worth**, **Assets**, **Liabilities** chart views
- Show/Hide values toggle
- Empty-state CTA: "Add your assets and liabilities first to see your net worth here"
- The chart is a time-series line chart driven by user-taken snapshots (not auto-daily)

### 3.5 Wealth → Allocation (`/allocation`)

- **Asset Allocation** donut/pie chart with legend
- **Monthly SIP Plan** widget (suggests per-month contribution to each class to reach targets)
- **Show/Hide values** toggle
- **Target Allocation** panel with a "Default" preset and **Edit** button, default percentages observed: Equity 55 / Debt 20 / Gold 10 / Alternatives 10 (balance likely Real Estate, visible as remaining 5%)
- Comparison of actual vs target; empty-state says "Add assets to see your allocation comparison"

### 3.6 Money → Expenses (`/expenses`)

- List page: Search, Export, Import, **Add** button, "0 entries" counter
- Date-range picker chips: This Week, Last 30 Days (default), This Month, Last Month, 6M, 12M, Custom
- Show/hide values toggle
- Empty-state message with "Add your first entry above"

#### Add Expense form (`/expenses/new`)

Two-segment toggle at top: **Expense / Income** (same form scaffolding).

Row-based entry (spreadsheet-like — "Add row" creates another line in the same form):

- **Date** (default today, e.g. "Sat, 18 Apr 2026")
- **Category** (combobox, see list below; "Add new category" and "Manage categories" links at the bottom)
- **Description** (free text, e.g. "Rent")
- **Amount** (numeric)
- **Currency** (default INR)
- **Recurring** toggle (ties into Settings → Recurring)
- **Add note (optional)**
- **Add tags**
- **Add row** — append another line
- **Cancel / Save**

**Expense categories** (seeded defaults):
Housing & Rent, Food & Dining, Groceries, Transport, Healthcare, Education, Insurance, EMI & Loans, Entertainment, Utilities, Shopping, Investment (default flagged as exempt from spend totals), Travel & Vacations, Subscriptions, Personal Care, Transfers & Remittance, Credit Card Payment (default flagged as exempt), Taxes, Cash Withdrawal, Childcare, Other Expense.

### 3.7 Money → Income (`/expenses?tab=income`)

Same form shape, Income segment. **Income categories**:
Salary, Freelance, Rental Income, Dividend, Interest, Business, Bonus, Investment Proceeds, Self Transfer, Other Income.

### 3.8 Money → Insights

Surfaces derived analytics:

- Cashflow trend (income vs expenses over time)
- Category breakdowns (top spend categories, % of spend)
- Savings rate
- Recurring-cost audit (driven by the Recurring subsystem)

(Details were not fully rendered for an empty account; listed here as observed entry points.)

### 3.9 Essentials (`/essentials`)

Financial health check with four cards observed:

- **Emergency Fund** — target vs actual liquid reserves
- **Savings Rate** — income vs expenses derived
- **Term Insurance** — user-declared cover adequacy
- **Health Insurance** — user-declared cover adequacy

There is a large summary donut (overall health score) above the cards. Clicking into a card presumably walks the user through inputs (not explored to avoid polluting the account).

### 3.10 Essentials → Goals (`/goals`)

- **Goals** list with "0 active goals" counter, Export button
- **+ New Goal** button
- **Inflation Calculator** utility (modal/panel)

#### Create New Goal form

- **Goal Name** (required)
- **Template** — dropdown of preset templates (e.g. Retirement, Home Down-payment, Child Education, Emergency Fund, Custom — template list is UI-only, not pre-cached here)
- **Target Amount** (required)
- **Currency** — INR / USD / EUR / GBP / SGD / AED / KWD / SAR / QAR / CAD (at least 10 entries)
- **Target Date** (required)
- **Track Progress By** (linked asset class) — options:
  Net Worth (all assets), Stocks & Equity, Equity Funds, Gold & Silver, FD & RD, EPF / PPF / NPS, Real Estate, Cash & Savings, International, Bonds, Debt Funds, Liquid Funds, Crypto, Employer Stock, SSY, Arbitrage Funds, Commodities, ULIP, Moneyback Insurance, Endowment Plans, Other
- **Link specific assets (optional)** — pick individual assets to count toward the goal
- **Create Goal** button

### 3.11 Import (`/import`)

Three modes:

- **Import from Broker** — dropdown of supported brokers (Zerodha, Groww, INDmoney, Upstox, ICICI Direct, CDSL, Angel One, Aionion, Chola Securities, mstock). Broker-specific "How to Export from X" instructions are rendered inline, then an "Upload X File" drop-zone.
- **Standard Import** — generic CSV format.
- Sub-tabs for scope: **Assets** vs **Income & Expenses**.
- Merge strategy: **Append** or **Update by Name** (toggle).

### 3.12 Settings (`/settings`)

Left-rail tabs:

- **Account** — Profile (Display Name, Email — immutable), Set Password (for email+password login alongside Google SSO), App Lock (4-digit PIN, auto-locks after 1 minute in background)
- **Preferences** — Base Display Currency, Exempt Expense Categories (toggles per category; Investment and Credit Card Payment are default-exempt), Exempt Income Categories, Custom Categories (add/edit/remove)
- **Recurring** — Recurring expense/income rules (the "Recurring" toggle on each transaction writes here)
- **Profiles** — Multiple profiles (e.g. Self vs. Spouse vs. Family) — appears to be a Pro feature
- **Shared Access** — Invite/manage a partner or advisor with view access
- **Data** — Export everything, Import everything, Wipe data
- **Plan & Billing** — Free vs Pro, upgrade/TRACK15 promo, subscription state

### 3.13 What's New (`/whats-new`)

In-app changelog / release notes page.

### 3.14 Cross-cutting UI

- **Global show/hide values** (eye-off icon in header) — blurs monetary values across the app (useful for screen-sharing).
- **Dark/Light theme toggle**.
- **Notifications** (bell icon, red-dot badge for new items).
- **Install App** — PWA install prompt.
- **Feedback** — opens a feedback form.
- **Upgrade to Pro** pill always visible in the sidebar bottom.
- Dismissible promo banner at top ("TRACK15").

## 4. Visualizations Catalog

| # | Widget | Type | Location | Notes |
|---|---|---|---|---|
| 1 | Net Worth KPI | Number + trend arrow | Overview | Currency-aware |
| 2 | Asset Allocation mini | Donut | Overview | Drills into /allocation |
| 3 | Cashflow mini | Stacked bar or combo (income vs expense) | Overview | This-month snapshot |
| 4 | Top Holdings | List with % of portfolio | Overview | Tied to Assets |
| 5 | Health Score | Gauge / donut | Overview & Essentials | Tied to 4 Essentials cards |
| 6 | Goals progress | Progress bars per goal | Overview & Goals | Linked assets roll up |
| 7 | Net Worth Trend | Time-series line | /snapshots | Driven by user-taken snapshots; toggles Net Worth / Assets / Liabilities |
| 8 | Allocation — Actual vs Target | Donut + side list, with deltas | /allocation | Shows over/under-weight per class |
| 9 | Monthly SIP Plan | List per class | /allocation | Prescribes per-month contributions to hit targets |
| 10 | Expense by category | Horizontal bar / donut | Money → Insights | Period-filtered |
| 11 | Income vs Expense over time | Line / stacked bar | Money → Insights | Period-filtered |
| 12 | Savings Rate | KPI + trend | Essentials | Derived from Income/Expense |
| 13 | Emergency Fund coverage | Bar / months-covered | Essentials | (actual emergency assets) / (monthly expense) |

## 5. Data Model (Inferred)

Entities and their approximate shapes:

- **User** — { id, email, displayName, baseCurrency, themePreference, appLockPin?, googleSub?, passwordHash?, plan (free/pro), createdAt }
- **Profile** — { id, userId, name, isDefault } — optional multi-profile support for household tracking
- **Asset** — { id, profileId, category (enum), subtype (enum), name, currency (ISO code), currentValue (decimal), costBasis?, quantity?, unitPrice?, startDate?, maturityDate?, interestRate?, geography?, subClass?, weight?, livePriceEnabled?, instrumentSymbol?, notes?, excludeFromAllocation (bool), createdAt, updatedAt }
- **Liability** — { id, profileId, category (enum: home/vehicle/personal/education/credit-card/gold/business/friends-family/other), name, currency, outstandingAmount, interestRate?, monthlyEmi?, startDate?, notes?, excludeFromAllocation (bool), createdAt, updatedAt }
- **Tag** — { id, profileId, label }
- **AssetTag / LiabilityTag** — many-to-many join
- **Transaction** (expense & income) — { id, profileId, type (expense|income), date, categoryId, description, amount (decimal), currency, notes?, tagsIds, recurringRuleId?, createdAt } (row-based form implies transactions are saved one-per-line)
- **Category** — { id, profileId?, type (expense|income), name, isDefaultExempt (bool), isCustom (bool) }
- **RecurringRule** — { id, profileId, transactionTemplate, cadence (daily|weekly|monthly|yearly|custom), startDate, endDate?, lastGeneratedAt }
- **Snapshot** — { id, profileId, takenAt, netWorth, totalAssets, totalLiabilities, breakdownJson } — user-triggered time-series points
- **Goal** — { id, profileId, name, templateId?, targetAmount, currency, targetDate, linkedAssetClass (enum), linkedAssetIds[] (optional), createdAt }
- **AllocationTarget** — { id, profileId, presetName, percentByClass (json: { equity: 55, debt: 20, gold: 10, alt: 10, realEstate: 5 }) }
- **FxRate** — { id, fromCurrency, toCurrency, rate, fetchedAt } — server-side cache for multi-currency normalization
- **ImportJob** — { id, profileId, source (zerodha|groww|generic|…), mode (append|update_by_name), filename, rowsImported, status, log, createdAt }
- **EssentialsState** — { id, profileId, emergencyFundTargetMonths, termCoverAmount, healthCoverAmount, selfDeclaredFields } — drives the health score

Derived / computed (not stored, or materialized on read):

- **NetWorth** = Σ(asset.currentValue in baseCcy) − Σ(liability.outstandingAmount in baseCcy)
- **AssetAllocation[class]** = Σ(asset.currentValue where class == X and !excludeFromAllocation) / totalAllocatedAssets
- **HealthScore** = weighted aggregate of Essentials cards
- **MonthlySipPlan[class]** = (targetValue[class] − currentValue[class]) / monthsToHorizon
- **GoalProgress** = (linked assets' currentValue) / targetAmount, projected to targetDate

## 6. Interaction Patterns

- **Two-step wizard** for Asset/Liability creation: pick category grid → fill form. Categories persist as a breadcrumb; you can re-pick mid-flow.
- **Spreadsheet-style multi-row entry** for transactions: "Add row" appends another line, Save commits all at once.
- **Dual-mode forms** via segment toggle (Asset ↔ Liability at top of wizard; Expense ↔ Income at top of transaction form).
- **Empty-state CTAs** lead the user into data entry for each widget.
- **Show/hide values** is global and persistent across pages.
- **Tag chips** with autocomplete, shared across assets/liabilities/transactions.
- **Date pickers**: native HTML5 date inputs; date chips on Money page are preset ranges.
- **Select lists** with "Add new …" affordance at the bottom (categories, tags).
- **Filters & search** are consistent: top-right search box, export/import buttons, "+ Add" primary button.
- **Promo banner** is persistent but dismissible (cookie-backed).
- **Live price (BETA)** toggle on Direct Stock — indicates a best-effort quote fetch for NSE/BSE symbols.
- **Snapshots** are user-triggered (no passive daily background snapshot observed for free tier).
- **Theme** toggle: light/dark, persists per user.

## 7. Open Questions (uncertainty flagged, needs verification before building)

1. **Live price provider** — Which source (NSE/BSE, Yahoo, broker feed)? Rate limit? Free vs Pro?
2. **FX rate source and cadence** — Is there a nightly refresh? Which API?
3. **Snapshot cadence** — Pure user-triggered, or does Pro add automatic daily snapshots?
4. **Goal templates** — Exact preset list (we observed "Select a template…" but did not enumerate the full dropdown).
5. **Recurring rules** — Supported cadences (monthly only? cron-style?) and whether past instances are back-filled.
6. **Household / profiles** — Is it a true multi-profile model or a tag-style switch? Free vs Pro gating?
7. **Shared Access** — View-only or edit? Per-profile or per-resource?
8. **Pro gating** — Exact feature matrix (live price, broker imports, snapshots frequency, multi-profile). Pricing page was not visited.
9. **Categories** — Can the user rename defaults, or only add custom? Are exempt flags global or per-category?
10. **Insights AI** — Are "Insights" widget texts generated (LLM) or rule-based?
11. **Import reconciliation** — When "Update by Name" matches, does it overwrite all fields or only quantities/values?
12. **Essentials inputs** — Full field list for Term / Health insurance cards (e.g. sum insured, riders) was not captured.
13. **Net Worth chart smoothing** — Does it interpolate between snapshots or step-chart them?
14. **Currency of display** — Do totals always render in base currency, or are per-asset currencies shown inline?
15. **Crypto category** — Appeared in Goals' linkedAssetClass but not in the asset wizard enumeration; may be a subtype under Alternatives/Other.

## 8. Screenshots Index

Screenshots were captured in-browser during research but were not persisted to disk because `save_to_disk` did not return a path accessible from the outputs workspace. The following list is the intended screenshot set (referenced by filename in case they are added manually):

- `./screenshots/00-login-dashboard.png` — Overview dashboard, empty state
- `./screenshots/01-sidebar-nav.png` — Full primary + tools nav
- `./screenshots/02-assets-empty.png` — `/assets` empty list
- `./screenshots/03-asset-wizard-categories.png` — 8-category grid
- `./screenshots/04-asset-form-direct-stock.png` — Stock form with live-price BETA
- `./screenshots/05-asset-form-mf.png` — Mutual fund form
- `./screenshots/06-asset-form-ppf.png` — EPF/PPF/NPS form
- `./screenshots/07-asset-form-real-estate.png` — Real estate form
- `./screenshots/08-asset-form-gold.png` — Gold form
- `./screenshots/09-liability-wizard-categories.png` — 9-category grid
- `./screenshots/10-liability-form.png` — Loan form (shared)
- `./screenshots/11-net-worth-snapshots.png` — `/snapshots` with Take New Snapshot
- `./screenshots/12-allocation.png` — Target vs Actual donut + SIP plan
- `./screenshots/13-expense-list.png` — Expense period chips
- `./screenshots/14-expense-form-multirow.png` — Add row / Recurring toggle
- `./screenshots/15-income-form.png` — Income segment
- `./screenshots/16-essentials-cards.png` — 4 health cards
- `./screenshots/17-goal-form.png` — New Goal form
- `./screenshots/18-import-broker.png` — Broker picker
- `./screenshots/19-settings-account.png` — Account + App Lock
- `./screenshots/20-settings-preferences.png` — Exempt categories + base currency
