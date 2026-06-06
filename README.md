# Pulse — Math Validator

A standalone Python validator for the financial intelligence engine behind **Pulse**, a cash-flow operating system for Canadian small businesses.

This file implements 15 financial metrics (cash gap forecasting, payroll coverage, DSO, vendor anomaly detection, GST reserve, runway, expansion readiness, and others) with **121 passing assertions** covering:

- Deterministic arithmetic for all 15 metrics across 4 worked example clients
- Monte Carlo probability bands for M-01 cash gap forecasting
- Vertical-aware routing (restaurant / contractor / agency / SaaS / e-commerce / retail)
- Cross-vertical proof tests — same number, different alert
- Thin-history graceful degradation (INSUFFICIENT_HISTORY paths)
- Structural dirty-data guards (DATA_QUALITY_FLAG paths)
- Cross-cutting extreme-reading routing (z > 4 → VERIFY DATA)

## Running

```bash
python3 pulse_math_validator.py
```

Outputs every intermediate calculation step and an ALL ASSERTIONS PASSED line if all 121 checks succeed.

## Status

This is the spec-validated math engine — the foundation layer of Pulse. Real-world calibration (seasonal curves, M-15 weight fitting, benchmark values) is deliberately deferred until real customer data is available.
