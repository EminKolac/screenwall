"""BIST-30 anonymization benchmark — extends `evaluation/` with two benchmarks:

- **Canary benchmark** (offline, deterministic): plant synthetic PII into carrier documents at
  format-specific positions (DOCX comment/header/footer, XLSX hidden-sheet/merged/comment, PDF OCR
  page, filename) with exact ground truth → measure recall, placeholder-family correctness,
  deterministic-token consistency, and export residual, then pinpoint each failure to a stage.
- **Real-document benchmark** (network): process downloaded BIST-30 IR documents unchanged and
  report operational rates (no precision/recall — no ground truth).

All generated documents + ground truth live in the gitignored `backend/data/bist30_benchmark/` dir.
Reports emit only value HASHES and types — never raw PII.
"""
