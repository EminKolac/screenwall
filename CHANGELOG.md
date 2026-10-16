# Değişiklik günlüğü

Screenwall'ın sürüm notları. En yeni sürüm en üstte.

## v0.1.2 (2026-10-11)

11 Ekim 2026'daki canlı denemede (v0.1.0 DMG'si, Ollama ile) görülen iki kusurun düzeltmesi.
Kurulum değişmedi. Düzeltilmiş sürüm, v0.1.2 DMG'sindeki uygulama `open` ile açılarak aynı
belgeyle denendi: başlık açık kaldı, öteki alanlar maskelendi, lokal LLM onayladı, PDF
"Maskelenmiş belge" başlığıyla ve gerçek değer içermeden indi.

### Uygulama

- İndirilen PDF'in başlığı artık "Maskelenmiş belge" (önce İngilizce "Anonymized Document"
  yazıyordu). Başlık `render_content_pdf` fonksiyonuna parametre oldu; ölçüm araçları
  (`emit_carriers`, `run_stress`, `run_gold`, `run_bench`, `bist30`) eski başlığı açıkça
  istiyor, böylece ölçüm taşıyıcıları ve parite kayıtları byte byte aynı kalıyor.
- İçinde belge türü adı geçen bir öbek artık kişi adı sayılmıyor. İngilizce ad tanıyıcısı büyük
  harfle başlayan iki kelimeyi kişi sanıyordu; "Tedarik Sözleşmesi (örnek, sentetik veri)"
  başlığı bu yüzden `<PERSON_1>` oluyordu. Yeni kural, istatistiksel ad tanıyıcısının bulduğu
  ve sözleşme, protokol, rapor, fatura, teklif, tutanak, şartname, dilekçe, yönetmelik, karar,
  ek gibi (İngilizcede agreement, contract, report, invoice gibi) bir belge türü adı içeren
  öbeği eliyor. Kelime listesi kapalı ve genel bilgiyle yazıldı, ölçüm dosyalarından alınmadı;
  ad olarak da kullanılan kelimeler ("Bill", "Will") bilerek yok. Yanındaki gerçek adlar
  etkilenmiyor ("Yetkili: Ahmet Yılmaz", "Sözleşmeyi imzalayan Ayşe Demir" yine maskeleniyor).
- API'nin gösterdiği sürüm 0.1.2.

### Site

- Proje sunumu (`Screenwall-Proje-Sunumu.pptx`, v11 filmi gömülü) repoda; README ve site bağlantı veriyor.
- Tanıtım sitesi repoda (`site/`) ve GitHub Pages'te, https://screenwall.site adresiyle (Cloudflare
  üzerinden).
  Önceki adres (screenwall.pages.dev) Türkiye'den açılmıyordu; github.io açılıyor. Metin kurumsal
  anlatıma, lokal LLM ve Claude/ChatGPT adlarına göre güncellendi; v11 filmi (50 sn) eklendi.

### Ölçümler

Değişiklikten önceki ve sonraki kod aynı makinede, aynı gün koşuldu (`docs/SCORECARD.md`,
"v0.1.2 yeniden ölçümü").

- Katı kritik recall 472/489 → 472/489, kanarya kaçağı 0/32 → 0/32, nötr cümle değişimi
  11/40 → 11/40 (aynı 11 cümle), gold kritik recall 1555/1555 → 1555/1555.
- Korunması gereken iş terimleri 10/90 → 30/90. Artışın tamamı "Fatura Dönemi" ve "Sözleşme
  Bedeli" terimlerinden geliyor: ikisi de kuralın genel listesindeki "fatura" ve "sözleşme"
  kelimelerini içeriyor. Terimler hiçbir listeye eklenmedi, ama bu artışı kuralın başka iş
  terimlerine genellendiğinin kanıtı saymıyoruz; öteki 5 terim hâlâ hiç korunmuyor.
