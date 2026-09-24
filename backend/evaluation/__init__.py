"""Anonymization evaluation harness — measure detection precision/recall/F1.

The production pipeline has behavioural tests (does it mask a known TCKN?) but no *accuracy*
measurement. This package adds one: a labelled corpus (text + ground-truth PII spans) and a
scorer, so claims about a change become numbers, not anecdotes.

Run everything the way reported numbers are produced (lists off, see docs/SCORECARD.md):
      make scorecard        # fast: no LLM, no real documents
      make scorecard-full   # live Qwen auditor + 30 real BIST PDFs
"""
