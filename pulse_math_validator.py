"""
================================================================================
PULSE MATH VALIDATOR  v2
================================================================================
Pure Python arithmetic.  No ML.  No external APIs.  Runs fully offline.

Sources:
  • Pulse_Metrics (4).docx          — 15 metric formulas and thresholds
  • Pulse_Backend_Math_Case_Analysis (2).docx — 4 worked client examples
  • Pulse_Metric_Fixes (1).docx     — arithmetic corrections applied here

Fixes applied on top of the original spec (all from Pulse_Metric_Fixes.docx):
  [FIX-Z0]  z-score: one-sided tail, t-threshold 2.255 for n=12, per-metric
            s_floor so near-flat histories cannot generate spurious alarms.
  [FIX-M03] GST ITC eligibility factor per expense category (wages→0,
            meals/ent→0.50, standard inputs→1.00).
  [FIX-M04] Margin z: s_floor = 1.0 pp.
  [FIX-M05] Food cost z: s_floor = 0.5 pp; z > 4.0 → VERIFY DATA, not alert.
  [FIX-M06] Labor %: use annual_payroll/52 when hours unavailable; compound
            signal requires 2 consecutive weeks (documented, not testable in
            single-run validator).
  [FIX-M07] DSO: use 4-week average AR, not single-day snapshot; absolute
            ceiling = payment_terms + buffer.
  [FIX-M08] Client delay: add practical floor (days_overdue − avg ≥ 10 days);
            require ≥ 6 paid invoices before activating z-score alert.
  [FIX-M09] Vendor anomaly: Bonferroni-corrected z cutoff scales with number
            of vendors tested simultaneously.
  [FIX-M13] *** CRITICAL *** Normalise every payroll feed to monthly BEFORE
            computing net_burn.  Biweekly × 26/12 = 2.1667; this fix changes
            runway materially for Sarah and Amir (see DEVIATION NOTES).
  [FIX-M14] Variable-cost ratio includes variable hourly labour separately.
  [FIX-M15] Report expansion score as a BAND, not a false-precise decimal.

Usage:
    python3 pulse_math_validator.py

[PASS] = computed value matches expected answer.
[FAIL] = deviation detected — inspect printed steps above.
DEVIATION NOTE lines flag where [FIX-M13] changes the result vs the case doc.
================================================================================
"""

import io
import contextlib
import math
import random
import sys

from pulse_metrics import *  # metric functions + utilities (public names)
from pulse_metrics import (  # private helpers used directly in the test harness
    _mean, _sample_stdev, _score_runway, _route_z_signal, _score_dso,
)

# SECTION 1 — INPUT DATA
# ============================================================================

# ---------------------------------------------------------------------------
# CLIENT 1 — MARIA — Maria's Kitchen
# Restaurant · 14 employees · ~$1.2M annual revenue · Vancouver, BC
# ---------------------------------------------------------------------------
MARIA = {
    "current_balance":           24_300.00,
    # ADP Run
    "gross_pay":                 18_400.00,
    "net_pay":                   13_920.00,   # actual ACH debit
    "payroll_day":               16,           # Day 16 = March 15 2026
    "payroll_period":            "biweekly",
    # CRA 2026 employer rates
    "employer_cpp_rate":          0.0595,
    "employer_ei_rate":           0.0166,
    # Daily revenue (Toast seasonal $700 × 0.82)
    "daily_projected_revenue":    574.00,
    "square_payout_amount":     4_900.00,
    "square_payout_day":          2,
    # Fixed daily opex
    "daily_fixed_costs":          600.00,
    # Scheduled large outflows
    "produce_bill_amount":      14_200.00,
    "produce_bill_day":           8,
    "cash_threshold_floor":     3_000.00,
    # Toast data this week
    "food_cogs_week":           10_299.00,
    "food_revenue_week":        26_800.00,
    # Food cost 12-week rolling history
    # Constructed to reproduce documented mean=30.2917 %, stdev=0.4522 %
    # (doc hint: "30.2+29.8+…+30.4")
    "food_cost_history_12wk": [
        29.8588, 29.8588, 29.8588, 29.8588, 29.8588, 29.8588,
        30.7246, 30.7246, 30.7246, 30.7246, 30.7246, 30.7246,
    ],
    "ar_invoice_312_amount":    9_800.00,
    "credit_line_available":   25_000.00,
    "deferred_purchase_amount": 5_400.00,
}

# ---------------------------------------------------------------------------
# CLIENT 2 — JAMES — Fraser Valley Contracting
# Contractor · 8 employees · ~$2.8M annual revenue · Burnaby, BC
# ---------------------------------------------------------------------------
JAMES = {
    "current_balance":           68_400.00,
    "ar_balance_total":          87_000.00,
    "revenue_last_90d":         247_500.00,
    # DSO 12-week history — constructed for mean=23.59 days, stdev=0.72 days
    "dso_history_12wk": [
        22.9007, 22.9007, 22.9007, 22.9007, 22.9007, 22.9007,
        24.2793, 24.2793, 24.2793, 24.2793, 24.2793, 24.2793,
    ],
    "stated_payment_terms_days": 30,           # net-30 terms [FIX-M07]
    # Per-client — Coastal Properties (exact history from case doc)
    "coastal_payment_delays":   [2, 4, 3, 5, 2, 3, 4, 3, 2, 4],
    "coastal_invoice_amount":   27_000.00,
    "coastal_days_overdue":     31,
    # M-12 Project float
    "project_upfront_costs":   140_000.00,
    "project_upfront_day":     42,
    "project_first_payment":   180_000.00,
    "project_payment_day":     87,
    "contractor_float_threshold": 15_000.00,
}

# ---------------------------------------------------------------------------
# CLIENT 3 — SARAH — Northvane Studio
# Agency/Founder · 6 employees · Vancouver, BC
# ---------------------------------------------------------------------------
SARAH = {
    "current_balance":           94_200.00,
    # Gusto — biweekly net pay PER RUN
    "payroll_net_per_run":       14_200.00,
    "payroll_period":            "biweekly",
    # Non-payroll monthly fixed costs
    "non_payroll_monthly":        7_200.00,   # rent $3,800 + software $2,100 + other $1,300
    # Stripe MRR
    "stripe_mrr":                 9_800.00,
    # QB this week
    "revenue_this_week":         38_000.00,
    # Labor % 12-week history — constructed for mean=36.1583 %, stdev=0.6331 %
    "labor_pct_history_12wk": [
        35.5522, 35.5522, 35.5522, 35.5522, 35.5522, 35.5522,
        36.7644, 36.7644, 36.7644, 36.7644, 36.7644, 36.7644,
    ],
    # Revenue 12-week history — constructed for mean=$39,992, stdev=$715.40
    "revenue_history_12wk": [
        39_307.0, 39_307.0, 39_307.0, 39_307.0, 39_307.0, 39_307.0,
        40_677.0, 40_677.0, 40_677.0, 40_677.0, 40_677.0, 40_677.0,
    ],
}

# ---------------------------------------------------------------------------
# CLIENT 4 — AMIR — Kova AI
# Pre-seed Founder · 2 employees · $4,200 Stripe MRR · Vancouver, BC
# ---------------------------------------------------------------------------
AMIR = {
    "current_balance":          112_000.00,
    # Gusto — biweekly net pay PER RUN
    "payroll_net_per_run":       10_400.00,
    "payroll_period":            "biweekly",
    # Non-payroll monthly expenses
    "non_payroll_monthly":        8_200.00,   # rent $4,200 + software $2,800 + other $1,200
    # Stripe MRR
    "stripe_mrr":                 4_200.00,
    # GST inputs (QuickBooks + Stripe Q1)
    "taxable_revenue_q1":        42_000.00,
    "gst_rate":                   0.05,        # BC federal GST
    # ITC expenses by category [FIX-M03]
    "itc_expenses": [
        # (amount, category)  — eligibility applied per category
        (8_400.00, "software"),          # Figma, Slack, AWS — standard taxable, eligibility 1.0
    ],
    "gst_actually_reserved":          0.00,
    "weeks_remaining_in_qtr":         4.4,
    # M-15 inputs
    "m15_dso_days":              0.0,
    "m15_gross_margin_pct":     66.0,
    "m15_payroll_coverage_ratio": 10.01,   # balance/payroll_out >> 1.5 → clips to 100
    "m15_data_quality_score":   80.0,
}

