"""BIST-10 fixed corpus benchmark — a reproducible, shareable evaluation of document anonymization.

Design goals (why this exists alongside `evaluation/bist30/`):

1. **Fixed, citable corpus.** A pinned set of public investor-relations documents from 10
   BIST-listed companies. The MANIFEST (url + sha256 + metadata) is committed to the repo; the
   document bytes are
   NOT (they stay in the gitignored data dir). Anyone can rebuild the identical corpus from the
   manifest and verify it by hash — which is what makes a head-to-head comparison meaningful.

2. **Ground truth on REAL documents.** `evaluation/bist30/` planted canaries in synthetic carrier
   files. Here the canaries are injected into COPIES of the real documents, so recall/precision are
   measured on real-world layout, language and noise — not on a toy page.

Two tracks:
  - **Operational** (all documents, unmodified): extraction/approval/export rates, timings,
    placeholder distribution. No precision/recall — there is no ground truth.
  - **Canary** (a subset, injected): value-level recall, precision, export residual, per-stage
    failure attribution. Ground truth is exact because we planted the values.

All canary values are synthetic. Reports contain only hashes, types and counts — never raw PII.
"""
