# Skor kartı

Bu belge Screenwall'ın ölçülmüş durumunu tutar. Fayda dışındaki sayılar `make scorecard-full`
ile üretilir; fayda ayrı bir komutla, `evaluation.goldbench.run_inference` ile ölçülür (aşağıda
"Hızlı yeniden ölçüm"). Skor kartının ham raporu
`backend/evaluation/results/<tarih-etiket>/scorecard.{md,json}` altındadır. Yeni koşu klasörleri
git'te yok sayılır ve bilerek eklenir (`git add -f`); bugün repoda yalnızca `2026-09-24-faz0-taban`
var. Aşağıda adı geçen diğer koşular yerel klasörlerdir.

## Son durum (7 Ekim 2026)

| Ölçüm | Değer | Kaynak koşu |
|---|---|---|
| Katı kritik recall (60 belge) | 472/489 | 2026-10-06, LLM kapalı |
| Canary kaçağı | 0/32 (yalın 0/16, etiketli 0/16) | 2026-10-06 |
| Gold kritik recall (60 belge, geliştirme seti) | 1555/1555 | 2026-10-06; 2026-10-07 (V2 korpusu olmadan, yalnız gold) |
| Stres: onaylı çıktıya sızıntı (canlı LLM) | 0/72 | 2026-09-25 |
| Stres: güvenli teslim (canlı LLM) | 59/62 | 2026-09-25 |
| must_keep korunan, liste yok (8 terim, 90 geçiş) | 10/90 | 2026-10-06 |
| Nötr cümle değişimi | 11/40 | 2026-10-06 |
| Gerçek belgede yoğunluk (yer tutucu / 1000 karakter) | 12,03 | 2026-10-06 |
| Karakter precision (yaklaşık, detect, 60 belge) | 0,836 | 2026-10-06 |
| Fayda: cevaplanabilir soru, liste yok / varsayılan listeyle | %63,2 (177/280) / %91,8 (257/280) | 2026-10-06 ve 2026-10-07, LLM kapalı |

must_keep paneli 8 iş teriminin 90 geçişidir (Teslim Tarihi 20; Fatura Dönemi, Gider Pusulası,
Sözleşme Bedeli, Ödeme Planı, Kalite Kontrol, Risk Değerlendirmesi ve Yönetim Kurulu 10'ar).
10/90 geçişleri sayar; korunan 10 geçişin hepsi "Ödeme Planı"dır, yani 8 terimden yalnız biri
korunuyor.

Bu sayıların hiçbiri mühürlü (görülmemiş) bir test setinden gelmiyor; 60 belgelik set kural
ayarında da kullanılmış geliştirme setidir. 1555/1555 ve öteki %100 sonuçlar bu setten gelir;
katı skorlayıcı aynı 60 belgede 472/489 verir. README'de eskiden yazan %98,9 fayda değeri
Ağustos'ta, izin listesi açıkken ve eski kodla ölçülmüştü; geçerli sayılmaz.

## Nasıl ölçülür

```bash
make scorecard        # hızlı: LLM kapalı, gerçek belge yok (deney döngüsü için)
make scorecard-full   # tam: canlı Qwen 3.5 4B + 30 gerçek BIST PDF'i (~1,5 saat)
```

Ön koşullar: `scorecard-full` için Ollama ve `qwen3.5:4b` çalışır durumda olmalı. Katı (strict)
ve stres bölümleri V2 kıyas korpusunu ister: `~/bist10-benchmark` (başka bir yer için
`FABLE_BENCH_CORPUS`); gerçek belge bölümü `backend/data/corpus_bist10/raw` altındaki PDF'leri
ister. İkisi de repoda yok. Temiz bir klonda yalnızca gold bölümü çalışır:
`cd backend && uv run python -m evaluation.scorecard --sections gold --tag <etiket>` (7 Ekim'de
korpus olmadan denendi: 1555/1555, çıkış kodu 0).

Ölçümün dört kuralı var. Bunlar kodla zorlanıyor, yalnız yazıyla değil:

1. **Listeler kapalı.** Varsayılan allow-list, `ALLOW_TERMS` / `DENY_TERMS` ve kullanıcının
   listeleri ölçüme girmez (`term_lists=False`). Her bölüm motora giden liste boyutunu kaydeder;
   0/0 değilse bölüm hata verir.
2. **LLM gerçekten çalışır.** `--llm on`, model erişilemezse koşuyu başlatmaz. Koşu sırasında
   düşen her LLM çağrısı belge başına sayılır; "LLM çalıştı" kapısı sıfır hata ister.
3. **Kısmi koşu tam koşuyla karışmaz.** `--limit`, atlanan bölüm ya da hatalı belge varsa rapor
   `complete: false` der ve neyin atlandığını yazar.
4. **Ham değer yok.** Rapor değerleri yalnız hash olarak taşır ve yazılmadan önce bilinen bütün
   sentetik değerlere karşı taranır.

Katı skorlayıcı, ChatGPT ile geliştirilen sürümün (Screenwall ChatGPT, V2)
`benchmark/scorer.py` dosyasının birebir kopyasıdır
(`backend/evaluation/strict/scorer.py`, sha256 `bd4a6816…` testle sabit). Motor listesiz çağrılır;
yani must_keep ve nötr cümle satırları motorun kendi aşırı maskelemesini ölçer.

## Faz 0 tabanı (24 Eylül 2026)

Koşu: `2026-09-24-faz0-taban`, canlı Qwen 3.5 4B, listeler kapalı, 30 gerçek belge.

Uyarı: koşu sürerken başka bir çalışma inceleme katmanının kodunu değiştiriyordu. Rapordaki
kaynak parmak izi bu yüzden temiz bir commit'e denk gelmiyor. Motor düzeyindeki sayılar (katı
skorlayıcı) önceki bağımsız ölçümle birebir aynı çıktı. Faz 2 deneyleri, her biri kendi
"öncesi" ölçümüyle temiz ağaçta koşulur.

