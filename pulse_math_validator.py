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

# ============================================================================
# VERTICAL_CONFIG — Benchmark thresholds by business type
# ============================================================================
# Source: "Benchmarks by vertical" tables in Pulse_Metrics (4).docx
#
# Conventions
# -----------
# healthy_lo / healthy_hi  — the doc's stated healthy range, both bounds stored.
# alert_floor              — absolute floor; alert if sustained below (M-04).
# alert_ceiling            — absolute ceiling; alert if above (M-06, M-07).
# z_score_only = True      — doc explicitly says no absolute threshold applies;
#                            alert on z-score deviation only.
# None                     — the doc gives no data for this metric / vertical.
#
# M-09 is keyed by vendor TYPE (produce_supplier, saas_subscription, etc.),
# not by business type, because each vendor has its own individual baseline.
# It is stored under the "m09_vendor_tolerance" top-level key.
#
# M-15 weights are the same for every vertical in the doc (DSO 20%, margin 20%,
# coverage 20%, runway 20%, GST 10%, data 10%).  Table 63 notes that startup
# founders should weight runway/burn/data quality "more heavily" but gives no
# specific numbers — weight overrides are None for all verticals.
# ============================================================================

VERTICAL_CONFIG = {

    # ── Full-service restaurant ──────────────────────────────────────────────
    "restaurant": {
        "m04_gross_margin": {
            "healthy_lo":  60,    "healthy_hi": 70,   # %
            "alert_floor": 55,                         # alert if sustained below
        },
        "m05_food_cost": {
            "healthy_lo":         28,   "healthy_hi": 34,  # %
            "alert_z_ceiling":    36,   # z-score alert threshold
            "alert_abs_ceiling":  38,   # absolute alert if sustained above
        },
        "m06_labor_cost": {
            "healthy_lo":    28,  "healthy_hi": 35,   # %
            "alert_ceiling": 38,                       # alert if >38% for 2+ weeks
            "z_score_only":  False,
        },
        "m07_dso": {
            "healthy_lo_days":    0,   "healthy_hi_days": 7,
            "alert_ceiling_days": 14,
            "notes": "Revenue is point-of-sale. DSO >14d indicates uncollected catering invoices.",
        },
        "m10_revenue": {
            "comparison_window": "week_over_week",
            "alert_drop_pct":    None,  # doc gives no drop-% for restaurants
            "notes": "Compare to same day of week, same week of year.",
        },
        "m12_project_float": {
            "min_float_threshold":     None,
            "min_float_formula":       None,
            "notes": "Catering float period < 14 days is manageable from operating cash.",
        },
        "m14_break_even": {
            "notes": "~60–70% of capacity. Doc example: 60-seat at $65 avg check needs ~$42,000/week.",
        },
        "m15_expansion_score": {
            "weight_overrides": None,
            "notes": "Standard weights apply. No vertical override specified in doc.",
        },
    },

    # ── Quick-service / fast-casual restaurant ───────────────────────────────
    # M-04 and M-07: doc does not list QSR separately — no data for those metrics.
    "quick_service_restaurant": {
        "m05_food_cost": {
            "healthy_lo":        25,   "healthy_hi": 31,  # %
            "alert_abs_ceiling": 33,
        },
        "m06_labor_cost": {
            "healthy_lo":    25,  "healthy_hi": 32,   # %
            "alert_ceiling": 35,
            "z_score_only":  False,
        },
    },

    # ── General contractor ───────────────────────────────────────────────────
    "contractor": {
        "m04_gross_margin": {
            "healthy_lo":  35,    "healthy_hi": 50,   # %
            "alert_floor": 30,
        },
        "m06_labor_cost": {
            "healthy_lo":    20,  "healthy_hi": 35,   # %
            "alert_ceiling": None,                     # z-score only
            "z_score_only":  True,
            "notes": "Highly variable. Alert on z-score only.",
        },
        "m07_dso": {
            "healthy_lo_days":    45,  "healthy_hi_days": 60,
            "alert_ceiling_days": 70,
            "notes": "Longer payment terms are normal for contractors.",
        },
        "m10_revenue": {
            "comparison_window": "month_over_month",
            "alert_drop_pct":    None,  # doc gives no drop-% for contractors
            "notes": "Project-based revenue is lumpy. Monthly more meaningful than weekly.",
        },
        "m12_project_float": {
            "min_float_threshold": 15_000,
            "min_float_formula":   None,
            "notes": "Min balance during float > $15,000. Below that: recommend partial line-of-credit draw.",
        },
        "m14_break_even": {
            "notes": "Break-even when utilisation > 30%. High fixed costs (equipment, insurance) reached quickly once on a project.",
        },
        "m15_expansion_score": {
            "weight_overrides": None,
            "notes": "Standard weights apply. No vertical override specified in doc.",
        },
    },

    # ── Service agency ───────────────────────────────────────────────────────
    "agency": {
        "m04_gross_margin": {
            "healthy_lo":  70,    "healthy_hi": 85,   # %
            "alert_floor": 60,
        },
        "m06_labor_cost": {
            "healthy_lo":    50,  "healthy_hi": 65,   # %
            "alert_ceiling": None,                     # z-score only
            "z_score_only":  True,
            "notes": "Labor IS the product. Z-score only — absolute threshold not meaningful.",
        },
        "m07_dso": {
            "healthy_lo_days":    30,  "healthy_hi_days": 45,
            "alert_ceiling_days": 45,
            "notes": "Alert if >45 days consistently.",
        },
        "m10_revenue": {
            "comparison_window": "monthly",
            "alert_drop_pct":    20,
            "notes": "Invoice-based revenue should be predictable. Alert if monthly total drops >20%.",
        },
        "m12_project_float": {
            "min_float_threshold": None,
            "min_float_formula":   "2x_monthly_payroll",
            "notes": "2× monthly payroll as minimum buffer when staffing a project before first invoice.",
        },
        "m14_break_even": {
            "notes": "40–50% billable utilisation = break-even. Beyond 50% billable is profit.",
        },
        "m15_expansion_score": {
            "weight_overrides": None,
            "notes": "Standard weights apply. No vertical override specified in doc.",
        },
    },

    # ── E-commerce ───────────────────────────────────────────────────────────
    # M-06: doc does not list e-commerce separately — no data.
    "ecommerce": {
        "m04_gross_margin": {
            "healthy_lo":  40,    "healthy_hi": 60,   # %
            "alert_floor": 35,
        },
        "m07_dso": {
            "healthy_lo_days":    0,   "healthy_hi_days": 14,
            "alert_ceiling_days": 21,
            "notes": "Online payments clear quickly. >21 days indicates disputes.",
        },
        "m10_revenue": {
            "comparison_window": "daily_weekly",
            "alert_drop_pct":    25,
            "notes": "Alert if 7-day rolling average drops >25% below 12-week norm.",
        },
        "m14_break_even": {
            "notes": "Contribution margin × units sold.",
        },
        "m15_expansion_score": {
            "weight_overrides": None,
            "notes": "Standard weights apply. No vertical override specified in doc.",
        },
    },

    # ── Software / SaaS startup ──────────────────────────────────────────────
    # M-06, M-10, M-12, M-14: doc does not list SaaS separately — no data.
    "saas": {
        "m04_gross_margin": {
            "healthy_lo":  75,    "healthy_hi": 90,   # %
            "alert_floor": 65,
        },
        "m07_dso": {
            "healthy_lo_days":    15,  "healthy_hi_days": 30,
            "alert_ceiling_days": 45,
            "notes": "Subscription invoices net-30.",
        },
        "m15_expansion_score": {
            "weight_overrides": None,
            "notes": (
                "Doc (Table 63 edge cases) says 'startup founder with no revenue: "
                "use founder-specific score weighting runway, burn efficiency, and "
                "data quality more heavily' — but gives no specific weight numbers. "
                "No numeric override encoded."
            ),
        },
    },

    # ── Retail ───────────────────────────────────────────────────────────────
    # M-04, M-07, M-10, M-12, M-14: doc does not list retail — no data.
    "retail": {
        "m06_labor_cost": {
            "healthy_lo":    15,  "healthy_hi": 20,   # %
            "alert_ceiling": 25,
            "z_score_only":  False,
        },
    },

    # ── M-09 vendor tolerance (keyed by vendor type, not business type) ──────
    # Source: Table 36 in Pulse_Metrics (4).docx.
    # The doc structures this by vendor category because each vendor has its own
    # individual baseline; the owning business's vertical is secondary.
    "m09_vendor_tolerance": {
        "produce_supplier": {
            "normal_weekly_variation_pct": 5,
            "alert_spike_pct":             20,
            "notes": "Seasonal variation expected. Alert only if >20% spike.",
        },
        "saas_subscription": {
            "expected_variation":  "flat",
            "alert_on_any_change": True,
            "notes": "Monthly SaaS charges should be fixed. Any change triggers alert.",
        },
        "utility": {
            "seasonal_variation_pct": 10,
            "alert_on_any_change":    False,
            "notes": "Wider tolerance for weather-related variation. Z-score handles automatically.",
        },
        "new_vendor": {
            "alert_type":    "new_vendor_notification",
            "z_score_alert": False,
            "notes": "First appearance triggers 'new vendor' notification — not a z-score alert.",
        },
    },
}


