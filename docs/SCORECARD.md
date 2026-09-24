# Skor kartı

Bu belge Fable'ın ölçülmüş durumunu tutar. Sayıların hepsi `make scorecard-full` ile üretilir;
ham rapor `backend/evaluation/results/<tarih-etiket>/scorecard.{md,json}` altındadır.

## Nasıl ölçülür

```bash
make scorecard        # hızlı: LLM kapalı, gerçek belge yok (deney döngüsü için)
make scorecard-full   # tam: canlı Qwen 3.5 4B + 30 gerçek BIST PDF'i (~1,5 saat)
```

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

Katı skorlayıcı, Screenwall V2'nin `benchmark/scorer.py` dosyasının birebir kopyasıdır
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

### Gold (Fable'ın kendi skorlayıcısı, pipeline, canlı LLM)

| Ölçüm | 60 belge | v5 alt kümesi (20) |
|---|---|---|
| Kritik recall (mention × format) | 1555/1555 | 596/596 |
| Metinde bulunamayan kritik mention (hariç) | 5 | 4 |
| Mention recall | 0,883 | 1,0 |
| Karakter precision (yaklaşık, detect) | 0,790 | 0,754 |

v5 alt kümesi, holdout'un dosya sırasına göre ilk 20 belgesidir ve yalnız finance ve legal
belgelerinden oluşur. Eski "holdout kritik recall 1.0" sayısı bu alt kümeden geliyordu.

### Katı skorlayıcı, tür bazında

Kritik türlerin (TCKN, IBAN, kart, telefon, e-posta) hepsi tam. Kaçanlar bilinen sınıflar:
eğitim 0/20, meslek 0/40, sendika 0/10, adli durum 0/10. Bunlar yarı tanımlayıcı sayılır ve Faz 2'nin
kanıt tablosunda "etiketli alan ya da güçlü bağlam" kuralıyla ele alınacak.

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
