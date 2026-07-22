"""Anonymization evaluation harness — measure detection precision/recall/F1.

The production pipeline has behavioural tests (does it mask a known TCKN?) but no *accuracy*
measurement. This package adds one: a labelled corpus (text + ground-truth PII spans) and a
scorer, so claims like "Privacy Filter improves recall" become numbers, not anecdotes.

Run:  uv run python -m evaluation.run           # baseline (Presidio only)
      USE_PRIVACY_FILTER=true uv run python -m evaluation.run   # + stage ② → compare
"""
