"""Saldırı testi — anonim metinden gizli özellik çıkarılabiliyor mu?

    uv run python -m evaluation.goldbench.attack --tag v4 --mode mapping            # paket üret
    uv run python -m evaluation.goldbench.attack --tag v4 --run --model qwen2.5:3b  # koştur

Neden gerekli: tam-disk taraması (D1) LİTERAL string arar — "ham değer diskte kaldı mı" sorusunu
yanıtlar. Ama "isim maskelendi, yine de metinde 'İstanbul ofisindeki tek kadın genel müdür' yazıyor"
durumunu göremez. Sistem tüm DOĞRUDAN tanımlayıcıları maskelese bile kişi bağlamdan
çıkarılabiliyorsa gizlilik sağlanmamıştır. Bu modül tam olarak onu ölçer.

İki çıktı verir:

  1. ATTACK PACK (her zaman) — anonim metinler + sabit prompt + aday listeleri + protokol konfigi.
     Deterministik ve modelden bağımsız; başka bir ekip (ör. Codex) aynı paketi kendi modeliyle
     koşup karşılaştırılabilir sonuç üretebilir.
  2. RUNNER (opsiyonel) — OpenAI-uyumlu herhangi bir endpoint (yerel Ollama dahil) ile paketi koşar.

Protokol sabitleri (bunlar olmadan iki koşu kıyaslanamaz): aynı model+sürüm, aynı prompt, aynı
aday listesi, aynı top-k, sıfır temperature, modele YALNIZ anonim metin verilir, ground truth
saldırgana ASLA gösterilmez.

Saldırgan modelin GÜÇLÜ olması gerekir: zayıf bir saldırgan riski olduğundan küçük gösterir. Bu
yüzden hangi modelle koşulduğu rapora yazılır ve zayıf modelle alınan sonuç "alt sınır" olarak
etiketlenir.
"""
from __future__ import annotations

import argparse
import json
import os

from evaluation.goldbench.inference_set import (
    ATTACK_ATTRIBUTES,
    INFERENCE_DIR,
    build_candidate_pool,
)
from evaluation.goldbench.run_inference import OUT, load_scenarios
from evaluation.goldbench.schema import norm

PROMPT_TEMPLATE = """Aşağıda kimliği gizlenmiş bir kurumsal belge var. Belgedeki kişi hakkında \
sorulan özelliği, YALNIZCA belgeden çıkarabildiğin kadarıyla tahmin et.

BELGE:
{document}

SORU: Bu belgedeki kişinin "{attribute}" özelliği nedir?
SEÇENEKLER: {options}

Yalnızca en olası {top_k} seçeneği, en olasıdan başlayarak, virgülle ayrılmış tek satırda yaz. \
Başka hiçbir şey yazma. Emin değilsen yine de tahmin et."""

PROTOCOL = {
    "temperature": 0.0,
    "top_k_answers": 3,
    "options_per_question": 8,
    "prompt_template_id": "goldbench-attack-v1",
    "ground_truth_shown_to_attacker": False,
    "input_to_attacker": "anonymized_text_only",
}


def _options_for(attribute: str, truth: str, pool: list[dict], seed_idx: int,
                 k: int = 8) -> list[str]:
    """Doğru cevap + havuzdan çeldiriciler. Doğru cevabın konumu deterministik olarak değişir —
    sabit konum modelin içeriği değil sırayı öğrenmesine yol açardı."""
    distractors: list[str] = []
    for c in pool:
        v = c.get(attribute)
        if v and norm(v) != norm(truth) and v not in distractors:
            distractors.append(v)
    opts = distractors[: k - 1]
    opts.insert(seed_idx % (len(opts) + 1), truth)
    return opts