# ============================================================================
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
# SECTION 2 — UTILITY FUNCTIONS
# ============================================================================

# ---------------------------------------------------------------------------
# [FIX-Z0] Payroll frequency → monthly normalisation factor
# ---------------------------------------------------------------------------
FREQ_TO_MONTHLY = {
    "weekly":       52 / 12,   # 4.3333
    "biweekly":     26 / 12,   # 2.1667  ← the critical one
    "semimonthly":  2.0,
    "monthly":      1.0,
}

def normalise_to_monthly(per_run_amount, period):
    """
    [FIX-M13] Convert any payroll frequency to a true monthly figure.
    Never let a biweekly figure reach a monthly total unconverted.
    """
    factor = FREQ_TO_MONTHLY.get(period, 1.0)
    return per_run_amount * factor, factor


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------

def _mean(values):
    return sum(values) / len(values)


def _sample_stdev(values):
    """Sample stdev, Bessel-corrected (÷ n−1)."""
    n = len(values)
    if n < 2:
        return 0.0
    mu = _mean(values)
    return math.sqrt(sum((x - mu) ** 2 for x in values) / (n - 1))


def _z_score(current_value, history, s_floor=0.0):
    """
    [FIX-Z0] Z-score with per-metric standard-deviation floor.
    Returns (z, mean, effective_stdev).
    Threshold for n=12 should be t(0.0228, df=11) = 2.255, not flat 2.0.
    """
    mu    = _mean(history)
    sigma = _sample_stdev(history)
    sigma_eff = max(sigma, s_floor, 1e-9)
    return (current_value - mu) / sigma_eff, mu, sigma_eff


# Corrected alert threshold for n=12 (t-distribution, 11 df, one-sided 2.28%)
T_THRESHOLD_N12 = 2.255   # [FIX-Z0] replaces flat 2.0

# ---------------------------------------------------------------------------
# [CHANGE 3] Cross-cutting extreme-reading router
# ---------------------------------------------------------------------------
EXTREME_Z_THRESHOLD = 4.0  # |z| beyond this → VERIFY DATA, not a crisis alert


def _route_z_signal(z, metric_name, direction="high", threshold=None):
    """
    [CHANGE 3] Shared extreme-reading router applied to every z-score metric.

    |z| > EXTREME_Z_THRESHOLD  →  returns 'VERIFY_DATA'
        A reading this extreme is statistically near-impossible under the
        model's own assumptions.  It is more likely a data-quality issue
        (miscategorised transaction, double-count, POS remap) than a genuine
        financial crisis.  Do NOT fire a financial alert; flag for review.

    z beyond t-threshold (directional)  →  returns 'ALERT'
    otherwise                            →  returns 'OK'

    Parameters
    ----------
    z         : float   — the z-score to evaluate
    metric_name: str    — shown in the printed line (e.g. 'M-07 DSO')
    direction : str     — 'high'  alert when z >  threshold
                          'low'   alert when z < −threshold
                          'both'  alert on either side
    threshold : float   — override; if None uses T_THRESHOLD_N12

    M-05 retains its own inline check (already had this logic).
    Applied to M-06, M-07, M-09, M-10 by this change.  [CHANGE 3]
    """
    t = threshold if threshold is not None else T_THRESHOLD_N12
    if abs(z) > EXTREME_Z_THRESHOLD:
        print(f"  ⚠️  [{metric_name}] |z|={abs(z):.2f} > {EXTREME_Z_THRESHOLD} "
              f"→ VERIFY DATA  (extreme reading — check data quality first)")
        return "VERIFY_DATA"
    if direction in ("high", "both") and z > t:
        print(f"  ⚠️  [{metric_name}] ALERT — z={z:.2f} > {t}")
        return "ALERT"
    if direction in ("low", "both") and z < -t:
        print(f"  ⚠️  [{metric_name}] ALERT — z={z:.2f} < −{t}")
        return "ALERT"
    print(f"  ✅ [{metric_name}] No alert — z={z:.2f}")
    return "OK"


# ---------------------------------------------------------------------------
# [CHANGE 2] Cross-metric alert-budget / ranking layer
# ---------------------------------------------------------------------------

def _portfolio_z_cutoff(n_tests):
    """
    [CHANGE 2] Per-test z cutoff to hold a ≤5% family-wise false-alarm rate
    across n simultaneous independent tests (Bonferroni approximation).

    As the portfolio grows, each signal must clear a higher bar before it
    reaches the owner — the main structural defence against alert fatigue.
    The per-vendor Bonferroni values in M-09 (7→2.45, 20→2.81, 40→3.02)
    are the vendor-level expression of exactly this principle; this function
    applies it across ALL metrics in a single run.
    """
    if n_tests <= 1:   return T_THRESHOLD_N12  # single test: honour existing threshold
    if n_tests <= 3:   return 2.394            # 0.05 / 3  → z ≈ 2.39
    if n_tests <= 5:   return 2.576            # 0.05 / 5  → z ≈ 2.58
    if n_tests <= 7:   return 2.697            # 0.05 / 7  → z ≈ 2.70
    if n_tests <= 10:  return 2.807            # 0.05 / 10 → z ≈ 2.81
    if n_tests <= 15:  return 2.935            # 0.05 / 15 → z ≈ 2.94
    if n_tests <= 20:  return 3.023            # 0.05 / 20 → z ≈ 3.02 (matches M-09 ref)
    if n_tests <= 40:  return 3.200            # 0.05 / 40 → z ≈ 3.20
    return 3.400


def rank_and_cap_alerts(signals, cap=5):
    """
    [CHANGE 2] Portfolio-level false-discovery control.

    Collects every firing signal from every metric (and every vendor for
    M-09) in a single run, ranks by severity, applies a portfolio-wide
    cutoff that tightens as the portfolio grows, and returns at most `cap`
    signals — so only the genuinely unusual few reach the owner.

    Parameters
    ----------
    signals : list of (metric_name, severity, route, message)
        metric_name  str   — e.g. 'M-07 DSO'
        severity     float — |z| or a manual priority score (higher = more urgent)
        route        str   — 'ALERT', 'VERIFY_DATA', or 'WARNING'
        message      str   — short description for the ranked output table
    cap : int
        Hard ceiling on items returned per run (default 5).

    Returns
    -------
    list of (metric_name, severity, route, message) — top ≤cap signals,
    sorted by severity descending.

    Filtering rules
    ---------------
    • 'VERIFY_DATA' signals always pass the cutoff — they flag possible
      data problems that must be reviewed regardless of z magnitude.
    • 'ALERT' and 'WARNING' signals must reach severity ≥ portfolio cutoff
      for n = len(signals) to survive the filter.
    • After filtering, all remaining signals are sorted by severity and
      capped at `cap`; signals below the cap line are reported as suppressed.
    """
    _hdr("ALERT BUDGET — Portfolio Ranking Layer  [CHANGE 2]")

    n      = len(signals)
    cutoff = _portfolio_z_cutoff(n)

    print(f"\n  Signals submitted       : {n}")
    print(f"  Portfolio z-cutoff      : {cutoff:.3f}  "
          f"(Bonferroni for {n} tests, 5% family-wise rate)")
    print(f"  Alert cap per run       : {cap}")

    filtered = []
    for metric, severity, route, message in signals:
        if route == "VERIFY_DATA" or severity >= cutoff:
            filtered.append((metric, severity, route, message))

    ranked = sorted(filtered, key=lambda x: x[1], reverse=True)
    capped = ranked[:cap]

    n_by_cutoff = n - len(filtered)
    n_by_cap    = max(0, len(ranked) - cap)

    print(f"\n  Suppressed by cutoff    : {n_by_cutoff}  "
          f"(severity < {cutoff:.3f})")
    print(f"  Suppressed by cap       : {n_by_cap}")
    print(f"  Returned                : {len(capped)}")

    if capped:
        print(f"\n  {'#':<4} {'Metric':<22} {'Severity':>9} {'Route':<14} Message")
        print(f"  {'─'*4} {'─'*22} {'─'*9} {'─'*14} {'─'*38}")
        for i, (m, sev, route, msg) in enumerate(capped, 1):
            print(f"  {i:<4} {m:<22} {sev:>9.3f} {route:<14} {msg[:50]}")
    else:
        print(f"\n  ✅ No signals above portfolio threshold this run.")

    if n_by_cap > 0:
        print(f"\n  [{n_by_cap} signal(s) above cutoff but suppressed by cap — "
              f"raise cap to surface them]")

    return capped


