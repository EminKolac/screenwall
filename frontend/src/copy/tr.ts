// Every user-facing string of the app. Turkish, sentence case, no exclamation marks.
import type { DocStatus, ErrorCode, FileKind, Mode, ProviderId } from "../api/contract";

// ---------------------------------------------------------------- errors

/** Exhaustive: adding a code to the contract without a sentence here fails the type check. */
export const errorText = {
  document_not_found: "Belge bulunamadı. Silinmiş olabilir.",
  document_busy: "Belge şu anda işleniyor. İşlem bitince tekrar deneyin.",
  unsupported_file_type: "Bu dosya türü desteklenmiyor. PDF, Word (.docx) ya da Excel (.xlsx) yükleyin.",
  file_too_large: "Dosya çok büyük. Daha küçük bir dosya deneyin.",
  invalid_file: "Dosya okunamadı. Bozuk ya da parola korumalı olabilir.",
  extraction_failed: "Belgeden metin çıkarılamadı.",
  not_in_review: "Belge şu anda incelemede değil.",
  not_approved: "Bu işlem için belgenin önce onaylanması gerekiyor.",
  no_content: "Belgenin maskeli metni bulunamadı; onaylanamaz.",
  unresolved_items: "Karar bekleyen öğeler var. Onaydan önce hepsine karar verin.",
  audit_not_clean: "Denetim yeni bir uyarı verdi. Gözden geçirip yeniden onaylayın.",
  invalid_decision: "Bu karar uygulanamadı. Seçimi kontrol edip tekrar deneyin.",
  stale_revision: "Belge bu arada değişti. Güncel hâlini yükleyip tekrar deneyin.",
  original_not_stored: "Bu belgenin orijinali saklanmadı; maske kaldırılamaz.",
  page_not_found: "Sayfa bulunamadı.",
  session_required: "Oturum sona erdi. Sayfayı yenileyin.",
  launch_token_required:
    "Bu sayfa Screenwall'ın başlatıcısından açılmadı ya da uygulama yeniden başladı. Screenwall'ı başlatıcısından yeniden açın.",
  csrf_failed: "Güvenlik doğrulaması başarısız oldu. Sayfayı yenileyip tekrar deneyin.",
  chat_not_allowed: "Sohbet yalnız onaylanmış belgelerle kullanılabilir.",
  preview_required: "Göndermeden önce gönderilecek metni onaylamanız gerekiyor.",
  preview_mismatch: "Belge değişti. Gönderilecek metni yeniden onaylayın.",
  provider_unavailable: "Seçilen sohbet sağlayıcısı şu anda kullanılamıyor.",
  ollama_unreachable: "Ollama'ya ulaşılamadı. Ollama'nın çalıştığından emin olun.",
  model_missing: "Yerel model yüklü değil. Modeli Ollama ile indirin.",
  cli_not_found: "Komut satırı aracı bulunamadı. Önce kurulumu yapın.",
  cli_upgrade_required: "Komut satırı aracının sürümü eski. Güncelleyip tekrar deneyin.",
  cli_login_required: "Komut satırı aracında oturum açılmamış. Giriş komutunu terminalde çalıştırın.",
  cli_timeout: "Yanıt 60 saniye içinde gelmedi. Daha kısa bir soru deneyin.",
  cli_output_limit: "Yanıt izin verilen boyutu aştığı için gösterilmedi.",
  cli_failed: "Komut satırı aracı bir hata verdi. Tekrar deneyin.",
  cli_unsafe_output: "Yanıt güvenlik denetiminden geçmediği için gösterilmedi.",
  invalid_citations: "Yanıttaki kaynak atıfları doğrulanamadığı için yanıt gösterilmedi.",
  internal_error: "Beklenmeyen bir hata oluştu. Tekrar deneyin.",
} satisfies Record<ErrorCode, string>;

export type ClientErrorCode = "network_error" | "unknown_error";
export type AnyErrorCode = ErrorCode | ClientErrorCode;

