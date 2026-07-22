"""Offline calibration report for the OpenAI Privacy Filter detector (stage ②).

Usage:
    uv run python -m app.cli.eval_privacy_filter [--model M] [--threshold T] [--exclude L1,L2]
                                                 [--file PATH]

Runs the model on a small embedded synthetic TR/EN corpus (fake identities, real trap patterns:
contract dates, budget amounts, public URLs, `<TYPE_n>` placeholders) and prints every raw span
with its score, its platform mapping, and whether the current threshold/exclude-list would keep
or drop it. Use it to calibrate `PRIVACY_FILTER_THRESHOLD` / `PRIVACY_FILTER_EXCLUDE_LABELS` —
especially for Turkish, where the model's recall is unproven.

Fully offline: the model must be pre-downloaded (PRIVACY_FILTER=1 scripts/setup_macos.sh);
loading is `local_files_only=True`. Exit codes: 0 ok, 2 model/extra unavailable.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.anonymization.privacy_filter import _LABEL_MAP, _load_pipeline, _norm_label
from app.config import get_settings

# Synthetic corpus — every identity/value below is fabricated.
_SAMPLES: list[tuple[str, str]] = [
    ("TR mektup (kişi/IBAN/e-posta/telefon)",
     "Sayın Ahmet Yılmaz, 18 Eylül 2026 tarihli sözleşme gereği ödemenizi "
     "TR33 0006 1005 1978 6457 8413 26 numaralı hesaba yapınız. Sorularınız için "
     "ahmet.yilmaz@example.com adresine yazabilir veya 0532 111 22 33 numarasını arayabilirsiniz."),
    ("TR İK kaydı (TCKN/adres/parola)",
     "Çalışan: Zeynep Kaya, TCKN 10000000146, adres: Atatürk Cad. No:15 Kadıköy/İstanbul. "
     "Sistem parolası Gizli123! olarak güncellendi."),
    ("EN email (person/phone/account/api-key)",
     "Please contact Maya Chen at maya.chen@example.com or +1 (415) 555-0124. The project file "
     "is under account 4829-1037-5581 and the staging API key is sk-test-abc123xyz."),
    ("TUZAK: iş metni (tarih/tutar/URL — maskelenMEmeli)",
     "Q2 lansmanı 18 Eylül 2026'da yapılacak; onaylanan bütçe 1.250.000 USD. Yol haritası "
     "https://example.com/roadmap adresinde yayımlandı ve CFO onayı bekleniyor."),
    ("TUZAK: placeholder'lı anonim metin (dokunulmamalı)",
     "Sözleşme <PERSON_1> ile <DATE_1> tarihinde imzalandı; ödeme <IBAN_1> hesabına yapıldı."),
]


def _report(pipe, text: str, threshold: float, exclude: frozenset[str]) -> tuple[int, dict]:
    kept, by_label = 0, {}
    for r in pipe(text):
        score = float(r.get("score", 0.0))
        label = _norm_label(str(r.get("entity_group") or r.get("entity") or ""))
        start, end = r.get("start"), r.get("end")
        if not label or label == "O" or start is None or end is None:
            continue
        term = text[int(start):int(end)].strip()
        mapped = _LABEL_MAP.get(label, "SENSITIVE")
        flags = []
        if score < threshold:
            flags.append(f"DROP<{threshold}")
        if label in exclude:
            flags.append("EXCLUDED")
        if "<" in term and ">" in term:
            flags.append("!! PLACEHOLDER-FP")
        status = " ".join(flags) if flags else "KEEP"
        print(f"    {label:18} → {mapped:14} {score:.3f}  {status:14} '{term[:40]}'")
        if status == "KEEP":
            kept += 1
            by_label[label] = by_label.get(label, 0) + 1
    return kept, by_label


def main(argv: list[str] | None = None) -> int:
    s = get_settings()
    ap = argparse.ArgumentParser(description="Privacy Filter offline calibration report.")
    ap.add_argument("--model", default=s.privacy_filter_model)
    ap.add_argument("--threshold", type=float, default=s.privacy_filter_threshold)
    ap.add_argument("--exclude", default=s.privacy_filter_exclude_labels,
                    help="comma-separated model labels to ignore (default from settings)")
    ap.add_argument("--file", default=None, help="also run on this UTF-8 text file")
    args = ap.parse_args(argv)
    exclude = frozenset(t.strip().upper() for t in args.exclude.split(",") if t.strip())

    try:
        pipe = _load_pipeline(args.model)
    except ImportError:
        print("transformers/torch missing — install with: uv sync --extra privacy",
              file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 — model not in local cache (local_files_only)
        print(f"model '{args.model}' not available offline ({type(e).__name__}).\n"
              "Pre-download once with: PRIVACY_FILTER=1 bash scripts/setup_macos.sh",
              file=sys.stderr)
        return 2

    print(f"model={args.model}  threshold={args.threshold}  excluded={len(exclude)} label(s)\n")
    samples = list(_SAMPLES)
    if args.file:
        samples.append((f"file: {args.file}", Path(args.file).read_text(encoding="utf-8")))

    totals: dict[str, int] = {}
    for title, text in samples:
        print(f"— {title}")
        kept, by_label = _report(pipe, text, args.threshold, exclude)
        for k, v in by_label.items():
            totals[k] = totals.get(k, 0) + v
        print(f"    => {kept} span KEEP\n")

    print("KEEP toplamları (kategori bazında):")
    for label, n in sorted(totals.items(), key=lambda kv: -kv[1]):
        print(f"  {label:18} {n}")
    print("\nKalibrasyon notu: TUZAK örneklerinde KEEP görüyorsanız threshold'u yükseltin veya "
          "ilgili etiketi PRIVACY_FILTER_EXCLUDE_LABELS'a ekleyin; gerçek PII örneklerinde eksik "
          "varsa threshold'u düşürüp yeniden bakın.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