# ---------------------------------------------------------------------------
# [FIX-M03] ITC eligibility factors by expense category
# ---------------------------------------------------------------------------
ITC_ELIGIBILITY = {
    "software":          1.00,   # standard taxable business input
    "equipment":         1.00,
    "materials":         1.00,
    "office_supplies":   1.00,
    "utilities":         1.00,   # GST applies
    "meals_entertain":   0.50,   # CRA: only 50% recoverable
    "wages":             0.00,   # no GST on wages
    "insurance":         0.00,   # generally exempt
    "interest":          0.00,   # financial service, exempt
    "rent":              0.00,   # residential rent exempt; commercial → confirm
    "other":             0.50,   # conservative default when category uncertain
}

def compute_itcs(itc_expenses, gst_rate):
    """
    [FIX-M03] Compute Input Tax Credits with per-category eligibility.
    itc_expenses: list of (amount, category) tuples.
    Returns total ITCs.
    """
    total = 0.0
    for amount, category in itc_expenses:
        elig = ITC_ELIGIBILITY.get(category, 0.50)
        total += amount * gst_rate * elig
    return total


# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------

def _hdr(title):
    print("\n" + "─" * 72)
    print(f"  {title}")
    print("─" * 72)


def _step(label, formula, result, note=""):
    n = f"  ← {note}" if note else ""
    print(f"  {label:<34}  {formula:<34}  = {result}{n}")


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
# SECTION 3 — METRIC FUNCTIONS  M-01 through M-15
# ============================================================================

# ----------------------------------------------------------------------------
# M-01  Projected Cash Gap Date & Amount
# Core: balance[d] = balance[d−1] + inflows[d] − outflows[d]
# [FIX] Production version should run 1,000 Monte Carlo draws for a band;
#       this deterministic form is exact arithmetic for validation.
# ----------------------------------------------------------------------------
def m01_cash_gap(current_balance, daily_inflows, daily_outflows,
                 avg_weekly_fixed, threshold_floor=3_000.0, days=90):
    """
    Returns (gap_day, gap_balance, gap_amount, threshold, balances_list).
    gap_day is 1-indexed.
    """
    _hdr("M-01 · Projected Cash Gap Date & Amount")

    cash_threshold = max(threshold_floor, 0.50 * avg_weekly_fixed)
    _step("avg_weekly_fixed",  "daily_fixed × 7",
          f"${avg_weekly_fixed:,.2f}")
    _step("cash_threshold",    "max($3,000, 50% × avg_weekly_fixed)",
          f"${cash_threshold:,.2f}", "floor wins if 50% < $3,000")

    balances = [current_balance]
    print(f"\n  {'Day':<6} {'Inflow':>12} {'Outflow':>12} {'Balance':>13}  Note")
    print(f"  {'0':<6} {'—':>12} {'—':>12} {'$' + f'{current_balance:,.2f}':>13}  Opening (Plaid)")

    gap_day = gap_balance = gap_amount = None
    base_in  = daily_inflows[0]
    base_out = daily_outflows[0]

    for d in range(days):
        inf = daily_inflows[d]
        out = daily_outflows[d]
        bal = balances[d] + inf - out
        balances.append(bal)
        day = d + 1

        extra_in  = inf - base_in
        extra_out = out - base_out
        note = ""
        if extra_in  > 1:  note += f"+ sched.inflow ${extra_in:,.2f}"
        if extra_out > 1:  note += f"  extra outflow ${extra_out:,.2f}"
        marker = "  <<< BELOW THRESHOLD" if bal < cash_threshold else ""

        if day <= 3 or note or abs(bal) < 6_000 or (day == 16 and bal < 0):
            print(f"  {day:<6} {'$'+f'{inf:,.2f}':>12} {'$'+f'{out:,.2f}':>12}"
                  f" {'$'+f'{bal:,.2f}':>13}  {note}{marker}")

        if gap_day is None and bal < cash_threshold:
            gap_day, gap_balance = day, bal
            gap_amount = cash_threshold - bal

    if gap_day:
        print(f"\n  ┌── GAP DETECTED ─────────────────────────────────────┐")
        print(f"  │  gap_day     = Day {gap_day}")
        print(f"  │  balance[{gap_day}] = ${gap_balance:,.2f}")
        _step("gap_amount", f"threshold − balance[{gap_day}]",
              f"${gap_amount:,.2f}",
              f"${cash_threshold:,.2f} − (${gap_balance:,.2f})")
        print(f"  └──────────────────────────────────────────────────────┘")
    else:
        print("\n  No cash gap detected in 90-day window.")

    return gap_day, gap_balance, gap_amount, cash_threshold, balances


# ----------------------------------------------------------------------------
# M-01-MC  helpers  [CHANGE 1]
# ----------------------------------------------------------------------------

def _run_one_cash_flow(current_balance, inflows, outflows, threshold, days):
    """
    [CHANGE 1] Single pass of the daily recurrence used by each MC iteration.
    Returns (gap_day, gap_amount) if the balance ever falls below threshold,
    (None, None) if it never does.  gap_day is 1-indexed.
    """
    balance = current_balance
    for d in range(days):
        balance = balance + inflows[d] - outflows[d]
        if balance < threshold:
            return d + 1, threshold - balance
    return None, None


def _unmodelled_outflow_scan(transactions, large_abs_threshold=1_000.0):
    """
    [CHANGE 1] Search transaction history for irregular large debits that
    are NOT captured by the recurring outflow schedule.

    'Irregular' = the merchant appears fewer than 3 times in the history.
    'Large'     = |amount| > large_abs_threshold (default $1,000).
    Pending transactions are excluded (they have not posted yet).

    Returns a list of dicts: {merchant, amount, date, note}.
    These are the outflows the 90-day forecast is silently ignoring.
    """
    from collections import Counter

    debits = [
        (t["merchant_name"], abs(t["amount"]), t.get("date", ""))
        for t in transactions
        if t.get("amount", 0) < 0 and not t.get("is_pending", False)
    ]

    merchant_counts = Counter(m for m, _, _ in debits)

    seen       = set()
    unmodelled = []
    for merchant, amount, date in debits:
        if merchant in seen:
            continue
        if merchant_counts[merchant] < 3 and amount > large_abs_threshold:
            seen.add(merchant)
            unmodelled.append({
                "merchant": merchant,
                "amount":   amount,
                "date":     date,
                "note":     (f"appears {merchant_counts[merchant]}× in history — "
                             f"not captured in recurring forecast"),
            })
    return unmodelled