- Stres testi canlı lokal LLM ile (Qwen 3.5 4B, listeler kapalı) mevcut kodda ilk kez yeniden
  ölçüldü: onaylı çıktıya sızıntı 0/72, güvenli teslim 59/62, LLM hatası 0; değişiklikten önce de
  aynı. README'deki tek başına komut (`TERM_LISTS=false … run_stress --mode mapping --llm on`)
  da önce ve sonra 72/72 geçti, kritik yanlış onay 0. LLM'in çalıştığı belgelerde medyan süre
  önce 8,7 sn, sonra 17,0 sn; fark makinedeki başka işlerin yükünden.
- İsteğe bağlı parite kontrolü (`PARITY=1 uv run pytest tests/parity`) beklendiği gibi 32 kayıtta
  farklı: gold'da "Fatura Dönemi", "Sözleşme Bedeli" ve "HİZMET SÖZLEŞMESİ" artık açık (ve yer
  tutucu numaraları kaydı), 4 gerçek BIST belgesinde belge adları. Kayıtlar bu değişikliğe göre yenilendi (`tests/parity/snapshots`); eskileri
  `archive/parity-snapshots-v0.1.1/` altında. Kaldırılan maskeler yalnız bu üç terim, kişi adı değil. Kuralın
  30 gerçek BIST PDF'inde düşürdüğü 198 PERSON span'inin hepsi belge adı ("Faaliyet Raporu",
  "Ana Sözleşme", "Yönetim Kurulu Kararı" gibi); aralarında kişi adı yok.
- Arka uçta 55 yeni test: Tesseract kurulu bu makinede 934 geçiyor, 2'si atlanıyor (önce
  879 + 2). Temiz klonda ve CI'da (Ubuntu, macOS) 932 geçiyor, 4'ü atlanıyor. README rozeti
  "932 backend + 79 frontend". Arayüz değişmedi.

## v0.1.1 (2026-10-11)

v0.1.0'ın gözden geçirilmesinde bulunan metin, kurulum ve belge sorunlarının düzeltmeleri. Yalnız
macOS; kurulum adımları v0.1.0'daki gibi.

### Uygulama

- Arayüz ve mesajlar, belgeyi denetleyen ve sohbette kullanılan modeli "lokal LLM" diye anıyor
  (örneğin sohbet sağlayıcısı "Lokal LLM (Ollama)").
- Bulut sohbeti seçeneğinin adı "ChatGPT (Codex CLI)"; metnin gideceği yer OpenAI (ChatGPT)
  olarak gösteriliyor.
- Bu bilgisayardaki API'nin başlığı ve sürümü artık Screenwall'ınki (başlık "Screenwall", sürüm
  uygulamanın sürüm numarası).

### Kurulum

- Başlatıcı yalnız uv'nin kendi yönettiği Python'u kullanıyor
  (`UV_PYTHON_PREFERENCE=only-managed`). İlk açılış artık sistemdeki `/usr/bin/python3` yer
  tutucusunu çalıştırmıyor; komut satırı geliştirici araçları kurulu olmayan Mac'lerde bu yer
  tutucu, araçları yükleme önerisini açabiliyordu.
- README ve `OKU-BENI.txt`: macOS ilk açılışta komut satırı geliştirici araçlarını yüklemeyi
  yine de önerirse Vazgeç'e basın, Screenwall'ın bunlara ihtiyacı yok; Terminal'deki
  "Failed to patch the install name" uyarısı önemsiz.

### Belgeler

- Test sayıları CI ile aynı: temiz klonda ve CI'da arka uçta 877 test geçiyor, 4'ü atlanıyor;
  Tesseract kurulu ve TAB verisi indirilmiş bir makinede 879 geçiyor, 2'si atlanıyor; arayüzde
  79 test geçiyor. README rozeti "877 backend + 79 frontend"; `docs/TESTING.md` dört koşullu
  atlamanın hepsini yazıyor.
