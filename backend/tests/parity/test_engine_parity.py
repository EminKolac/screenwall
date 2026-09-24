"""Byte-identical parity with the pre-Faz-1 engine (snapshots in tests/parity/snapshots).

Opt-in because it runs the real engine over ~180 documents (~70 s):

    PARITY=1 uv run pytest tests/parity -q

Refresh the snapshots ONLY for an intended behaviour change, and record the reason in
thoughts/EXPERIMENTS.md:  uv run python -m tests.parity.capture --out tests/parity/snapshots
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.parity.capture import capture, compare

SNAPSHOTS = Path(__file__).parent / "snapshots"

pytestmark = pytest.mark.skipif(os.environ.get("PARITY") != "1",
                                reason="set PARITY=1 to run the engine parity check")


def test_engine_matches_baseline_snapshots(tmp_path: Path) -> None:
    capture(tmp_path, None)
    assert compare(tmp_path, SNAPSHOTS, None) == 0
