// Fictional documents, people and companies. Any resemblance to real ones is accidental.
import { buildDoc, type DocDef, type UnitDef } from "./build";
import type { MockDoc } from "./types";

const minutes = (n: number) => Date.now() - n * 60_000;

const deck: DocDef = {
  id: "doc-sunum",
  filename: "Yatırımcı Sunumu 2026-Ç2.pdf",
  kind: "pdf",
  mode: "mapping",
  status: "needs_review",
  createdAt: minutes(42),
  pages: { count: 3, style: "slide" },
  units: [
    { page: 1, kind: "heading", location: "Sayfa 1", text: "[[m:ORG#kuzey:KUZEY ENERJİ|Kuzey Enerji Dağıtım A.Ş. adından yayıldı]] — 2026 İkinci Çeyrek Sonuçları" },
    { page: 1, location: "Sayfa 1", text: "Yatırımcı sunumu · 12 Ağustos 2026" },
    { page: 1, location: "Sayfa 1", text: "[[m:ORG#kuzey:Kuzey Enerji Dağıtım A.Ş.|Yasal ek: A.Ş.]] Yönetim Kurulu adına [[m:PERSON:Murat Aksoy|Unvan bağlamı ve isim sözlüğü]]" },
    { page: 2, kind: "heading", location: "Sayfa 2", text: "Finansal özet" },
    { page: 2, location: "Sayfa 2", text: "Yatırım Harcamaları 1.240 milyon TL'ye ulaştı; FAVÖK marjı %31,4 oldu." },
    { page: 2, location: "Sayfa 2", text: "Net borç / FAVÖK oranı 1,6x seviyesinde kaldı." },
    { page: 2, location: "Sayfa 2", text: "[[s:ORG:Kuzey Grubu|Kurum olabilir: yasal ek yok, tek başına marka adı]] abone sayısı 2,1 milyona çıktı." },
    { page: 2, location: "Sayfa 2", text: "[[s:ORG:KuzeyNet|Kurum olabilir: marka adı, kanıt yetersiz]] fiber kapsama alanı %18 genişledi." },
    { page: 3, kind: "heading", location: "Sayfa 3", text: "Yatırımcı ilişkileri" },
    { page: 3, location: "Sayfa 3", text: "[[s:ORG:Kuzey Grubu|Kurum olabilir: yasal ek yok, tek başına marka adı]] 2027 yılında 310 milyon TL ek yatırım planlıyor." },
    { page: 3, location: "Sayfa 3", text: "İletişim: [[m:PERSON:Selin Özdemir|Alan etiketi ve isim sözlüğü]] · [[m:EMAIL:selin.ozdemir@kuzeyenerji.com.tr|E-posta biçimi]] · [[m:PHONE:0212 555 01 23|Sabit hat biçimi]]" },
    { page: 3, location: "Sayfa 3", text: "Hazırlayan: [[f:PERSON:S. Özdemir|Denetim: baş harf ve soyadı bir kişiyi gösterebilir]], Kurumsal Finansman" },
  ],
};

const lease: DocDef = {
  id: "doc-kira",
  filename: "Kira Sözleşmesi.docx",
  kind: "docx",
  mode: "mapping",
  status: "approved",
  createdAt: minutes(60 * 26),
  units: [
    { kind: "heading", location: "Başlık", text: "Konut kira sözleşmesi" },
    { location: "Madde 1", text: "Kiraya veren: [[m:PERSON:Ayşe Demirtaş|Alan etiketi ve isim sözlüğü]], T.C. Kimlik No: [[m:TCKN:18462957350|TCKN doğrulandı]]" },
    { location: "Madde 1", text: "Kiracı: [[m:PERSON:Emre Yıldırım|Alan etiketi ve isim sözlüğü]], [[m:ADDRESS:Moda Cad. No: 14 D: 3, Kadıköy / İstanbul|Adres işareti ve kapı numarası]]" },
    { location: "Madde 2", text: "Aylık kira bedeli 18.500 TL olup her ayın 5'inde [[m:IBAN:TR12 0006 4000 0011 2345 6789 01|IBAN biçimi]] numaralı hesaba ödenir." },
    { location: "Madde 3", text: "Sözleşme 1 Eylül 2026 tarihinde başlar ve bir yıl sürer. Taraflardan biri bitişten 30 gün önce yazılı bildirimde bulunmazsa sözleşme aynı koşullarla uzar." },
    { location: "Madde 4", text: "Kiracı iletişim: [[m:PHONE:0532 418 27 90|Cep telefonu biçimi]] · [[m:EMAIL:emre.yildirim@ornekposta.com|E-posta biçimi]]" },
    { location: "Madde 5", text: "Depozito olarak iki aylık kira bedeli, [[m:PERSON:Ayşe Demirtaş|Kanıtlı kişiden yayıldı]] tarafından teslim alınmıştır." },
  ],
};