- Korunması gereken iş terimleri doğru anlatıldı: 10/90, 8 iş teriminin 90 geçişini sayıyor ve
  korunan 10 geçişin hepsi "Ödeme Planı". Eski izin listesi 90 terimi değil, bu 8 terimi
  içeriyordu.
- Veri klasörü cümlesi düzeltildi: belgeler, ayarlar, kayıtlar ve Python ortamı
  `~/Library/Application Support/Screenwall` altında; uv, Python 3.12 ve indirme önbelleği
  `~/.local` ve `~/.cache/uv` altında. `OKU-BENI.txt` kaldırma listesine `~/.local/bin/uvx` ve
  `~/.config/uv` eklendi.
- README'deki "Ne denendi, ne denenmedi" bölümüne 11 Ekim 2026'daki deneme eklendi: yayımlanan
  DMG'deki uygulama Ollama ile uçtan uca çalıştı (maskeleme, lokal LLM denetimi, onay, maskeyi
  geri alıp yeniden onay, PDF indirme). Finder'dan açılış ve Gatekeeper uyarısı (tarayıcıyla
  indirilmiş DMG), geliştirici araçları olmayan bir Mac, macOS 14–15 ve Intel Mac hâlâ
  denenmedi.
- Stres testinin tek başına komutu, yayımlanan 59/62 ile aynı koşulda: `TERM_LISTS=false` ve
  `--llm on`.
- `docs/SCORECARD.md`: fayda sayılarının `make scorecard-full` ile değil ayrı bir komutla
  ölçüldüğü yazıyor; ürünün eski iç adı kaldırıldı, katı skorlayıcının geldiği sürüm README'deki
  karşılaştırmayla aynı adla, "Screenwall ChatGPT" diye geçiyor.
- Geliştirme için Node.js 20 veya üstü gerekiyor (Playwright testleri bunu ister).
- `OKU-BENI.txt`'nin "Screenwall nedir?" bölümü şirket dokümanlarındaki hassas bilgiler üzerinden
  yeniden yazıldı.
- `THIRD_PARTY_LICENSES.md`: derlenmiş arayüzdeki React, React Router ve TanStack Query'nin MIT
  lisans metinleri, telif satırlarıyla birlikte eklendi; bu dosya sürüm paketleriyle gelir.
- `SECURITY.md`: güvenlik açığı bildirimi bölümü; ayrıntılar herkese açık bir issue'ya yazılmaz,
  gerçek belge ya da kişisel veri eklenmez.
- `.gitattributes`: arşivdeki eski kod (Windows başlatıcısı dahil) GitHub'ın dil istatistiğinde
  sayılmıyor.
- `Screenwall-Yatirimci-Sunum.pptx` README ve filmle aynı dili konuşuyor. Tasarım ve yerleşim değişmedi.
  - Kurumsal anlatım; lokal LLM; Claude ve ChatGPT adıyla anılıyor.
  - Şüphede karar kullanıcının.
  - Örnek slaytında uygulamanın 11 Ekim'deki gerçek kurumsal çıktısı var.
  - Karşılaştırmadaki eski kod adları yerine "Screenwall Claude" ve "Screenwall ChatGPT" yazıyor.
  - Test sayıları CI ile aynı, 1555/1555'in geliştirme setinden geldiği belirtiliyor.

## v0.1.0 (2026-10-10)

İlk yayımlanan sürüm. Yalnız macOS: Apple Silicon ve Intel, macOS 14 (Sonoma) veya üstü. Haziran
ile Eylül 2026 arasında `main` dalında yapılan çalışma (tespit motoru, Türkçe tanıyıcılar, beş
katmanlı depolama, ilk arayüz, GoldBench korpusu) bu sürümün temelidir; aşağıdakiler onun
üzerine ayrı bir geliştirme dalında yapılanlardır.

### İndirme ve kurulum