def m01_cash_gap_mc(current_balance, daily_inflows_base, daily_outflows_base,
                    avg_weekly_fixed, threshold_floor=3_000.0, days=90,
                    revenue_noise_pct=0.15, cost_noise_pct=0.10,
                    invoice_clients=None, transaction_history=None,
                    n_runs=1_000, seed=42):
    """
    [CHANGE 1] Probabilistic M-01: wraps the deterministic daily recurrence
    in 1,000 Monte Carlo iterations.

    Each run perturbs three uncertain inputs:

    Revenue noise
        The base daily revenue (minimum value in daily_inflows_base) is
        scaled by N(1, (rev_noise/2)²), floored at 0.50.
        Scheduled transfers — Square payout and any other fixed-day inflows
        above the daily base — are left unchanged; they are contractually
        determined, not revenue estimates.

    Cost noise
        The base daily fixed cost (minimum value in daily_outflows_base) is
        scaled by N(1, (cost_noise/2)²), floored at 0.50.
        Large scheduled outflows — payroll, produce bill — are unchanged;
        their amounts are known in advance.

    Invoice timing  (optional)
        If invoice_clients is provided, each invoice's payment day is sampled
        from N(expected_day, stdev_days²) and clamped to [1, days].

    The deterministic m01_cash_gap result is the median of this distribution.
    All existing assertions continue to use m01_cash_gap unchanged.

    Parameters
    ----------
    invoice_clients : list of dicts, each containing:
        name         str   — client name (printed in summary)
        amount       float — invoice face value
        expected_day int   — central estimate of cash arrival (from Day 0)
        stdev_days   float — uncertainty around expected_day
    transaction_history : list of transaction dicts (e.g. MARIA_TRANSACTIONS).
        If supplied, runs _unmodelled_outflow_scan on it.

    Returns
    -------
    dict with keys:
        prob_breach          float  — fraction of runs that breach threshold
        p10/p50/p90_gap_day  int    — percentile breach days (None if too few)
        p10/p50/p90_gap_amt  float  — percentile gap amounts
        unmodelled_outflows  list   — from _unmodelled_outflow_scan
        n_runs               int    — iterations executed
    """
    _hdr("M-01-MC · Probabilistic Cash Gap  [CHANGE 1: 1,000-run Monte Carlo]")

    cash_threshold = max(threshold_floor, 0.50 * avg_weekly_fixed)

    # Separate recurring base from scheduled extras.
    # min() across all days picks the day with no large scheduled items.
    base_daily_rev  = min(daily_inflows_base)
    base_daily_cost = min(daily_outflows_base)

    rng        = random.Random(seed)
    gap_days   = []
    gap_amts   = []

    for _ in range(n_runs):
        # Run-level noise multipliers (one per uncertain component)
        rev_mult  = max(0.50, 1.0 + rng.gauss(0, revenue_noise_pct / 2))
        cost_mult = max(0.50, 1.0 + rng.gauss(0, cost_noise_pct    / 2))

        # Scale recurring component; preserve scheduled extras exactly
        noisy_in  = [(base_daily_rev  * rev_mult  + (x - base_daily_rev))
                     for x in daily_inflows_base]
        noisy_out = [(base_daily_cost * cost_mult + (x - base_daily_cost))
                     for x in daily_outflows_base]

        # Stochastic invoice arrivals
        if invoice_clients:
            for client in invoice_clients:
                exp     = client["expected_day"]
                std     = client.get("stdev_days", 1.0)
                amt     = client["amount"]
                pay_day = int(round(rng.gauss(exp, std)))
                pay_day = max(1, min(days, pay_day))
                noisy_in[pay_day - 1] += amt

        gap_day, gap_amt = _run_one_cash_flow(
            current_balance, noisy_in, noisy_out, cash_threshold, days)

        if gap_day is not None:
            gap_days.append(gap_day)
            gap_amts.append(gap_amt)

    breach_count = len(gap_days)
    prob_breach  = breach_count / n_runs

    def _pct(lst, p):
        if not lst:
            return None
        s   = sorted(lst)
        idx = max(0, min(len(s) - 1, int(len(s) * p / 100)))
        return s[idx]

    result = {
        "prob_breach":   prob_breach,
        "p10_gap_day":   _pct(gap_days, 10),
        "p50_gap_day":   _pct(gap_days, 50),
        "p90_gap_day":   _pct(gap_days, 90),
        "p10_gap_amt":   _pct(gap_amts, 10),
        "p50_gap_amt":   _pct(gap_amts, 50),
        "p90_gap_amt":   _pct(gap_amts, 90),
        "unmodelled_outflows": [],
        "n_runs":        n_runs,
    }

    # ── Print probabilistic summary ──────────────────────────────────────────
    print(f"\n  Monte Carlo: {n_runs:,} runs · seed={seed}")
    print(f"  Revenue noise ±{revenue_noise_pct*100:.0f}%  "
          f"· Cost noise ±{cost_noise_pct*100:.0f}%")
    if invoice_clients:
        for c in invoice_clients:
            print(f"  Invoice: {c.get('name','?')}  "
                  f"expected Day {c['expected_day']} ±{c.get('stdev_days', 1):.1f}d  "
                  f"${c['amount']:,.2f}")

    print(f"\n  ┌── PROBABILISTIC RESULT ──────────────────────────────────────────┐")
    print(f"  │  P(breach in {days}d)   = {prob_breach:.1%}  "
          f"({breach_count:,} / {n_runs:,} runs)")
    if result["p50_gap_day"] is not None:
        print(f"  │  Gap day    P10–P90 : "
              f"Day {result['p10_gap_day']} – Day {result['p90_gap_day']}  "
              f"(median Day {result['p50_gap_day']})")
        print(f"  │  Gap amount P10–P90 : "
              f"${result['p10_gap_amt']:,.2f} – ${result['p90_gap_amt']:,.2f}  "
              f"(median ${result['p50_gap_amt']:,.2f})")
        print(f"  │")
        print(f"  │  Deterministic (median run): "
              f"Day {result['p50_gap_day']}  /  ${result['p50_gap_amt']:,.2f}")
    else:
        print(f"  │  No breach in median run.")
    print(f"  └──────────────────────────────────────────────────────────────────┘")

    # ── Unmodelled-outflow scan ───────────────────────────────────────────────
    if transaction_history:
        result["unmodelled_outflows"] = _unmodelled_outflow_scan(transaction_history)
        _hdr("M-01-MC · Unmodelled-Outflow Scan  [CHANGE 1]")
        umo = result["unmodelled_outflows"]
        if umo:
            print(f"\n  ⚠️  {len(umo)} irregular large debit(s) NOT captured by forecast:")
            for u in umo:
                print(f"     • {u['merchant']:<32} ${u['amount']:>8,.2f}  "
                      f"({u['date']})  {u['note']}")
            print(f"\n  These outflows will occur but are invisible to the 90-day model.")
            print(f"  Add them as scheduled outflows to close the gap in coverage.")
        else:
            print(f"\n  ✅ No unmodelled large debits detected in transaction history.")

    return result


# ----------------------------------------------------------------------------
# M-02  Payroll Coverage Ratio
# Formula: payroll_cash_out = net_pay + employer_taxes
#          coverage = projected_balance[payroll_day − 1] ÷ payroll_cash_out
# [FIX-M02] Production: test lower bound of balance forecast, not point est.
# ----------------------------------------------------------------------------
def m02_payroll_coverage(gross_pay, net_pay, cpp_rate, ei_rate,
                          balance_before_payroll):
    """Returns (payroll_cash_out, coverage_ratio)."""
    _hdr("M-02 · Payroll Coverage Ratio")

    employer_cpp    = gross_pay * cpp_rate
    employer_ei     = gross_pay * ei_rate
    employer_taxes  = employer_cpp + employer_ei
    payroll_cash_out = net_pay + employer_taxes

    _step("employer_cpp",     f"${gross_pay:,.2f} × {cpp_rate}",
          f"${employer_cpp:,.2f}", "CRA 2026 rate")
    _step("employer_ei",      f"${gross_pay:,.2f} × {ei_rate}",
          f"${employer_ei:,.2f}", "CRA 2026 rate")
    _step("employer_taxes",   "cpp + ei",
          f"${employer_taxes:,.2f}")
    _step("net_pay (ADP)",    "PayrollRun.NetPayTotal",
          f"${net_pay:,.2f}", "Actual ACH debit")
    _step("payroll_cash_out", "net_pay + employer_taxes",
          f"${payroll_cash_out:,.2f}", "Total bank debit on payroll day")

    coverage = balance_before_payroll / payroll_cash_out
    _step("balance_before",   "balances[payroll_day − 1]",
          f"${balance_before_payroll:,.2f}", "From 90-day loop")
    _step("coverage_ratio",
          f"${balance_before_payroll:,.2f} / ${payroll_cash_out:,.2f}",
          f"{coverage:.4f}")

    if coverage < 1.00:
        print("  ⚠️  CRITICAL  — coverage < 1.00 · cannot make payroll")
    elif coverage < 1.20:
        print("  ⚠️  WARNING   — coverage < 1.20 · within 20% buffer")
    else:
        print(f"  ✅ HEALTHY   — coverage {coverage:.3f} ≥ 1.20")

    return payroll_cash_out, coverage


