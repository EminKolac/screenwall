# BIST-10 Anonimleştirme Benchmark'ı — Uygulama Rehberi

> **Amaç:** Farklı ekiplerin/sistemlerin **aynı sınava** girip sonuçlarının kıyaslanabilmesi.
> Bu rehberi uygulayan her sistem, aynı korpus + aynı metrik tanımı + aynı çıktı şemasını kullanır.
>
> **Bu rehberi okuyan diğer sistem (ör. Codex/ChatGPT tarafı) için:** aşağıdaki adımları birebir
> uygula ve §7'deki çıktı şemasında sonuç üret. Kendi metriğini icat etme; §5'teki tanımlar bağlayıcı.

---

## 1. Korpus — sabit, hash'le doğrulanabilir

**Kaynak:** BIST'te işlem gören 10 halka açık şirketin **resmi yatırımcı ilişkileri** sayfalarından
kamuya açık belgeler. Yalnız şu kaynaklar geçerli: şirketin kendi IR alan adı, `kap.org.tr`,
`borsaistanbul.com`. Aggregator/blog/üçüncü taraf ayna **kullanılmaz**.

**Şirketler (10):** THYAO · TURSG · TTKOM · AKBNK · GARAN · SAHOL · FROTO · EREGL · TUPRS · BIMAS

**Belge türleri:** faaliyet raporu, finansal tablolar, finansal sonuç sunumu, yatırımcı sunumu,
sürdürülebilirlik raporu, genel kurul belgeleri, kurumsal yönetim raporu, esas sözleşme,
ara dönem raporu, özel durum açıklaması, operasyonel veri.

**Format:** Metin yoğun formatlar önceliklidir → `pdf`, `docx`, `doc`. (`xlsx`/`xls` opsiyonel;
tabloları çoğunlukla metin taşımadığı için varsayılan seçimde **dışarıda** bırakılır.)

**Boyut:** ≤ 300 belge, şirket başına ≤ 40, dosya başına ≤ 25 MB.

### 1.1 Korpusu yeniden kurma (ZORUNLU yol)

Korpusun kendisi **repoda değildir** (telif + boyut). Repoda **manifest** vardır:

```
backend/evaluation/corpus_bist10/manifest/corpus_manifest.jsonl
backend/evaluation/corpus_bist10/manifest/corpus_summary.json
```

Manifest her belge için `source_url` + `sha256` taşır. Aynı korpusu kurmak için:

1. Manifest'teki `validity == "ok"` satırların `source_url`'lerini indir.
2. Her dosyanın SHA-256'sını hesapla, manifest'teki `sha256` ile **karşılaştır**.
3. Eşleşmeyen dosyayı korpustan **çıkar** ve raporunda `hash_mismatch` olarak bildir
   (yayıncı belgeyi güncellemiş olabilir — bu normaldir, ama kıyas dışı bırakılmalıdır).
4. Kaç belgeyle çalıştığını raporunda **açıkça** yaz.

> Hash uyuşmazlığı sonuçları geçersiz kılmaz; sadece iki tarafın **kesişim kümesi** üzerinden
> kıyaslama yapılmasını gerektirir. Karşılaştırma her zaman **ortak `id` kümesi** üzerinden yapılır.

Bu repoda korpusu kurmak için:
```bash
cd backend && uv run python -m evaluation.corpus_bist10.fetch --max-docs 300
```

---

## 2. İki iz (track) — ikisi de zorunlu

| İz | Girdi | Cevap anahtarı | Ne ölçer |
|---|---|---|---|
| **1 · Operasyonel** | Korpusun tamamı, **değiştirilmeden** | Yok | Davranış: çıkarım/onay/export oranları, süre, karartma yoğunluğu |
| **2 · Canary** | Bir alt küme, **sentetik PII enjekte edilmiş** | Var (biz yerleştirdik) | Doğruluk: recall, sızıntı, aşama bazlı hata |

**Neden ikisi birden:** İz 1 tek başına doğruluk söylemez (neyin kişisel veri olduğunu bilmiyoruz).
İz 2 tek başına gerçekçilik söylemez (enjekte ettiğimiz değerler doğal metin değil). Birlikte
anlamlıdırlar.

---

## 3. Canary enjeksiyonu — kurallar