### Sert kapılar

| Kapı | Hedef | Taban | Sonuç |
|---|---|---|---|
| Katı kritik recall (60 belge) | ≥ 472/489 | 472/489 | geçti |
| Canary kaçağı | 0/32 | 0/32 | geçti |
| Stres: onaylı çıktıya sızıntı (canlı LLM) | 0/72 | 0/72 | geçti |
| Stres: güvenli teslim (canlı LLM) | ≥ 59/62 | 59/62 | geçti |
| LLM gerçekten çalıştı | 0 hata | 0 hata (gold 19,6 sn, stres 15,6 sn medyan) | geçti |

### Aşırı maskeleme (Faz 2'nin hedefleri)

| Ölçüm | Taban | Hedef |
|---|---|---|
| must_keep korunan, liste yok (yüksek iyi) | 10/90 | ≥ 80/90 |
| Nötr cümle değişimi (düşük iyi) | 11/40 | ≤ 2/40 |
| Gerçek belgede yoğunluk (yer tutucu / 1000 karakter) | 12,24 | en az %50 düşüş |
| Gold NO_MASK ihlali (pipeline, liste yok) | 210/270 | — |

Gerçek belgelerdeki yer tutucuların %67'si PERSON, %27'si LOCATION. Bunlar Akbank ve BİM'in
kamuya açık raporları; içlerindeki kişi adları yönetim kurulu üyeleri gibi az sayıda gerçek kişi.

### Gold (bu reponun kendi skorlayıcısı, pipeline, canlı LLM)

| Ölçüm | 60 belge | v5 alt kümesi (20) |
|---|---|---|
| Kritik recall (mention × format) | 1555/1555 | 596/596 |
| Metinde bulunamayan kritik mention (hariç) | 5 | 4 |
| Mention recall | 0,883 | 1,0 |
| Karakter precision (yaklaşık, detect) | 0,790 (2026-10-06: 0,836) | 0,754 (2026-10-06: 0,820) |

Karakter precision Faz 2 deney 3a'dan (bağlam kırpma) sonra yükseldi; recall sayıları değişmedi.

v5 alt kümesi, holdout'un dosya sırasına göre ilk 20 belgesidir ve yalnız finance ve legal
belgelerinden oluşur. Eski "holdout kritik recall 1.0" sayısı bu alt kümeden geliyordu.

### Katı skorlayıcı, tür bazında

Kritik türlerden TCKN, IBAN, kart, telefon, e-posta, sağlık ve engellilik tam. 489 kritik
değerden kaçan 17'nin hepsi ad (169/179) ve adres (43/50); 16'sı kısmi kaçak (değerin bir parçası
açıkta kalıyor), 1'i değerin tamamı. Kritik olmayan yarı-tanımlayıcılar: eğitim 0/20, meslek 0/40,
sendika 0/10, hukuki durum 0/10, maaş 16/20. Bunlar Faz 2'nin kanıt tablosunda "etiketli alan ya
da güçlü bağlam" kuralıyla ele alınacak.