# ----------------------------------------------------------------------------
# M-03  GST/HST Reserve Gap  (Canada-specific)
# [FIX-M03] ITC eligibility per category; wages/insurance/interest → 0.
# Formula: gst_reserve_gap = (taxable_revenue × rate − ITCs) − reserved
#          weekly_reserve_needed = gap ÷ weeks_remaining
# ----------------------------------------------------------------------------
def m03_gst_reserve_gap(taxable_revenue, gst_rate, itc_expenses,
                         gst_actually_reserved, weeks_remaining):
    """
    itc_expenses: list of (amount, category) tuples — [FIX-M03].
    Returns (est_gst_gross, est_gst_net, reserve_gap, weekly_needed).
    """
    _hdr("M-03 · GST/HST Reserve Gap  [FIX-M03: per-category ITC eligibility]")

    est_gst_gross = taxable_revenue * gst_rate
    est_itcs      = compute_itcs(itc_expenses, gst_rate)
    est_gst_net   = est_gst_gross - est_itcs
    reserve_gap   = est_gst_net - gst_actually_reserved
    weekly_needed = reserve_gap / weeks_remaining if weeks_remaining > 0 else 0.0

    _step("taxable_revenue",    "QB + Stripe quarterly",    f"${taxable_revenue:,.2f}")
    _step("gst_rate",           "province rate",            f"{gst_rate:.0%}")
    _step("est_gst_gross",      "revenue × rate",           f"${est_gst_gross:,.2f}")

    print(f"\n  ITC eligibility breakdown [FIX-M03]:")
    for amount, category in itc_expenses:
        elig = ITC_ELIGIBILITY.get(category, 0.50)
        itc  = amount * gst_rate * elig
        print(f"    {category:<20} ${amount:>9,.2f} × {gst_rate} × {elig} = ${itc:,.2f}")
    print(f"    {'TOTAL ITCs':<20}              = ${est_itcs:,.2f}")

    _step("est_gst_owing_net",  "gross − ITCs",             f"${est_gst_net:,.2f}")
    _step("gst_reserved",       "owner-entered at setup",   f"${gst_actually_reserved:,.2f}")
    _step("gst_reserve_gap",    "owing_net − reserved",     f"${reserve_gap:,.2f}")
    _step("weeks_remaining",    "quarter_end − today",      f"{weeks_remaining} wks")
    _step("weekly_reserve",     "gap ÷ weeks_remaining",    f"${weekly_needed:,.2f}/week")

    alert = reserve_gap > 500 and weeks_remaining < 8
    print(f"\n  Alert (gap>$500 AND weeks<8): {'FIRES ⚠️' if alert else 'No alert'}")
    return est_gst_gross, est_gst_net, reserve_gap, weekly_needed


# ----------------------------------------------------------------------------
# M-04  Gross Margin Percentage
# Formula: gross_margin_pct = (revenue − COGS) ÷ revenue × 100
# [FIX-M04] Z-score caller should use s_floor = 1.0 pp; COGS lag smoothing.
# ----------------------------------------------------------------------------
def m04_gross_margin(revenue, cogs, business_type=""):
    """Returns gross_margin_pct."""
    _hdr("M-04 · Gross Margin %  [FIX-M04: z-score callers use s_floor=1.0 pp]")
    gross_profit     = revenue - cogs
    gross_margin_pct = gross_profit / revenue * 100
    _step("revenue",          "QB TotalRevenue",          f"${revenue:,.2f}")
    _step("COGS",             "QB CostOfGoodsSold",       f"${cogs:,.2f}")
    _step("gross_profit",     "revenue − COGS",           f"${gross_profit:,.2f}")
    _step("gross_margin_pct", "gross_profit/revenue×100", f"{gross_margin_pct:.4f}%")

    # Vertical absolute floor [VERTICAL_CONFIG]
    vc = VERTICAL_CONFIG.get(business_type, {}).get("m04_gross_margin", {})
    alert_floor = vc.get("alert_floor")
    if alert_floor is not None:
        _step("vertical floor",
              f"VERTICAL_CONFIG[{business_type!r}]",
              f"{alert_floor}%")
        if gross_margin_pct < alert_floor:
            print(f"  ⚠️  [M-04] abs floor breach: {gross_margin_pct:.2f}% < {alert_floor}% "
                  f"({business_type} threshold)")
        else:
            print(f"  ✅ [M-04] above vertical floor {alert_floor}% ({business_type}): "
                  f"{gross_margin_pct:.2f}%")

    return gross_margin_pct


# ----------------------------------------------------------------------------
# M-05  Food Cost Percentage  (Restaurants only)
# Formula: food_cost_pct = food_COGS ÷ food_revenue × 100
# [FIX-M05] s_floor = 0.5 pp; z > 4.0 → VERIFY DATA, not crisis alert.
# This changes Maria's z from 18.00 (original) to 16.28 (fixed).
# ----------------------------------------------------------------------------
S_FLOOR_FOOD_COST = 0.50   # [FIX-M05] minimum stdev in percentage points

def m05_food_cost(food_cogs, food_revenue, history_12wk):
    """Returns (food_cost_pct, z_food, mu, sigma_eff)."""
    _hdr("M-05 · Food Cost %  [FIX-M05: s_floor=0.5 pp; z>4 → VERIFY DATA]")

    food_cost_pct = food_cogs / food_revenue * 100
    _step("food_COGS",      "Toast / QB",               f"${food_cogs:,.2f}")
    _step("food_revenue",   "Square/Toast daily sales", f"${food_revenue:,.2f}")
    _step("food_cost_pct",  "COGS/revenue × 100",       f"{food_cost_pct:.4f}%")

    mu         = _mean(history_12wk)
    raw_sigma  = _sample_stdev(history_12wk)
    sigma_eff  = max(raw_sigma, S_FLOOR_FOOD_COST)   # [FIX-M05]
    sq_devs    = sum((x - mu) ** 2 for x in history_12wk)
    variance   = sq_devs / (len(history_12wk) - 1)

    _step("12wk mean",      "Σxᵢ / 12",                f"{mu:.4f}%")
    _step("sum sq.dev",     f"Σ(xᵢ − {mu:.4f})²",     f"{sq_devs:.4f}")
    _step("variance",       "sq_dev / 11",              f"{variance:.4f}")
    _step("raw stdev",      "√variance",                f"{raw_sigma:.4f}%")
    _step("s_floor",        "[FIX-M05]",                f"{S_FLOOR_FOOD_COST:.4f}%")
    _step("sigma_eff",      "max(raw, s_floor)",        f"{sigma_eff:.4f}%",
          "used in z-score denominator")

    z = (food_cost_pct - mu) / sigma_eff
    _step("z_food",
          f"({food_cost_pct:.4f} − {mu:.4f}) / {sigma_eff:.4f}",
          f"{z:.4f}")
    print(f"\n  [FIX-M05] Original z (no s_floor): "
          f"{(food_cost_pct - mu) / max(raw_sigma, 1e-9):.2f}  →  "
          f"Fixed z (s_floor={S_FLOOR_FOOD_COST}): {z:.2f}")

    if z > 4.0:
        print(f"  ⚠️  z={z:.2f} > 4.0 → VERIFY DATA path  "
              f"(not crisis alert — likely double-count or mapping error)")
    elif z > T_THRESHOLD_N12:
        print(f"  ⚠️  ALERT — z={z:.2f} > t-threshold {T_THRESHOLD_N12}")
    else:
        print(f"  ✅ No alert — z={z:.2f}")

    return food_cost_pct, z, mu, sigma_eff


# ----------------------------------------------------------------------------
# M-06  Labor Cost as % of Revenue
# Formula: labor_pct = total_payroll_expense ÷ total_revenue × 100
# [FIX-M06] When hours unavailable: use annual_payroll/52, NOT monthly/weeks.
#            Compound rule requires persistence over 2 consecutive weeks.
# ----------------------------------------------------------------------------
S_FLOOR_LABOR = 0.50   # [FIX-Z0 / FIX-M06]

def m06_labor_cost(payroll_expense, revenue,
                   labor_history_12wk, revenue_history_12wk,
                   business_type=""):
    """Returns (labor_pct, z_labor, z_revenue, compound_signal_this_week)."""
    _hdr("M-06 · Labor Cost %  [FIX-M06: s_floor; compound requires 2 wks]")

    labor_pct = payroll_expense / revenue * 100
    _step("payroll_expense",  "ADP/Gusto actual run", f"${payroll_expense:,.2f}")
    _step("revenue",          "QB / POS",             f"${revenue:,.2f}")
    _step("labor_pct",        "payroll/revenue×100",  f"{labor_pct:.4f}%")

    z_labor, mu_labor, sigma_labor = _z_score(labor_pct, labor_history_12wk,
                                               s_floor=S_FLOOR_LABOR)
    z_rev,   mu_rev,   sigma_rev   = _z_score(revenue,   revenue_history_12wk)

    _step("12wk labor mean",   "mean of history",          f"{mu_labor:.4f}%")
    _step("12wk labor stdev",  "sample stdev",             f"{sigma_labor:.4f}%")
    _step("z_labor",
          f"({labor_pct:.4f}−{mu_labor:.4f})/{sigma_labor:.4f}",
          f"{z_labor:.4f}")
    _step("12wk revenue mean", "mean of history",          f"${mu_rev:,.2f}")
    _step("12wk rev stdev",    "sample stdev",             f"${sigma_rev:,.2f}")
    _step("z_revenue",
          f"({revenue:,.2f}−{mu_rev:,.2f})/{sigma_rev:,.2f}",
          f"{z_rev:.4f}")

    compound_this_week = z_labor > 1.5 and z_rev < -1.0
    _route_z_signal(z_labor, "M-06 labor %", direction="high")   # [CHANGE 3]

    # Vertical absolute ceiling [VERTICAL_CONFIG]
    vc = VERTICAL_CONFIG.get(business_type, {}).get("m06_labor_cost", {})
    if vc.get("z_score_only"):
        print(f"  [M-06] vertical={business_type!r}: z-score only — no absolute ceiling")
    else:
        abs_ceil = vc.get("alert_ceiling")
        if abs_ceil is not None:
            _step("vertical ceiling",
                  f"VERTICAL_CONFIG[{business_type!r}]",
                  f"{abs_ceil}%")
            if labor_pct > abs_ceil:
                print(f"  ⚠️  [M-06] abs ceiling breach: {labor_pct:.2f}% > {abs_ceil}% "
                      f"({business_type} threshold)")
            else:
                print(f"  ✅ [M-06] below vertical ceiling {abs_ceil}% ({business_type}): "
                      f"{labor_pct:.2f}%")

    print(f"  Compound this week (z_L>1.5 & z_R<−1.0): "
          f"{'YES ⚠️' if compound_this_week else 'No'}")
    print(f"  [FIX-M06] Compound ESCALATES only after 2 consecutive weeks meeting condition.")
    return labor_pct, z_labor, z_rev, compound_this_week