### 3.1 Değerler
Tüm canary değerleri **sentetiktir**; gerçek hiçbir kişiye ait değildir. Ortak katalog:
`backend/evaluation/bist30/canary.py` → `canary_catalog()`.

Zorunlu türler (en az bunlar): kişi adı (TR + EN), e-posta, cep telefonu (TR), sabit telefon,
TCKN (checksum geçerli), TR-IBAN, kredi kartı (Luhn geçerli TEST numarası), adres, hesap/müşteri
numarası, API key/secret, token içeren URL, IP, plaka, pasaport.

Her canary şu alanları taşır: `cid`, `expected_family` (beklenen yer tutucu ailesi), `critical`
(kaçarsa gerçek ihlal mi), `base_detectable` (temel motorun yapısal olarak yakalayabileceği tür mü).

### 3.2 Yerleştirme — format özel kanallar
Canary'ler **gerçek belgenin kopyasına** yazılır (orijinal dosya değiştirilmez):

| Format | Kanallar |
|---|---|
| PDF | ilk / orta / son sayfanın alt kenar bandına metin satırları |
| DOCX | gövde paragrafı · tablo hücresi · **header** · **footer** |
| XLSX | hücre · **gizli sayfa** |

Her canary, benzersiz ve **PII olmayan** bir konum işaretçisiyle birlikte yazılır
(`anc0001x <değer>`). İşaretçi, değeri sonradan bulmak içindir; küçük harfli anlamsız bir dizedir
(büyük harfli olursa NER onu da varlık sanıp yutar — ölçümü bozar).

### 3.3 Varyantlar (opsiyonel ama önerilir)
`line_break` (değeri satır sonuyla böl) ve `case_space` (büyük/küçük harf + boşluk varyantı).

---

## 4. Çalıştırma yapılandırması — sabitlenmeli

Raporda **mutlaka** bildirilecek ayarlar:

| Ayar | Bu repodaki varsayılan |
|---|---|
| Ek bağlamsal model (Privacy Filter vb.) | **KAPALI** (`use_privacy_filter=false`) |
| Tespit skor eşiği | `0.4` |
| Denetleyici (auditor) | deterministik sezgisel (LLM yok) |
| Maks. iterasyon | 3 |
| Çalışma anında dış ağ çağrısı | **0 (yasak)** |

> Ek model kullanılacaksa **iki çalıştırma** yapılır (kapalı / açık) ve ikisi de raporlanır.
> Model çalışma anında internetten indirilmez; lokalde yoksa bu durum açıkça raporlanır.

---

## 5. Metrik tanımları — **bağlayıcı**

### 5.1 Canary izi (cevap anahtarı var)

Bir yerleştirme (placement) için sırayla:

| Alan | Tanım |
|---|---|
| `extracted` | Değer, çıkarılan (extracted) metinde **var mı**? (boşluk-duyarsız karşılaştırma) |
| `masked` | Değer, **anonimleştirilmiş metnin tamamında yok mu**? (yoksa `true`) |
| `residual_in_export` | Değer, **dışa aktarılan dosyada** var mı? (varsa **sızıntı**) |
| `family_ok` | Atanan yer tutucu ailesi, `expected_family` ile aynı mı |

Bundan türeyen metrikler:

```
value_recall                = masked / extracted
recall_incl_extraction_loss = masked / toplam_yerleştirme      ← uçtan uca gerçek recall
export_residual             = residual_in_export sayısı        ← sızıntı (ship blocker)
critical_false_negative     = critical=true VE (sızdı VEYA çıkarıldı ama maskelenmedi)
family_correct_of_masked    = family_ok / masked
```

**`recall_incl_extraction_loss` asıl metriktir.** Çıkarılamayan bir değer de kaçırılmış demektir;
`value_recall` tek başına çıkarım hatalarını gizler.

### 5.2 Operasyonel iz (cevap anahtarı yok)

```
processed_rate     = işlenen / toplam
approved_rate      = onaylanan / işlenen
export_ok_rate     = export üretilebilen / işlenen
empty_extraction   = metin çıkmayan belge sayısı
redaction_density  = üretilen yer tutucu / (çıkarılan karakter / 1000)   ← aşırı-maskeleme göstergesi
mean_seconds, p95_seconds
```

