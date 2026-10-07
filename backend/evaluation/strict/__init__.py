"""Strict output-only scorer, copied from Screenwall V2 (`benchmark/`).

`scorer.py` is a byte-identical copy of V2 `benchmark/scorer.py`; its sha256 (bd4a6816…253b) is
pinned by tests/unit/test_strict_scorer.py. Do not edit or reformat it (not even with ruff): a
rule change needs a new scorer version and renamed results, never an in-place edit.

`run.py` is V2 `benchmark/run.py` (sha256 41c382a0…f43) adapted only so that `--system fable`
uses this repo's engine through the normal package imports.

    uv run python -m evaluation.strict.run --system fable \
        --corpus "${FABLE_BENCH_CORPUS:-$HOME/bist10-benchmark}" --out <new empty dir>
"""
