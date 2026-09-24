"""Real-document BIST-30 benchmark (corpus collection + offline pipeline run + mode comparison).

Sibling of `evaluation.bist30` (the synthetic canary benchmark, owned by another working session —
do not modify that package from here). This package owns:
  - `companies`  : the verified BIST-30 constituent list (source + date recorded)
  - `fetch`      : manifest-writing downloader for official IR/KAP documents (gitignored data dir)
  - `netguard`   : socket guard proving zero non-local network calls during processing
  - `run_real`   : run the corpus through the REAL pipeline offline; operational metrics
  - `report`     : aggregate results into CSV/JSONL/Markdown

Raw downloaded documents and all generated artifacts live under `data/bist30_benchmark/` (repo-root
`/data/**` is gitignored) and are never committed.
"""