- `Screenwall-macOS.dmg`: sürükle-bırak kurulum. İçinde `Screenwall.app`, `Applications`
  kısayolu ve `OKU-BENI.txt` var. Uygulama açılınca bir Terminal penceresi ilerlemeyi gösterir;
  belgeler, ayarlar, kayıtlar ve Python ortamı `~/Library/Application Support/Screenwall`
  altında durur; uv ve Python 3.12 `~/.local` ve `~/.cache/uv` altına kurulur.
- `Screenwall-macOS.zip`: aynı uygulama klasör olarak, başlatıcısı `Screenwall.command`.
- `install-macos.sh`: zip'i indirip `SHA256SUMS.txt` ile doğrulayan, `~/Screenwall`
  klasörüne kurup başlatan tek komutluk kurulum. Eski sürümü silmez, yanına taşır.
- Başlatıcı `uv`'yi bulur ya da kurar, Python ortamını kurar, Ollama'yı ve denetçi modelini
  (`qwen3.5:4b`) denetler, eksikse indirir, sunucuyu `127.0.0.1:8765` adresinde başlatır ve
  tarayıcıyı açar.
- Uygulama Apple tarafından imzalanmadı; ilk açılışta sağ tık > Aç gerekir; macOS 15 ve sonrasında bu reddedilirse Sistem Ayarları › Gizlilik ve Güvenlik › Yine de Aç.
- Windows paketleri arşive taşındı; Windows desteklenmiyor.

### Uygulama

- İnceleme merkezli yeni arayüz: orijinal ve maskeli metin yan yana, PDF'te sayfa görüntüsü
  üzerinde işaretler, metni seçerek maskeleme, her maskenin nedeni, klavye kısayolları, açık ve
  koyu tema.
- Belgeler arka planda sırayla işlenir; yükleme beklemeden döner, yarıda kalan belgeler yeniden
  başlatmada kurtarılır.
- Kararlar (bu geçiş, bu belge ya da her zaman) kalıcıdır; belge reddedilebilir.
- Sohbet: lokal LLM (Ollama) varsayılan. İsteğe bağlı bulut sohbeti kullanıcının kendi Claude Code
  CLI ya da Codex CLI (ChatGPT hesabıyla) oturumuyla çalışır. Buluta gidecek metnin tamamı,
  önceki mesajlar dahil, önce gösterilir; onay olmadan hiçbir şey gönderilmez; her gönderim
  içeriği olmadan yerel bir kayda yazılır.
- Ayarlar: varsayılan mod, sohbet sağlayıcısı, "Her zaman maskele" ve "Asla maskeleme" listeleri.

### Tespit ve denetim

- Onay fail-closed: belge yalnız lokal LLM denetimi gerçekten cevap verdiyse, denetim temizse ve
  açık madde kalmadıysa otomatik onaylanır. Elle onay gerekirse denetimi yeniden çalıştırır;
  Ollama çalışmıyorsa onay verilmez.
- Belge başına kilit ve revizyon numarası: eski bir ekran yanlış yeri değiştiremez, işlenen belge
  silinemez. Denetçinin bulduğu değerler saklanır; sonraki kararlar onarılmış maskeleri geri
  açmaz.
- Bağlamlı kişi adı yalnız ada kırpılır; aynı kişi tek etiket alır.
- e-Devlet belgelerinde büyük harfle yazılmış etiketli ad ("Adı :", "Soyadı :") ve resmî adres
  biçimi ("MAH. … SK. NO: … İLÇE / İL") maskelenir.
