// What an uploaded file "contains" in mock mode: a small meeting note with two open suggestions.
import type { FileKind, Mode } from "../contract";
import { buildDoc, type UnitDef } from "./build";
import type { MockDoc } from "./types";

const PROCESSING_MS = 4000;
let counter = 0;

const note: Array<Omit<UnitDef, "location" | "page">> = [
  { kind: "heading", text: "Toplantı tutanağı" },
  { text: "Tarih: 18 Eylül 2026 · Yer: Genel Müdürlük toplantı salonu" },
  { text: "Katılımcılar: [[m:PERSON:Deniz Aydın|Alan etiketi ve isim sözlüğü]], [[m:PERSON:Ece Kurt|Liste bağlamı ve isim sözlüğü]] ve [[m:ORG:Atlas Lojistik A.Ş.|Yasal ek: A.Ş.]] temsilcileri." },
  { text: "[[s:ORG:Atlas Grubu|Kurum olabilir: yasal ek yok]] ile yürütülen tedarik görüşmeleri olumlu ilerliyor; ikinci tur ekim ayında yapılacak." },
  { text: "Proje ekibi yeni dönemde [[s:LOCATION:Mavi Ofis|Yer ya da kurum adı olabilir: kanıt yetersiz]] çalışma alanına taşınacak." },
  { text: "İletişim: [[m:PHONE:0216 444 18 20|Sabit hat biçimi]] · [[m:EMAIL:deniz.aydin@atlaslojistik.com.tr|E-posta biçimi]]" },
];

const sheet = [
  ["Ad Soyad", "Görev", "Telefon", "Not"],
  ["[[m:PERSON:Deniz Aydın|Sütun başlığı: Ad Soyad]]", "Satın alma", "[[m:PHONE:0532 610 20 30|Cep telefonu biçimi]]", "[[s:ORG:Atlas Grubu|Kurum olabilir: yasal ek yok]] ile görüşülecek"],
  ["[[m:PERSON:Ece Kurt|Sütun başlığı: Ad Soyad]]", "Lojistik", "[[m:PHONE:0544 710 20 30|Cep telefonu biçimi]]", "[[s:LOCATION:Mavi Ofis|Yer ya da kurum adı olabilir: kanıt yetersiz]] taşınması"],
];

export function kindOf(filename: string): FileKind | null {
  const ext = /\.([a-z]+)$/i.exec(filename)?.[1]?.toLowerCase();
  return ext === "pdf" || ext === "docx" || ext === "xlsx" ? ext : null;
}

export function createUploadedDoc(filename: string, kind: FileKind, mode: Mode, now: number): MockDoc {
  counter += 1;
  const id = `doc-yeni-${now.toString(36)}-${counter}`;
  const broken = /bozuk/i.test(filename);
  const units: UnitDef[] =
    kind === "xlsx"
      ? sheet.flatMap((row, r) => row.map((text, c) => ({ text, location: `Sayfa1 · ${"ABCD"[c]}${r + 1}`, table: { id: "t1", row: r, col: c } })))
      : note.map((unit) => ({ ...unit, location: kind === "pdf" ? "Sayfa 1" : "Bölüm 1", page: kind === "pdf" ? 1 : undefined }));
  return buildDoc({
    id,
    filename,
    kind,
    mode,
    status: "queued",
    createdAt: now,
    units: broken ? [] : units,
    pages: kind === "pdf" && mode === "mapping" && !broken ? { count: 1, style: "a4" } : undefined,
    reasons: broken ? [{ code: "extraction_failed", text: "Dosya açılamadı; bozuk ya da parola korumalı olabilir." }] : [],
    processing: { start: now, duration: PROCESSING_MS, outcome: broken ? "failed" : "needs_review" },
  });
}