export const clientErrorText: Record<ClientErrorCode, string> = {
  network_error: "Uygulamanın sunucusuna ulaşılamadı. Uygulamanın çalıştığından emin olun.",
  unknown_error: "Beklenmeyen bir yanıt alındı. Sayfayı yenileyip tekrar deneyin.",
};

/** Chat provider status reasons (ProviderStatus.problem) that never come back as a request
 *  error. unsupported_os: Claude and Codex cannot run on Windows (backend chat/providers.py). */
export type ProviderProblemCode = "unsupported_os";

export const providerProblemText: Record<ProviderProblemCode, string> = {
  unsupported_os: "Bu sağlayıcı Windows'ta henüz desteklenmiyor. Yerel (Ollama) sohbeti kullanabilirsiniz.",
};

export function isErrorCode(code: string): code is ErrorCode {
  return Object.prototype.hasOwnProperty.call(errorText, code);
}

function isProviderProblem(code: string): code is ProviderProblemCode {
  return Object.prototype.hasOwnProperty.call(providerProblemText, code);
}

export function errorMessage(code: string): string {
  if (isErrorCode(code)) return errorText[code];
  if (isProviderProblem(code)) return providerProblemText[code];
  if (code === "network_error") return clientErrorText.network_error;
  return clientErrorText.unknown_error;
}

// ---------------------------------------------------------------- vocabularies

export const statusLabel: Record<DocStatus, string> = {
  queued: "Sırada",
  extracting: "Metin çıkarılıyor",
  masking: "Maskeleniyor",
  auditing: "Denetleniyor",
  needs_review: "İncelemede",
  approved: "Onaylı",
  rejected: "Reddedildi",
  failed: "Hata",
};

export const statusDetail: Record<"queued" | "extracting" | "masking" | "auditing", string> = {
  queued: "Belge sırada. Birazdan işlenmeye başlayacak.",
  extracting: "Sayfalardaki metin ve tablolar okunuyor.",
  masking: "Kişisel veriler bulunuyor ve maskeleniyor.",
  auditing: "Yerel model maskeli metni kalıntılara karşı denetliyor.",
};

export const modeText: Record<Mode, { label: string; consequence: string }> = {
  mapping: {
    label: "Takma ad",
    consequence: "Orijinal metin bu bilgisayarda saklanır. Maskeleri geri alabilir, sayfa görünümünü kullanabilirsiniz.",
  },
  destructive: {
    label: "Geri döndürülemez",
    consequence: "Orijinal metin saklanmaz. En güçlü gizlilik budur; maskeler sonradan kaldırılamaz.",
  },
};

export const kindLabel: Record<FileKind, string> = { pdf: "PDF", docx: "DOCX", xlsx: "XLSX" };

const families: Record<string, string> = {
  PERSON: "Kişi",
  ORG: "Kurum",
  LOCATION: "Konum",
  ADDRESS: "Adres",
  TCKN: "TCKN",
  VKN: "Vergi no",
  IBAN: "IBAN",
  PHONE: "Telefon",
  EMAIL: "E-posta",
  CREDIT_CARD: "Kart",
  CARD: "Kart",
  ACCOUNT: "Hesap no",
  PASSPORT: "Pasaport",
  SSN: "Sosyal güvenlik no",
  DL: "Ehliyet",
  USERNAME: "Kullanıcı adı",
  DISABILITY: "Engellilik",
  NRP: "Grup",
  SENSITIVE: "Hassas",
  DATE: "Tarih",
  PLATE: "Plaka",
  URL: "Bağlantı",
  IP: "IP adresi",
  SECRET: "Gizli anahtar",
  SALARY: "Maaş",
  HEALTH: "Sağlık",
  ID: "Kimlik no",
  CUSTOM: "Özel",
};

/** Families offered when masking a selection by hand. */
export const selectableFamilies = ["PERSON", "ORG", "LOCATION", "ADDRESS", "EMAIL", "PHONE", "TCKN", "IBAN", "DATE", "CUSTOM"];

export function familyLabel(family: string | null): string {
  if (!family) return "Diğer";
  return families[family] ?? family;
}

