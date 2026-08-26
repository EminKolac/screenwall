# Fable — Öğrencilere Yönelik Etkinlik Önerileri

Kurumsal sunumun alternatifi olarak, üniversite/lise kitlesi için tasarlanmış etkinlikler.
Her etkinlik: süre · seviye · malzeme · kazanım. Ortak güvenlik kuralı en altta.

---

## 1. "PII Avı" — elle karartma yarışması (giriş seviyesi)

**Süre:** 45-60 dk · **Seviye:** lise + üniversite giriş · **Malzeme:** 5-6 sentetik belge çıktısı (GoldBench üreticisinden), kalem

Öğrenciler basılı sentetik sözleşme/rapor üzerinde kişisel verileri elle bulup karartır.
Sonra aynı belgeler canlı olarak Fable'dan geçirilir; insan-vs-makine skoru tahtaya yazılır.

- Beklenen ders: insanlar bariz olanı (TCKN, telefon) bulur ama **quasi-tanımlayıcıları**
  (meslek+ilçe+yaş kombinasyonu) kaçırır; makine tersini de yapabilir.
- Kapanış tartışması: "Ad yoksa kişi anonim midir?" → dolaylı tanımlama kavramı.
- **Kazanım:** KVKK'daki kişisel veri / özel nitelikli veri ayrımı, dolaylı tanımlama sezgisi.

## 2. "Maskeyi Kandır" — kırmızı takım CTF'i (orta-ileri)

**Süre:** 2-3 saat (etkinlik) ya da 1 hafta (online) · **Seviye:** üniversite, güvenlik/yazılım
**Malzeme:** Fable kurulu bir makine ya da API ucu, puan tablosu

Öğrenciler **sentetik** PII içeren belgeler üretip Fable'dan sızırmaya çalışır. Puanlama
stres korpusumuzun gerçek taksonomisiyle: satıra bölünmüş değer, format varyantı, gizli
sayfa, üstbilgi/altbilgi, görsel içine gömülü metin...

- Kural: yalnız sentetik değerler (checksum'lı sahte TCKN üretici verilir); gerçek kişi verisi
  diskalifiye.
- **Projeye geri dönüşü:** her başarılı sızıntı, imzalı bir stres vakası olarak korpusa girer —
  stres setimiz bugün 72 belge; bu etkinlik onu büyütür.
- **Kazanım:** saldırgan düşünme, fail-closed kavramı, "tespit ≠ güvenlik" ayrımı.

## 3. "Korpus Yazarlığı" — bağımsız test seti atölyesi (dil/hukuk öğrencileri dahil!)

**Süre:** 90 dk · **Seviye:** karışık — hukuk, dilbilim, İİBF öğrencileri özellikle değerli
**Malzeme:** şablon YOK (bilerek), etiketleme kılavuzu (1 sayfa), örnek JSON şeması

Her öğrenci serbest üslupla 2-3 gerçekçi Türkçe belge yazar (dilekçe, İK yazısı, banka
yazışması) ve içindeki PII'ları `must_mask` / `must_keep` olarak etiketler.

- **Projeye geri dönüşü (en değerlisi):** bizim ölçüm altyapımızın bilinen açığı "kendi
  şablonumuzla kendimizi notlamak". Öğrenci yazımı belgeler, şablon üreticimizden gerçekten
  bağımsız bir Türkçe test seti üretir — v5 planındaki `evaluation/independent/` boşluğunu
  doldurur.
- Çift-etiketleme (iki öğrenci aynı belgeyi bağımsız etiketler) → etiketleyiciler-arası uyum
  tartışması: "PII nedir?" sorusunun sanıldığı kadar net olmadığını bizzat yaşarlar.
- **Kazanım:** veri etiketleme disiplini, benchmark tasarımı, ölçüm dürüstlüğü.

## 4. "Tanıyıcı Yaz" hackathonu (yazılım, ileri)

**Süre:** 1 gün · **Seviye:** üniversite CS · **Malzeme:** repo + GoldBench koşucusu, liderlik tablosu

Takımlar Fable'a yeni bir tanıyıcı ekler (örnek hedefler: öğrenci numarası, IP, pasaport
harici kimlikler, UYAP dosya no) ve **aynı komutla** ölçülür:

