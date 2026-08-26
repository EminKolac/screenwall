"""240 gold belge üretir: 6 alan × 40, her biri pdf+docx+xlsx taşıyıcı olarak.

    uv run python -m evaluation.goldbench.generate

Determinizm sözleşmesi: aynı `--seed` → byte-byte aynı taşıyıcılar → aynı sha256. Manifest bunu
kaydeder; ikinci bir ekip (Codex) aynı seed'le aynı korpusu yeniden üretebilir. Korpus gerçek PII
içermediği için serbestçe paylaşılabilir — BIST korpusunun aksine URL çürümesi/hash uyumsuzluğu
riski de yoktur.

Determinizmin GERÇEK sınırı (ölçüldü, varsayım değil — raporda da böyle yazılacak):

  - `content_sha256` (metin + cevap anahtarı): **240/240 deterministik.** Asıl yeniden
    üretilebilirlik çapası budur. İkinci bir ekip aynı seed'le aynı korpusu ürettiğini bununla
    doğrular.
  - DOCX/XLSX taşıyıcı byte'ları: **240/240 deterministik** — ama ancak `emit_carriers` içindeki
    normalleştirmeden sonra. Ham python-docx/openpyxl çıktısı hem ZIP girdi tarihlerine hem
    docProps/core.xml'e üretim anını yazıyordu (ölçüldü: 2 sn arayla (…15,58,40) → (…15,58,42)).
  - PDF taşıyıcı byte'ları: **233/240 deterministik.** Kalan 7'si aynı süreçte 240 render boyunca
    biriken PyMuPDF iç durumundan (font subsetting) etkileniyor; boyut farkı birkaç byte, METİN
    İÇERİĞİ aynı. Trailer `/ID` sabitlendi ve `PYTHONHASHSEED=0` denendi — ikisi de bu 7'yi
    kapatmadı. Kapatılamayan bu artık, gizlenmek yerine kaydedilir: taşıyıcı sha256'sı ikincil
    doğrulamadır, birincil ölçüt `content_sha256`'dır.

Split kuralı (veri sızıntısını önler):
  - dev 120 / public 60 / holdout 60
  - holdout AYRI bir seed'den üretilir ve gold etiketleri `holdout_gold/` altında ayrı tutulur;
    koşu script'leri o dizini OKUMAZ. Bu PROSEDÜREL bir mühürlemedir, kriptografik değil —
    aynı kişi hem geliştirici hem benchmark yazarı olduğu için rapora bu sınır açıkça yazılır.
  - Aynı şablon+kişi kombinasyonu birden fazla split'e düşmez (her split kendi kişilerini üretir).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from pathlib import Path

from evaluation.corpus_bist10.emit_carriers import emit
from evaluation.goldbench.identity import Person, make_person
from evaluation.goldbench.schema import GoldDocument
from evaluation.goldbench.templates import DOMAINS, DocBuilder

DATA = Path("data/goldbench")
DOCS = DATA / "docs"
MANIFEST_DIR = Path("evaluation/goldbench/manifest")
GOLD_DIR = DATA / "gold"
HOLDOUT_GOLD_DIR = DATA / "holdout_gold"

FORMATS = ("pdf", "docx", "xlsx")
DOMAIN_ORDER = ("finance", "legal", "health", "hr", "public", "correspondence")

# Kullanıcı spekti: 240 belge = 6 alan × 40; dil 160 TR / 40 EN / 40 karışık.
PER_DOMAIN = 40
SPLIT_SIZES = {"dev": 120, "public": 60, "holdout": 60}
HOLDOUT_SEED_OFFSET = 900_000  # holdout tamamen ayrı bir kişi/varyant uzayından gelir


def _lang_for(global_index: int) -> str:
    """Her 6'lık grupta 4 TR + 1 EN + 1 karışık → 240 belgede tam 160/40/40.

    GLOBAL indeks kullanılır (alan başına sıfırlanan indeks değil): alan başına 40 belge 6'ya
    bölünmediğinden, yerel indeksle desen her alanda kırpılır ve dağılım 168/36/36'ya kayar.
    """
    m = global_index % 6
    if m == 4:
        return "en"
    if m == 5:
        return "mixed"
    return "tr"


def _people_for(rng: random.Random, lang: str, base: int) -> list[Person]:
    """Belge başına 2-4 veri sahibi. Karışık dilde kişiler farklı dillerden gelir."""
    n = rng.randint(2, 4)
    out: list[Person] = []
    for k in range(n):
        if lang == "mixed":
            plang = "en" if k % 2 else "tr"
        elif lang == "en":
            plang = "en"
        else:
            plang = "tr"
        out.append(make_person(rng, base + k, plang))
    return out


def build_document(doc_id: str, domain: str, index: int, seed: int, split: str,
                   global_index: int | None = None) -> GoldDocument:
    """Tek bir gold belge + cevap anahtarı üretir (deterministik)."""
    rng = random.Random(f"{seed}:{domain}:{index}")
    lang = _lang_for(index if global_index is None else global_index)
    people = _people_for(rng, lang, base=index * 10)
    builder = DocBuilder(doc_id)
    DOMAINS[domain](builder, rng, people)  # type: ignore[operator]
    content, mentions = builder.build()
    return GoldDocument(
        doc_id=doc_id, domain=domain, language=lang, split=split,
        text=content.plain_text, mentions=mentions,
        subjects=[p.subject_id for p in people],
    ), content  # type: ignore[return-value]


def _assign_splits() -> list[str]:
    """240 belgeye split etiketi: alan ve dil dağılımı split'ler arasında dengeli kalsın diye
    döngüsel atama yapılır (her 4 belgeden 2 dev, 1 public, 1 holdout)."""
    pattern = ["dev", "dev", "public", "holdout"]
    return [pattern[i % 4] for i in range(PER_DOMAIN * len(DOMAIN_ORDER))]


def generate(seed: int = 20260812, out_docs: Path = DOCS) -> dict:
    out_docs.mkdir(parents=True, exist_ok=True)
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    HOLDOUT_GOLD_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    splits = _assign_splits()
    manifest: list[dict] = []
    gold_rows: list[dict] = []
    holdout_rows: list[dict] = []
    failures: list[dict] = []
    i = 0

    for domain in DOMAIN_ORDER:
        for k in range(PER_DOMAIN):
            split = splits[i]
            doc_id = f"{domain}-{k:03d}"
            doc_seed = seed + (HOLDOUT_SEED_OFFSET if split == "holdout" else 0)
            gdoc, content = build_document(  # type: ignore[misc]
                doc_id, domain, k, doc_seed, split, global_index=i)
            i += 1

            for fmt in FORMATS:
                try:
                    data = emit(content, fmt)
                except Exception as e:  # noqa: BLE001 — tek bozuk belge tüm üretimi durdurmasın
                    # Sessizce düşürmek yerine kaydedilir: manifestte hiç görünmeyen bir belge
                    # "hiç seçilmedi" ile ayırt edilemez.
                    failures.append({"doc_id": doc_id, "format": fmt,
                                     "error": type(e).__name__})
                    continue
                fname = f"{doc_id}.{fmt}"
                (out_docs / fname).write_bytes(data)
                gdoc.formats[fmt] = fname
                manifest.append({
                    "doc_id": doc_id, "domain": domain, "language": gdoc.language,
                    "split": split, "format": fmt, "filename": fname,
                    "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data),
                    "mention_count": len(gdoc.mentions),
                    "entity_count": len({m.entity_id for m in gdoc.mentions}),
                })

            # İçerik çapası: metin + cevap anahtarı. Taşıyıcı formatından ve render motorundan
            # bağımsız olduğu için her koşulda deterministik — asıl yeniden üretilebilirlik ölçütü.
            csha = hashlib.sha256(
                (gdoc.text + "␟" + json.dumps(
                    [m.to_gold_dict() for m in gdoc.mentions],
                    ensure_ascii=False, sort_keys=True)).encode("utf-8")).hexdigest()
            for entry in manifest:
                if entry["doc_id"] == doc_id:
                    entry["content_sha256"] = csha

            row = {**gdoc.meta_dict(), "content_sha256": csha, "text": gdoc.text,
                   "mentions": [m.to_gold_dict() for m in gdoc.mentions]}
            (holdout_rows if split == "holdout" else gold_rows).append(row)

    with (MANIFEST_DIR / "gold_manifest.jsonl").open("w", encoding="utf-8") as f:
        for m in manifest:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    with (GOLD_DIR / "gold.jsonl").open("w", encoding="utf-8") as f:
        for r in gold_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (HOLDOUT_GOLD_DIR / "gold.jsonl").open("w", encoding="utf-8") as f:
        for r in holdout_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    by_split: dict[str, int] = {}
    by_lang: dict[str, int] = {}
    by_fmt: dict[str, int] = {}
    for m in manifest:
        by_fmt[m["format"]] = by_fmt.get(m["format"], 0) + 1
    for r in gold_rows + holdout_rows:
        by_split[r["split"]] = by_split.get(r["split"], 0) + 1
        by_lang[r["language"]] = by_lang.get(r["language"], 0) + 1

    return {
        "seed": seed,
        "documents": len(gold_rows) + len(holdout_rows),
        "carriers": len(manifest),
        "carriers_expected": (len(gold_rows) + len(holdout_rows)) * len(FORMATS),
        "by_split": by_split, "by_language": by_lang, "by_format": by_fmt,
        "total_mentions": sum(len(r["mentions"]) for r in gold_rows + holdout_rows),
        "emit_failures": failures,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="GoldBench korpusunu üret (deterministik)")
    ap.add_argument("--seed", type=int, default=20260812)
    args = ap.parse_args(argv)

    # Hash randomizasyonu sabitlenir: PDF determinizmini TAM sağlamıyor (bkz. modül docstring'i,
    # 7/240 artık kalıyor) ama üretim ortamları arası gereksiz oynamayı azaltır ve maliyeti sıfır.
    # Kütüphane fonksiyonu `generate()` bundan etkilenmez — testler onu doğrudan çağırır.
    if os.environ.get("PYTHONHASHSEED") != "0":
        # flush zorunlu: execve süreci Python'un stdout buffer'ını boşaltmadan değiştirir.
        print("PYTHONHASHSEED=0 ile yeniden başlatılıyor (PDF determinizmi için)…", flush=True)
        os.execve(sys.executable,
                  [sys.executable, "-m", "evaluation.goldbench.generate", *(argv or sys.argv[1:])],
                  {**os.environ, "PYTHONHASHSEED": "0"})
    summary = generate(seed=args.seed)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"manifest -> {MANIFEST_DIR / 'gold_manifest.jsonl'}")
    print(f"gold     -> {GOLD_DIR / 'gold.jsonl'}  (holdout ayrı: {HOLDOUT_GOLD_DIR})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