### 5.3 ⛔ HESAPLANMAYACAK metrikler

**Gerçek belgelerde `precision` / `F1` hesaplanmaz ve iddia edilmez.**
Sebep: precision, belgedeki kişisel verinin **tam envanterini** gerektirir. Gerçek bir faaliyet
raporunda bu envanter etiketlenmemiştir. Precision hesaplamak, doğru maskelenmiş gerçek bir ismi
sessizce "yanlış pozitif" saymak olur → sayı anlamsızlaşır.

Aşırı maskelemeyi ölçmek için `redaction_density` ve **yer tutucu aile dağılımı** raporlanır.
Precision gerçekten isteniyorsa, §9'daki elle etiketleme adımı yapılmalıdır.

**Ayrıca:** Halka açık yönetici isimlerinin maskelenmesi **ne başarı ne hatadır**; bunu bir
metriğe dönüştürme.

---

## 6. Hata sınıflandırması — her başarısızlık bir aşamaya bağlanır

| Kod | Anlamı |
|---|---|
| `S3_not_extracted:<kanal>` | Değer o kanaldan hiç çıkarılamadı (kör nokta) |
| `S4_ocr_not_extracted` | Görüntü sayfası: OCR yok veya kalitesi düşük |
| `S6_no_base_recognizer` | Temel motorda bu tür için tanıyıcı **yok** (yapısal boşluk) |
| `S8_detected_not_masked` | Çıkarıldı ve tanınabilirdi ama maskelenmedi (eşik/çakışma) |
| `S9_wrong_family` | Maskelendi ama **yanlış** yer tutucu ailesiyle |
| `S10_partial_or_overlap_lost` | Tespit edildi ama çakışma çözümünde kayboldu / kısmen maskelendi |
| `S14_export_residual` | Anonim katmanda maskeliydi ama **dışa aktarılan dosyada geri geldi** |
| `ok` | Çıkarıldı → maskelendi → doğru aile → export'ta yok |

Her kritik hata için raporda: **aşama · kök neden · kanıt · etkilenen tür/format · önerilen düzeltme
· düzeltmenin genel mi belgeye özel mi olduğu.**

---

## 7. Çıktı şeması — **kıyaslama bunun üzerinden yapılır**

Aşağıdaki dosyalar üretilmelidir:

```
results/<tag>/run_config.json        # §4'teki ayarlar
results/<tag>/operational.jsonl      # belge başına 1 satır
results/<tag>/canary.jsonl           # belge başına 1 satır (içinde placements[])
results/<tag>/metrics.json           # §5'teki türetilmiş metrikler
results/<tag>/REPORT.md              # insan-okunur özet
```

**`operational.jsonl` satırı:**
```json
{"id","ticker","format","doc_type","result","status","language","extracted_chars",
 "anon_chars","placeholder_families":{},"placeholders_total","by_source":{},
 "empty_extraction","ocr_warning","export_ok","seconds"}
```

**`canary.jsonl` satırı:**
```json
{"id","ticker","format","result","status","seconds",
 "placements":[{"canary_id","fmt","channel","expected_family","critical","base_detectable",
                "extracted","detected","masked","family_ok","residual_in_export","stage","vhash"}]}
```

> `vhash` = değerin SHA-256'sının ilk 16 hanesi. **Raporlarda ham PII değeri asla yazılmaz** —
> ne gerçek ne sentetik. Karşılaştırma `vhash` üzerinden yapılır.

Bu repoda:
```bash
uv run python -m evaluation.corpus_bist10.run_bench --track both --tag run1
uv run python -m evaluation.corpus_bist10.report --tag run1
```

---

## 8. Güvenlik kontrolleri — raporda cevaplanacak

- [ ] Ham belge / eşleme tablosu içeren katmanlar dışa açılmıyor
- [ ] Dışa aktarılan çıktı **yalnızca** denetlenmiş anonim içerikten üretiliyor
- [ ] Çalışma anında **dış ağ çağrısı yok** (model indirme dahil)
- [ ] Ham belge içeriği veya canary değerleri **loglara sızmıyor**
- [ ] Raporlar ham PII içermiyor (yalnız hash + tür + sayı)
- [ ] Belirsizlik durumunda belge **otomatik onaylanmıyor** (fail-closed)
- [ ] Korpus dosyaları versiyon kontrolüne **eklenmemiş**