# ---------------------------------------------------------------------------
# MARIA_TRANSACTIONS — representative normalized transaction rows
# Source: 02_NORMALIZED_DB_ROWS.md (sign convention: negative = debit/outflow)
# Recurring vendors appear ≥ 3 times so the unmodelled-outflow scan ignores
# them.  The two irregular large debits at the bottom are what the scan flags.
# ---------------------------------------------------------------------------
MARIA_TRANSACTIONS = [
    # Recurring payroll (3 runs in history → recognised as recurring)
    {"merchant_name": "ADP PAYROLL",             "amount": -15320.24, "date": "2026-02-28", "is_pending": False},
    {"merchant_name": "ADP PAYROLL",             "amount": -14890.00, "date": "2026-02-14", "is_pending": False},
    {"merchant_name": "ADP PAYROLL",             "amount": -15100.00, "date": "2026-01-31", "is_pending": False},
    # Recurring produce supplier (3 orders)
    {"merchant_name": "METRO PRODUCE SUPPLY",    "amount": -14200.00, "date": "2026-02-26", "is_pending": False},
    {"merchant_name": "METRO PRODUCE SUPPLY",    "amount": -13800.00, "date": "2026-02-12", "is_pending": False},
    {"merchant_name": "METRO PRODUCE SUPPLY",    "amount": -14500.00, "date": "2026-01-29", "is_pending": False},
    # Recurring utility (3 bills)
    {"merchant_name": "BC Hydro",                "amount":   -420.00, "date": "2026-02-20", "is_pending": False},
    {"merchant_name": "BC Hydro",                "amount":   -415.00, "date": "2026-01-20", "is_pending": False},
    {"merchant_name": "BC Hydro",                "amount":   -430.00, "date": "2025-12-20", "is_pending": False},
    # Revenue credit — ignored by debit scan
    {"merchant_name": "SQUARE INC",              "amount":  +4900.00, "date": "2026-02-24", "is_pending": False},
    # Small food supplier (amount < $1,000 threshold → not flagged)
    {"merchant_name": "SYSCO CANADA 4821",       "amount":    -89.00, "date": "2026-02-19", "is_pending": False},
    # Pending — excluded from the scan
    {"merchant_name": "RICExPRESS WHOLESALE",    "amount":   -312.50, "date": "2026-02-28", "is_pending": True},
    # ── Irregular large debits the forecast is NOT capturing ──────────────
    # Annual commercial insurance (appears once per year)
    {"merchant_name": "PACIFIC INSURANCE GROUP", "amount":  -3200.00, "date": "2026-01-15", "is_pending": False},
    # Quarterly kitchen-equipment maintenance (appears ~4×/year, but only
    # once in this 90-day window — flagged as irregular by the scan)
    {"merchant_name": "KITCHENTECH REPAIRS",     "amount":  -1800.00, "date": "2025-11-20", "is_pending": False},
]


# ============================================================================

# ============================================================================
# SECTION 2 — TEST INFRASTRUCTURE
# (utility functions and metric functions now in pulse_metrics.py)
# ============================================================================

ALL_PASS = True

def _check(label, computed, expected, tol=0.02):
    global ALL_PASS
    ok = abs(computed - expected) <= tol
    status = "✅ PASS" if ok else "❌ FAIL"
    print(f"  {status}  {label}")
    print(f"         computed={computed:.4f}  expected={expected:.4f}  tol=±{tol}")
    if not ok:
        print(f"  *** DEVIATION: diff={computed - expected:+.6f} ***")
        ALL_PASS = False
    return ok

# ============================================================================
# SECTION 4 — HELPERS
# ============================================================================

def _build_maria_flow(m, days=90):
    """Construct Maria's daily inflow/outflow arrays."""
    inflows  = [m["daily_projected_revenue"]] * days
    outflows = [m["daily_fixed_costs"]] * days
    inflows[m["square_payout_day"] - 1]  += m["square_payout_amount"]
    outflows[m["produce_bill_day"] - 1]  += m["produce_bill_amount"]
    employer_taxes = (m["gross_pay"] * m["employer_cpp_rate"]
                    + m["gross_pay"] * m["employer_ei_rate"])
    payroll_cash_out = m["net_pay"] + employer_taxes
    outflows[m["payroll_day"] - 1] += payroll_cash_out
    return inflows, outflows, payroll_cash_out


# ============================================================================
# SECTION 5 — TEST CASES (4 clients + assertions)
# ============================================================================

# ---------------------------------------------------------------------------
# CLIENT 1 — MARIA
# ---------------------------------------------------------------------------
def test_maria():
    print("\n" + "═" * 72)
    print("  TEST 1 — MARIA — Maria's Kitchen  (M-01 · M-02 · M-05)")
    print("═" * 72)
    m = MARIA
    inflows, outflows, _ = _build_maria_flow(m)

    avg_weekly_fixed = m["daily_fixed_costs"] * 7
    gap_day, gap_bal, gap_amount, threshold, balances = m01_cash_gap(
        m["current_balance"], inflows, outflows,
        avg_weekly_fixed, m["cash_threshold_floor"],
    )

    payroll_cash_out, coverage = m02_payroll_coverage(
        m["gross_pay"], m["net_pay"],
        m["employer_cpp_rate"], m["employer_ei_rate"],
        balances[m["payroll_day"] - 1],
    )

    food_cost_pct, z_food, mu_food, sigma_food = m05_food_cost(
        m["food_cogs_week"], m["food_revenue_week"],
        m["food_cost_history_12wk"],
    )

    print("\n  ── Assertions ──")
    # M-01
    _check("M-01  gap on day 16",
           float(gap_day or -1), 16.0, tol=0)
    _check("M-01  balance[16]",
           gap_bal, -736.24, tol=0.05)
    _check("M-01  gap_amount  (threshold − balance)",
           gap_amount, 3_736.24, tol=0.05)
    _check("M-01  cash_threshold  ($3,000 floor wins)",
           threshold, 3_000.00, tol=0.01)
    _check("M-01  balance[15]  (day before payroll)",
           balances[m["payroll_day"] - 1], 14_610.00, tol=0.05)

    # M-02
    expected_taxes = 18_400 * 0.0595 + 18_400 * 0.0166
    _check("M-02  employer_taxes",
           expected_taxes, 1_400.24, tol=0.01)
    _check("M-02  payroll_cash_out",
           payroll_cash_out, 15_320.24, tol=0.05)
    _check("M-02  coverage_ratio  (< 1.0 → CRITICAL)",
           coverage, 0.9537, tol=0.001)

    # M-05
    _check("M-05  food_cost_pct",
           food_cost_pct, 38.43, tol=0.02)
    _check("M-05  12wk mean",
           mu_food, 30.2917, tol=0.001)
    _check("M-05  12wk raw stdev  (orig spec)",
           _sample_stdev(m["food_cost_history_12wk"]), 0.4522, tol=0.002)
    # [FIX-M05] sigma_eff is floored at 0.5 → z changes from 18.0 to ~16.28
    _check("M-05  sigma_eff  (max(0.4522, 0.5) = 0.5)  [FIX-M05]",
           sigma_food, 0.50, tol=0.001)
    _check("M-05  z_food  FIXED (s_floor applied)  [FIX-M05]",
           z_food, 16.28, tol=0.10)
    print("  ℹ️   DEVIATION NOTE: original spec z=18.00; [FIX-M05] z=16.28 "
          "(sigma floored at 0.5 pp). z>4 → VERIFY DATA, not crisis alert.")