- Korunan terimler kesme işaretiyle gelen eki de kapsar ("Yönetim Kurulu'nun").
- PDF açıklamaları (annotation) okunur; okunamayan görsel metni için uyarı verilir.
- E-posta tanıyıcısı ağa çıkmaz; hiç tetiklenmeyen 6 hazır Presidio tanıyıcısı kayıttan çıkarıldı.
- Tespit motoru küçük modüllere bölündü; çıktı eski motorla bayt bayt karşılaştırıldı.
- Denetçi ve sohbet için lokal LLM `qwen3.5:4b`; en fazla bir onarım turu.
- Privacy Filter aşaması (varsayılan kapalıydı, belge başına yaklaşık 38 kat yavaştı) arşive
  taşındı. Kullanılmayan presidio-anonymizer kaldırıldı; presidio-analyzer 2.2.362'ye sabitlendi.

### Güvenlik

- Yerel sunucuda Host ve Origin izin listesi, oturum çerezi ve CSRF belirteci, istek boyutu
  sınırı ve güvenlik başlıkları. Veri klasörü yalnız kullanıcıya açık (0700 klasör, 0600 dosya).
- Paketli uygulamada her açılışa özel başlatma anahtarı: bu bilgisayardaki başka kullanıcı
  hesapları oturum açamaz.
- Ollama adresi, açık izin verilmedikçe yalnız bu bilgisayar olabilir; Ollama bulut modelleri
  reddedilir; denetçi istekleri vekil sunucuyu (proxy) atlar.
- "Geri döndürülemez" modda ham değer hiçbir yere yazılmaz; sunucu kayıtları kişisel veri
  süzgecinden geçer.

### Ölçüm

- Tek komutla skor kartı: `make scorecard` (LLM kapalı) ve `make scorecard-full` (canlı lokal
  LLM ve 30 gerçek belge). ChatGPT sürümünün katı puanlayıcısının birebir kopyası eklendi.
- Skor kartı listeler kapalıyken ölçer, LLM'in her belgede gerçekten çalışıp çalışmadığını sayar,
  kısmi koşuları işaretler ve raporlarda ham değer taşımaz.
- Dürüst taban ([`docs/SCORECARD.md`](docs/SCORECARD.md)): katı kritik yakalama 472/489, sahte
  kimlik kaçağı 0/32, stres testinde onaylı çıktıya sızıntı 0/72 ve güvenli teslim 59/62,
  korunması gereken iş terimleri 10/90 (8 iş teriminin 90 geçişi), nötr cümle değişimi 11/40.
  README'de daha önce yazan 0/90, bütün test terimlerini içeren bir izin listesinden geliyordu;
  düzeltildi.

### Belgeler

- README baştan düzenlendi: indirme ve kurulum, nasıl çalıştığı, gizlilik güvenceleri, test
  sonuçları ve bilinen sınırlar.
- `docs/DEPLOYMENT.md`, `docs/API.md` (v2 API), `docs/TESTING.md` ve `SECURITY.md` güncellendi.
- Tanıtım filmi (`screenwall-promo.mp4`), demo animasyonu ve sunum yenilendi.
- Lisans: AGPL-3.0-only ([`LICENSE`](LICENSE)); üçüncü taraf lisans özeti
  ([`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md)); DejaVu yazı tiplerinin lisans metni
  repoda ve sürüm dosyalarında.

### Testler

- Arka uçta temiz klonda ve CI'da 877 test geçiyor, 4'ü atlanıyor. Tesseract kurulu ve TAB
  verisi indirilmiş bir makinede 879 geçiyor, 2'si atlanıyor (7 ve 10 Ekim 2026'da koşuldu,
  ikisinde de aynı sonuç). Arayüzde 79 test geçiyor.
- Arayüz için Playwright testleri (sahte API ile) ve axe ile erişilebilirlik denetimi.
- CI: arka uç testleri Ubuntu ve macOS'ta; arayüz için tip denetimi, birim testleri ve derleme.
- Duman testi: her sürüm GitHub'ın Apple Silicon ve Intel macOS sunucularında açılır, sentetik
  bir belge yüklenip maskelenir; iki sunucuda da geçmezse sürüm oluşmaz.

Bilinen sınırlar için README'deki "Bilinen sınırlar" bölümüne bakın.