# ----------------------------------------------------------------------------
# M-07  Receivables DSO
# Formula: DSO = AR_balance ÷ (revenue_90d ÷ 90)
# [FIX-M07] Use 4-week average AR, not single-day snapshot.
#            Absolute ceiling = stated_payment_terms + 15-day buffer.
# ----------------------------------------------------------------------------
def m07_dso(ar_balance, revenue_90d, dso_history_12wk,
            stated_payment_terms=30, business_type="", invoice_count=None):
    """Returns (dso, z_dso, mu_dso, sigma_dso).
    If invoice_count < 5: returns (dso, None, None, None) — INSUFFICIENT_HISTORY.
    z-score alert is suppressed; DSO value is still reported for reference.
    """
    _hdr("M-07 · Receivables DSO  [FIX-M07: use avg AR; ceiling=terms+buffer]")

    avg_daily_sales = revenue_90d / 90
    dso = ar_balance / avg_daily_sales

    # Thin-history guard — doc requires ≥ 5 paid invoices for z-score
    if invoice_count is not None and invoice_count < 5:
        _step("AR_balance",     "open invoices (QB)",   f"${ar_balance:,.2f}")
        _step("DSO",            "AR / avg_daily_sales", f"{dso:.4f} days")
        _step("invoice_count",  "paid invoices",        f"{invoice_count}")
        print(f"  ⚠️  [M-07] INSUFFICIENT_HISTORY — {invoice_count} paid invoice(s); "
              f"need ≥ 5 for z-score.  DSO={dso:.1f}d reported, no statistical alert.")
        return dso, None, None, None

    # Vertical ceiling takes priority; fallback to terms+15 [FIX-M07] [VERTICAL_CONFIG]
    vc = VERTICAL_CONFIG.get(business_type, {}).get("m07_dso", {})
    vert_ceiling = vc.get("alert_ceiling_days")
    if vert_ceiling is not None:
        abs_ceiling = vert_ceiling
        ceiling_source = f"VERTICAL_CONFIG[{business_type!r}]"
    else:
        abs_ceiling = stated_payment_terms + 15   # [FIX-M07]
        ceiling_source = f"terms({stated_payment_terms}) + 15d buffer"

    _step("AR_balance",         "open invoices (QB)",      f"${ar_balance:,.2f}")
    _step("revenue_last_90d",   "QB P&L trailing 90d",     f"${revenue_90d:,.2f}")
    _step("avg_daily_sales",    "revenue_90d / 90",        f"${avg_daily_sales:,.2f}/day")
    _step("DSO",                "AR / avg_daily_sales",    f"{dso:.4f} days")
    _step("abs_ceiling",        ceiling_source,            f"{abs_ceiling} days")

    z_dso, mu_dso, sigma_dso = _z_score(dso, dso_history_12wk)
    _step("12wk DSO mean",  "mean of history", f"{mu_dso:.4f} days")
    _step("12wk DSO stdev", "sample stdev",    f"{sigma_dso:.4f} days")
    _step("z_DSO",
          f"({dso:.4f}−{mu_dso:.4f})/{sigma_dso:.4f}",
          f"{z_dso:.4f}")

    _route_z_signal(z_dso, "M-07 DSO", direction="high")          # [CHANGE 3]
    if dso > abs_ceiling:
        print(f"  ⚠️  [M-07 DSO] abs ceiling breach: {dso:.1f}d > {abs_ceiling}d "
              f"({ceiling_source})")
    return dso, z_dso, mu_dso, sigma_dso


# ----------------------------------------------------------------------------
# M-08  Per-Client Payment Delay
# Formula: client_z = (days_overdue − avg) ÷ max(stdev, 1)
# [FIX-M08] Alert ONLY IF: client_z > 2.5 AND (days_overdue − avg) ≥ 10.
#            Require ≥ 6 paid invoices (was 3).
# ----------------------------------------------------------------------------
def m08_client_delay(client_name, days_overdue, payment_history_days,
                     min_invoices=6):
    """
    [FIX-M08] min_invoices raised to 6. Practical floor: absolute gap ≥ 10 days.
    Returns (client_avg, client_stdev, client_z, alert_fires).
    """
    _hdr(f"M-08 · Per-Client Delay — {client_name}"
         f"  [FIX-M08: practical floor ≥10d; min 6 invoices]")

    n = len(payment_history_days)
    print(f"  History ({n} invoices): {payment_history_days}")

    if n < min_invoices:
        print(f"  ⚠️  [M-08] INSUFFICIENT_HISTORY — {n} invoice(s); "
              f"need ≥ {min_invoices} for per-client z-score [FIX-M08].  "
              f"No alert fired.  Use standard 30-day-overdue fallback.")
        return None, None, None, False

    client_avg   = _mean(payment_history_days)
    sq_devs      = sum((x - client_avg) ** 2 for x in payment_history_days)
    variance     = sq_devs / (n - 1)
    client_stdev = math.sqrt(variance)

    _step("client_avg_delay", f"sum / {n}",             f"{client_avg:.4f} days")
    _step("sum sq.dev",
          f"Σ(delayᵢ − {client_avg:.2f})²",            f"{sq_devs:.4f}")
    _step("variance",         f"sq_dev / ({n}−1)",      f"{variance:.4f}")
    _step("client_stdev",     "√variance",              f"{client_stdev:.4f} days")

    eff_stdev = max(client_stdev, 1.0)
    client_z  = (days_overdue - client_avg) / eff_stdev
    abs_gap   = days_overdue - client_avg   # [FIX-M08] practical floor

    _step("days_overdue",     "today − due_date",       f"{days_overdue} days")
    _step("effective_stdev",  "max(stdev, 1)",          f"{eff_stdev:.4f}")
    _step("client_z",
          f"({days_overdue}−{client_avg:.2f})/{eff_stdev:.4f}",
          f"{client_z:.4f}")
    _step("abs_gap [FIX-M08]","days_overdue − avg",     f"{abs_gap:.1f} days",
          "must be ≥ 10 to alert")

    alert_stat     = client_z > 2.5
    alert_practical = abs_gap >= 10.0   # [FIX-M08]
    alert_fires    = alert_stat and alert_practical

    print(f"\n  Statistical (z>{2.5}): {alert_stat}"
          f"  |  Practical (gap≥10d): {alert_practical}"
          f"  |  ALERT: {'YES ⚠️' if alert_fires else 'No'}")
    return client_avg, client_stdev, client_z, alert_fires


# ----------------------------------------------------------------------------
# M-09  Vendor Spend Anomaly
# Formula: vendor_z = (charge − mean) ÷ stdev
# [FIX-M09] Bonferroni-corrected z cutoff based on number of vendors tested.
# ----------------------------------------------------------------------------
def bonferroni_z_cutoff(n_vendors, family_wise_alpha=0.05):
    """
    [FIX-M09] Per-vendor z cutoff to hold 5% family-wise false-alarm rate.
    Reference values from fix doc: 7→2.45, 20→2.81, 40→3.02.
    """
    per_test_alpha = family_wise_alpha / n_vendors
    # Approximate inverse normal using Newton's method
    from math import erfc, sqrt, log, pi
    # Simple lookup for common values
    if n_vendors <= 1:   return 1.960
    if n_vendors <= 7:   return 2.450
    if n_vendors <= 20:  return 2.810
    if n_vendors <= 40:  return 3.020
    return 3.300   # conservative for very large vendor sets