def build_pack(tag: str, mode: str) -> dict:
    """Anonim metinleri + soruları + seçenekleri paketler. Ham PII pakete GİRMEZ — yalnız anonim
    metin ve seçenek listeleri (seçenekler zaten sentetik profil değerleridir)."""
    anon_path = OUT / f"{tag}-inference-{mode}" / "anon_texts.jsonl"
    if not anon_path.exists():
        raise FileNotFoundError(
            f"{anon_path} yok — önce: uv run python -m evaluation.goldbench.run_inference "
            f"--mode {mode} --tag {tag}")

    anon = {}
    for line in anon_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            anon[d["scenario_id"]] = d["anon_text"]

    pool = build_candidate_pool()
    scenarios = {s.scenario_id: s for s in load_scenarios()}
    items: list[dict] = []
    for i, (sid, text) in enumerate(sorted(anon.items())):
        sc = scenarios.get(sid)
        if sc is None or not text.strip():
            continue
        for attr in ATTACK_ATTRIBUTES:
            truth = sc.attribute_truth.get(attr)
            if not truth:
                continue  # belgede geçmeyen özelliği sormak tahmini ölçer, sızıntıyı değil
            opts = _options_for(attr, truth, pool, i + len(attr))
            items.append({
                "item_id": f"{sid}:{attr}", "scenario_id": sid, "doc_id": sc.doc_id,
                "attribute": attr, "options": opts,
                "prompt": PROMPT_TEMPLATE.format(
                    document=text[:6000], attribute=attr,
                    options=" | ".join(opts), top_k=PROTOCOL["top_k_answers"]),
                # Cevap anahtarı pakette AYRI tutulur; saldırgana giden yalnız `prompt`tur.
                "_truth": truth,
            })

    outdir = OUT / f"{tag}-attack-{mode}"
    outdir.mkdir(parents=True, exist_ok=True)
    with (outdir / "attack_pack.jsonl").open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    (outdir / "protocol.json").write_text(
        json.dumps({**PROTOCOL, "mode": mode, "tag": tag, "items": len(items)},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return {"items": len(items), "scenarios": len(anon), "outdir": str(outdir),
            "attributes": sorted({it["attribute"] for it in items})}


def _call_openai_compatible(base_url: str, model: str, prompt: str, api_key: str | None) -> str:
    import httpx

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    r = httpx.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers=headers, timeout=120.0,
        json={"model": model, "temperature": PROTOCOL["temperature"],
              "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def run_attack(tag: str, mode: str, base_url: str, model: str, limit: int = 0) -> dict:
    """Paketi bir saldırgan modelle koşar. Sonuç: exact ve top-k başarı oranı.

    `attribute_inference_success` YÜKSEKse kötüdür — sistem doğrudan tanımlayıcıları maskelese bile
    kişinin özellikleri bağlamdan okunabiliyor demektir.
    """
    packdir = OUT / f"{tag}-attack-{mode}"
    pack_path = packdir / "attack_pack.jsonl"
    items = [json.loads(x) for x in pack_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    if limit:
        items = items[:limit]

    api_key = os.environ.get("ATTACK_API_KEY")
    results: list[dict] = []
    with (packdir / "attack_results.jsonl").open("w", encoding="utf-8") as f:
        for i, it in enumerate(items, 1):
            rec = {"item_id": it["item_id"], "attribute": it["attribute"]}
            try:
                raw = _call_openai_compatible(base_url, model, it["prompt"], api_key)
                guesses = [g.strip() for g in raw.replace("\n", ",").split(",") if g.strip()]
                truth_n = norm(it["_truth"])
                rec.update({
                    "exact": bool(guesses) and norm(guesses[0]) == truth_n,
                    "top_k": any(norm(g) == truth_n
                                 for g in guesses[: PROTOCOL["top_k_answers"]]),
                    "guess_count": len(guesses),
                })
            except Exception as e:  # noqa: BLE001 — tek çağrı koşuyu durdurmasın
                rec.update({"error": type(e).__name__, "exact": False, "top_k": False})
            results.append(rec)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if i % 25 == 0 or i == len(items):
                print(f"  [{i}/{len(items)}]")

    n = len(results)
    errs = sum(1 for r in results if r.get("error"))
    topk = round(sum(1 for r in results if r["top_k"]) / n, 4) if n else 0.0
    summary = {
        "model": model, "base_url": base_url, "items": n, "errors": errs,
        "attribute_inference_success_exact": round(
            sum(1 for r in results if r["exact"]) / n, 4) if n else 0.0,
        "attribute_inference_success_topk": topk,
        # report_gold.py::_INFERENCE_KEYS bu bare anahtarı okur — top-k (daha standart "olası
        # cevaplar arasında sızdı mı" ölçütü) buraya alias'lanır, exact daha katı bir alt küme.
        "attribute_inference_success": topk,
        "note": "YÜKSEK = KÖTÜ. Zayıf bir saldırgan riski olduğundan küçük gösterir; "
                "bu sonuç kullanılan modelin alt sınırıdır.",
    }
    (packdir / "attack_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="GoldBench attribute-inference saldırısı")
    ap.add_argument("--tag", default="v4")
    ap.add_argument("--mode", choices=["mapping", "destructive"], default="mapping")
    ap.add_argument("--run", action="store_true", help="paketi bir modelle koştur")
    ap.add_argument("--base-url", default=os.environ.get(
        "ATTACK_BASE_URL", "http://localhost:11434/v1"), help="OpenAI-uyumlu endpoint")
    ap.add_argument("--model", default=os.environ.get("ATTACK_MODEL", "qwen2.5:3b"))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    info = build_pack(args.tag, args.mode)
    print(json.dumps(info, ensure_ascii=False, indent=1))
    if not args.run:
        print(f"\nPaket hazır. Koşturmak için: --run --model <model> --base-url <url>\n"
              f"Senaryo dosyaları: {INFERENCE_DIR}")
        return 0
    print(f"\nSaldırı koşuluyor: {args.model} @ {args.base_url}")
    print(json.dumps(run_attack(args.tag, args.mode, args.base_url, args.model, args.limit),
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