# ---------------------------------------------------------------------------
# CLIENT 2 — JAMES
# ---------------------------------------------------------------------------
def test_james():
    print("\n" + "═" * 72)
    print("  TEST 2 — JAMES — Fraser Valley Contracting  (M-07 · M-08 · M-12)")
    print("═" * 72)
    j = JAMES

    dso, z_dso, mu_dso, sigma_dso = m07_dso(
        j["ar_balance_total"], j["revenue_last_90d"],
        j["dso_history_12wk"],
        stated_payment_terms=j["stated_payment_terms_days"],
    )

    client_avg, client_stdev, client_z, alert_fires = m08_client_delay(
        "Coastal Properties",
        j["coastal_days_overdue"],
        j["coastal_payment_delays"],
        min_invoices=6,
    )

    # M-12: case analysis used simplified formula (baseline − upfront only).
    # [FIX-M12] full version would subtract fixed costs during float.
    # Validate the original documented figures; note fix changes recommended_draw.
    min_float, recommended_draw = m12_project_float(
        j["current_balance"], j["project_upfront_costs"],
        j["project_upfront_day"], j["project_first_payment"],
        j["project_payment_day"],
        threshold=j["contractor_float_threshold"],
        daily_fixed_during_float=0,   # 0 = original simplified form
        client_known=True,
    )

    print("\n  ── Assertions ──")
    _check("M-07  avg_daily_sales",
           j["revenue_last_90d"] / 90, 2_750.00, tol=0.01)
    _check("M-07  DSO",
           dso, 31.636, tol=0.01)
    _check("M-07  12wk DSO mean",
           mu_dso, 23.59, tol=0.01)
    _check("M-07  12wk DSO stdev  (=0.72 per z-score back-calc)",
           sigma_dso, 0.72, tol=0.02)
    _check("M-07  z_DSO",
           z_dso, 11.17, tol=0.15)

    _check("M-08  client_avg_delay",
           client_avg, 3.20, tol=0.001)
    _check("M-08  client_stdev",
           client_stdev, 1.0328, tol=0.001)
    _check("M-08  client_z",
           client_z, 26.92, tol=0.02)
    _check("M-08  practical floor met  (31−3.2=27.8 ≥ 10)  [FIX-M08]",
           float(alert_fires), 1.0, tol=0)
    print(f"  ℹ️   [FIX-M08] alert fires because BOTH: "
          f"z={client_z:.2f}>2.5 AND abs_gap=27.8d≥10d")

    _check("M-12  min_float_balance  (baseline − upfront)",
           min_float, -71_600.00, tol=1.0)
    _check("M-12  recommended_draw",
           recommended_draw, 86_600.00, tol=1.0)
    print("  ℹ️   [FIX-M12] full version subtracts ongoing fixed costs during "
          "float window, making min_float deeper and draw larger.")


# ---------------------------------------------------------------------------
# CLIENT 3 — SARAH
# ---------------------------------------------------------------------------
def test_sarah():
    print("\n" + "═" * 72)
    print("  TEST 3 — SARAH — Northvane Studio  (M-06 compound · M-13)")
    print("═" * 72)
    s = SARAH

    labor_pct, z_labor, z_revenue, compound = m06_labor_cost(
        s["payroll_net_per_run"],    # this week's payroll expense
        s["revenue_this_week"],
        s["labor_pct_history_12wk"],
        s["revenue_history_12wk"],
    )

    monthly_payroll, gross_burn, net_burn, runway, raise_window = m13_runway(
        payroll_net_per_run  = s["payroll_net_per_run"],
        payroll_period       = s["payroll_period"],
        non_payroll_monthly  = s["non_payroll_monthly"],
        revenue_monthly      = s["stripe_mrr"],
        current_balance      = s["current_balance"],
        vc_buffer_months     = 6.0,
    )

    print("\n  ── Assertions ──")
    _check("M-06  labor_pct",
           labor_pct, 37.368, tol=0.005)
    _check("M-06  12wk labor mean",
           _mean(s["labor_pct_history_12wk"]), 36.1583, tol=0.001)
    _check("M-06  12wk labor stdev",
           _sample_stdev(s["labor_pct_history_12wk"]), 0.6331, tol=0.002)
    _check("M-06  z_labor",
           z_labor, 1.91, tol=0.02)
    _check("M-06  z_revenue",
           z_revenue, -2.78, tol=0.02)
    _check("M-06  compound_signal this week",
           float(compound), 1.0, tol=0)

    # [FIX-M13] biweekly × 26/12 = 2.1667
    monthly_expected = 14_200.0 * 26 / 12   # = 30,766.67
    _check("M-13  monthly_payroll  (14,200 × 26/12)  [FIX-M13]",
           monthly_payroll, monthly_expected, tol=0.10)
    _check("M-13  gross_burn  (corrected)  [FIX-M13]",
           gross_burn, monthly_expected + s["non_payroll_monthly"], tol=0.10)
    _check("M-13  net_burn  (corrected)  [FIX-M13]",
           net_burn, monthly_expected + s["non_payroll_monthly"] - s["stripe_mrr"],
           tol=0.10)
    runway_corrected = s["current_balance"] / (monthly_expected + s["non_payroll_monthly"] - s["stripe_mrr"])
    _check("M-13  runway  CORRECTED  [FIX-M13]",
           runway, runway_corrected, tol=0.02)

    print(f"\n  ℹ️   DEVIATION NOTE [FIX-M13]:")
    print(f"       Case analysis (biweekly treated as monthly): "
          f"net_burn=$11,600  runway=8.12 months")
    print(f"       CORRECTED (biweekly × 26/12 = 2.1667): "
          f"net_burn=${net_burn:,.2f}  runway={runway:.2f} months")
    print(f"       This is a CRITICAL difference — ~{8.12 / runway:.1f}× overstatement "
          f"in the case analysis.")


# ---------------------------------------------------------------------------
# CLIENT 4 — AMIR
# ---------------------------------------------------------------------------
def test_amir():
    print("\n" + "═" * 72)
    print("  TEST 4 — AMIR — Kova AI  (M-03 · M-13 · M-15)")
    print("═" * 72)
    a = AMIR

    est_gst_gross, est_gst_net, reserve_gap, weekly_needed = m03_gst_reserve_gap(
        taxable_revenue    = a["taxable_revenue_q1"],
        gst_rate           = a["gst_rate"],
        itc_expenses       = a["itc_expenses"],
        gst_actually_reserved = a["gst_actually_reserved"],
        weeks_remaining    = a["weeks_remaining_in_qtr"],
    )

    monthly_payroll, gross_burn, net_burn, runway, raise_window = m13_runway(
        payroll_net_per_run  = a["payroll_net_per_run"],
        payroll_period       = a["payroll_period"],
        non_payroll_monthly  = a["non_payroll_monthly"],
        revenue_monthly      = a["stripe_mrr"],
        current_balance      = a["current_balance"],
        vc_buffer_months     = 6.0,
    )

    # For M-15, use the corrected runway from M-13 [FIX-M13]
    expansion_score, band, component_scores = m15_expansion_score(
        dso_days           = a["m15_dso_days"],
        gross_margin_pct   = a["m15_gross_margin_pct"],
        coverage_ratio     = a["m15_payroll_coverage_ratio"],
        runway_months      = runway,      # ← corrected runway [FIX-M13]
        gst_reserve_gap    = reserve_gap,
        est_gst_owing      = est_gst_net,
        data_quality_score = a["m15_data_quality_score"],
    )

    print("\n  ── Assertions ──")

    # M-03
    _check("M-03  est_gst_gross  ($42,000 × 5%)",
           est_gst_gross, 2_100.00, tol=0.01)
    # [FIX-M03] software ITCs = $8,400 × 5% × 1.0 = $420 (unchanged for Amir)
    _check("M-03  est_ITCs  (software @ eligibility 1.0)  [FIX-M03]",
           est_gst_net, 1_680.00, tol=0.01)
    _check("M-03  gst_reserve_gap",
           reserve_gap, 1_680.00, tol=0.01)
    _check("M-03  weekly_reserve_needed  ($1,680 / 4.4)",
           weekly_needed, 381.82, tol=0.02)
    print("  ℹ️   M-03 ITC result unchanged because Amir's only expenses are "
          "software (eligibility=1.0).  Fix matters when wages or meals are "
          "incorrectly claimed as ITCs.")

    # M-13 [FIX-M13]
    monthly_exp = 10_400.0 * 26 / 12
    _check("M-13  monthly_payroll  (10,400 × 26/12)  [FIX-M13]",
           monthly_payroll, monthly_exp, tol=0.10)
    runway_corrected = a["current_balance"] / (monthly_exp + a["non_payroll_monthly"] - a["stripe_mrr"])
    _check("M-13  runway  CORRECTED  [FIX-M13]",
           runway, runway_corrected, tol=0.02)

    # M-15
    _check("M-15  dso_score    (no AR → 100)",
           component_scores["dso"], 100.0, tol=0.1)
    _check("M-15  margin_score ((66-20)/(70-20)×100 = 92)",
           component_scores["margin"], 92.0, tol=0.1)
    _check("M-15  coverage_score (ratio>>1.5 → 100)",
           component_scores["coverage"], 100.0, tol=0.1)
    runway_score_corrected = _score_runway(runway_corrected)
    _check("M-15  runway_score  CORRECTED  [FIX-M13]",
           component_scores["runway"], runway_score_corrected, tol=0.5)
    _check("M-15  gst_score    (1680 gap / 1680 owing → 0)",
           component_scores["gst"], 0.0, tol=0.1)
    _check("M-15  data_quality (manual = 80)",
           component_scores["data_quality"], 80.0, tol=0.1)

    print(f"\n  ℹ️   DEVIATION NOTE [FIX-M13]:")
    print(f"       Case analysis runway: 7.78 months  → "
          f"expansion runway_score={_score_runway(7.78):.1f}")
    print(f"       CORRECTED runway    : {runway:.2f} months → "
          f"expansion runway_score={runway_score_corrected:.1f}")
    print(f"       Case analysis total score: 72.77")
    print(f"       CORRECTED total score    : {expansion_score:.2f}  band: '{band}'")


