# Maria — Normalized Database Rows (After Phase 1 + Phase 2)

This is what `01_RAW_API_RESPONSES.md` becomes **after** the pipeline normalizes it into PostgreSQL. Every table uses the exact schema from `Pulse_TechSpec.docx`. Every row traces back to a specific API field.

The flow: **Raw API JSON → normalize → these rows → `pulse_math_validator.py` reads these → alerts.**

---

## `businesses` — the root entity

One row. Created at onboarding, not pulled from any API.

| id | owner_name | owner_email | business_name | business_type | province | gst_rate | cash_threshold | alert_channel | timezone | tier |
|---|---|---|---|---|---|---|---|---|---|---|
| `7a4ab8ce-...` | Maria Souza | maria@mariaskitchen.ca | Maria's Kitchen | restaurant | BC | 0.0500 | 3000.00 | both | America/Vancouver | operator |

> `cash_threshold = 3000.00` and `gst_rate = 0.05` are exactly the values the validator's M-01 and M-03 use.

---

## `integrations` — connected external services

Five rows — one per connected provider. Tokens encrypted with pgcrypto (shown redacted).

| id | business_id | provider | access_token | token_expires_at | provider_account_id | is_active | last_synced_at | error_count |
|---|---|---|---|---|---|---|---|---|
| `int-01` | `7a4ab8ce-...` | plaid | `\xc3a8...[enc]` | (no expiry) | blgvv1ZxK7iqK6Bd9wGG | true | 2026-02-28 03:02:11 | 0 |
| `int-02` | `7a4ab8ce-...` | quickbooks | `\x9f2b...[enc]` | 2026-02-28 04:09:00 | realm_4620816365 | true | 2026-02-28 03:02:40 | 0 |
| `int-03` | `7a4ab8ce-...` | adp | `\x71de...[enc]` | 2026-02-28 05:00:00 | MK1 | true | 2026-02-28 03:03:05 | 0 |
| `int-04` | `7a4ab8ce-...` | toast | `\x4a8c...[enc]` | 2026-03-29 00:00:00 | 8a1f-mk-vancouver | true | 2026-02-28 03:03:30 | 0 |
| `int-05` | `7a4ab8ce-...` | square | `\xb5e0...[enc]` | 2026-08-28 00:00:00 | sq_loc_MK_8821 | true | 2026-02-28 03:03:52 | 0 |

---

## `daily_balances` — bank balance history

From Plaid Balance API. One row per sync. Note the sign convention is corrected here (intuitive: positive balance).

| id | business_id | balance_date | balance_current | balance_available | account_id | source |
|---|---|---|---|---|---|---|
| `bal-0228` | `7a4ab8ce-...` | 2026-02-28 | 24300.00 | 23150.00 | blgvv1ZxK7iqK6Bd9wGG | plaid |

> `balance_current = 24300.00` → this is the **opening balance (Day 0)** in the validator's M-01 cash-flow loop.

---

## `transactions` — every bank transaction

From Plaid Transactions API. 1,847 rows total; representative sample shown. **Sign flipped from Plaid convention** (here: negative = debit/outflow, positive = credit/inflow) and **categorized** in Phase 2.

| plaid_transaction_id | date | amount | merchant_name | category | category_confidence | category_source | is_pending | is_fixed_cost |
|---|---|---|---|---|---|---|---|---|
| lPNjeW1nR6CD... | 2026-02-28 | -15320.24 | ADP PAYROLL | payroll | 1.000 | rules | false | true |
| Wd9zKEPnR6CD... | 2026-02-26 | -14200.00 | METRO PRODUCE SUPPLY | food_cost | 1.000 | rules | false | false |
| 8gKgNVPnR6CD... | 2026-02-24 | +4900.00 | SQUARE INC | revenue | 1.000 | rules | false | false |
| x4PpqVPnR6CD... | 2026-02-20 | -420.00 | BC Hydro | utilities | 0.940 | plaid_ml | false | true |
| mQ2RstPnR6CD... | 2026-02-19 | -89.00 | SYSCO CANADA 4821 | food_cost | 0.860 | claude | false | false |
| pending_tx_a91kdj2 | 2026-02-28 | -312.50 | RICExPRESS WHOLESALE | food_cost | 1.000 | rules | **true** | false |

> The pending RICExPRESS row (`is_pending = true`) is **excluded** from forecasts until it posts — per the Plaid spec rule. Categorization shows all three layers in action: rules engine (40%), Plaid ML (30%), Claude fallback (30%).

---

## `invoices` — receivables from QuickBooks

From QB Invoice query. Paid invoice (INV-301) included to show how `client_payment_profiles` gets built.

