# Fable skor kartı — 2026-09-24-faz0-taban

- Zaman: 2026-09-24T14:26:54+03:00 → 2026-09-24T16:01:27+03:00
- Kod: fable-v2 @ 7d81d93f21 (+71 commit edilmemiş yol)
- Kaynak parmak izi: app/ `82dfbc6ca608ca2e` · evaluation/ `66d3507bffa8c1c4` (results/ ve önbellekler hariç)
- LLM denetçisi: **on** (gold, stress bölümünde; auditor_provider=ollama, require_llm_auditor=True, model=qwen3.5:4b)
- Terim listeleri (allow/deny, motora giden): gold 0/0 · strict 0/0 · stress 0/0 · real 0/0 · sha256 `65e47d39248a7493…` = boş listeler
- Bölümler: gold, strict, stress, real · limit: yok · gerçek belge: 30
- Korpus: `~/bist10-benchmark`

## Kapılar (plan §3)

| Kapı | Hedef | Değer | Sonuç | Not |
|---|---|---|---|---|
| Katı kritik recall (60 belge, allow-list yok) | >= 472/489 | 472/489 | PASS |  |
| Fable skorlayıcısı, holdout kritik recall: Faz 0 tabanından geri gidiş yok | >= taban | 1555/1555 (60/60 belge) | NOT_MEASURED | otomatik taban yok; Faz 0 taban skor kartıyla karşılaştırın |
| v5 20-belge alt kümesinde kritik recall (Fable skorlayıcısı) | 1.0 | 596/596 | PASS |  |
| Canary kaçağı (bare + contextual) | 0/32 | 0/32 | PASS |  |
| Stres: onaylı çıktıya sızıntı (canlı LLM) | 0/72 | 0/72 | PASS |  |
| Stres: güvenli teslim (canlı LLM) | >= 59/62 | 59/62 | PASS |  |
| LLM denetçisi gerçekten çalıştı (süre + sıfır LLM hatası) | >= 1.0 sn medyan ve 0 LLM hatası | gold 19.62 sn, 0 LLM hatası, stress 15.56 sn, 0 LLM hatası | PASS |  |

## (a) Fable GoldBench skorlayıcısı — holdout (pdf + docx + xlsx)

LLM: on