---

## 9. Adil kıyaslama protokolü

1. Her iki taraf da §1'deki manifest'ten korpusu kurar; **ortak `id` kümesi** belirlenir.
2. Her iki taraf §4'teki yapılandırmayla çalışır; farklı çalışıyorsa **bunu bildirir**.
3. Her iki taraf §7 şemasında çıktı üretir.
4. Kıyaslama **yalnız şu metrikler** üzerinden yapılır:
   `recall_incl_extraction_loss` · `export_residual` · `critical_false_negatives`
   · `approved_rate` · `redaction_density` · `p95_seconds`.
5. **Precision karşılaştırılmaz** (§5.3). Karşılaştırmak isteniyorsa önce ortak bir elle
   etiketlenmiş alt küme (20–30 belge) oluşturulmalıdır — bu, tarafların **birlikte** yapması
   gereken tek manuel iştir.
6. Kazanan ilan etmeden önce şu sorulur: *iki taraf aynı belgelerde mi, aynı ayarlarla mı,
   aynı metrik tanımıyla mı çalıştı?* Üçü de "evet" değilse **kıyas geçersizdir**.

---

## 10. Sık yapılan hatalar (ölçümü bozar)

| Hata | Neden bozar |
|---|---|
| Sentetik taşıyıcı belge kullanmak | Gerçek düzen/gürültü yok → recall olduğundan yüksek çıkar |
| Büyük harfli konum işaretçisi | NER işaretçiyi varlık sanıp yutar → "maskelenmedi" yanlış pozitifi |
| Bağlam kelimesiz düşük skorlu tür koymak | TR tanıyıcıların çoğu bağlamla tetiklenir; bağlamsız değer haksız FN üretir |
| Sadece `value_recall` raporlamak | Çıkarım kayıplarını gizler; `recall_incl_extraction_loss` şart |
| Gerçek belgede precision iddia etmek | Cevap anahtarı yok (§5.3) |
| Farklı korpus/ayarla kıyaslamak | Skorlar aynı sınavın notu olmaz |
| Denetim katmanına ikinci bir NER koymak | Yakınsamaz: her turda yeni hayalet varlık üretir |

---

## 11. İKİ MOD — her ikisi de uygulanmalı ve ayrı ayrı ölçülmelidir

Sistem iki farklı gizlilik vaadi sunar. Bunlar **farklı şeyler** vaat ettiği için **farklı testlerle**
doğrulanır. Her iki modu da uygula ve her ikisi için de ayrı sonuç üret.

| | Mod **M — `mapping`** (takma adlaştırma) | Mod **D — `destructive`** (geri döndürülemez) |
|---|---|---|
| Ham belge (katman 1) | saklanır | **hiç yazılmaz** |
| Çıkarılan metin + eşleme tablosu (katman 2) | saklanır | **hiç yazılmaz** |
| Anonim çıktı (katman 3) | saklanır | saklanır |
| Denetim raporu (katman 4) | saklanır (PII'siz) | saklanır (PII'siz) |
| Geri döndürülebilir mi? | **Evet** — eşlemeyi elinde tutan geri alabilir | **Hayır** |
| İnsan incelemesi neyi görür | orijinal + anonim | yalnız anonim |
| Hukuki niteliği | KVKK/GDPR'da **hâlâ kişisel veri** | anonim hale getirme hedefi |

> **Terminoloji uyarısı — raporda buna dikkat et:** Mod M *anonimleştirme değil,
> **takma adlaştırmadır** (pseudonymization)*. Geri dönüş anahtarı diskte durduğu sürece veri
> kişisel veri olmaya devam eder. "Anonimleştirdik" ifadesini yalnız Mod D için kullan.

