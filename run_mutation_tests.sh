#!/bin/sh
# Test runner for mutmut. Called once per mutant.
# Uses the 121-assertion validator as the primary kill mechanism (0.1 s).
# Property tests are run separately on surviving mutants (see Guardrail 2).
export MUTANT_UNDER_TEST=1
python3 pulse_math_validator.py
