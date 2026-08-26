"""TAB (Text Anonymization Benchmark) üzerinde DIŞ doğrulama ölçümü.

    uv run python scripts/measure_tab.py [--limit N]

Neden ayrı ve neden önemli: GoldBench'i de sistemi de aynı taraf yazdı — "kendi ödevini kendin
notlamak" riski (PLAN.md §15.2 bunu açıkça kaydediyor). TAB bağımsız: Norsk Regnesentral'in
yayımladığı, UZMAN etiketli 254 gerçek AİHM kararı. Buradaki skor bizim şablonlarımızdan,
sözlüklerimizden ve allow-list'imizden habersizdir.

DÜRÜSTLÜK KAYITLARI (rapora aynen girmeli):
- TAB İNGİLİZCEDİR. Bu skor sistemin TÜRKÇE başarısını ÖLÇMEZ; ana Türkçe skorla BİRLEŞTİRİLEMEZ.
  Ölçtüğü şey: TR'ye özel hiçbir kural devrede değilken çekirdek boru hattının (Presidio EN +
  ortografik kapı + resolve_spans) bağımsız, uzman-etiketli, gerçek belgelerde ne yaptığı.
- TAB'ın `identifier_class` taksonomisi bizimkine `tab.map_identifier_class` ile eşlenir; birebir
  aynı tanım değildir (bkz. o fonksiyonun docstring'i).
- Alan-bazlı kaymayı gizlememek için hukuk metni olduğu ayrıca belirtilir.

Metrik: karakter düzeyinde recall — DIRECT (doğrudan tanımlayıcı) ve TÜM sınıflar ayrı ayrı.
Karakter düzeyi seçildi çünkü span sınırları iki şema arasında birebir tutmaz; "değerin kaç
karakteri açıkta kaldı" sorusu şema farkından bağımsızdır.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40, help="belge sayısı (0 = hepsi)")
    ap.add_argument("--max-chars", type=int, default=20000,
                    help="belge başına taranacak azami karakter (AİHM kararları çok uzun)")
    args = ap.parse_args(argv)

    from app.anonymization.presidio_engine import PresidioEngine
    from evaluation.goldbench.external import tab

    if not tab.is_fetched():
        print(json.dumps({"fetched": False,
                          "note": "TAB indirilmemiş — `tab.fetch_default()` çalıştırın."}))
        return 0

    docs = tab.load(limit=args.limit or None)
    engine = PresidioEngine()

    tot = {"direct": [0, 0], "all": [0, 0]}   # [kapsanan_karakter, toplam_karakter]
    per_class: dict[str, list[int]] = {}

    for doc in docs:
        text = doc.text[:args.max_chars]
        covered = set()
        for s in engine.detect(text):
            covered.update(range(s.start, s.end))
        for span in tab.to_gold_spans(doc):
            start, end = span["start"], span["end"]
            if start >= len(text):
                continue                       # kırpılan kuyruğa düşen span sayılmaz
            end = min(end, len(text))
            chars = [i for i in range(start, end) if not text[i].isspace()]
            if not chars:
                continue
            hit = sum(1 for i in chars if i in covered)
            cls = span["identifier_class"]
            slot = per_class.setdefault(cls, [0, 0])
            slot[0] += hit
            slot[1] += len(chars)
            tot["all"][0] += hit
            tot["all"][1] += len(chars)
            if cls == "DIRECT":
                tot["direct"][0] += hit
                tot["direct"][1] += len(chars)

    def rate(pair):
        return round(pair[0] / pair[1], 4) if pair[1] else None

    print(json.dumps({
        "source": "TAB (Norsk Regnesentral, MIT) — İNGİLİZCE hukuk metni",
        "documents": len(docs),
        "char_recall_direct": rate(tot["direct"]),
        "char_recall_all": rate(tot["all"]),
        "by_identifier_class": {k: rate(v) for k, v in sorted(per_class.items())},
        "caveat": "Türkçe skorla BİRLEŞTİRİLEMEZ; TR'ye özel kurallar bu metinlerde devrede değil.",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
