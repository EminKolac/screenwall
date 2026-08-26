# Kalibrasyon kayıtları — Faz 1 (v4)

Her ayar, GoldBench ile ölçülüp kabul/red edildi. Kural: kritik entity recall **%95 sert alt
sınır** — bir ayar bunun altına düşürüyorsa geri alınır, sınır esnetilmez (kullanıcı kararı).

## Taban çizgisi (Faz 0, 12-24 belge, ayarsız)

| Metrik | Değer |
|---|---|
| mention_recall | 0.968 |
| over_masking_rate | **1.00** (24/24) |
| redaction_coverage_score | 0.42 |
| utility_retention | **0.339** |
| kritik entity recall | ~0.96 |

## Kök neden — Türkçe bağlam artışı hiç çalışmıyordu

`xx_ent_wiki_sm` (Türkçe NER modeli) lemmatizer içermiyor — her token'ın lemma'sı boş string.
Presidio'nun varsayılan `LemmaContextAwareEnhancer` bağlam kelimesini lemma üzerinden arıyor, bu
yüzden "Müşteri **hesap** no…" gibi bağlam kelimesi tam bitişikken bile hiçbir artış tetiklenmedi.
Etkilenen HER düşük-skorlu Türkçe tanıyıcı (VKN 0.2, TR_PHONE 0.3, TR_ACCOUNT 0.25, genel SECRET_KEY
0.15) eşiğin (0.4) altında kalıcı olarak sıkışmıştı.

**Doğrulama:** `"His SSN is 123-45-6789."` (EN) → 0.85 (artış çalışıyor); `"Musteri hesap no
8842-556310-04"` (TR) → 0.25 (artış çalışmıyor). İngilizce etkilenmedi (`en_core_web_sm`'de
lemmatizer var).

**Uygulanan çözüm:** `app/anonymization/context_enhancer.py::SurfaceFormContextAwareEnhancer` —
lemma yerine ham token yüzey biçimini kullanan bir alt sınıf. Bilinen sınır: Türkçe'nin sondan
eklemeli yapısını normalize etmez ("hesap" ≠ alt-dizge "hesabınız", ünsüz yumuşaması). Kapsam
dışı bırakılan gerçek stemming'den daha küçük, daha güvenli bir adım.

## Karar 1 — `low_score_entity_names` (nlp.py)

**Denendi:** `["ORGANIZATION", "NRP"]`
**Denenmedi/reddedildi:** `LOCATION`, `PERSON`

Gerekçe: `presidio_analyzer`'ın yerleşik `SpacyRecognizer`'ı `context = []` taşıyor — yani bu
listeye giren bir tür bağlamla ASLA kurtarılamaz, kalıcı olarak 0.85×0.4=0.34'te kilitlenir (kod
okunarak doğrulandı, varsayılmadı). Bu onu bir kadran değil, bir kapatma anahtarı yapıyor.

- **ORGANIZATION, NRP** → kapatıldı. İkisi de bizim şemamızda tanımlı bir identifier class değil
  ve en büyük aşırı-maskeleme aileleriydi (BIST koşusu: ORG 41k, NRP 36k geçiş).
- **LOCATION** → dokunulmadı. `grep`'le doğrulandı: Türkçe için özel bir adres tanıyıcısı YOK,
  adres maskeleme tamamen genel LOCATION NER'e dayanıyor. Kapatmak adres recall'unu çökertirdi.
- **PERSON** → dokunulmadı. En yüksek kritiklik seviyesi.

## Karar 2 — Allow-list (`allowlist_tr.py` + `config.py:allow_terms`)

`deny_terms`'ün simetriği ama uygulama noktası FARKLI: `presidio_engine.py`'de
`resolve_spans(spans)` çağrısından **hemen önce** filtrelenir, sonra DEĞİL. Sonra filtrelemek
bir tuzaktır: allow'lanan bir ORGANIZATION span'i çakışma nedeniyle bir TR_VKN span'ini
bastırmışsa, sonradan eleme VKN'yi geri getirmez.

~90 terimlik sabit Türkçe kurumsal/hukuki/muhasebe/İK/kamu sözlüğü. Sıfır recall riski taşır —
yalnızca listedeki belirli terimleri bastırır, hiçbir gerçek PII türüne dokunmaz.

## Ölçülen sonuç (72 belge, kalibrasyon sonrası)

| Metrik | Öncesi | Sonrası | Hedef |
|---|---|---|---|
| over_masking_rate | 1.00 | **0.00** (0/144) | ≤ 0.10 ✅ |
| redaction_coverage_score | 0.42 | **0.88** | — |
| critical_entity_recall | ~0.96 | **0.9907–0.9969** | ≥ 0.95 ✅ |
| utility_retention | 0.339 | **0.928** | ≥ 0.90 ✅ |
| mention_recall | 0.968 | 0.937 | — (hafif düşüş, over-masking'in maliyeti) |

Kritik entity recall DÜŞMEDİ, arttı — bağlam artışı düzeltmesi gerçek Türkçe tanıyıcıları da
canlandırdı, sadece gürültüyü kesmedi.

## Kalan (bu turda kapsam dışı, Faz 2)

- `critical_false_negatives: 2` — ikisi de ADDRESS türü, bilinen LOCATION sınırının sonucu.
- `leaked_in_export: 59`, kısmi sızıntı 100 — bitişiklik (adjacency) boşluğu ve mevcut export
  residual sorunuyla ilişkili, Faz 2'nin işi.
- Stress koşusu bu kalibrasyon turunda çalıştırılmadı — Faz 4'te release gate'in tam koşusunda
  ölçülecek.

## Yeniden üretim

```bash
uv run python -m evaluation.goldbench.run_gold --mode mapping --tag <tag> --split dev,public
uv run python -m evaluation.goldbench.run_inference --mode mapping --tag <tag>
uv run python -m evaluation.goldbench.report_gold --tag <tag> --mode mapping
```

---

## v5 iyileştirme döngüsü kapanışı (2026-08-26)

Tam kayıt: `thoughts/EXPERIMENTS.md` → "v5-improvement-loop". Özet:

| Metrik | Önce | Sonra |
|---|---|---|
| Stres kritik yanlış onay | 2-4 | **0/72** (release gate ilk kez) |
| Holdout kritik recall (fast/PF) | 0.9845 / 0.9905 | **1.0 / 1.0** (20-belge alt-küme, 2× determinist) |
| Fayda | 0.9179 | **0.9893** |
| Kanarya (bağlamsız dahil) | 15/16 | **16/16** |
| Aşırı-maskeleme probu | 21/40 | 11/40 (fast yolun yapısal sınırı; PF yolunda kayboluyor) |
| TRIR | ölçülmedi | ölçülmedi (saldırgan model diskten silinmiş; pack hazır) |

Kalibrasyon değişiklikleri: ACCOUNT gruplu desen 0.45 (bağlamsız geçer) · PF exclude'dan
OCCUPATION/JOBTITLE/JOBDEPARTMENT çıkarıldı (GoldBench şeması meslek=QUASI; alt-kümede
doğrulanamadı, tam holdout koşusu gerektirir) · TR_PERSON_CTX etiket-bağlamlı kişi tanıyıcısı ·
PERSON'a iki ortografik kural (tek-kelime + küçük-harfli-kelime içeren) · soyad/yapışık-ad/
yapısal varyant yayılımı · satır-kaydırma (\n-daraltma) turu · kesik-uç uzatması.
