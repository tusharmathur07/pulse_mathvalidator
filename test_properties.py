"""
Property-based tests for pulse_math_validator.py.

These sit alongside the 121 example-based assertions in the validator itself.
They state rules that must hold for every possible input, and let Hypothesis
try thousands of inputs trying to break them.

Run with: python3 -m pytest test_properties.py -q
"""

from hypothesis import given, strategies as st, settings
from pulse_math_validator import m15_expansion_score


# ---------------------------------------------------------------------------
# PROPERTY 1 — Upstream-None propagation through M-15
# ---------------------------------------------------------------------------
# Rule (per M-15 docstring GAP-3):
# If ANY upstream metric input is None (because a guard fired upstream with
# DATA_QUALITY_FLAG or INSUFFICIENT_HISTORY), m15_expansion_score must still
# return a valid (score, band, components) result — never crash, never use
# None silently in arithmetic. The unavailable component should be
# down-weighted to zero and named in the band string.
#
# We let Hypothesis pick: for each of the 7 component inputs, either a
# reasonable numeric value OR None. 2^7 = 128 combinations of which inputs
# are present vs missing, and Hypothesis varies the numerics across the
# present ones. months_of_data optionally triggers the [PARTIAL] band.
# ---------------------------------------------------------------------------

def _maybe_none(numeric_strategy):
    """Either a sensible float or None — Hypothesis picks."""
    return st.one_of(st.none(), numeric_strategy)


@given(
    dso_days           = _maybe_none(st.floats(min_value=0,   max_value=200)),
    gross_margin_pct   = _maybe_none(st.floats(min_value=-50, max_value=100)),
    coverage_ratio     = _maybe_none(st.floats(min_value=0,   max_value=10)),
    runway_months      = _maybe_none(st.floats(min_value=0,   max_value=60)),
    gst_reserve_gap    = _maybe_none(st.floats(min_value=0,   max_value=50000)),
    est_gst_owing      = _maybe_none(st.floats(min_value=0,   max_value=50000)),
    data_quality_score = _maybe_none(st.floats(min_value=0,   max_value=100)),
    months_of_data     = st.one_of(st.none(), st.integers(min_value=1, max_value=36)),
)
@settings(max_examples=500)
def test_m15_handles_any_none_input(
    dso_days, gross_margin_pct, coverage_ratio,
    runway_months, gst_reserve_gap, est_gst_owing,
    data_quality_score, months_of_data
):
    """M-15 must never crash, no matter which subset of inputs is None."""
    result = m15_expansion_score(
        dso_days, gross_margin_pct, coverage_ratio,
        runway_months, gst_reserve_gap, est_gst_owing,
        data_quality_score, months_of_data
    )

    # Result must be a 3-tuple (score, band, components)
    assert result is not None, "M-15 returned None instead of degraded result"
    assert len(result) == 3, f"M-15 expected 3-tuple, got {len(result)}-tuple"

    score, band, components = result

    # Score must be a number in [0, 100], never None
    assert score is not None, "M-15 score is None — should be a degraded number"
    assert 0 <= score <= 100, f"M-15 score out of bounds: {score}"

    # Band must be a non-empty string
    assert isinstance(band, str) and len(band) > 0, f"M-15 band invalid: {band!r}"


# ---------------------------------------------------------------------------
# PROPERTY 2 — Dirty-data propagation through M-10 → M-01
# ---------------------------------------------------------------------------
# Rule: If M-10 returns thin-history (None, None, None, None), the downstream
# consumer (M-01) sees that as a None somewhere in its daily_inflows list.
# M-01 must guard against that — never crash on None, never multiply None
# by a number. Either return a clean result (None treated as zero or skip)
# or return the established None-tagged tuple.
# ---------------------------------------------------------------------------

from pulse_math_validator import m01_cash_gap

@given(
    current_balance = st.floats(min_value=0, max_value=100000,
                                allow_nan=False, allow_infinity=False),
    # daily_inflows: list of either a positive float OR None (simulates
    # what happens when an upstream guard left a hole in the data)
    daily_inflows = st.lists(
        st.one_of(
            st.none(),
            st.floats(min_value=0, max_value=10000,
                      allow_nan=False, allow_infinity=False)
        ),
        min_size=1, max_size=90
    ),
    daily_outflows = st.lists(
        st.floats(min_value=0, max_value=10000,
                  allow_nan=False, allow_infinity=False),
        min_size=1, max_size=90
    ),
    threshold = st.floats(min_value=0, max_value=10000,
                          allow_nan=False, allow_infinity=False),
    days = st.integers(min_value=1, max_value=90),
)
@settings(max_examples=500)
def test_m01_handles_none_in_inflows(
    current_balance, daily_inflows, daily_outflows, threshold, days
):
    """M-01 must not crash when daily_inflows contains None (dirty upstream)."""
    try:
        result = m01_cash_gap(
            current_balance, daily_inflows, daily_outflows, threshold, days
        )
    except (TypeError, ValueError) as e:
        # If M-01 crashes on None, that's a real bug — Hypothesis just found it.
        raise AssertionError(
            f"M-01 crashed on None in daily_inflows: {type(e).__name__}: {e}"
        )

    # If M-01 returned, the result must be the expected 5-tuple shape
    # (gap_day, gap_balance, gap_amount, cash_threshold, balances) per the
    # validator. Either with real numbers OR with None values guarded.
    assert result is not None, "M-01 returned None instead of a tuple"
    assert len(result) == 5, f"M-01 expected 5-tuple, got {len(result)}-tuple"