| external_id | source | customer_name | amount | balance_due | issue_date | due_date | paid_date | status | days_to_pay |
|---|---|---|---|---|---|---|---|---|---|
| 312 | quickbooks | Miller & Sons Catering | 9800.00 | 9800.00 | 2026-01-26 | 2026-02-25 | (null) | overdue | (null) |
| 309 | quickbooks | Westside Events Co | 3200.00 | 3200.00 | 2026-02-10 | 2026-03-12 | (null) | open | (null) |
| 301 | quickbooks | Miller & Sons Catering | 5600.00 | 0.00 | 2025-12-15 | 2026-01-14 | 2026-01-30 | paid | +16 |

> INV-312 is **3 days overdue** as of 2026-02-28 (due Feb 25). Feeds M-07 (DSO) and M-08 (per-client delay). INV-301 paid 16 days late → builds Miller & Sons' delay profile below.

---

## `bills` — payables from QuickBooks

From QB Bill query. Feeds the outflow schedule in Phase 3.

| external_id | vendor_name | amount | balance_due | due_date | status |
|---|---|---|---|---|---|
| BILL-77 | Pacific Linen Service | 2100.00 | 2100.00 | 2026-03-08 | open |
| BILL-79 | GreaseAway Disposal | 880.00 | 880.00 | 2026-03-22 | open |

---

## `payroll_runs` — payroll schedule and history

From ADP. The most recent run (history) + the projected next run. `cash_out` is auto-generated (`net_pay + employer_taxes`).

| external_id | source | check_date | gross_pay | net_pay | employer_taxes | cash_out | employee_count | pay_frequency | is_projected |
|---|---|---|---|---|---|---|---|---|---|
| PR-2026-0228-MK | adp | 2026-02-28 | 18400.00 | 13920.00 | 1400.24 | 15320.24 | 9 | biweekly | false |
| (sched) | adp | 2026-03-15 | 18400.00 | 13920.00 | 1400.24 | 15320.24 | 9 | biweekly | **true** |

> `cash_out = 15320.24` on the **projected** Mar-15 run is exactly the "extra outflow" the validator's M-01 loop applies on Day 16. M-02 payroll coverage uses `net_pay + employer_taxes` against the balance the day before.

---

## `client_payment_profiles` — per-client delay model

Built by aggregating each customer's paid-invoice history. Drives M-08.

| customer_name | invoice_count | avg_delay_days | stdev_days | p90_delay_days | min_delay | max_delay |
|---|---|---|---|---|---|---|
| Miller & Sons Catering | 7 | 14.20 | 4.80 | 21 | 8 | 23 |
| Westside Events Co | 3 | 2.00 | 1.50 | 4 | 1 | 4 |

> Miller & Sons pays ~14 days late on average. With INV-312 already 3 days overdue, the model projects payment around Day 11–17 — informing when the $9,800 inflow lands in the forecast.

---

## `daily_revenue` — POS revenue (Toast + Square)

Toast net sales + Square payments, reconciled. Feeds M-05 (food cost %) and M-10 (revenue trend).

| revenue_date | source | net_sales | food_cost | food_cost_pct | labor_cost | labor_pct | covers |
|---|---|---|---|---|---|---|---|
| 2026-02-28 (wk) | toast | 26800.00 | 10299.00 | 38.43 | 9650.00 | 36.01 | 1240 |
| 2026-02-24 (wk) | square | 4900.00 | (null) | (null) | (null) | (null) | (null) |

> `food_cost_pct = 38.43` is the exact value the validator's M-05 flagged — it computes z=16.27 against the 12-week mean of 30.29%, routing to the **VERIFY DATA** path (likely a double-counted invoice), not a false crisis alert.

---

## The Complete Picture — What Feeds Each Metric

| Metric | Reads from these rows | Maria's result |
|---|---|---|
| M-01 Cash Gap | daily_balances + payroll_runs + invoices + transactions | Gap on Day 16, balance −$736.24 |
| M-02 Payroll Coverage | payroll_runs + daily_balances | 0.95 — CRITICAL |
| M-03 GST Reserve | invoices + P&L + businesses.gst_rate | computed from taxable revenue |
| M-05 Food Cost % | daily_revenue (Toast) | 38.43% → VERIFY DATA |
| M-07 DSO | invoices + P&L | from receivables |
| M-08 Per-Client Delay | invoices + client_payment_profiles | Miller & Sons watched |

---

## The Honest Caveat

This is a **faithful structural replication** — the field names, types, sign conventions, token handling, cents-vs-dollars quirks, pending-transaction rules, and the categorization layers are all exactly as the real APIs behave and as your schema defines.

The **values** are constructed to match Maria's case-analysis numbers so they flow cleanly into your validator. Real Plaid sandbox data will have 1,847 messy real transactions, not 6 clean ones — but the *shape* is identical. When you wire up the real Plaid integration in Step 5, the normalization code Claude Code writes will produce rows in exactly this form.
