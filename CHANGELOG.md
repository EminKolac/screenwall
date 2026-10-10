# Değişiklik günlüğü

Screenwall'ın sürüm notları. En yeni sürüm en üstte.

## v0.1.0 (2026-10-10)

İlk yayımlanan sürüm. Yalnız macOS: Apple Silicon ve Intel, macOS 14 (Sonoma) veya üstü. Haziran
ile Eylül 2026 arasında `main` dalında yapılan çalışma (tespit motoru, Türkçe tanıyıcılar, beş
katmanlı depolama, ilk arayüz, GoldBench korpusu) bu sürümün temelidir; aşağıdakiler onun
üzerine `fable-v2` dalında yapılanlardır.

### İndirme ve kurulum

- `Screenwall-macOS.dmg`: sürükle-bırak kurulum. İçinde `Screenwall.app`, `Applications`
  kısayolu ve `OKU-BENI.txt` var. Uygulama açılınca bir Terminal penceresi ilerlemeyi gösterir;
  Screenwall'ın yazdığı her şey `~/Library/Application Support/Screenwall` altında durur.
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
- Denetçi ve yerel sohbet modeli `qwen3.5:4b`; en fazla bir onarım turu.
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

- Tek komutla skor kartı: `make scorecard` (LLM kapalı) ve `make scorecard-full` (canlı yerel
  LLM ve 30 gerçek belge). ChatGPT sürümünün katı puanlayıcısının birebir kopyası eklendi.
- Skor kartı listeler kapalıyken ölçer, LLM'in her belgede gerçekten çalışıp çalışmadığını sayar,
  kısmi koşuları işaretler ve raporlarda ham değer taşımaz.
- Dürüst taban ([`docs/SCORECARD.md`](docs/SCORECARD.md)): katı kritik yakalama 472/489, sahte
  kimlik kaçağı 0/32, stres testinde onaylı çıktıya sızıntı 0/72 ve güvenli teslim 59/62,
  korunması gereken iş terimleri 10/90, nötr cümle değişimi 11/40. README'de daha önce yazan
  0/90, bütün test terimlerini içeren bir izin listesinden geliyordu; düzeltildi.

### Belgeler

- README baştan düzenlendi: indirme ve kurulum, nasıl çalıştığı, gizlilik güvenceleri, test
  sonuçları ve bilinen sınırlar.
- `docs/DEPLOYMENT.md`, `docs/API.md` (v2 API), `docs/TESTING.md` ve `SECURITY.md` güncellendi.
- Tanıtım filmi (`screenwall-promo.mp4`), demo animasyonu ve sunum yenilendi.
- Lisans: AGPL-3.0-only ([`LICENSE`](LICENSE)); üçüncü taraf lisans özeti
  ([`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md)); DejaVu yazı tiplerinin lisans metni
  repoda ve sürüm dosyalarında.

### Testler

- Arka uçta 879 test geçiyor, 2'si atlanıyor; arayüzde 79 test geçiyor (7 ve 10 Ekim 2026'da
  koşuldu, ikisinde de aynı sonuç).
- Arayüz için Playwright testleri (sahte API ile) ve axe ile erişilebilirlik denetimi.
- CI: arka uç testleri Ubuntu ve macOS'ta; arayüz için tip denetimi, birim testleri ve derleme.
- Duman testi: her sürüm GitHub'ın Apple Silicon ve Intel macOS sunucularında açılır, sentetik
  bir belge yüklenip maskelenir; iki sunucuda da geçmezse sürüm oluşmaz.

Bilinen sınırlar için README'deki "Bilinen sınırlar" bölümüne bakın.