export const providerDestination: Record<ProviderId, string> = {
  ollama: "Bu bilgisayar",
  claude_cli: "Anthropic (Claude)",
  codex_cli: "OpenAI (Codex)",
};

export const providerWhere: Record<ProviderId, string> = {
  ollama: "Bu bilgisayarda çalışır. Metin dışarı çıkmaz.",
  claude_cli: "Maskeli metin Anthropic'e gider.",
  codex_cli: "Maskeli metin OpenAI'ye gider.",
};

// ---------------------------------------------------------------- screens

export const tr = {
  app: {
    name: "Screenwall",
    skipLink: "İçeriğe geç",
    openLibrary: "Belgeleri aç",
    closeLibrary: "Belgeleri kapat",
    settings: "Ayarlar",
    localFooter: "Her şey bu bilgisayarda işlenir",
    mockBadge: "Örnek veri",
    mockShort: "Kurgusal belgeler",
    mockHint: "Bu oturum kurgusal örnek verilerle çalışıyor; sunucuya bağlanmıyor.",
    crashTitle: "Bir şeyler ters gitti",
    crashBody: "Bu ekran beklenmedik bir hatayla karşılaştı. Sayfayı yenilemek çoğu zaman sorunu çözer.",
    reload: "Sayfayı yenile",
    notFoundTitle: "Sayfa bulunamadı",
    notFoundBody: "Aradığınız adres bu uygulamada yok.",
    backHome: "Belgelere dön",
  },
  common: {
    close: "Kapat",
    cancel: "Vazgeç",
    retry: "Tekrar dene",
    loading: "Yükleniyor",
    copy: "Kopyala",
    copied: "Kopyalandı",
    copyFailed: "Kopyalanamadı. Metni elle seçip kopyalayın.",
    copyCommand: (command: string) => `${command} komutunu kopyala`,
    saved: "Kaydedildi",
    notifications: "Bildirimler",
    dismiss: "Bildirimi kapat",
  },
  library: {
    title: "Belgeler",
    upload: "Yükle",
    uploadHint: "PDF, Word ya da Excel dosyası yükleyin",
    modeLabel: "Yükleme modu",
    search: "Belgelerde ara",
    filtersLabel: "Duruma göre süz",
    filters: { all: "Tümü", review: "İncelemede", approved: "Onaylı", processing: "İşleniyor", failed: "Hata" },
    listLabel: "Belge listesi",
    empty: "Henüz belge yok.",
    noMatch: "Bu aramayla eşleşen belge yok.",
    clearFilters: "Süzgeçleri temizle",
    loadError: "Belgeler yüklenemedi.",
    pending: (n: number) => `${n} karar bekliyor`,
    readyToApprove: "Onaya hazır",
    approvedMeta: (n: number) => `${n} alan maskeli`,
    rejectedMeta: "Reddedildi",
    failedMeta: "İşlenemedi",
    progress: "İşlem ilerlemesi",
  },
  upload: {
    inputLabel: "Yüklenecek dosyaları seçin",
    dropTitle: "Bırakın, bu bilgisayarda işlenecek",
    dropBody: (mode: string) => `${mode} modunda maskelenir. Dosyalar hiçbir yere gönderilmez.`,
    queueTitle: "Yüklemeler",
    sending: "Gönderiliyor",
    ready: "İncelemeye hazır",
    approved: "Onaylandı",
    failed: "Yüklenemedi",
    open: "Aç",
    dismiss: (name: string) => `${name} bildirimini kapat`,
    readyToast: (name: string) => `${name} incelemeye hazır`,
  },
  home: {
    emptyTitle: "İlk belgenizi ekleyin",
    emptyBody:
      "PDF, Word ya da Excel dosyasını bu pencereye sürükleyin. Kişisel veriler bu bilgisayarda bulunur ve maskelenir; dosyanız hiçbir yere gönderilmez.",
    emptyAction: "Belge ekle",
    emptyHint: "Dosyaları pencerenin herhangi bir yerine de bırakabilirsiniz.",
    features: [
      { title: "Yerel işleme", body: "Metin çıkarma, maskeleme ve denetim bu bilgisayarda yapılır." },
      { title: "Her maskenin nedeni", body: "Her maskeli alanın yanında neden maskelendiği yazar." },
      { title: "Onaydan sonra kullanım", body: "Onaylanan belgeyi indirir ya da onunla sohbet edersiniz." },
    ],
    selectTitle: "Bir belge seçin",
    selectBody: "Soldaki listeden bir belge açın ya da yeni bir belge ekleyin.",
    openFirstReview: "Sıradaki incelemeyi aç",
  },
  review: {
    regionLabel: "İnceleme alanı",
    approve: "Onayla",
    blocked: (n: number) => `${n} karar bekliyor`,
    ready: "Onaya hazır",
    download: "İndir",
    downloading: "Hazırlanıyor",
    chat: "Sohbet",
    reject: "Reddet",
    more: "Diğer işlemler",
    delete: "Sil",
    readOnly: "Bu belgede kararlar değiştirilemez.",
    approveDialog: {
      title: "Belgeyi onayla",
      body: "Onaylanan belge indirilebilir ve sohbette kullanılabilir. Onaydan sonra bir maskeyi değiştirirseniz belge yeniden onay bekler.",
      checking: "Yerel denetçi belgenin son hâlini kontrol ediyor. Bu birkaç saniye sürebilir.",
      confirm: "Onayla",
    },
    rejectDialog: {
      title: "Belgeyi reddet",
      body: "Reddedilen belge indirilemez ve sohbette kullanılamaz.",
      reasonLabel: "Neden (isteğe bağlı)",
      reasonPlaceholder: "Örneğin: yanlış dosya yüklendi",
      confirm: "Reddet",
    },
    deleteDialog: {
      title: "Belgeyi sil",
      body: (name: string) =>
        `${name} ve bu belge için verilen tüm kararlar bu bilgisayardan kaldırılır. Bu işlem geri alınamaz.`,
      confirm: "Sil",
    },
    toast: {
      approved: "Belge onaylandı",
      rejected: "Belge reddedildi",
      deleted: "Belge silindi",
      staleReloaded: "Belge bu arada değişti; güncel hâli yüklendi.",
      auditNotClean: "Denetim yeni bir uyarı verdi; gözden geçirip yeniden onaylayın.",
    },
    panes: {
      original: "Orijinal",
      masked: "Maskeli",
      originalHint: "Yalnız bu bilgisayarda",
      maskedHint: "İndirilen dosyaya ve modele giden metin",
      switchLabel: "Görünen metin",
      viewLabel: "Orijinal görünüm",
      text: "Metin",
      page: "Sayfa",
    },
    destructive: {
      title: "Orijinal saklanmadı",
      body: "Bu belge geri döndürülemez modda işlendi. Orijinal metin hiçbir yere yazılmadı; burada yalnız maskeli sürüm görünür.",
    },
    page: {
      label: (n: number) => `Sayfa ${n}`,
      of: (n: number, total: number) => `${n} / ${total}`,
      prev: "Önceki sayfa",
      next: "Sonraki sayfa",
      zoomIn: "Yakınlaştır",
      zoomOut: "Uzaklaştır",
      zoom: (n: number) => `%${n}`,
      zoomLabel: "Yakınlaştırma",
      imageAlt: (n: number) => `Orijinal belge, sayfa ${n}`,
      marksLabel: "Sayfa üzerindeki işaretler",
      noText: "Bu sayfadan metin çıkarılamadı; sayfayı elle kontrol edin.",
      imageError: "Sayfa görüntüsü yüklenemedi.",
    },
    table: (n: number) => `Tablo ${n}`,
    tableHint: " · her hücrede üstte orijinal, altında maskeli değer",
    loadError: "İnceleme verisi alınamadı.",
    notFoundTitle: "Belge bulunamadı",
    notFoundBody: "Belge silinmiş ya da bağlantı hatalı olabilir.",
    processingNote: "Bu işlem tamamen bu bilgisayarda yapılır. Hazır olunca belge kendiliğinden açılır.",
    failedTitle: "Belge işlenemedi",
    rejectedTitle: "Belge reddedildi",
    rejectedBody: "Bu belge indirilemez ve sohbette kullanılamaz. Yeniden işlemek için dosyayı tekrar yükleyin.",
    reasonsTitle: "Dikkat edilmesi gerekenler",
  },
  marks: {
    masked: "maskelendi",
    added: "sizin maskelediğiniz",
    kept: "açık bırakıldı",
    suggestion: "öneri, karar bekliyor",
    finding: "denetim bulgusu, karar bekliyor",
    aria: (text: string, family: string, state: string) => `${text}, ${family}, ${state}`,
  },
  steps: {
    label: "İşlem adımları",
    names: ["Yüklendi", "Çıkarıldı", "Maskelendi", "Denetlendi", "Onay"],
    state: {
      done: "tamamlandı",
      current: "şu anki adım",
      upcoming: "bekliyor",
      failed: "başarısız",
      rejected: "reddedildi",
    },
  },
  findings: {
    tab: "Bulgular",
    panelLabel: "Bulgular ve sohbet",
    pendingTitle: "Karar bekleyen",
    pendingEmpty: "Karar bekleyen öğe yok. Belge onaya hazır.",
    maskedTitle: "Maskelenenler",
    maskedEmpty: "Maskelenmiş alan yok.",
    keptTitle: "Açık bırakılanlar",
    keptEmpty: "Açık bırakılan alan yok.",
    suggestion: "Öneri",
    finding: "Denetim bulgusu",
    occurrences: (n: number) => `${n} geçiş`,
    mask: "Maskele",
    keep: "Açık bırak",
    allOccurrences: (n: number) => `Tüm geçişler (${n})`,
    unmask: "Maskeyi kaldır",
    scopeLabel: "Kapsam",
    scopeOccurrence: "Bu geçiş",
    scopeDocument: "Belgedeki tüm geçişler",
    neverMask: "Hiçbir belgede maskeleme",
    neverMaskHint: "Terim genel listeye eklenir ve sonraki belgelerde de açık kalır.",
    remask: "Yeniden maskele",
    addedByYou: "Sizin eklediğiniz",
    groupCount: (n: number) => `${n}`,
    auditFooter: (model: string) => `Denetim: ${model} · yerel`,
    auditOffline: "Denetim modeline şu anda ulaşılamıyor",
    destructiveNoUnmask: "Geri döndürülemez modda maske kaldırılamaz.",
  },
  selection: {
    label: "Seçimi maskele",
    mask: "Maskele",
    family: "Tür",
    allOccurrences: "Tüm geçişler",
    overlap: "Seçim maskeli bir alanla çakışıyor",
    close: "Seçimi kapat",
  },
  keys: {
    footerLabel: "Klavye kısayolları",
    footer: [
      { keys: ["J", "K"], text: "sonraki/önceki" },
      { keys: ["M"], text: "maskele" },
      { keys: ["U"], text: "maskeyi kaldır" },
      { keys: ["A"], text: "onayla" },
      { keys: ["?"], text: "tümü" },
    ],
    dialogTitle: "Klavye kısayolları",
    dialogBody: "Kısayollar yazı alanlarında çalışmaz.",
    list: [
      { keys: ["J"], text: "Sonraki öğeye geç" },
      { keys: ["K"], text: "Önceki öğeye geç" },
      { keys: ["M"], text: "Seçili metni ya da öneriyi maskele" },
      { keys: ["U"], text: "Seçili maskeyi kaldır ya da öneriyi açık bırak" },
      { keys: ["A"], text: "Onayla" },
      { keys: ["?"], text: "Bu listeyi göster" },
      { keys: ["Esc"], text: "Pencereyi ya da seçimi kapat" },
    ],
    blocked: (n: number) => `Onaydan önce ${n} karar bekliyor`,
  },
  chat: {
    tab: "Sohbet",
    lockedTitle: "Sohbet onaydan sonra açılır",
    lockedBody: "Onaylanmamış belgeler hiçbir sağlayıcıya gönderilmez. Önce incelemeyi tamamlayın.",
    providerLabel: "Sağlayıcı",
    changeProvider: "Değiştir",
    changeProviderLabel: "Sağlayıcıyı değiştir",
    providersLoading: "Sağlayıcılar denetleniyor",
    providersError: "Sağlayıcı durumu alınamadı.",
    loginCommand: "Giriş komutu",
    scopeLabel: "Kapsam",
    scopeCurrent: "Bu belge",
    scopeAdd: "Belge ekle",
    scopeHint: "Yalnız onaylı belgeler eklenebilir.",
    scopeNone: "Eklenebilecek başka onaylı belge yok.",
    removeDoc: (name: string) => `${name} kapsamdan çıkar`,
    inputLabel: "Soru",
    placeholder: "Belge hakkında bir soru yazın",
    send: "Gönder",
    showPayload: "Gönderilecek metni göster",
    waiting: "Yanıt bekleniyor",
    elapsed: (s: number) => `${s} sn`,
    emptyTitle: "Belgeye soru sorun",
    emptyBody: "Yanıtlar yalnız maskeli metinden üretilir ve kaynaklarıyla birlikte gelir.",
    sources: "Kaynaklar",
    citation: (id: string, label: string) => `Kaynak ${id}: ${label}`,
    meta: (provider: string, secs: string) => `${provider} · ${secs} sn`,
    you: "Siz",
    assistant: "Yanıt",
    messagesLabel: "Sohbet mesajları",
    newChat: "Yeni sohbet",
    consent: {
      title: "Gönderimi onaylayın",
      inspectTitle: "Gönderilecek metin",
      destination: "Hedef",
      cloudBody: (dest: string) =>
        `Bu metin bu bilgisayardan çıkar ve ${dest} tarafından işlenir. Orijinal metin ve eşleme tablosu gönderilmez.`,
      localBody: "Bu metin yalnız bu bilgisayardaki modele verilir.",
      sources: "Kaynaklar",
      payload: "Gönderilecek metin",
      chars: (n: string) => `${n} karakter`,
      checkbox: (dest: string) => `Bu metnin ${dest} tarafına gönderileceğini anladım`,
      send: "Gönder",
    },
  },
  settings: {
    title: "Ayarlar",
    loadError: "Ayarlar alınamadı.",
    modeTitle: "Varsayılan mod",
    modeHint: "Yeni yüklemeler bu modla işlenir.",
    chatTitle: "Sohbet",
    defaultProvider: "Varsayılan sağlayıcı",
    providersTitle: "Sağlayıcı durumu",
    provider: {
      ready: "Hazır",
      notReady: "Kullanılamıyor",
      local: "Yerel",
      cloud: "Bulut",
      installed: "Kurulu",
      notInstalled: "Kurulu değil",
      compatible: "Uyumlu",
      incompatible: "Güncelleme gerekli",
      loggedIn: "Giriş yapıldı",
      loggedOut: "Giriş yapılmadı",
      version: (v: string) => `Sürüm ${v}`,
      model: (m: string) => `Model ${m}`,
    },
    termsTitle: "Terim listeleri",
    termsHint: "Bu listeler tüm belgelerde geçerlidir. Varsayılan olarak boştur.",
    alwaysMask: "Her zaman maskele",
    neverMask: "Asla maskeleme",
    addTerm: "Ekle",
    termPlaceholder: "Terim yazın",
    addTermLabel: (list: string) => `${list} listesine terim ekle`,
    removeTerm: (term: string) => `${term} terimini kaldır`,
    emptyList: "Liste boş",
    duplicate: "Bu terim zaten listede.",
    themeTitle: "Görünüm",
    themeLabel: "Tema",
    theme: { system: "Sistem", light: "Açık", dark: "Koyu" },
    save: "Kaydet",
    saved: "Ayarlar kaydedildi",
  },
} as const;