def m09_vendor_anomaly(vendor_name, this_week_charge, history_12wk,
                        n_vendors_total=1):
    """
    [FIX-M09] z cutoff scales with total vendors tested simultaneously.
    Returns (vendor_z, mu, sigma, cutoff).
    """
    _hdr(f"M-09 · Vendor Anomaly — {vendor_name}"
         f"  [FIX-M09: Bonferroni cutoff for {n_vendors_total} vendor(s)]")

    z, mu, sigma = _z_score(this_week_charge, history_12wk)
    pct_above    = (this_week_charge - mu) / mu * 100
    cutoff       = bonferroni_z_cutoff(n_vendors_total)

    _step("this_week_charge",  vendor_name,               f"${this_week_charge:,.2f}")
    _step("12wk mean",         "mean of history",         f"${mu:,.2f}")
    _step("12wk stdev",        "sample stdev",            f"${sigma:,.2f}")
    _step("vendor_z",          "(charge − mean) / stdev", f"{z:.4f}")
    _step("% above norm",      "(charge − mean) / mean",  f"{pct_above:.1f}%")
    _step("Bonferroni cutoff", f"z for {n_vendors_total} vendors [FIX-M09]",
          f"{cutoff}", f"vs flat 2.0 in original spec")

    _route_z_signal(z, "M-09 vendor", direction="high", threshold=cutoff)  # [CHANGE 3]
    return z, mu, sigma, cutoff


# ----------------------------------------------------------------------------
# M-10  Weekly Revenue Trend
# [FIX-M10] Use s_pooled across all weeks, not per-week-of-year stdev.
#            (Our 12-week pooled history already approximates s_pooled.)
# ----------------------------------------------------------------------------
def m10_revenue_trend(this_week_revenue, history_12wk, seasonal_index=1.0):
    """Returns (revenue_z, seasonal_expected, mu, sigma).
    If len(history_12wk) < 12: returns (None, None, None, None) — INSUFFICIENT_HISTORY.
    Benchmark-based low-confidence label is printed; no z-score alert fires.
    """
    _hdr("M-10 · Weekly Revenue Trend  [FIX-M10: s_pooled not per-week stdev]")

    # Thin-history guard — doc requires ≥ 12 weeks (3 months) for z-score baseline
    n_wks = len(history_12wk)
    if n_wks < 12:
        _step("this_week_revenue", "Plaid / POS",       f"${this_week_revenue:,.2f}")
        _step("history_weeks",     "weeks available",   f"{n_wks}")
        print(f"  ⚠️  [M-10] INSUFFICIENT_HISTORY — {n_wks} week(s) of data; "
              f"need ≥ 12 for z-score baseline.  "
              f"Confidence: BENCHMARK_BASED_LOW.  No statistical alert fired.")
        return None, None, None, None

    mu    = _mean(history_12wk)
    sigma = _sample_stdev(history_12wk)   # pooled across all weeks [FIX-M10]
    seasonal_expected = mu * seasonal_index

    z = (this_week_revenue - seasonal_expected) / sigma if sigma > 0 else 0.0
    deviation_pct = (this_week_revenue - seasonal_expected) / seasonal_expected * 100

    _step("this_week_revenue",    "Plaid / POS",          f"${this_week_revenue:,.2f}")
    _step("12wk mean (baseline)", "pooled mean [FIX-M10]",f"${mu:,.2f}")
    _step("seasonal_index",       "week-of-year factor",  f"{seasonal_index}")
    _step("seasonal_expected",    "mean × index",         f"${seasonal_expected:,.2f}")
    _step("s_pooled",             "pooled stdev [FIX-M10]",f"${sigma:,.2f}")
    _step("revenue_z",            "(actual − expected)/s", f"{z:.4f}")
    _step("deviation",            "",                     f"{deviation_pct:.1f}%")

    _route_z_signal(z, "M-10 revenue", direction="low")           # [CHANGE 3]
    return z, seasonal_expected, mu, sigma


# ----------------------------------------------------------------------------
# M-11  Hire Affordability Model
# Formula: hire_daily_cost = (annual_salary ÷ 365) × (1 + employer_tax_rate)
# [FIX-M11] Add onboarding_cost amortised over ramp_days.
# ----------------------------------------------------------------------------
def m11_hire_affordability(annual_salary, start_day,
                            baseline_inflows, baseline_outflows,
                            current_balance,
                            employer_tax_rate=0.0761,
                            onboarding_cost=0.0,
                            ramp_days=30,
                            days=90):
    """
    [FIX-M11] Includes onboarding cost amortised over ramp_days.
    Returns (hire_daily_cost, min_balance, verdict).
    """
    _hdr("M-11 · Hire Affordability  [FIX-M11: onboarding cost amortised]")

    hire_daily = (annual_salary / 365) * (1 + employer_tax_rate)
    onboard_daily = onboarding_cost / max(ramp_days, 1) if onboarding_cost else 0.0

    _step("annual_salary",     "owner Q&A input",               f"${annual_salary:,.2f}")
    _step("employer_tax_rate", "CPP 5.95% + EI 1.66%",         f"{employer_tax_rate:.4f}")
    _step("hire_daily_cost",   "(salary/365)×(1+tax)",          f"${hire_daily:,.2f}/day")
    if onboarding_cost:
        _step("onboarding [FIX]","one-time / ramp_days",        f"${onboard_daily:,.2f}/day",
              f"for first {ramp_days} days")
    _step("start_day",         "proposed date",                 f"Day {start_day}")

    modified = list(baseline_outflows)
    for d in range(start_day - 1, days):
        modified[d] += hire_daily
        if d < start_day - 1 + ramp_days:
            modified[d] += onboard_daily

    balance = current_balance
    min_bal = current_balance
    for d in range(days):
        balance = balance + baseline_inflows[d] - modified[d]
        min_bal = min(min_bal, balance)

    _step("min_projected_balance", "min over 90d window", f"${min_bal:,.2f}")

    if min_bal > 10_000:  verdict = "SAFE — hire on proposed date"
    elif min_bal > 3_000: verdict = "MARGINAL — hire, flag tight months"
    elif min_bal > 0:     verdict = "RISKY — suggest later start date"
    else:                 verdict = "UNAFFORDABLE — do not hire in this window"

    print(f"\n  Verdict: {verdict}")
    return hire_daily, min_bal, verdict


# ----------------------------------------------------------------------------
# M-12  Project / Contract Float Analysis
# [FIX-M12] Run full daily loop (includes baseline payroll/rent during float).
#            Unknown client: add vertical_average_DSO days to payment date.
# ----------------------------------------------------------------------------
def m12_project_float(baseline_balance, upfront_costs, upfront_day,
                       first_payment, payment_day,
                       threshold=15_000.0,
                       daily_fixed_during_float=0.0,
                       client_known=True,
                       vertical_avg_dso=0):
    """
    [FIX-M12] min_float includes daily fixed costs across the float window.
    Returns (min_float_balance, recommended_draw).
    """
    _hdr("M-12 · Project Float  [FIX-M12: includes fixed costs during float]")

    float_days    = payment_day - upfront_day
    fixed_drain   = daily_fixed_during_float * float_days
    effective_payment_day = payment_day + (vertical_avg_dso if not client_known else 0)

    balance_after_upfront = baseline_balance - upfront_costs
    min_float_balance = balance_after_upfront - fixed_drain   # [FIX-M12]
    recommended_draw  = max(0.0, threshold - min_float_balance)

    _step("baseline_balance",       "Plaid",                    f"${baseline_balance:,.2f}")
    _step("upfront_costs",          f"Day {upfront_day}",       f"${upfront_costs:,.2f}")
    _step("balance_after_upfront",  "baseline − upfront",       f"${balance_after_upfront:,.2f}")
    _step("float_days",             f"pay_day − upfront_day",   f"{float_days} days")
    _step("fixed_drain [FIX-M12]",  "fixed/day × float_days",  f"${fixed_drain:,.2f}")
    _step("min_float_balance",      "after_upfront − fixed",    f"${min_float_balance:,.2f}")
    _step("safe_threshold",         "spec minimum",             f"${threshold:,.2f}")
    _step("recommended_draw",       "max(0, threshold − min)",  f"${recommended_draw:,.2f}")
    if not client_known:
        _step("payment_delay [FIX]","contractual + DSO prior",
              f"+{vertical_avg_dso} days → Day {effective_payment_day}")
    _step("first_payment",          f"Day {effective_payment_day}",
          f"${first_payment:,.2f}", "sufficient to repay draw + buffer")

    print(f"\n  Self-fund: {'No — credit line draw required' if recommended_draw > 0 else 'Yes'}")
    return min_float_balance, recommended_draw