- Liderlik tablosu tek metrik DEĞİL üç metrik: recall ↑ · aşırı-maskeleme probu ↓ · holdout
  regresyonu = 0. "Recall'u artırırken probu bozan takım kaybeder" — gerçek mühendislik
  takası bizzat yaşanır.
- Repo'daki gerçek dersler mini-sunumla açılır: Presidio'nun gizli IGNORECASE'i, kısa span'in
  uzun span'i bastırması gibi "biz de düştük" hataları.
- **Kazanım:** regex/NER pratiği, ölçüm-güdümlü geliştirme, KEEP/DISCARD disiplini.

## 5. "Bir Günlük Veri İzin" — farkındalık günlüğü (lise, yazılım gerektirmez)

**Süre:** 1 hafta ödev + 40 dk tartışma · **Seviye:** lise

Öğrenciler bir gün boyunca hangi form/uygulama/karta hangi kişisel veriyi verdiklerini not
eder (değerleri DEĞİL, türlerini: "ad", "konum", "okul no"...). Sınıfta tür bazında histogram
çıkarılır; "hangisi gerekliydi?" tartışılır.

- Fable bağlantısı: derste tek canlı demo — PII'lı bir sentetik dilekçenin maskelenmesi.
- **Kazanım:** veri minimizasyonu sezgisi; teknik olmayan kitleye gizlilik kavramı.

## 6. Bitirme projesi / staj konuları (ilan edilebilir liste)

Her biri repo'daki gerçek, ölçülmüş bir boşluğa bağlı:

| Konu | Bağlı olduğu ölçülmüş boşluk |
|---|---|
| Türkçe NER ince-ayarı (BERTurk) ve GoldBench'te A/B | fast yolda PERSON, prob 11/40 FP |
| UDF (UYAP) format desteği | format kapsamı — hukuk kitlesi için kritik |
| Privacy Filter hızlandırma (ONNX/quantization) | ölçülen 38× yavaşlama |
| TRIR saldırı koşusu + rapor otomasyonu | tek "ölçülmedi" kalan gate |
| Etiketleyiciler-arası uyum çalışması (madde 3 verisiyle) | benchmark geçerliliği |

## 7. Etik münazara oturumu (hukuk/felsefe ile ortak)

**Süre:** 60 dk · **Önerme örnekleri:**
- "Takma-adlaştırma (mapping) yeterlidir; gerçek anonimleştirme (destructive) fazla kayıptır."
- "Kamu yararına araştırma için sağlık verisi, kişi izni olmadan anonimleştirilerek kullanılabilir."
- Fable'ın iki modu (mapping/destructive) münazaranın somut zemini olarak gösterilir.

---

## Ortak güvenlik kuralları (her etkinlik için bağlayıcı)

1. **Gerçek kişisel veri ASLA kullanılmaz** — tüm belgeler sentetik; TCKN'ler checksum-geçerli
   ama sahte üretilir (üreteci biz veririz).
2. Öğrenci bilgisayarlarından hiçbir belge dış servise gönderilmez — Fable'ın %100 yerel
   çalışması etkinliğin kendisi için de geçerli kuraldır (bu, ürün mesajının yaşayan kanıtıdır).
3. CTF/korpus katkılarında lisans ve isim-atfı baştan yazılı netleştirilir.
4. Yarışma skorlarında "işlenemedi" ayrı sayılır; sızıntı sayıları ham değerle değil hash'le
   raporlanır (bizim rapor disiplinimizin aynısı — öğrencilere de bu disiplin öğretilir).
