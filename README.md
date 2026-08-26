<div align="center">

<img src="docs/media/hero.png" alt="Screenwall — Belgeni ver, verini verme" width="880">

[![tests](https://img.shields.io/badge/tests-337%20passing-2F6B4F)](backend/tests)
[![stres](https://img.shields.io/badge/stres%20testi-0%2F72%20s%C4%B1z%C4%B1nt%C4%B1-2F6B4F)](#-benchmark--iddia-değil-sayı)
[![python](https://img.shields.io/badge/python-3.12-6B675C)](backend/pyproject.toml)
[![platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-6B675C)](#-kurulum)
[![local](https://img.shields.io/badge/%C3%A7al%C4%B1%C5%9Fma-%25100%20yerel-1C1B18)](#neden-screenwall)

<img src="docs/media/demo.gif" alt="Screenwall demo — tespit, maskeleme ve onay" width="820">

**[▶ 42 saniyelik tanıtım videosu](screenwall-promo.mp4)** · **[📽 Yatırımcı sunumu (PPTX)](Screenwall-Yatirimci-Sunum.pptx)** · **[📊 Teknik rapor](Fable-Sunum-Rapor.pptx)**

</div>

---

## Neden Screenwall?

Bir sözleşmeyi, bordroyu ya da sağlık raporunu ChatGPT'ye yapıştırdığın an, içindeki
TCKN'ler, IBAN'lar, adlar ve tanılar **geri alınamaz şekilde** dışarı çıkar. KVKK yalnız
şirketlerin sorunu değil: müvekkilinin, müşterinin, çalışanının verisi senin sorumluluğunda.

Screenwall aradaki perdedir: belge **senin makinende** taranır, kişisel veriler deterministik
`<PERSON_1>` etiketlerine çevrilir, yalnız onaylı anonim kopya dışarı çıkar. Sistem emin
olamadığında **otomatik onaylamaz** — belge sana düşer. Güvenlik ayar değil, varsayılandır.

Ve piyasadaki araçların aksine **"bize güven" demiyoruz — sayı veriyoruz** (aşağıda).

## ✨ Özellikler

- 📄 **PDF · DOCX · XLSX** — yapı korunarak: tablolar, üstbilgi/altbilgi, açıklamalar, taranmış sayfalar (OCR)
- 🔍 **3 aşamalı tespit** — Presidio (TR+EN) + 15 özel Türkçe tanıyıcı + yerel Privacy Filter modeli
- 🇹🇷 **Türkçe'ye gerçekten hazır** — checksum'lı TCKN, IBAN, GSM, plaka, sağlık/engellilik terimleri, adres kalıpları, İ/ı-güvenli normalizasyon
- 🔁 **Denetim döngüsü** — kalıntı bulunursa geri beslenir (max 3); şüphede insana düşer (*fail-closed*)
- ↩️ **Tek tıkla geri alma** — yanlış maskelenen terimi UI'dan geri al; belge yeniden taranır
- 🗄 **5 katmanlı depo** — yalnız onaylı anonim katman paylaşılabilir; *destructive* modda orijinal hiç diske yazılmaz (KVKK m.3 anonimleştirme)
- 🔌 **%100 yerel** — onaydan önce tek bir dış çağrı yok; internet bile gerekmez
- 💬 **Onay sonrası sohbet** — anonim kopya üzerinden istediğin LLM'e sor (OpenAI/Anthropic/Ollama)

## 📊 Benchmark — iddia değil, sayı

<img src="docs/media/metrics.jpg" alt="Ölçülmüş güvenlik" width="640">

| Metrik | Sonuç |
|---|---|
| 72 tuzaklı belgede kritik sızıntı (stres) | **0 / 72** |
| Kritik veri yakalama (mühürlü holdout) | **%100*** |
| Belgenin işe yararlığı (utility retention) | **%98,9** |
| Sahte kimlik probu | **16/16** yakalandı |
| Otomatik test | **337 yeşil** |

Ölçüm altyapısı: **GoldBench** (240 gold belge, mühürlü holdout) · 72'lik stres korpusu
(satıra bölünmüş PII, gizli sayfa, taranmış PDF, zip-bomb…) · bağımsız kanarya/aşırı-maskeleme
probları · TAB (EN) dış doğrulaması. Deney günlüğü: [`thoughts/EXPERIMENTS.md`](thoughts/EXPERIMENTS.md).

### İki bağımsız sistem, aynı sınav

Aynı korpus + sabit kurallar + bağımsız skorlayıcı ile ikinci bir sistem (Sol/Codex) koşuldu:

| Test | Screenwall | Sol |
|---|---|---|
| Kritik veri yakalama | **1.00*** | 0.68 (kural-eşit: 0.86) |
| Aşırı-maskeleme | 0/90 | 0/90 |
| Stres kritik sızıntı | **0/72** | 9/72 |
| Gereksiz maskeleme probu | 11/40 | **3/40 — Sol önde** |

*Mühürlü holdout alt-kümesi. Dürüstlük notlarının tamamı (ev-sahibi avantajı, kural farkları,
"ölçülmedi" kalan TRIR gate'i): [`docs/CALIBRATION.md`](backend/docs/CALIBRATION.md).

## 🏗 Mimari

```
Yükle ─▶ Doğrula ─▶ Çıkar (yapı korunur) ─▶ ┌── Denetim döngüsü (max 3) ──┐
                                            │  3-aşamalı tespit → maskele  │
                                            │  Denetçi temiz mi? ──hayır──┘
                                            └──── evet ▼
                              ONAYLANDI ◀── insan incelemesi (şüphede)
                                  │
                    anonim PDF indir · onay-sonrası sohbet (yalnız anonim katman)
```

## 🚀 Kurulum

```bash
git clone https://github.com/EminKolac/screenwall.git && cd screenwall

# Backend
cd backend && uv sync
uv run python -m spacy download en_core_web_sm
uv run python -m spacy download xx_ent_wiki_sm
uv run uvicorn app.main:app --reload

# Frontend (yeni terminal)
cd frontend && npm install && npm run dev
```

Tarayıcıda `http://localhost:5173`. Opsiyonel güçlendirmeler (yerel denetçi LLM, Privacy
Filter, sohbet sağlayıcıları): [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## 🧪 Ölçümleri kendin koş

```bash
cd backend
uv run python -m evaluation.goldbench.run_gold   --mode mapping --tag benim
uv run python -m evaluation.goldbench.run_stress --mode mapping --tag benim
uv run python scripts/measure_canary.py
```

Korpuslar deterministik üretilir (aynı seed → aynı byte'lar); benchmark kuralları dış
sistemler için de sabittir — bağımsız Sol koşusu bu kurallarla yapıldı.

## 🗺 Yol haritası

- [ ] Çift-tıkla kurulum (teknik bilgi gerektirmeyen başlatıcı)
- [ ] UYAP **UDF** desteği (avukatların gerçek formatı)
- [ ] Kalite modunun 38× yavaşlığını kapatan model optimizasyonu
- [ ] Gereksiz maskeleme: 11/40 → 3/40 (Sol'un çıtası)
- [ ] TRIR saldırı-direnci koşusu (paket hazır, gate dürüstçe "ölçülmedi")

## 📜 Lisans

Henüz lisans seçilmedi — kod inceleme için açıktır; yeniden kullanım izni lisans eklenene
kadar saklıdır. (Yakında.)