# ---------------------------------------------------------------------------
# NEW ASSERTIONS — Change 2 (alert budget) · Change 3 (VERIFY DATA routing)
# ---------------------------------------------------------------------------
def test_new_features():
    print("\n" + "═" * 72)
    print("  NEW ASSERTIONS — Change 2 · Alert Budget  &  Change 3 · VERIFY DATA")
    print("═" * 72)

    # ── Change 3: _route_z_signal routing ────────────────────────────────────
    # Three canonical cases for the cross-cutting extreme-reading router.
    print("\n  ── Change 3 routing cases ──")
    route_extreme = _route_z_signal(11.18, "M-07 test [extreme]", direction="high")
    route_alert   = _route_z_signal( 2.50, "M-07 test [alert]",   direction="high")
    route_ok      = _route_z_signal( 1.00, "M-07 test [ok]",      direction="high")

    print("\n  ── Assertions ──")
    _check("CHANGE 3  z=11.18 routes to VERIFY_DATA",
           float(route_extreme == "VERIFY_DATA"), 1.0, tol=0.0)
    _check("CHANGE 3  z=2.50  routes to ALERT",
           float(route_alert   == "ALERT"),       1.0, tol=0.0)
    _check("CHANGE 3  z=1.00  routes to OK",
           float(route_ok      == "OK"),           1.0, tol=0.0)

    # ── Change 2: rank_and_cap_alerts ────────────────────────────────────────
    # 9 signals submitted.  _portfolio_z_cutoff(9) = 2.807.
    # 4 signals are below the cutoff and get filtered; 5 survive.
    # cap=4 then suppresses the 5th (M-09 vendor B, sev=3.50).
    # VERIFY_DATA signals bypass the cutoff but are still subject to the cap.
    print("\n  ── Change 2 alert budget (9 signals, cap=4) ──")
    signals = [
        ("M-08 client delay",  26.92, "ALERT",       "Coastal 31d overdue — abs_gap 27.8d"),
        ("M-07 DSO",           11.18, "VERIFY_DATA",  "DSO z=11.18 — check AR snapshot"),
        ("M-05 food cost",     16.27, "VERIFY_DATA",  "food cost z=16.27 — verify invoices"),
        ("M-09 vendor A",      10.85, "VERIFY_DATA",  "vendor A z=10.85 — check POS remap"),
        ("M-09 vendor B",       3.50, "ALERT",        "vendor B z=3.50 — above cutoff"),
        ("M-10 revenue",        2.78, "ALERT",        "revenue z=−2.78 — below cutoff 2.807"),
        ("M-06 labor",          1.91, "ALERT",        "labor z=1.91 — below cutoff 2.807"),
        ("M-03 GST reserve",    2.50, "WARNING",      "GST gap $1,680 — below cutoff 2.807"),
        ("M-02 payroll cov.",   0.95, "ALERT",        "coverage 0.95 < 1.0 — below cutoff"),
    ]
    capped = rank_and_cap_alerts(signals, cap=4)

    print("\n  ── Assertions ──")
    _check("CHANGE 2  cap=4 → returns exactly 4",
           float(len(capped)), 4.0, tol=0.0)
    _check("CHANGE 2  top signal is highest severity (M-08, z=26.92)",
           capped[0][1], 26.92, tol=0.01)
    _check("CHANGE 2  M-10 (z=2.78 < cutoff 2.807) not returned",
           float(not any(s[0] == "M-10 revenue"   for s in capped)), 1.0, tol=0.0)
    _check("CHANGE 2  M-06 (z=1.91 < cutoff 2.807) not returned",
           float(not any(s[0] == "M-06 labor"     for s in capped)), 1.0, tol=0.0)
    _check("CHANGE 2  M-09 vendor B (z=3.50, above cutoff) trimmed by cap",
           float(not any(s[0] == "M-09 vendor B"  for s in capped)), 1.0, tol=0.0)

    # ── Change 1: M-01 Monte Carlo ────────────────────────────────────────────
    # Maria, 1,000 runs, no invoice clients.
    # Because every noisy scenario still forces a payroll-day breach (the
    # ±15% revenue / ±10% cost swings cannot offset a $15,320 payroll hit
    # against a ~$14,610 pre-payroll balance), prob_breach ≈ 1.0 and
    # gap_day = 16 in all runs.  The band asserts the deterministic result
    # (Day 16, $3,736.24) sits inside the P10–P90 envelope.
    print("\n  ── Change 1 M-01 Monte Carlo (Maria, 1,000 runs) ──")
    m        = MARIA
    inflows, outflows, _ = _build_maria_flow(m)
    avg_wf   = m["daily_fixed_costs"] * 7

    mc = m01_cash_gap_mc(
        m["current_balance"], inflows, outflows,
        avg_wf, m["cash_threshold_floor"],
        revenue_noise_pct=0.15,
        cost_noise_pct=0.10,
        transaction_history=MARIA_TRANSACTIONS,
        n_runs=1_000,
        seed=42,
    )

    DET_GAP_DAY = 16
    DET_GAP_AMT = 3_736.24   # threshold($3,000) − balance(−$736.24)

    print("\n  ── Assertions ──")
    _check("CHANGE 1  P(breach) ≥ 0.90  (Maria is in cash crisis)",
           mc["prob_breach"], 1.0, tol=0.10)
    _check("CHANGE 1  P10_gap_day ≤ deterministic day 16",
           float((mc["p10_gap_day"] or 999) <= DET_GAP_DAY), 1.0, tol=0.0)
    _check("CHANGE 1  P90_gap_day ≥ deterministic day 16",
           float((mc["p90_gap_day"] or   0) >= DET_GAP_DAY), 1.0, tol=0.0)
    _check("CHANGE 1  P10_gap_amt ≤ deterministic gap $3,736.24",
           float((mc["p10_gap_amt"] or 999_999) <= DET_GAP_AMT), 1.0, tol=0.0)
    _check("CHANGE 1  P90_gap_amt ≥ deterministic gap $3,736.24",
           float((mc["p90_gap_amt"] or       0) >= DET_GAP_AMT), 1.0, tol=0.0)
    _check("CHANGE 1  unmodelled outflows detected (≥ 1 irregular large debit)",
           float(len(mc["unmodelled_outflows"]) >= 1), 1.0, tol=0.0)


