"""Score predicted spans against gold spans (span-overlap based, type-agnostic).

For anonymization the safety-relevant question is COVERAGE: was each true-PII character range
masked by *something*? Any placeholder over those characters hides the value, regardless of which
label the detector used (a name masked as <LOCATION> is still hidden). So matching is by overlap,
not exact boundaries, and not conditioned on the predicted type.

- **recall**    = gold spans overlapped by >=1 prediction / all gold spans   (missed PII = leak)
- **precision** = predictions overlapping >=1 gold span / all predictions    (the rest = over-mask)
- **over_mask** = predictions that cover no true PII                          (false positives)
"""
from __future__ import annotations

from dataclasses import dataclass


def overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """True if half-open intervals [a_start,a_end) and [b_start,b_end) share any character."""
    return a_start < b_end and b_start < a_end


@dataclass
class Aggregate:
    gold: int = 0
    covered: int = 0      # gold overlapped by >=1 prediction  (recall numerator)
    pred: int = 0
    pred_hits: int = 0    # predictions overlapping >=1 gold    (precision numerator)

    @property
    def recall(self) -> float:
        return 1.0 if self.gold == 0 else self.covered / self.gold

    @property
    def precision(self) -> float:
        return 1.0 if self.pred == 0 else self.pred_hits / self.pred

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 0.0 if (p + r) == 0 else 2 * p * r / (p + r)

    @property
    def over_mask(self) -> int:
        return self.pred - self.pred_hits


def score(gold, pred, agg: Aggregate | None = None) -> Aggregate:
    """Accumulate one sample's gold/pred spans into `agg` (or a fresh Aggregate) and return it."""
    a = agg or Aggregate()
    a.gold += len(gold)
    a.pred += len(pred)
    for g in gold:
        if any(overlaps(g.start, g.end, p.start, p.end) for p in pred):
            a.covered += 1
    for p in pred:
        if any(overlaps(p.start, p.end, g.start, g.end) for g in gold):
            a.pred_hits += 1
    return a