const staffRows = [
  ["Ad Soyad", "Departman", "Telefon", "E-posta", "Yönetici"],
  ["[[m:PERSON:Deniz Akalın|Sütun başlığı: Ad Soyad]]", "Finans", "[[m:PHONE:0532 111 22 33|Cep telefonu biçimi]]", "[[m:EMAIL:deniz.akalin@kuzeyenerji.com.tr|E-posta biçimi]]", "[[s:PERSON:M. Aksoy|Kişi olabilir: baş harf ve soyadı]]"],
  ["[[m:PERSON:Burak Tan|Sütun başlığı: Ad Soyad]]", "Operasyon", "[[m:PHONE:0544 222 33 44|Cep telefonu biçimi]]", "[[m:EMAIL:burak.tan@kuzeyenerji.com.tr|E-posta biçimi]]", "[[s:PERSON:M. Aksoy|Kişi olabilir: baş harf ve soyadı]]"],
  ["[[m:PERSON:Elif Karaca|Sütun başlığı: Ad Soyad]]", "İnsan Kaynakları", "[[m:PHONE:0555 333 44 55|Cep telefonu biçimi]]", "[[m:EMAIL:elif.karaca@kuzeyenerji.com.tr|E-posta biçimi]]", "Genel Müdürlük"],
  ["[[m:PERSON:Can Ertürk|Sütun başlığı: Ad Soyad]]", "Bilgi Teknolojileri", "[[m:PHONE:0530 444 55 66|Cep telefonu biçimi]]", "[[m:EMAIL:can.erturk@kuzeyenerji.com.tr|E-posta biçimi]]", "Genel Müdürlük"],
];
const COLUMNS = "ABCDE";

const staff: DocDef = {
  id: "doc-personel",
  filename: "Personel Listesi.xlsx",
  kind: "xlsx",
  mode: "mapping",
  status: "needs_review",
  createdAt: minutes(95),
  units: staffRows.flatMap((row, r) =>
    row.map((text, c): UnitDef => ({ text, location: `Personel · ${COLUMNS[c]}${r + 1}`, table: { id: "t1", row: r, col: c } })),
  ),
};

const report: DocDef = {
  id: "doc-hasta",
  filename: "Hasta Raporu.pdf",
  kind: "pdf",
  mode: "mapping",
  status: "needs_review",
  createdAt: minutes(12),
  pages: { count: 2, style: "a4", unreadable: [2] },
  reasons: [{ code: "ocr_unreadable_page", text: "Bir sayfa okunamadı; o sayfa elle kontrol edilmeli." }],
  units: [
    { page: 1, kind: "heading", location: "Sayfa 1", text: "Epikriz raporu" },
    { page: 1, location: "Sayfa 1", text: "Hasta: [[m:PERSON:Selin Arıkan|Hasta alanı ve isim sözlüğü]] · T.C. Kimlik No: [[m:TCKN:32571486938|TCKN doğrulandı]]" },
    { page: 1, location: "Sayfa 1", text: "Doğum tarihi: [[m:DATE:14.03.1987|Doğum tarihi bağlamı]] · Protokol no: 2026-118" },
    { page: 1, location: "Sayfa 1", text: "Tanı: akut bronşit. Hasta [[m:HEALTH:astım öyküsü|Özel nitelikli sağlık verisi]] nedeniyle takip altında." },
    { page: 1, location: "Sayfa 1", text: "Sorumlu hekim: Dr. [[m:PERSON:Kerem Yalçın|Unvan bağlamı ve isim sözlüğü]]" },
    { page: 1, location: "Sayfa 1", text: "Kontrol muayenesi iki hafta sonra önerildi." },
  ],
};

const receipt: DocDef = {
  id: "doc-dekont",
  filename: "Banka Dekontu.pdf",
  kind: "pdf",
  mode: "destructive",
  status: "approved",
  createdAt: minutes(60 * 50),
  units: [
    { kind: "heading", location: "Sayfa 1", page: 1, text: "Havale dekontu" },
    { location: "Sayfa 1", page: 1, text: "Gönderen: [[m:PERSON:Tolga Şen|Alan etiketi ve isim sözlüğü]]" },
    { location: "Sayfa 1", page: 1, text: "Alıcı IBAN: [[m:IBAN:TR33 0001 0017 4523 8765 4321 07|IBAN biçimi]]" },
    { location: "Sayfa 1", page: 1, text: "Açıklama: Eylül 2026 kira ödemesi" },
    { location: "Sayfa 1", page: 1, text: "Tutar: 18.500,00 TL · İşlem tarihi: 05.09.2026" },
  ],
};

const minutesDoc: DocDef = {
  id: "doc-tutanak",
  filename: "Eski Tutanak.docx",
  kind: "docx",
  mode: "mapping",
  status: "failed",
  createdAt: minutes(60 * 75),
  reasons: [{ code: "extraction_failed", text: "Dosya açılamadı; bozuk ya da parola korumalı olabilir." }],
  units: [],
};

export function createFixtures(): MockDoc[] {
  return [deck, report, staff, lease, receipt, minutesDoc].map(buildDoc);
}