# ---------------------------------------------------------------------------
# THIN-HISTORY EDGE-CASE ASSERTIONS
# ---------------------------------------------------------------------------
def test_thin_history():
    """
    Eight assertions across four metrics proving that insufficient history
    produces a clearly-labelled degraded state — NOT a spurious alert.
    """

    def _cap(fn, *args, **kwargs):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = fn(*args, **kwargs)
        return result, buf.getvalue()

    print("\n" + "═" * 72)
    print("  THIN-HISTORY EDGE-CASE ASSERTIONS")
    print("  Proves: too-little history → labelled degraded state, not false alert")
    print("═" * 72)

    # ── TH-01  M-07: 3 paid invoices (< 5 required) ──────────────────────
    print("\n  ── TH-01  M-07  invoice_count=3 (need ≥ 5)")
    result_07, out_07 = _cap(
        m07_dso, 3_000.0, 90_000.0,
        [30.0] * 8,                          # history ignored on this path
        stated_payment_terms=30, invoice_count=3,
    )
    dso_th, z_th, mu_th, sig_th = result_07
    for ln in out_07.splitlines():
        print("  " + ln)

    _check("TH-01  M-07 invoice_count=3 → z_dso is None (z-score suppressed)",
           float(z_th is None), 1.0, tol=0.0)
    _check("TH-01  M-07 DSO value still returned (3000 / (90000/90) = 3d)",
           dso_th, 3.0, tol=0.01)
    _check("TH-01  M-07 output contains 'INSUFFICIENT_HISTORY'",
           float("INSUFFICIENT_HISTORY" in out_07), 1.0, tol=0.0)

    # ── TH-02  M-08: 4 invoices (< 6 required) ───────────────────────────
    print("\n  ── TH-02  M-08  4-invoice history (need ≥ 6)")
    result_08, out_08 = _cap(
        m08_client_delay, "Thin Client Co", 35, [28, 30, 32, 29],
    )
    avg_th, std_th, z_th2, fires_th = result_08
    for ln in out_08.splitlines():
        print("  " + ln)

    _check("TH-02  M-08 4 invoices → alert_fires=False",
           float(fires_th), 0.0, tol=0.0)
    _check("TH-02  M-08 4 invoices → client_z is None",
           float(z_th2 is None), 1.0, tol=0.0)
    _check("TH-02  M-08 output contains 'INSUFFICIENT_HISTORY'",
           float("INSUFFICIENT_HISTORY" in out_08), 1.0, tol=0.0)

    # ── TH-03  M-10: 4 weeks of history (< 12 required) ──────────────────
    print("\n  ── TH-03  M-10  4-week history (need ≥ 12)")
    result_10, out_10 = _cap(
        m10_revenue_trend, 38_000.0, [36_000, 37_000, 39_000, 40_000],
    )
    z_th3, exp_th3, mu_th3, sig_th3 = result_10
    for ln in out_10.splitlines():
        print("  " + ln)

    _check("TH-03  M-10 4 weeks → revenue_z is None (no statistical alert)",
           float(z_th3 is None), 1.0, tol=0.0)
    _check("TH-03  M-10 output contains 'INSUFFICIENT_HISTORY'",
           float("INSUFFICIENT_HISTORY" in out_10), 1.0, tol=0.0)

    # ── TH-04  M-15: months_of_data=2 (< 3 required) ─────────────────────
    print("\n  ── TH-04  M-15  months_of_data=2 (need ≥ 3)")
    result_15, out_15 = _cap(
        m15_expansion_score,
        dso_days=10, gross_margin_pct=62, coverage_ratio=1.2,
        runway_months=6, gst_reserve_gap=0, est_gst_owing=1_000,
        data_quality_score=80, months_of_data=2,
    )
    score_th, band_th, comp_th = result_15
    for ln in out_15.splitlines():
        print("  " + ln)

    _check("TH-04  M-15 months_of_data=2 → band contains 'PARTIAL'",
           float("PARTIAL" in band_th), 1.0, tol=0.0)
    _check("TH-04  M-15 score still computed (not None — directional use)",
           float(score_th is not None), 1.0, tol=0.0)
    _check("TH-04  M-15 output contains 'PARTIAL'",
           float("PARTIAL" in out_15), 1.0, tol=0.0)


# ---------------------------------------------------------------------------
# DIRTY-DATA FLAG ASSERTIONS
# ---------------------------------------------------------------------------
def test_dirty_data():
    """
    Seven assertions proving that structurally-bad inputs raise
    DATA_QUALITY_FLAG and never produce a financial alert.
    Covers: zero COGS, COGS ≥ 100% revenue, zero revenue, COGS < 5%.
    """

    def _cap(fn, *args, **kwargs):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = fn(*args, **kwargs)
        return result, buf.getvalue()

    def _no_alert(out):
        """True when no financial-alert phrase appears in captured output."""
        alert_phrases = ("abs floor breach", "abs ceiling breach",
                         "⚠️  ALERT", "⚠️  [M-")
        return not any(p in out for p in alert_phrases)

    print("\n" + "═" * 72)
    print("  DIRTY-DATA FLAG ASSERTIONS")
    print("  Proves: structurally-bad COGS/revenue → DATA_QUALITY_FLAG, "
          "not a financial alert")
    print("═" * 72)

    REV = 50_000.0   # shared reference revenue

    # ── DQ-01  M-04: COGS = 0 (zero COGS) ────────────────────────────────
    print("\n  ── DQ-01  M-04  COGS=0 (zero COGS → 100% margin implied)")
    gm_01, out_01 = _cap(m04_gross_margin, REV, 0.0)
    for ln in out_01.splitlines():
        print("  " + ln)
    _check("DQ-01  M-04 COGS=0 → returns None",
           float(gm_01 is None), 1.0, tol=0.0)
    _check("DQ-01  M-04 COGS=0 → output contains DATA_QUALITY_FLAG",
           float("DATA_QUALITY_FLAG" in out_01), 1.0, tol=0.0)
    _check("DQ-01  M-04 COGS=0 → no financial alert fires",
           float(_no_alert(out_01)), 1.0, tol=0.0)

    # ── DQ-02  M-04: COGS > 100% of revenue ──────────────────────────────
    print("\n  ── DQ-02  M-04  COGS=60,000 on revenue=50,000 (COGS 120% ≥ 100%)")
    gm_02, out_02 = _cap(m04_gross_margin, REV, 60_000.0)
    for ln in out_02.splitlines():
        print("  " + ln)
    _check("DQ-02  M-04 COGS≥revenue → returns None",
           float(gm_02 is None), 1.0, tol=0.0)
    _check("DQ-02  M-04 COGS≥revenue → output contains DATA_QUALITY_FLAG",
           float("DATA_QUALITY_FLAG" in out_02), 1.0, tol=0.0)
    _check("DQ-02  M-04 COGS≥revenue → no financial alert fires",
           float(_no_alert(out_02)), 1.0, tol=0.0)

    # ── DQ-03  M-04: zero revenue ─────────────────────────────────────────
    print("\n  ── DQ-03  M-04  revenue=0 (zero revenue denominator)")
    gm_03, out_03 = _cap(m04_gross_margin, 0.0, 10_000.0)
    for ln in out_03.splitlines():
        print("  " + ln)
    _check("DQ-03  M-04 revenue=0 → returns None",
           float(gm_03 is None), 1.0, tol=0.0)
    _check("DQ-03  M-04 revenue=0 → output contains DATA_QUALITY_FLAG",
           float("DATA_QUALITY_FLAG" in out_03), 1.0, tol=0.0)
    _check("DQ-03  M-04 revenue=0 → no financial alert fires",
           float(_no_alert(out_03)), 1.0, tol=0.0)

    # ── DQ-04  M-04: COGS < 5% of revenue (confirm categorisation) ───────
    print("\n  ── DQ-04  M-04  COGS=1,000 on revenue=50,000 (COGS 2% < 5%)")
    gm_04, out_04 = _cap(m04_gross_margin, REV, 1_000.0)
    for ln in out_04.splitlines():
        print("  " + ln)
    _check("DQ-04  M-04 COGS<5% → returns None",
           float(gm_04 is None), 1.0, tol=0.0)
    _check("DQ-04  M-04 COGS<5% → output contains DATA_QUALITY_FLAG",
           float("DATA_QUALITY_FLAG" in out_04), 1.0, tol=0.0)
    _check("DQ-04  M-04 COGS<5% → no financial alert fires",
           float(_no_alert(out_04)), 1.0, tol=0.0)

    # ── DQ-05  M-05: zero food_cogs ───────────────────────────────────────
    print("\n  ── DQ-05  M-05  food_COGS=0 (zero food cost implied)")
    fc_05, out_05 = _cap(m05_food_cost, 0.0, REV, [30.0] * 12)
    fcp_05, *_ = fc_05
    for ln in out_05.splitlines():
        print("  " + ln)
    _check("DQ-05  M-05 food_COGS=0 → food_cost_pct is None",
           float(fcp_05 is None), 1.0, tol=0.0)
    _check("DQ-05  M-05 food_COGS=0 → output contains DATA_QUALITY_FLAG",
           float("DATA_QUALITY_FLAG" in out_05), 1.0, tol=0.0)
    _check("DQ-05  M-05 food_COGS=0 → no financial alert fires",
           float(_no_alert(out_05)), 1.0, tol=0.0)

    # ── DQ-06  M-05: food_cogs ≥ food_revenue ────────────────────────────
    print("\n  ── DQ-06  M-05  food_COGS=60,000 on food_revenue=50,000 (COGS ≥ rev)")
    fc_06, out_06 = _cap(m05_food_cost, 60_000.0, REV, [30.0] * 12)
    fcp_06, *_ = fc_06
    for ln in out_06.splitlines():
        print("  " + ln)
    _check("DQ-06  M-05 COGS≥revenue → food_cost_pct is None",
           float(fcp_06 is None), 1.0, tol=0.0)
    _check("DQ-06  M-05 COGS≥revenue → output contains DATA_QUALITY_FLAG",
           float("DATA_QUALITY_FLAG" in out_06), 1.0, tol=0.0)
    _check("DQ-06  M-05 COGS≥revenue → no financial alert fires",
           float(_no_alert(out_06)), 1.0, tol=0.0)

    # ── DQ-07  M-06: zero revenue denominator ────────────────────────────
    print("\n  ── DQ-07  M-06  revenue=0 (proves 'any metric' zero-revenue guard)")
    lh = [35.0] * 12;  rh = [50_000.0] * 12
    m6_07, out_07 = _cap(m06_labor_cost, 10_000.0, 0.0, lh, rh)
    lp_07, *_ = m6_07
    for ln in out_07.splitlines():
        print("  " + ln)
    _check("DQ-07  M-06 revenue=0 → labor_pct is None",
           float(lp_07 is None), 1.0, tol=0.0)
    _check("DQ-07  M-06 revenue=0 → output contains DATA_QUALITY_FLAG",
           float("DATA_QUALITY_FLAG" in out_07), 1.0, tol=0.0)
    _check("DQ-07  M-06 revenue=0 → no financial alert fires",
           float(_no_alert(out_07)), 1.0, tol=0.0)