| Ölçüm | Holdout (60/60 belge) | v5 alt kümesi (20/20 belge) | Ölçüm yolu |
|---|---|---|---|
| Kritik recall (mention × format) | 1555/1555 | 596/596 | pipeline |
| Kritik mention, metinde bulunamayan (recall'dan hariç) | 5 | 4 | çıkarım |
| Kritik recall, format başına (60 belge) | pdf 515/515 · docx 520/520 · xlsx 520/520 |  | pipeline |
| Mention recall | 0.8829 | 1.0 | pipeline |
| Entity recall | 0.8589 | 1.0 | pipeline |
| Karakter recall | 0.8923 | 0.9994 | detect |
| Karakter precision (yaklaşık) | 0.7898 | 0.7544 | detect |
| F2 | 0.8697 | 0.9384 | detect |
| Kısmi sızıntı (mention) | 69 | 0 | pipeline |
| Export'ta sızıntı | 231 | 0 | pipeline export |
| NO_MASK ihlali (liste yok, dürüst) | 210/270 | 90/150 | pipeline, liste yok |
| Belge / kayıt / işlenen | 60 / 180 / 180 | 20 / 60 / 60 |  |
| Durumlar | approved 180 | approved 60 |  |
| Denetim / LLM kararı / LLM hatası | 180 / 180 / 0 | 60 / 60 / 0 |  |
| Medyan sn/dosya | 19.62 | 17.3 |  |

- 20 belgelik alt küme: first 20 documents of holdout_gold/gold.jsonl = run_gold --split holdout --formats pdf,docx,xlsx --limit 60 (the limit counts document x format pairs); finance-* and legal-* only, no health/hr/public/correspondence. Bugünkü sıra bu kurala uyuyor: evet.
- **detect**: `engine.detect()` orijinal metinde (yayılım, tablo geçişi, allow-list yok). **pipeline**: değer `run_pipeline` çıktısında yok; terim listeleri kapalı (allow 0 / deny 0: varsayılan allow-list, ALLOW_TERMS / DENY_TERMS ve kullanıcı listeleri yok).
- Kritik recall yalnız çıkarılan metinde bulunan mention'ları sayar; bulunamayanlar ayrı satırda.
- NO_MASK satırı liste olmadan ölçülür, yani dürüsttür: must_keep terimlerini koruyan bir allow-list yok. Aynı soruyu motor düzeyinde (b) bölümündeki must_keep satırı ölçer.
- LLM kanıtı (geçti): medyan 19.62 sn/dosya (makul); 0 denetim LLM kararı almadı (0 belge); beklenen: ~5-7 s/file with qwen3.5:4b; ~0.1 s/file without an LLM; 0 LLM failures.

## (b) Katı skorlayıcı (V2 kopyası, motor allow-list olmadan)

| Ölçüm | Değer |
|---|---|
| Kritik recall (partial guard) | 472/489 |
| Literal kritik recall | 488/489 |
| Tüm mention recall | 527/629 |
| Canary kaçağı, bare + contextual (düşük iyi) | 0/32 (bare 0/16 · contextual 0/16) |
| Kritik canary kaçağı | 0/28 |
| Nötr cümle değişimi (düşük iyi) | 11/40 |
| must_keep korunan, liste yok (yüksek iyi) | 10/90 |
| İşlenemeyen belge | 0 |
| sn/öğe | 0.196 |

scorer.py sha256 `bd4a6816969109a9…` (testle sabit) · allow-list: none (engine called directly, no extra_allow_terms) · dış ağ: blocked

## (c) Stres — 72/72 sabit dosya, tam pipeline

| Ölçüm | Değer |
|---|---|
| Onaylı çıktıya sızıntı, kritik yanlış onay (düşük iyi) | 0/72 |
| Herhangi bir durumda sızıntı | 0/72 |
| Güvenli teslim: safe_output → onaylı, sızıntısız | 59/62 |
| Fail-closed uyumu | 10/10 |
| İnsana yönlendirilen (temkinli) | 3 |
| Gerçekten test edilen ve geçen | 55/55 |
| Durumlar | approved 59 · rejected:invalid 10 · needs_human_review 3 |
| Denetim / LLM kararı / LLM hatası | 59 / 59 / 0 |
| Medyan sn/dosya (pipeline'a giren) | 15.56 |

LLM: **on** · kanıt: geçti (süre makul, 0 LLM hatası; ~5-7 s/file with qwen3.5:4b; ~0.1 s/file without an LLM; 0 LLM failures) · manifest sha256 `6987daa6221960cd…`

## (d) Gerçek belgeler — redaction_density

| Ölçüm | Değer |
|---|---|
| Ölçülen / istenen belge | 30 / 30 |
| redaction_density (yer tutucu / 1000 karakter, tümü) | 12.2434 |
| Belge başına medyan yoğunluk | 13.368 |
| Karakter / yer tutucu | 1020713 / 12497 |
| Hata / boş çıkarım / atlanan | 0 / 0 / 22 |
| Yer tutucu aileleri | PERSON 8404 (%67.2) · LOCATION 3315 (%26.5) · URL 203 (%1.6) · ORG 169 (%1.4) · PHONE 152 (%1.2) · DATE 130 (%1.0) · PLATE 108 (%0.9) · EMAIL 15 (%0.1) · SSN 1 (%0.0) |

| Dosya | Sayfa | Karakter | Yer tutucu | Yoğunluk | sn |
|---|---|---|---|---|---|
| AKBNK-08eadcbe_Akbank_2025_Olağan_Genel_Kurul_Toplantısı_Zaptı.pdf | 7 | 13379 | 174 | 13.0055 | 24.53 |
| AKBNK-0dde8262_Akbank_2024_TSRS_Uyumlu_Sürdürülebilirlik_Raporu.pdf | 27 | 149497 | 1519 | 10.1607 | 65.86 |
| AKBNK-26e47adc_Akbank_2019_Genel_Kurul_Toplantısı_Tutanağı.pdf | 5 | 15883 | 217 | 13.6624 | 3.95 |
| AKBNK-302ced4d_Akbank_Bilgilendirme_Dokümanı_2022_GK_.pdf | 8 | 15290 | 266 | 17.397 | 5.61 |
| AKBNK-3150a1a1_Akbank_Bilgilendirme_Dokümanı_2019_GK_.pdf | 7 | 13586 | 254 | 18.6957 | 5.1 |
| AKBNK-3d51f2ce_Akbank_Kurumsal_Yönetim_İlkelerine_Uyum_Raporu.pdf | 17 | 59568 | 699 | 11.7345 | 27.3 |
| AKBNK-487ed5b2_Akbank_Toplantı_Çağrısı_ve_Gündem_2025_GK_.pdf | 2 | 4596 | 72 | 15.6658 | 1.27 |
| AKBNK-592a201d_Akbank_2025_Olağan_Genel_Kurul_Toplantısı_Hazirun_Cetveli.pdf | 10 | 40839 | 187 | 4.579 | 14.63 |
| AKBNK-5d2816fa_Akbank_Bilgilendirme_Dokümanı_2021_GK_.pdf | 6 | 13985 | 257 | 18.3768 | 5.84 |
| AKBNK-63a7f8f8_Akbank_Bilgilendirme_Dokümanı_2023_GK_.pdf | 18 | 39238 | 673 | 17.1517 | 13.25 |
| AKBNK-88058b31_Akbank_Toplantı_Çağrısı_ve_Vekaletname_2020_GK_.pdf | 6 | 13038 | 166 | 12.732 | 4.95 |
| AKBNK-a292d114_Akbank_22.03.2024_Olağan_Genel_Kurul_Toplantısı_Zaptı.pdf | 8 | 16556 | 199 | 12.0198 | 20.52 |
| AKBNK-a2ffff8f_Akbank_Genel_Kurul_İç_Yönergesi.pdf | 6 | 17883 | 170 | 9.5062 | 6.88 |
| AKBNK-ab60e842_Akbank_Bilgilendirme_Dokümanı_2020_GK_.pdf | 12 | 29130 | 452 | 15.5166 | 11.89 |
| AKBNK-cc8a5e68_Akbank_Kurumsal_Sunum_Corporate_Presentation_.pdf | 49 | 42745 | 231 | 5.4041 | 207.71 |
| AKBNK-d447ce0d_Akbank_Bilgilendirme_Dokümanı_2025_GK_.pdf | 12 | 36682 | 664 | 18.1015 | 9.94 |
| AKBNK-f96a1ba9_Akbank_Bilgilendirme_Dokümanı_2024_GK_.pdf | 16 | 34243 | 581 | 16.967 | 11.53 |
| BIMAS-036de2b3_BİM_2013_Kurumsal_Yönetim_İlkeleri_Uyum_Raporu.pdf | 12 | 53739 | 611 | 11.3698 | 9.85 |
| BIMAS-0a24c03a_BİM_Yatırımcı_Sunumu_-_1Ç26.pdf | 26 | 11748 | 166 | 14.1301 | 8.78 |
| BIMAS-21582cc2_BİM_Yatırımcı_Sunumu_-_2025_Finansal_Sonuçları.pdf | 32 | 18060 | 346 | 19.1584 | 13.75 |
| BIMAS-229cb996_BİM_2021-Q1_Çeyrek_Faaliyet_Raporu.pdf | 8 | 15505 | 185 | 11.9316 | 5.89 |
| BIMAS-24b3cc4b_BİM_Yatırımcı_Sunumu_-_2022_Finansal_Sonuçları.pdf | 33 | 17110 | 286 | 16.7154 | 20.16 |
| BIMAS-2e447039_BİM_2023_Kurumsal_Yönetim_İlkeleri_Uyum_Raporu.pdf | 6 | 33684 | 431 | 12.7954 | 14.42 |
| BIMAS-3e8b7af7_BİM_2026-Q1_Dönemsel_Finansal_Sonuçlar.pdf | 58 | 178614 | 1801 | 10.0832 | 41.39 |
| BIMAS-40e2bb46_BİM_2024-Q1_Çeyrek_Faaliyet_Raporu.pdf | 9 | 15921 | 174 | 10.929 | 3.99 |
| BIMAS-498b2395_BİM_Yatırımcı_Sunumu_-_1Ç25.pdf | 26 | 11277 | 147 | 13.0354 | 5.03 |
| BIMAS-5d276b85_BİM_Yatırımcı_Sunumu_-_2024_Finansal_Sonuçları.pdf | 32 | 18522 | 320 | 17.2768 | 8.23 |
| BIMAS-7f9f6604_BİM_Yatırımcı_Sunumu_-_2Ç24.pdf | 26 | 15122 | 228 | 15.0774 | 6.44 |
| BIMAS-83850078_BİM_2019_Kurumsal_Yönetim_İlkeleri_Uyum_Raporu.pdf | 18 | 38942 | 546 | 14.0209 | 9.42 |
| BIMAS-a72cb7cd_BİM_2025_Kurumsal_Yönetim_İlkeleri_Uyum_Raporu.pdf | 5 | 36331 | 475 | 13.0742 | 7.91 |

Seçim: PDFs in data/corpus_bist10/raw sorted by NFC filename; skip files over --real-max-pages pages or the upload size limit; measure the first N left. Yol: ingest + engine.anonymize (no allow-list, no deny-list, no auditor). Precision hesaplanmaz (BENCHMARK_GUIDE §5.3).

## Süreler

| Bölüm | Durum | Geçen sn | Medyan sn/dosya (strict: sn/öğe) |
|---|---|---|---|
| gold | ok | 4072.02 | — |
| strict | ok | 26.27 | 0.196 |
| stress | ok | 978.45 | 15.56 |
| real | ok | 596.41 | 9.635 |

## Notlar

- Rapor ham değer içermez: değerler yalnız vhash (sha256'nın ilk 16 hanesi) olarak geçer ve dosya
  yazılmadan önce bilinen bütün sentetik değerlere karşı taranır (`pii_scan`).
- Öğe başına ham çıktılar git dışındaki `backend/data/scorecard/<koşu>/` altındadır.
- (a) ve (c) mevcut koşucuları (`run_gold`, `run_stress`) kullanır, ama koşunun kendi storage
  kökünde ve terim listeleri kapalı (`term_lists=False`, boş ALLOW_TERMS / DENY_TERMS).
- `--llm on` = `auditor_provider=ollama` + `require_llm_auditor=True`; model yoksa koşu başlamadan
  durur. Koşu sırasında düşen her LLM çağrısı belge başına sayılır; LLM kapısı sıfır hata ister.