## Canlı LLM stres kontrolü (25 Eylül 2026)

Koşu: `2026-09-25-v3-stress-check` (yerel klasör), commit `421c47f` üzerinde, yalnız stres
bölümü, canlı Qwen 3.5 4B, listeler kapalı, `require_llm_auditor=True`.

| Ölçüm | Değer |
|---|---|
| Onaylı çıktıya sızıntı, kritik yanlış onay | 0/72 |
| Herhangi bir durumda sızıntı | 0/72 |
| Güvenli teslim: safe_output → onaylı, sızıntısız | 59/62 |
| Fail-closed uyumu | 10/10 |
| Durumlar | approved 59 · rejected:invalid 10 · needs_human_review 3 |
| Denetim / LLM kararı / LLM hatası | 59 / 59 / 0 |
| Medyan sn/dosya | 4,93 |

Faz 0 tabanındaki stres sayılarıyla aynı. Medyan süre tabandakinden (15,56 sn) kısa; nedeni
ayrıca incelenmedi. Bu koşu gold, strict ve gerçek belge bölümlerini ölçmedi.

## Hızlı yeniden ölçüm (6 Ekim 2026)

Bağımsız değerlendirme sırasında, commit `421c47f` üzerinde (birkaç commit edilmemiş değişiklikle),
LLM kapalı ve listeler kapalı koşuldu. Koşular: `2026-10-06-eval-2026-10-06` (gold, strict,
stres) ve `2026-10-06-eval-review-real` (30 gerçek belge).

| Ölçüm | 6 Ekim | Faz 0 tabanı | Not |
|---|---|---|---|
| Katı kritik recall | 472/489 | 472/489 | aynı |
| Canary kaçağı | 0/32 | 0/32 | aynı |
| Nötr cümle değişimi | 11/40 | 11/40 | aynı; hedef ≤ 2/40 |
| must_keep korunan | 10/90 | 10/90 | aynı; hedef ≥ 80/90 |
| Gold kritik recall (60 belge) | 1555/1555 | 1555/1555 | aynı |
| Stres sızıntısı | 0/72 | 0/72 | LLM kapalıyken hiçbir belge onaylanmadığı için bu koşuda bilgi vermez |
| Stres güvenli teslim | 0/62 | 59/62 | LLM kapalıyken hiçbir belge onaylanmaz; bu kapı yalnız canlı LLM ile ölçülür |
| Gerçek belgede yoğunluk | 12,03 | 12,24 | −%1,7; hedef en az −%50 |
| Karakter precision (60 belge) | 0,836 | 0,790 | deney 3a'dan sonra |

Fayda (`evaluation.goldbench.run_inference`, 120 senaryo, 280 soru, LLM kapalı): varsayılan
Türkçe izin listesi açıkken 257/280 (%91,8), bütün listeler kapalıyken 177/280 (%63,2). 7 Ekim'de
aynı komutla yeniden koşuldu ve aynı sonuç çıktı. İki koşu arasında yalnız listeler değişiyor;
yani aradaki 80 soruyu izin listesindeki terimler kurtarıyor. Uygulama listeyle çalışır, skor
kartı listesiz ölçer: dürüst değer %63,2'dir.

## Teşhis: aşırı maskeleme nereden geliyor

Katı panellerde motor tek tek çalıştırılıp sorumlu span'ler döküldü
(`thoughts/EXPERIMENTS.md`, "Faz 2 teşhisi"):

- 11 nötr cümle hatasının 11'i de bağlamsız bir spaCy isabeti (sabit 0,85 puan): 6'sı cümle
  başındaki tek kelimenin LOCATION sanılması ("Şirket", "Bilanço"), 5'i Title-Case bir terimin
  PERSON sanılması ("Vergi Usul Kanunu", "Disiplin Kurulu").
- 80 must_keep kaybının 80'i de bağlamsız PERSON isabeti (60'ı İngilizce, 20'si Türkçe model).
  30'u satır başı "Etiket:" biçiminde ("Fatura Dönemi: Ekim 2026").
- Gerçek kişi adlarının 70'i de yalnız NER ile ve "Etiket:" biçimi olmadan bulunuyor ("Hesap
  sahibi Elif Demir"). İkisini ayıran şey adın bir isim olması; bu yüzden kişi kanıtı için isim
  sözlüğü gerekiyor (plan §4, Faz 2 deney 4).