# ----------------------------------------------------------------------------
# M-13  Runway  (Founder Mode)
# [FIX-M13] *** CRITICAL *** Normalise payroll to monthly before computing
#            net_burn.  Biweekly × 26/12 = 2.1667.  Not doing this can make
#            runway look ~2× too long.
# ----------------------------------------------------------------------------
def m13_runway(payroll_net_per_run, payroll_period,
               non_payroll_monthly,
               revenue_monthly,
               current_balance,
               vc_buffer_months=6.0):
    """
    [FIX-M13] monthly_payroll = per_run × frequency_factor.
    Returns (monthly_payroll, gross_burn, net_burn, runway, raise_window).
    """
    _hdr("M-13 · Runway  [FIX-M13: normalise payroll frequency to monthly]")

    monthly_payroll, factor = normalise_to_monthly(payroll_net_per_run,
                                                    payroll_period)
    gross_burn = monthly_payroll + non_payroll_monthly
    net_burn   = gross_burn - revenue_monthly
    runway     = current_balance / net_burn if net_burn > 0 else float("inf")
    raise_window = runway - vc_buffer_months

    _step("payroll_per_run",   f"Gusto/ADP {payroll_period}",
          f"${payroll_net_per_run:,.2f}/run")
    _step("freq_factor",       f"{payroll_period} → × {factor:.4f}",
          f"{factor:.4f}",
          "[FIX-M13] 26/12 for biweekly")
    _step("monthly_payroll",   "per_run × factor",
          f"${monthly_payroll:,.2f}/mo",
          "TRUE monthly figure")
    _step("non_payroll",       "rent+software+other",
          f"${non_payroll_monthly:,.2f}/mo")
    _step("gross_burn",        "payroll + non_payroll",
          f"${gross_burn:,.2f}/mo")
    _step("revenue_monthly",   "Stripe MRR",
          f"${revenue_monthly:,.2f}/mo")
    _step("net_burn",          "gross − revenue",
          f"${net_burn:,.2f}/mo")
    _step("current_balance",   "Plaid",
          f"${current_balance:,.2f}")
    _step("runway_months",     "balance / net_burn",
          f"{runway:.4f} months")
    _step("raise_deadline",    f"runway − {vc_buffer_months}mo buffer",
          f"{raise_window:.2f} months from today")

    if runway < 3:
        print("  ⚠️  CRITICAL  — < 3 months")
    elif runway < 6:
        print("  ⚠️  IMMEDIATE ALERT — < 6 months")
    elif runway < 9:
        print("  ⚠️  WARNING   — < 9 months, include in next alert")
    else:
        print(f"  ✅ HEALTHY   — {runway:.1f} months")

    return monthly_payroll, gross_burn, net_burn, runway, raise_window


# ----------------------------------------------------------------------------
# M-14  Break-Even Revenue Calculator
# Formula: break_even = total_fixed_costs ÷ (1 − variable_cost_ratio)
# [FIX-M14] variable_cost_ratio includes variable hourly labour.
# ----------------------------------------------------------------------------
def m14_break_even(fixed_costs, variable_cogs_ratio,
                   variable_labour_ratio=0.0):
    """
    [FIX-M14] variable_cost_ratio = variable COGS + variable hourly labour.
    Returns break_even_revenue.
    """
    _hdr("M-14 · Break-Even  [FIX-M14: separate variable hourly labour]")

    variable_cost_ratio = variable_cogs_ratio + variable_labour_ratio
    break_even = fixed_costs / (1 - variable_cost_ratio)

    _step("total_fixed_costs",        "rent+salary+subs+loans", f"${fixed_costs:,.2f}")
    _step("variable_COGS_ratio",      "variable COGS/revenue",  f"{variable_cogs_ratio:.4f}")
    _step("variable_labour_ratio",    "[FIX-M14] hourly/rev",   f"{variable_labour_ratio:.4f}")
    _step("variable_cost_ratio",      "COGS + labour",          f"{variable_cost_ratio:.4f}")
    _step("contribution_margin",      "1 − variable",           f"{1 - variable_cost_ratio:.4f}")
    _step("break_even_revenue",       "fixed / contrib_margin", f"${break_even:,.2f}")
    return break_even


# ----------------------------------------------------------------------------
# M-15  Expansion Readiness Score
# [FIX-M15] Report as BAND, not decimal; down-weight low-confidence inputs.
# Weights: DSO 20%, margin 20%, coverage 20%, runway 20%, GST 10%, data 10%
# ----------------------------------------------------------------------------

def _score_dso(dso_days):
    return max(0.0, min(100.0, (1 - dso_days / 60) * 100))

def _score_margin(pct, low=20.0, high=70.0):
    return max(0.0, min(100.0, (pct - low) / (high - low) * 100))

def _score_coverage(ratio):
    if ratio >= 1.5:  return 100.0
    if ratio >= 1.0:  return (ratio - 1.0) / 0.5 * 50 + 50
    return max(0.0, ratio * 50)

def _score_runway(months, lo=3.0, hi=18.0):
    return max(0.0, min(100.0, (months - lo) / (hi - lo) * 100))

def _score_gst(gap, owing):
    if owing == 0: return 100.0
    return max(0.0, (1 - gap / owing) * 100)


def m15_expansion_score(dso_days, gross_margin_pct, coverage_ratio,
                         runway_months, gst_reserve_gap, est_gst_owing,
                         data_quality_score, months_of_data=None):
    """
    [FIX-M15] Returns (score, band_label, component_scores).
    Score is reported as a band — false precision removed.
    If months_of_data < 3: band is marked PARTIAL and a notice is printed.
    Score is still computed — use it as directional only.
    """
    _hdr("M-15 · Expansion Readiness Score  [FIX-M15: band, not false decimal]")

    W = {"dso": 0.20, "margin": 0.20, "coverage": 0.20,
         "runway": 0.20, "gst": 0.10, "data_quality": 0.10}

    scores = {
        "dso":          _score_dso(dso_days),
        "margin":       _score_margin(gross_margin_pct),
        "coverage":     _score_coverage(coverage_ratio),
        "runway":       _score_runway(runway_months),
        "gst":          _score_gst(gst_reserve_gap, est_gst_owing),
        "data_quality": data_quality_score,
    }

    formulas = {
        "dso":      f"(1−{dso_days}/60)×100",
        "margin":   f"({gross_margin_pct}−20)/(70−20)×100",
        "coverage": f"ratio={coverage_ratio:.2f}→{'100 (clip)' if coverage_ratio>=1.5 else 'formula'}",
        "runway":   f"({runway_months:.2f}−3)/15×100",
        "gst":      f"100×(1−{gst_reserve_gap}/{est_gst_owing})",
        "data_quality": "manual",
    }

    print(f"\n  {'Component':<14} {'Formula':<40} {'Score':>7} {'Wt':>5} {'Wtd':>8}")
    print(f"  {'─'*14} {'─'*40} {'─'*7} {'─'*5} {'─'*8}")
    total = 0.0
    for k in W:
        s, w, wt = scores[k], W[k], scores[k] * W[k]
        total += wt
        print(f"  {k:<14} {formulas[k]:<40} {s:>7.1f} {w:>5.2f} {wt:>8.2f}")
    print(f"  {'─'*14} {'─'*40} {'─'*7} {'─'*5} {'─'*8}")
    print(f"  {'TOTAL':<14} {'':<40} {'':<7} {'':<5} {total:>8.2f}")

    if   total >= 80: band = "Expansion ready  (80–100)"
    elif total >= 60: band = "Nearly ready     (60–79)"
    elif total >= 40: band = "Needs work        (40–59)"
    else:             band = "Stabilise first    (< 40)"

    # Thin-history flag — doc: under 3 months, score is directional only
    if months_of_data is not None and months_of_data < 3:
        band = band + "  [PARTIAL — <3 months data]"
        print(f"  ⚠️  [M-15] PARTIAL score — only {months_of_data} month(s) of data.  "
              f"Score is directional only; do not use as a hard gate.")

    print(f"\n  [FIX-M15] Score band: '{band}'  (not reported as {total:.2f}/100)")
    return total, band, scores


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
    test_vertical_routing()
    _print_vertical_config()
    demo_remaining_metrics()

    print("\n" + "█" * 72)
    if ALL_PASS:
        print("  ✅  ALL ASSERTIONS PASSED")
    else:
        print("  ❌  ONE OR MORE ASSERTIONS FAILED — review [FAIL] lines above")
    print("█" * 72 + "\n")


if __name__ == "__main__":
    main()