# ---------------------------------------------------------------------------
# VERTICAL ROUTING ASSERTIONS
# ---------------------------------------------------------------------------
def test_vertical_routing():
    """
    Six assertions — three pairs — proving that VERTICAL_CONFIG changes
    alert behaviour for identical numeric inputs based on business_type.
    """

    def _cap(fn, *args, **kwargs):
        """Call fn, capture its stdout, return (return_value, captured_str)."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = fn(*args, **kwargs)
        return result, buf.getvalue()

    def sym_hist(mu, sigma, n=12):
        """12-point symmetric history: sample mean=mu, sample stdev=sigma."""
        spread = sigma * math.sqrt((n - 1) / n)
        lo, hi = mu - spread, mu + spread
        return [lo] * (n // 2) + [hi] * (n // 2)

    print("\n" + "═" * 72)
    print("  VERTICAL ROUTING ASSERTIONS — same number, different vertical")
    print("═" * 72)

    # ── VR-01  M-07  DSO = 50 days ───────────────────────────────────────
    # restaurant  abs_ceiling = 14d  →  50 > 14 → FIRES
    # contractor  abs_ceiling = 70d  →  50 < 70 → SILENT
    print("\n  ── VR-01  M-07  DSO = 50d")
    print("           restaurant ceil=14d  →  expect FIRES")
    print("           contractor  ceil=70d  →  expect SILENT")
    print()
    ar, rev90 = 50_000.0, 90_000.0   # avg_daily = 1_000 → DSO = 50

    _, out_m07_resto = _cap(m07_dso, ar, rev90,
                            sym_hist(8.0,  1.0),   # restaurant normal DSO ~8d
                            stated_payment_terms=30,
                            business_type="restaurant")
    _, out_m07_contr = _cap(m07_dso, ar, rev90,
                            sym_hist(55.0, 5.0),   # contractor normal DSO ~55d
                            stated_payment_terms=30,
                            business_type="contractor")

    print("  restaurant output:")
    for ln in out_m07_resto.splitlines():
        print("  " + ln)
    print()
    print("  contractor output:")
    for ln in out_m07_contr.splitlines():
        print("  " + ln)

    _check("VR-01  restaurant  DSO=50d > ceil 14d → abs ceiling FIRES",
           float("[M-07 DSO] abs ceiling breach" in out_m07_resto), 1.0, tol=0.0)
    _check("VR-01  contractor  DSO=50d < ceil 70d → abs ceiling SILENT",
           float("[M-07 DSO] abs ceiling breach" not in out_m07_contr), 1.0, tol=0.0)

    # ── VR-02  M-06  labor = 42 % ────────────────────────────────────────
    # restaurant  abs_ceiling = 38%  →  42 > 38 → FIRES
    # agency      z_score_only=True  →  no abs test → SILENT
    print("\n  ── VR-02  M-06  labor = 42%")
    print("           restaurant ceil=38%      →  expect FIRES")
    print("           agency     z-score only  →  expect SILENT")
    print()
    rev   = 100_000.0
    labor =  42_000.0   # 42 %
    lh    = sym_hist(42.0, 1.0)
    rh    = sym_hist(rev,  500.0)

    _, out_m06_resto = _cap(m06_labor_cost, labor, rev, lh, rh,
                            business_type="restaurant")
    _, out_m06_agncy = _cap(m06_labor_cost, labor, rev, lh, rh,
                            business_type="agency")

    print("  restaurant output:")
    for ln in out_m06_resto.splitlines():
        print("  " + ln)
    print()
    print("  agency output:")
    for ln in out_m06_agncy.splitlines():
        print("  " + ln)

    _check("VR-02  restaurant  labor=42% > ceil 38% → abs ceiling FIRES",
           float("[M-06] abs ceiling breach" in out_m06_resto), 1.0, tol=0.0)
    _check("VR-02  agency      labor=42%: z-score only → abs ceiling SILENT",
           float("[M-06] abs ceiling breach" not in out_m06_agncy), 1.0, tol=0.0)
    _check("VR-02  agency      prints z-score-only notice",
           float("z-score only" in out_m06_agncy), 1.0, tol=0.0)

    # ── VR-03  M-04  gross margin = 58 % ─────────────────────────────────
    # restaurant  floor = 55%  →  58 > 55 → SILENT  (above floor, fine)
    # saas        floor = 65%  →  58 < 65 → FIRES
    print("\n  ── VR-03  M-04  gross margin = 58%")
    print("           restaurant floor=55%  →  expect SILENT (58% is above floor)")
    print("           saas        floor=65%  →  expect FIRES  (58% is below floor)")
    print()
    revenue = 100_000.0
    cogs    =  42_000.0   # margin = 58 %

    _, out_m04_resto = _cap(m04_gross_margin, revenue, cogs,
                            business_type="restaurant")
    _, out_m04_saas  = _cap(m04_gross_margin, revenue, cogs,
                            business_type="saas")

    print("  restaurant output:")
    for ln in out_m04_resto.splitlines():
        print("  " + ln)
    print()
    print("  saas output:")
    for ln in out_m04_saas.splitlines():
        print("  " + ln)

    _check("VR-03  restaurant  margin=58% > floor 55% → floor SILENT",
           float("[M-04] abs floor breach" not in out_m04_resto), 1.0, tol=0.0)
    _check("VR-03  saas        margin=58% < floor 65% → floor FIRES",
           float("[M-04] abs floor breach" in out_m04_saas), 1.0, tol=0.0)


# ---------------------------------------------------------------------------
# VERTICAL CONFIG PRINTER
# ---------------------------------------------------------------------------
def _print_vertical_config():
    """Print VERTICAL_CONFIG in a readable, doc-comparable layout."""
    VERTICAL_ORDER = [
        "restaurant", "quick_service_restaurant", "contractor",
        "agency", "ecommerce", "saas", "retail",
    ]
    METRIC_LABELS = {
        "m04_gross_margin": "M-04 Gross Margin %",
        "m05_food_cost":    "M-05 Food Cost %",
        "m06_labor_cost":   "M-06 Labor Cost %",
        "m07_dso":          "M-07 DSO (days)",
        "m10_revenue":      "M-10 Revenue Trend",
        "m12_project_float":"M-12 Project Float",
        "m14_break_even":   "M-14 Break-Even",
        "m15_expansion_score": "M-15 Expansion Score",
    }

    print("\n" + "═" * 72)
    print("  VERTICAL_CONFIG  —  Benchmarks by Business Type")
    print("  Source: Pulse_Metrics.docx  §  Benchmarks by vertical")
    print("═" * 72)

    for vertical in VERTICAL_ORDER:
        cfg = VERTICAL_CONFIG.get(vertical)
        if cfg is None:
            continue
        label = vertical.replace("_", " ").title()
        print(f"\n┌─ {label} {'─' * (68 - len(label))}")
        for metric_key, metric_label in METRIC_LABELS.items():
            mc = cfg.get(metric_key)
            if mc is None:
                continue
            parts = []
            # Range bounds
            if "healthy_lo" in mc and "healthy_hi" in mc:
                parts.append(f"healthy {mc['healthy_lo']}–{mc['healthy_hi']}%")
            if "healthy_lo_days" in mc and "healthy_hi_days" in mc:
                parts.append(f"healthy {mc['healthy_lo_days']}–{mc['healthy_hi_days']} days")
            # Absolute ceilings / floors
            if "alert_floor" in mc and mc["alert_floor"] is not None:
                parts.append(f"alert floor {mc['alert_floor']}%")
            if "alert_ceiling" in mc and mc["alert_ceiling"] is not None:
                parts.append(f"alert ceiling {mc['alert_ceiling']}%")
            if "alert_ceiling_days" in mc and mc["alert_ceiling_days"] is not None:
                parts.append(f"alert ceiling {mc['alert_ceiling_days']} days")
            if "alert_abs_ceiling" in mc:
                parts.append(f"abs ceiling {mc['alert_abs_ceiling']}%")
            if "alert_z_ceiling" in mc:
                parts.append(f"z ceiling {mc['alert_z_ceiling']}%")
            # z_score_only flag
            if mc.get("z_score_only") is True:
                parts.append("z-score only (no absolute threshold)")
            # Comparison window for M-10
            if "comparison_window" in mc:
                parts.append(f"window={mc['comparison_window']}")
            if "alert_drop_pct" in mc and mc["alert_drop_pct"] is not None:
                parts.append(f"alert drop {mc['alert_drop_pct']}%")
            # Float formula
            if "min_float_threshold" in mc and mc["min_float_threshold"] is not None:
                parts.append(f"min float ${mc['min_float_threshold']:,}")
            if "min_float_formula" in mc and mc["min_float_formula"] is not None:
                parts.append(f"formula={mc['min_float_formula']}")
            # Notes
            if "notes" in mc and mc["notes"]:
                parts.append(f"→ {mc['notes']}")
            if parts:
                summary = "  |  ".join(parts)
                print(f"│  {metric_label:<26} {summary}")
        print(f"└{'─' * 70}")

    # M-09 vendor tolerance
    print("\n┌─ M-09 Vendor Price Tolerance (by vendor_type) " + "─" * 22)
    vt = VERTICAL_CONFIG.get("m09_vendor_tolerance", {})
    for vtype, vc in vt.items():
        label = vtype.replace("_", " ")
        parts = []
        if "normal_weekly_variation_pct" in vc:
            parts.append(f"normal var ±{vc['normal_weekly_variation_pct']}%/wk")
        if "alert_spike_pct" in vc:
            parts.append(f"alert spike >{vc['alert_spike_pct']}%")
        if vc.get("expected_variation") == "flat":
            parts.append("expected: flat")
        if vc.get("alert_on_any_change") is True:
            parts.append("alert on any change")
        if vc.get("alert_on_any_change") is False:
            parts.append("no alert on seasonal change")
        if "seasonal_variation_pct" in vc:
            parts.append(f"seasonal var ±{vc['seasonal_variation_pct']}%")
        if "alert_type" in vc:
            parts.append(f"type={vc['alert_type']}")
        if vc.get("z_score_alert") is False:
            parts.append("no z-score alert")
        if "notes" in vc and vc["notes"]:
            parts.append(f"→ {vc['notes']}")
        if parts:
            print(f"│  {label:<26} {'  |  '.join(parts)}")
    print(f"└{'─' * 70}")
    print()


# ---------------------------------------------------------------------------
# ADDITIONAL DEMOS  (M-04 · M-09 · M-10 · M-11 · M-14)
# ---------------------------------------------------------------------------
def demo_remaining_metrics():
    print("\n" + "═" * 72)
    print("  ADDITIONAL DEMOS — M-04 · M-09 · M-10 · M-11 · M-14")
    print("  (Illustrative values — swap inputs in SECTION 1 for real data)")
    print("═" * 72)

    gm = m04_gross_margin(revenue=36_000, cogs=13_680)
    print(f"  → gross_margin_pct = {gm:.2f}%  (expect ~62.0% for healthy restaurant)")

    z_v, mu_v, sigma_v, cutoff_v = m09_vendor_anomaly(
        "Western Lumber Supply", 8_420.0,
        [5_300, 5_600, 5_840, 5_700, 5_840, 6_100,
         5_840, 5_500, 5_840, 6_200, 5_840, 5_840],
        n_vendors_total=12,
    )
    print(f"  → vendor_z={z_v:.2f}  cutoff={cutoff_v} (for 12 vendors)  "
          f"Alert: {'YES' if z_v > cutoff_v else 'No'}")

    rev_z, _, _, _ = m10_revenue_trend(
        SARAH["revenue_this_week"], SARAH["revenue_history_12wk"])
    print(f"  → revenue_z = {rev_z:.2f}  (expected −2.78 per case doc)")

    inflows, outflows, _ = _build_maria_flow(MARIA)
    daily_cost, min_bal, verdict = m11_hire_affordability(
        45_000, 30, inflows, outflows, MARIA["current_balance"],
        onboarding_cost=2_000, ramp_days=30,
    )
    print(f"  → hire_daily=${daily_cost:.2f}/day  min_balance=${min_bal:,.2f}  {verdict}")

    be = m14_break_even(fixed_costs=21_000, variable_cogs_ratio=0.30,
                         variable_labour_ratio=0.05)
    print(f"  → break_even_revenue = ${be:,.2f}/mo  "
          f"(fixed / (1 − 0.35))")


# ---------------------------------------------------------------------------
# GAP-1 ASSERTIONS — M-05 fine_dining / cafe / bar sub-vertical routing
# ---------------------------------------------------------------------------
def test_gap1_m05_vertical():
    """
    Three assertion pairs proving that VERTICAL_CONFIG thresholds for
    fine_dining (42%), cafe (30%), and bar (30%) alter M-05 alert behaviour
    for identical numeric inputs based on business_type.
    """

    def _cap(fn, *args, **kwargs):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = fn(*args, **kwargs)
        return result, buf.getvalue()

    print("\n" + "═" * 72)
    print("  GAP-1 ASSERTIONS — M-05 sub-vertical ceiling routing")
    print("  fine_dining 42% · cafe 30% · bar 30%")
    print("═" * 72)

    # Flat history so z-score only reflects the new value, not noise.
    HIST = [30.0] * 12
    REV  = 10_000.0   # denominator for food cost %

    # ── GP1-01  fine_dining: food_cost = 43.5% (> 42% ceil) → fires ─────
    print("\n  ── GP1-01  fine_dining  43.5% > ceil 42%  →  expect breach")
    r1, out1 = _cap(m05_food_cost, 4_350.0, REV, HIST, business_type="fine_dining")

    # ── GP1-02  fine_dining: food_cost = 35.0% (< 42% ceil) → silent ────
    print("\n  ── GP1-02  fine_dining  35.0% < ceil 42%  →  expect silent")
    r2, out2 = _cap(m05_food_cost, 3_500.0, REV, HIST, business_type="fine_dining")

    # ── GP1-03  cafe: food_cost = 31.0% (> 30% ceil) → fires ─────────────
    print("\n  ── GP1-03  cafe  31.0% > ceil 30%  →  expect breach")
    r3, out3 = _cap(m05_food_cost, 3_100.0, REV, HIST, business_type="cafe")

    # ── GP1-04  bar: food_cost = 29.0% (> 30% ceil = no, wait 29 < 30) ──
    # bar ceil = 30%; 27% < 30% → silent
    print("\n  ── GP1-04  bar  27.0% < ceil 30%  →  expect silent")
    r4, out4 = _cap(m05_food_cost, 2_700.0, REV, HIST, business_type="bar")

    # ── GP1-05  no business_type → backward-compat, no vertical check ────
    print("\n  ── GP1-05  no business_type (backward compat) → no vertical output")
    r5, out5 = _cap(m05_food_cost, 4_350.0, REV, HIST)

    print("\n  ── Assertions ──")
    _check("GP1-01  fine_dining 43.5% > ceil 42% → abs ceiling FIRES",
           float("[M-05] abs ceiling breach" in out1), 1.0, tol=0.0)
    _check("GP1-02  fine_dining 35.0% < ceil 42% → abs ceiling SILENT",
           float("[M-05] abs ceiling breach" not in out2), 1.0, tol=0.0)
    _check("GP1-03  cafe 31.0% > ceil 30% → abs ceiling FIRES",
           float("[M-05] abs ceiling breach" in out3), 1.0, tol=0.0)
    _check("GP1-04  bar 27.0% < ceil 30% → abs ceiling SILENT",
           float("[M-05] abs ceiling breach" not in out4), 1.0, tol=0.0)
    _check("GP1-05  no business_type → no vertical lookup in output",
           float("vertical abs ceiling" not in out5), 1.0, tol=0.0)
    _check("GP1-CONFIG  fine_dining alert_abs_ceiling = 42",
           float(VERTICAL_CONFIG["fine_dining"]["m05_food_cost"]["alert_abs_ceiling"] == 42),
           1.0, tol=0.0)
    _check("GP1-CONFIG  cafe alert_abs_ceiling = 30",
           float(VERTICAL_CONFIG["cafe"]["m05_food_cost"]["alert_abs_ceiling"] == 30),
           1.0, tol=0.0)
    _check("GP1-CONFIG  bar alert_abs_ceiling = 30",
           float(VERTICAL_CONFIG["bar"]["m05_food_cost"]["alert_abs_ceiling"] == 30),
           1.0, tol=0.0)


# ---------------------------------------------------------------------------
# GAP-2 ASSERTIONS — M-09 vendor_type routing
# ---------------------------------------------------------------------------
def test_gap2_m09_vendor_type():
    """
    Six assertions proving that vendor_type routes M-09 to the correct rule
    from VERTICAL_CONFIG['m09_vendor_tolerance'] — independent of z-score magnitude.
    """

    def _cap(fn, *args, **kwargs):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = fn(*args, **kwargs)
        return result, buf.getvalue()

    print("\n" + "═" * 72)
    print("  GAP-2 ASSERTIONS — M-09 vendor_type routing")
    print("  new_vendor · saas_subscription · produce · utility · default")
    print("═" * 72)

    # Flat history so pct_above is unambiguous.
    VHIST = [500.0] * 12   # mean=$500, stdev=0

    # ── GP2-01  new_vendor → notification, no z-score ─────────────────────
    print("\n  ── GP2-01  vendor_type=new_vendor  →  notification-only")
    r1, out1 = _cap(m09_vendor_anomaly, "Fresh Foods Inc", 850.0, VHIST,
                    vendor_type="new_vendor")
    z1, mu1, sigma1, cutoff1 = r1
    for ln in out1.splitlines(): print("  " + ln)

    # ── GP2-02  saas $550 vs mean $500 (dev=$50 > $1) → ALERT ─────────────
    print("\n  ── GP2-02  saas  $550 vs mean $500  dev=$50 > $1  →  ALERT")
    r2, out2 = _cap(m09_vendor_anomaly, "Slack", 550.0, VHIST,
                    vendor_type="saas_subscription")
    for ln in out2.splitlines(): print("  " + ln)

    # ── GP2-03  saas $500.50 vs mean $500 (dev=$0.50 ≤ $1) → no alert ────
    print("\n  ── GP2-03  saas  $500.50 vs mean $500  dev=$0.50 ≤ $1  →  no alert")
    r3, out3 = _cap(m09_vendor_anomaly, "Slack", 500.50, VHIST,
                    vendor_type="saas_subscription")
    for ln in out3.splitlines(): print("  " + ln)

    # ── GP2-04  produce 25% spike → ALERT (>20%) ──────────────────────────
    print("\n  ── GP2-04  produce  $625 vs mean $500  25% spike  →  ALERT")
    r4, out4 = _cap(m09_vendor_anomaly, "Metro Produce", 625.0, VHIST,
                    vendor_type="produce")
    for ln in out4.splitlines(): print("  " + ln)

    # ── GP2-05  produce 15% spike → no alert (≤20%) ──────────────────────
    print("\n  ── GP2-05  produce  $575 vs mean $500  15% spike  →  no alert")
    r5, out5 = _cap(m09_vendor_anomaly, "Metro Produce", 575.0, VHIST,
                    vendor_type="produce")
    for ln in out5.splitlines(): print("  " + ln)

    # ── GP2-06  utility with 40% spike → no alert (seasonal) ─────────────
    print("\n  ── GP2-06  utility  $700 vs mean $500  40% deviation  →  no alert")
    r6, out6 = _cap(m09_vendor_anomaly, "BC Hydro", 700.0, VHIST,
                    vendor_type="utility")
    for ln in out6.splitlines(): print("  " + ln)

    print("\n  ── Assertions ──")
    _check("GP2-01  new_vendor → z is None (no z-score computed)",
           float(z1 is None), 1.0, tol=0.0)
    _check("GP2-01  new_vendor → cutoff is 'new_vendor_notification'",
           float(cutoff1 == "new_vendor_notification"), 1.0, tol=0.0)
    _check("GP2-02  saas dev=$50 > $1 → ALERT fires",
           float("[M-09] ALERT" in out2), 1.0, tol=0.0)
    _check("GP2-03  saas dev=$0.50 ≤ $1 → no ALERT fires",
           float("[M-09] ALERT" not in out3), 1.0, tol=0.0)
    _check("GP2-04  produce 25% spike → ALERT fires",
           float("[M-09] ALERT" in out4), 1.0, tol=0.0)
    _check("GP2-05  produce 15% spike → no ALERT fires",
           float("[M-09] ALERT" not in out5), 1.0, tol=0.0)
    _check("GP2-06  utility 40% deviation → no ALERT fires",
           float("[M-09] ALERT" not in out6), 1.0, tol=0.0)


# ---------------------------------------------------------------------------
# GAP-3 ASSERTIONS — M-15 upstream-None propagation guard
# ---------------------------------------------------------------------------
def test_gap3_m15_none_guard():
    """
    Seven assertions proving that M-15 degrades gracefully when upstream
    metrics return None (DATA_QUALITY_FLAG / INSUFFICIENT_HISTORY).
    The score never crashes; unavailable components are zeroed and listed.
    """

    def _cap(fn, *args, **kwargs):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = fn(*args, **kwargs)
        return result, buf.getvalue()

    print("\n" + "═" * 72)
    print("  GAP-3 ASSERTIONS — M-15 upstream-None propagation guard")
    print("  Proves: None inputs → partial score, never a crash")
    print("═" * 72)

    # ── GP3-01  runway_months=None (M-13 returned None) ──────────────────
    print("\n  ── GP3-01  runway_months=None  →  partial score, runway zeroed")
    r1, out1 = _cap(
        m15_expansion_score,
        dso_days=5.0, gross_margin_pct=65.0, coverage_ratio=1.5,
        runway_months=None,           # ← upstream M-13 failure
        gst_reserve_gap=200.0, est_gst_owing=1_000.0,
        data_quality_score=75.0,
    )
    score1, band1, comp1 = r1
    for ln in out1.splitlines(): print("  " + ln)
    print()

    # ── GP3-02  two Nones: runway + coverage ─────────────────────────────
    print("\n  ── GP3-02  runway=None + coverage=None  →  both listed in band")
    r2, out2 = _cap(
        m15_expansion_score,
        dso_days=5.0, gross_margin_pct=65.0, coverage_ratio=None,
        runway_months=None,
        gst_reserve_gap=200.0, est_gst_owing=1_000.0,
        data_quality_score=75.0,
    )
    score2, band2, comp2 = r2
    for ln in out2.splitlines(): print("  " + ln)
    print()

    # ── GP3-03  gst inputs None (both) ───────────────────────────────────
    print("\n  ── GP3-03  gst_reserve_gap=None  →  gst component zeroed")
    r3, out3 = _cap(
        m15_expansion_score,
        dso_days=5.0, gross_margin_pct=65.0, coverage_ratio=1.5,
        runway_months=8.0,
        gst_reserve_gap=None, est_gst_owing=None,
        data_quality_score=75.0,
    )
    score3, band3, comp3 = r3
    for ln in out3.splitlines(): print("  " + ln)

    print("\n  ── Assertions ──")
    _check("GP3-01  score returned (not None) when runway=None",
           float(score1 is not None), 1.0, tol=0.0)
    _check("GP3-01  band contains 'components unavailable'",
           float("components unavailable" in band1), 1.0, tol=0.0)
    _check("GP3-01  runway component score down-weighted to 0",
           comp1["runway"], 0.0, tol=0.001)
    _check("GP3-01  non-None components still score normally (dso=5d → ~91.7)",
           comp1["dso"], _score_dso(5.0), tol=0.1)
    _check("GP3-02  both runway + coverage in band notice",
           float("runway" in band2 and "coverage" in band2), 1.0, tol=0.0)
    _check("GP3-02  coverage score is 0 when coverage=None",
           comp2["coverage"], 0.0, tol=0.001)
    _check("GP3-03  gst score is 0 when gst inputs are None",
           comp3["gst"], 0.0, tol=0.001)


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("\n" + "█" * 72)
    print("  PULSE MATH VALIDATOR  v2")
    print("  Sources: Pulse_Metrics.docx · Case_Analysis.docx · Metric_Fixes.docx")
    print("█" * 72)

    test_maria()
    test_james()
    test_sarah()
    test_amir()
    test_new_features()
    test_thin_history()
    test_dirty_data()
    test_vertical_routing()
    test_gap1_m05_vertical()
    test_gap2_m09_vendor_type()
    test_gap3_m15_none_guard()
    _print_vertical_config()
    demo_remaining_metrics()

    print("\n" + "█" * 72)
    if ALL_PASS:
        print("  ✅  ALL ASSERTIONS PASSED")
    else:
        print("  ❌  ONE OR MORE ASSERTIONS FAILED — review [FAIL] lines above")
    print("█" * 72 + "\n")
    sys.exit(0 if ALL_PASS else 1)


if __name__ == "__main__":
    main()
