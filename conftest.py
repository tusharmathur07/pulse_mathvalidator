"""
conftest.py — Hypothesis settings for mutation testing.

mutmut 3.x sets MUTANT_UNDER_TEST in the environment for every mutant run.
When that variable is present we switch to a reduced-example profile so
each mutant is evaluated in ~1 s instead of ~13 s.

Full-suite runs (CI, pre-commit) use the default profiles declared on each
@given decorator (200–500 examples).
"""
import os
from hypothesis import HealthCheck, settings

if os.environ.get("MUTANT_UNDER_TEST"):
    settings.register_profile(
        "mutation",
        max_examples=30,
        suppress_health_check=[HealthCheck.too_slow],
    )
    settings.load_profile("mutation")
