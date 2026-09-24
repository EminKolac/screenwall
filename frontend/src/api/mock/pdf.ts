// A minimal single-page PDF of the masked text, so "İndir" produces a real file in mock mode.
// Helvetica cannot draw every Turkish letter, so the mock transliterates to ASCII.
const MAP: Record<string, string> = { ç: "c", Ç: "C", ğ: "g", Ğ: "G", ı: "i", İ: "I", ö: "o", Ö: "O", ş: "s", Ş: "S", ü: "u", Ü: "U", â: "a", î: "i", û: "u" };

const ascii = (text: string) =>
  Array.from(text)
    .map((ch) => MAP[ch] ?? ch)
    .join("")
    .replace(/[^\x20-\x7e]/g, "-");

const escape = (text: string) => text.replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");

function wrap(paragraph: string, width = 88): string[] {
  const words = ascii(paragraph).split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let line = "";
  for (const word of words) {
    if (line && line.length + word.length + 1 > width) {
      lines.push(line);
      line = word;
    } else line = line ? `${line} ${word}` : word;
  }
  if (line) lines.push(line);
  return lines;
}

export function buildPdf(title: string, paragraphs: string[]): Blob {
  const lines = [ascii(title), "", ...paragraphs.flatMap((p) => [...wrap(p), ""])].slice(0, 52);
  const text = lines.map((l) => `(${escape(l)}) Tj T*`).join("\n");
  const stream = `BT\n/F1 11 Tf\n15 TL\n56 780 Td\n${text}\nET`;
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
  ];
  let body = "%PDF-1.4\n";
  const offsets: number[] = [];
  objects.forEach((object, i) => {
    offsets.push(body.length);
    body += `${i + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xref = body.length;
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  body += offsets.map((o) => `${String(o).padStart(10, "0")} 00000 n \n`).join("");
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return new Blob([body], { type: "application/pdf" });
}
