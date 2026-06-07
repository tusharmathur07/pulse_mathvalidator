"""
pulse_metrics.py — Production metric functions for Pulse.

Extracted from pulse_math_validator.py so mutation testing targets only
production arithmetic, not the test-assertion scaffolding.

Imported by:
  pulse_math_validator.py  (self-test harness)
  test_properties.py       (Hypothesis property tests)
"""

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

    # ── Fine-dining restaurant ───────────────────────────────────────────────
    # Source: Pulse_Metrics.docx sub-vertical food-cost breakdowns.
    # Higher food quality lifts healthy range vs. standard restaurant (28–34%).
    "fine_dining": {
        "m05_food_cost": {
            "healthy_lo":        30,   "healthy_hi": 38,  # %
            "alert_abs_ceiling": 42,   # alert if sustained above 42%
        },
    },

    # ── Café ─────────────────────────────────────────────────────────────────
    # Lower food cost range than full-service — beverages drive margin.
    "cafe": {
        "m05_food_cost": {
            "healthy_lo":        25,   "healthy_hi": 35,  # %
            "alert_abs_ceiling": 30,
        },
    },

    # ── Bar ──────────────────────────────────────────────────────────────────
    # Lowest food cost range — alcohol/beverage margin dominates.
    "bar": {
        "m05_food_cost": {
            "healthy_lo":        18,   "healthy_hi": 26,  # %
            "alert_abs_ceiling": 30,
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
    # ── GAP-4: dirty-data guard — None element or undersized input lists ────
    if (any(v is None for v in daily_inflows) or
            any(v is None for v in daily_outflows) or
            len(daily_inflows) < days or
            len(daily_outflows) < days):
        return None, None, None, None, None

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
    # ── GAP-6: zero payroll guard ──────────────────────────────────────────
    # Coverage is undefined when there's no payroll to cover (skipped pay
    # period, zero-employee period).
    if net_pay == 0:
        return None, None

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
    """Returns gross_margin_pct, or None if a DATA_QUALITY_FLAG is raised.
    Guards (checked before any division):
      revenue ≤ 0          → DATA_QUALITY_FLAG
      cogs == 0            → DATA_QUALITY_FLAG (0% COGS / 100% margin implied)
      cogs ≥ revenue       → DATA_QUALITY_FLAG (≥ 100% COGS)
      cogs / revenue < 5%  → DATA_QUALITY_FLAG (confirm categorisation)
    """
    _hdr("M-04 · Gross Margin %  [FIX-M04: z-score callers use s_floor=1.0 pp]")
    _step("revenue", "QB TotalRevenue",    f"${revenue:,.2f}")
    _step("COGS",    "QB CostOfGoodsSold", f"${cogs:,.2f}")

    # ── Data-quality guards ────────────────────────────────────────────────
    if revenue <= 0:
        print(f"  🚫 [M-04] DATA_QUALITY_FLAG — revenue={revenue:,.2f} is zero/negative.  "
              f"Cannot compute margin.  Check pipeline source.")
        return None
    if cogs == 0:
        print(f"  🚫 [M-04] DATA_QUALITY_FLAG — COGS=0 implies 100% gross margin.  "
              f"Verify expense categorisation is complete before alerting.")
        return None
    cogs_pct = cogs / revenue
    if cogs_pct >= 1.0:
        print(f"  🚫 [M-04] DATA_QUALITY_FLAG — COGS {cogs_pct * 100:.1f}% ≥ 100% of revenue.  "
              f"Check for duplicate line items or data mapping error.")
        return None
    if cogs_pct < 0.05:
        print(f"  🚫 [M-04] DATA_QUALITY_FLAG — COGS {cogs_pct * 100:.2f}% < 5% of revenue.  "
              f"Confirm expense categorisation — do not treat as a real margin signal.")
        return None
    # ──────────────────────────────────────────────────────────────────────

    gross_profit     = revenue - cogs
    gross_margin_pct = gross_profit / revenue * 100
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

def m05_food_cost(food_cogs, food_revenue, history_12wk, business_type=None):
    """Returns (food_cost_pct, z_food, mu, sigma_eff), or (None)*4 if DATA_QUALITY_FLAG.
    Guards (checked before any division):
      food_revenue ≤ 0       → DATA_QUALITY_FLAG
      food_cogs == 0         → DATA_QUALITY_FLAG (0% food cost implied)
      food_cogs ≥ food_revenue → DATA_QUALITY_FLAG (≥ 100% food cost)
    GAP-1: business_type (fine_dining, cafe, bar, restaurant, …) looks up
    alert_abs_ceiling from VERTICAL_CONFIG instead of hardcoded threshold.
    """
    _hdr("M-05 · Food Cost %  [FIX-M05: s_floor=0.5 pp; z>4 → VERIFY DATA]")
    _step("food_COGS",    "Toast / QB",               f"${food_cogs:,.2f}")
    _step("food_revenue", "Square/Toast daily sales", f"${food_revenue:,.2f}")

    # ── Data-quality guards ────────────────────────────────────────────────
    if food_revenue <= 0:
        print(f"  🚫 [M-05] DATA_QUALITY_FLAG — food_revenue={food_revenue:,.2f} is "
              f"zero/negative.  Cannot compute food cost %.  Check POS data.")
        return None, None, None, None
    if food_cogs == 0:
        print(f"  🚫 [M-05] DATA_QUALITY_FLAG — food_COGS=0 implies 0% food cost.  "
              f"Verify all food purchases are categorised before alerting.")
        return None, None, None, None
    if food_cogs >= food_revenue:
        print(f"  🚫 [M-05] DATA_QUALITY_FLAG — food_COGS ({food_cogs:,.2f}) ≥ "
              f"food_revenue ({food_revenue:,.2f}).  "
              f"Check for duplicate entries or data mapping error.")
        return None, None, None, None
    # ──────────────────────────────────────────────────────────────────────

    food_cost_pct = food_cogs / food_revenue * 100
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

    # Vertical absolute ceiling [VERTICAL_CONFIG]  [GAP-1]
    # When business_type is supplied, look up alert_abs_ceiling from the config
    # (covers fine_dining/cafe/bar sub-verticals as well as restaurant/qsr).
    if business_type is not None:
        vc = VERTICAL_CONFIG.get(business_type, {}).get("m05_food_cost", {})
        abs_ceil = vc.get("alert_abs_ceiling")
        if abs_ceil is not None:
            _step("vertical abs ceiling",
                  f"VERTICAL_CONFIG[{business_type!r}]",
                  f"{abs_ceil}%")
            if food_cost_pct > abs_ceil:
                print(f"  ⚠️  [M-05] abs ceiling breach: {food_cost_pct:.2f}% > {abs_ceil}% "
                      f"({business_type} threshold)")
            else:
                print(f"  ✅ [M-05] below vertical ceiling {abs_ceil}% ({business_type}): "
                      f"{food_cost_pct:.2f}%")

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

    # Data-quality guard — zero/negative revenue denominator
    if revenue <= 0:
        _step("payroll_expense", "ADP/Gusto actual run", f"${payroll_expense:,.2f}")
        _step("revenue",         "QB / POS",             f"${revenue:,.2f}")
        print(f"  🚫 [M-06] DATA_QUALITY_FLAG — revenue={revenue:,.2f} is zero/negative.  "
              f"Cannot compute labor %.  Check POS/QB data.")
        return None, None, None, None

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

    # Data-quality guard — zero/negative revenue_90d denominator
    if revenue_90d <= 0:
        _step("AR_balance",      "open invoices (QB)",   f"${ar_balance:,.2f}")
        _step("revenue_last_90d","QB P&L trailing 90d",  f"${revenue_90d:,.2f}")
        print(f"  🚫 [M-07] DATA_QUALITY_FLAG — revenue_90d={revenue_90d:,.2f} is "
              f"zero/negative.  Cannot compute DSO.  Check QB P&L data.")
        return None, None, None, None

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
                        n_vendors_total=1, vendor_type=None):
    """
    [FIX-M09] z cutoff scales with total vendors tested simultaneously.
    GAP-2: vendor_type routes to VERTICAL_CONFIG['m09_vendor_tolerance'] rules.

    vendor_type rules (from VERTICAL_CONFIG['m09_vendor_tolerance']):
      'new_vendor'        — first-appearance notification only; no z-score.
                            Returns (None, None, None, 'new_vendor_notification').
      'saas_subscription' — alert if |charge − mean| > $1.00 (expected: flat).
      'produce'           — alert only if >20% above mean (seasonal spikes ok).
      'utility'           — no alert; ±10% seasonal variation expected.
      None / anything else — existing Bonferroni z-score path (default).

    Existing callers without vendor_type fall through to the default path.
    Returns (vendor_z, mu, sigma, cutoff).
    """
    _hdr(f"M-09 · Vendor Anomaly — {vendor_name}"
         f"  [FIX-M09: Bonferroni cutoff for {n_vendors_total} vendor(s)]")

    # ── new_vendor: first-appearance — notification only, no z-score ──────
    if vendor_type == "new_vendor":
        print(f"  ℹ️  [M-09] vendor_type=new_vendor — '{vendor_name}' is a first appearance.")
        print(f"       Route: NEW_VENDOR_NOTIFICATION  (not a z-score financial alert).")
        print(f"       Action: flag for owner review; no financial alert fired.")
        return None, None, None, "new_vendor_notification"

    # Compute base stats shared by all remaining paths
    z, mu, sigma = _z_score(this_week_charge, history_12wk)
    pct_above    = (this_week_charge - mu) / mu * 100 if mu > 0 else 0.0
    cutoff       = bonferroni_z_cutoff(n_vendors_total)

    _step("this_week_charge",  vendor_name,               f"${this_week_charge:,.2f}")
    _step("12wk mean",         "mean of history",         f"${mu:,.2f}")
    _step("12wk stdev",        "sample stdev",            f"${sigma:,.2f}")
    _step("vendor_z",          "(charge − mean) / stdev", f"{z:.4f}")
    _step("% above norm",      "(charge − mean) / mean",  f"{pct_above:.1f}%")

    # ── saas_subscription: alert on any deviation above $1.00 ────────────
    if vendor_type == "saas_subscription":
        deviation = abs(this_week_charge - mu)
        _step("$ deviation",       "|charge − mean|",         f"${deviation:.2f}")
        print(f"  [M-09] vendor_type=saas_subscription — expected flat; "
              f"alert if |Δ| > $1.00")
        if deviation > 1.0:
            print(f"  ⚠️  [M-09] ALERT — SaaS charge changed by ${deviation:.2f} "
                  f"(expected flat, tolerance $1.00)")
        else:
            print(f"  ✅ [M-09] SaaS charge within $1.00 of mean — no alert")
        return z, mu, sigma, cutoff

    # ── produce: alert only if >20% above mean ────────────────────────────
    if vendor_type == "produce":
        print(f"  [M-09] vendor_type=produce — alert only if >20% above mean "
              f"(seasonal spikes ≤20% normal)")
        if pct_above > 20.0:
            print(f"  ⚠️  [M-09] ALERT — produce spike {pct_above:.1f}% above mean "
                  f"(threshold: >20%)")
        else:
            print(f"  ✅ [M-09] Produce: {pct_above:.1f}% ≤ 20% threshold — no alert")
        return z, mu, sigma, cutoff

    # ── utility: no alert (±10% seasonal variation expected) ─────────────
    if vendor_type == "utility":
        print(f"  [M-09] vendor_type=utility — ±10% seasonal variation expected; "
              f"no alert threshold")
        print(f"  ✅ [M-09] Utility: {pct_above:.1f}% deviation — "
              f"within expected seasonal range")
        return z, mu, sigma, cutoff

    # ── default: existing Bonferroni z-score path ──────────────────────────
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
    # ── GAP-5: negative balance guard ─────────────────────────────────────
    # Runway is undefined when already overdrawn; M-01 cash gap is the
    # correct alert for this state.
    if current_balance < 0:
        return None, None, None, None, None

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

    GAP-3: upstream-None propagation guard.
    Any input that is None (DATA_QUALITY_FLAG or INSUFFICIENT_HISTORY from an
    upstream metric) is down-weighted to zero.  The function never crashes —
    it degrades gracefully to a partial score over available components.
    The band label lists which components were unavailable.
    """
    _hdr("M-15 · Expansion Readiness Score  [FIX-M15: band, not false decimal]")

    W = {"dso": 0.20, "margin": 0.20, "coverage": 0.20,
         "runway": 0.20, "gst": 0.10, "data_quality": 0.10}

    # ── GAP-3: upstream-None propagation guard ────────────────────────────
    # Detect which components have None inputs (upstream metric failed).
    # Each unavailable component is scored 0 and listed in the band notice.
    unavailable = []
    if dso_days           is None: unavailable.append("dso")
    if gross_margin_pct   is None: unavailable.append("margin")
    if coverage_ratio     is None: unavailable.append("coverage")
    if runway_months      is None: unavailable.append("runway")
    if gst_reserve_gap    is None or est_gst_owing is None:
        unavailable.append("gst")
    if data_quality_score is None: unavailable.append("data_quality")

    if unavailable:
        print(f"  ⚠️  [M-15] GAP-3 upstream-None guard: {len(unavailable)} component(s) "
              f"unavailable — {unavailable}")
        print(f"       Down-weighted to 0.  Score is partial over available components only.")

    # Build scores: None inputs contribute 0 instead of crashing
    scores = {
        "dso":          0.0 if "dso"          in unavailable else _score_dso(dso_days),
        "margin":       0.0 if "margin"        in unavailable else _score_margin(gross_margin_pct),
        "coverage":     0.0 if "coverage"      in unavailable else _score_coverage(coverage_ratio),
        "runway":       0.0 if "runway"        in unavailable else _score_runway(runway_months),
        "gst":          0.0 if "gst"           in unavailable else _score_gst(gst_reserve_gap, est_gst_owing),
        "data_quality": 0.0 if "data_quality"  in unavailable else data_quality_score,
    }

    # Build formula strings safely — never format None
    def _fmt_coverage():
        if "coverage" in unavailable: return "N/A (upstream None)"
        return f"ratio={coverage_ratio:.2f}→{'100 (clip)' if coverage_ratio >= 1.5 else 'formula'}"

    formulas = {
        "dso":          "N/A (upstream None)" if "dso"          in unavailable else f"(1−{dso_days}/60)×100",
        "margin":       "N/A (upstream None)" if "margin"       in unavailable else f"({gross_margin_pct}−20)/(70−20)×100",
        "coverage":     _fmt_coverage(),
        "runway":       "N/A (upstream None)" if "runway"       in unavailable else f"({runway_months:.2f}−3)/15×100",
        "gst":          "N/A (upstream None)" if "gst"          in unavailable else f"100×(1−{gst_reserve_gap}/{est_gst_owing})",
        "data_quality": "N/A (upstream None)" if "data_quality" in unavailable else "manual",
    }

    print(f"\n  {'Component':<14} {'Formula':<40} {'Score':>7} {'Wt':>5} {'Wtd':>8}")
    print(f"  {'─'*14} {'─'*40} {'─'*7} {'─'*5} {'─'*8}")
    total = 0.0
    for k in W:
        s, w, wt = scores[k], W[k], scores[k] * W[k]
        total += wt
        note = "  ← N/A" if k in unavailable else ""
        print(f"  {k:<14} {formulas[k]:<40} {s:>7.1f} {w:>5.2f} {wt:>8.2f}{note}")
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

    # GAP-3: append unavailable component list to band string
    if unavailable:
        band = band + f"  [components unavailable: {', '.join(unavailable)}]"

    print(f"\n  [FIX-M15] Score band: '{band}'  (not reported as {total:.2f}/100)")
    return total, band, scores