# ---------------------------------------------------------------------------
# PROPERTY 3 — Output Bounds
# ---------------------------------------------------------------------------
# Three sub-properties, one per metric:
#   3a. m13_runway     : runway months (result[3]) >= 0
#   3b. m04_gross_margin: gross_margin_pct <= 100 when not None
#   3c. m02_payroll_coverage: coverage_ratio (result[1]) >= 0
# ---------------------------------------------------------------------------

from pulse_math_validator import m13_runway, m04_gross_margin, m02_payroll_coverage


# 3a ── m13_runway ─────────────────────────────────────────────────────────

@given(
    payroll_net_per_run  = st.floats(min_value=0, max_value=100_000,
                                     allow_nan=False, allow_infinity=False),
    payroll_period       = st.sampled_from(["weekly", "biweekly",
                                            "semimonthly", "monthly"]),
    non_payroll_monthly  = st.floats(min_value=0, max_value=100_000,
                                     allow_nan=False, allow_infinity=False),
    revenue_monthly      = st.floats(min_value=0, max_value=100_000,
                                     allow_nan=False, allow_infinity=False),
    current_balance      = st.floats(min_value=-10_000, max_value=1_000_000,
                                     allow_nan=False, allow_infinity=False),
)
@settings(max_examples=500)
def test_m13_runway_is_non_negative(
    payroll_net_per_run, payroll_period, non_payroll_monthly,
    revenue_monthly, current_balance,
):
    """M-13 runway months must be >= 0 for any non-negative balance."""
    result = m13_runway(
        payroll_net_per_run, payroll_period,
        non_payroll_monthly, revenue_monthly, current_balance,
    )

    assert result is not None, "M-13 returned None unexpectedly"
    assert len(result) == 5, f"M-13 expected 5-tuple, got {len(result)}"
    _, _, _, runway, _ = result
    if runway is None:
        return  # GAP-5 guard fired (negative balance) — acceptable
    assert runway >= 0, f"M-13 runway is negative: {runway}"


# 3b ── m04_gross_margin ───────────────────────────────────────────────────

@given(
    revenue       = st.floats(min_value=0, max_value=1_000_000,
                              allow_nan=False, allow_infinity=False),
    cogs          = st.floats(min_value=0, max_value=1_000_000,
                              allow_nan=False, allow_infinity=False),
    business_type = st.sampled_from(["", "restaurant", "cafe",
                                     "bar", "fine_dining"]),
)
@settings(max_examples=500)
def test_m04_gross_margin_at_most_100(revenue, cogs, business_type):
    """M-04 gross margin % must be <= 100 whenever it returns a real value."""
    result = m04_gross_margin(revenue, cogs, business_type)

    if result is None:
        return  # guard fired — acceptable
    assert result <= 100, f"M-04 gross margin exceeded 100%: {result}"


# 3c ── m02_payroll_coverage ───────────────────────────────────────────────

@given(
    gross_pay             = st.floats(min_value=0, max_value=100_000,
                                      allow_nan=False, allow_infinity=False),
    net_pay               = st.floats(min_value=0, max_value=100_000,
                                      allow_nan=False, allow_infinity=False),
    cpp_rate              = st.floats(min_value=0, max_value=0.20,
                                      allow_nan=False, allow_infinity=False),
    ei_rate               = st.floats(min_value=0, max_value=0.10,
                                      allow_nan=False, allow_infinity=False),
    balance_before_payroll = st.floats(min_value=0, max_value=1_000_000,
                                       allow_nan=False, allow_infinity=False),
)
@settings(max_examples=500)
def test_m02_coverage_ratio_is_non_negative(
    gross_pay, net_pay, cpp_rate, ei_rate, balance_before_payroll,
):
    """M-02 coverage ratio must be >= 0 for any non-negative balance."""
    result = m02_payroll_coverage(
        gross_pay, net_pay, cpp_rate, ei_rate, balance_before_payroll,
    )

    assert result is not None, "M-02 returned None unexpectedly"
    assert len(result) == 2, f"M-02 expected 2-tuple, got {len(result)}"
    _, coverage = result
    if coverage is None:
        return  # GAP-6 guard fired (zero payroll) — acceptable
    assert coverage >= 0, f"M-02 coverage ratio is negative: {coverage}"