Modu belge başına seçilebilir yap (API'de `mode` alanı) ve varsayılanı yapılandırmadan oku.
Token tutarlılığı **her iki modda da belge içinde korunur** (okunabilirlik için); Mod D'de bu
tutarlılık yalnızca bellekte üretilir, diske yazılmaz.

---

## 12. İKİ BENCHMARK — ortak metrikler + moda özel bütünlük testleri

Her iki mod **aynı tespit metriklerini** üretir (§5) — böylece modlar birbiriyle kıyaslanabilir.
Üstüne her mod, **kendi vaadini** doğrulayan testleri çalıştırır.

### 12.1 Benchmark M — geri dönüş ÇALIŞMALI ve dışarı sızmamalı

| # | Test | Beklenen |
|---|---|---|
| M1 | **Eşleme bütünlüğü** — katman 3'teki her `<TÜR_n>` token'ı eşleme tablosunda çözülüyor mu | tamamı çözülür |
| M2 | **Round-trip** — token'ları eşlemeyle geri koy, her canary'nin orijinal değeri geri gelmeli | tamamı geri gelir |
| M3 | **Kapsama** — eşleme tablosu API yanıtında, logda, export edilen dosyada ve katman 5'te **görünmemeli** | 0 sızıntı |

M3 için en az şunları kontrol et: `GET /api/documents/{id}`, `/findings`, `/anonymized`,
üretilen çıktı dosyası, ve uygulama logları.

### 12.2 Benchmark D — geri dönüş İMKÂNSIZ olmalı

| # | Test | Beklenen |
|---|---|---|
| D1 | **Tam ağaç PII taraması** — işlem bitince depolama kökü altındaki **her baytı** her canary değeri için tara | **0 eşleşme** |
| D2 | Eşleme dosyası ve katman 1 / katman 2 çıktısı diskte var mı | **yok** |
| D3 | **Geri alma denemesi** — eşleme okunmaya çalışılır | `None` döner, yeniden kurulamaz |
| D4 | Tespit metrikleri (§5) | Mod M ile **aynı** olmalı — yok etme tespit kalitesini düşürmemeli |

**D1 kabul kapısıdır:** tek bir eşleşme bile Mod D'nin başarısız olduğu anlamına gelir.

### 12.3 Raporlama
İki modun sonucunu **ayrı** dosyalara yaz (`results/<tag>-mapping/`, `results/<tag>-destructive/`)
ve karşılaştırma tablosunda şu satırları ver: `recall_incl_extraction_loss` · `export_residual` ·
`critical_false_negatives` · M1–M3 / D1–D4 sonuçları · `p95_seconds`.

---

## 13. KORPUS İKİ PARÇADIR — dengeyi doğru yerde ara

Gerçek dünyada BIST yatırımcı belgeleri **neredeyse tamamen PDF**'tir (iki bağımsız taramada
doğrulandı: 302 pdf / 6 Excel / **0 DOCX**). Bu yüzden format dengesi **korpusa kota koyarak**
değil, **ikinci bir parça inşa ederek** sağlanır.

### Parça A — gerçek dilim (temsil gücü)
`corpus_manifest.jsonl`'deki 308 belge, **değiştirilmeden**. Sahadaki davranışı bu ölçer.
Format dağılımı gerçektir ve dengelenmez.

### Parça B — dengeli format üçlüleri (format karşılaştırması)
Parça A'dan **deterministik olarak seçilen 30 belge** alınır, içeriği **bir kez** çıkarılır, sonra
**aynı içerik** üç ayrı kapta yeniden üretilir: **PDF + DOCX + XLSX** → **90 belge, tam 30/30/30**.

Bu neden doğru yöntem: formatlar arası recall farkı artık **içerik farkından değil, format
işlemeden** kaynaklanır — elmalarla elmalar kıyaslanır. Ayrıca BIST'in Word yayımladığı gibi bir
yanılsama üretmez. Parça B kayıtları manifest'te `derived_container` olarak işaretlenir.

**Seçim kuralı (birebir uygulanmalı):** `corpus_manifest.jsonl` içinde `validity == "ok"` olan
kayıtlar `id`'ye göre sıralanır; en kalabalık 3 `doc_type` alınır; her birinden ilk 10 belge seçilir
→ 30 kaynak belge. Kaynaklar `sha256` ile kaydedilir, böylece iki taraf aynı 30 belgeden üretir.

Canary enjeksiyonu **her iki parçaya da** uygulanır; Parça B'de her format kendi özel kanallarını
kullanır (DOCX: gövde/tablo/header/footer · XLSX: hücre/gizli sayfa · PDF: sayfa metni).
