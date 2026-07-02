"""Generate a clean PDF from the APPROVED anonymized content (storage layer 3) ONLY.

The download path never re-serializes the original file and never touches the placeholder↔original
mapping — it renders the anonymized `ExtractedContent` (blocks that already carry `<TYPE_n>`
placeholders) into a fresh PDF. So *what was audited is exactly what is shipped*: none of the
original document's un-audited channels (image pixels, DOCX headers/footers, XLSX comments,
metadata, formula source, spelling variants) can leak into the output.

Rendering uses PyMuPDF's `Story` (HTML→PDF, auto-paginated — already a dependency, no new one). A
bundled DejaVu Sans font is embedded via `@font-face` so Turkish glyphs (ç ğ ı İ ö ş ü) always
render regardless of host fonts.
"""
from __future__ import annotations

import html
import io
from pathlib import Path

import fitz  # PyMuPDF

from app.extraction.base import Block, BlockType, ExtractedContent

_FONTS_DIR = Path(__file__).parent / "fonts"
_MARGIN = 36  # 0.5 inch

# `djv` is resolved from the bundled TTFs in _FONTS_DIR via the Story archive.
_CSS = """
@font-face { font-family: djv; src: url("DejaVuSans.ttf"); }
@font-face { font-family: djv; font-weight: bold; src: url("DejaVuSans-Bold.ttf"); }
* { font-family: djv; font-size: 10pt; color: #111; }
h1 { font-size: 15pt; font-weight: bold; margin: 0 0 12pt 0; }
h2 { font-size: 12pt; font-weight: bold; margin: 12pt 0 4pt 0; }
h3 { font-size: 10.5pt; font-weight: bold; margin: 10pt 0 3pt 0; color: #333; }
p  { margin: 0 0 5pt 0; line-height: 1.35; }
.label { font-weight: bold; color: #555; }
.muted { color: #666; font-style: italic; }
/* Table rows are wrapped text lines (not fixed cells) so a wide sheet or a very long cell
   never clips horizontally — every audited value shows, wrapping to the next line. */
.row {
  font-size: 9pt; margin: 0 0 2pt 0; line-height: 1.3;
  white-space: pre-wrap; word-break: break-word;
}
"""


def _label_for(location: str) -> str | None:
    """DOCX header/footer/comment blocks carry these in `location`; label them in the output."""
    loc = (location or "").lower()
    for key, lbl in (("header", "Header"), ("footer", "Footer"), ("comment", "Comment")):
        if loc.startswith(key):
            return lbl
    return None


def _paragraph_html(b: Block) -> str:
    text = html.escape(b.text)
    label = _label_for(b.location)
    return f'<p><span class="label">[{label}]</span> {text}</p>' if label else f"<p>{text}</p>"


def _table_html(b: Block) -> str:
    # The sheet name is emitted by the extractor as an anonymized heading block — never rendered
    # raw here (raw `b.sheet` would be un-audited PII). `table_lines()` groups only populated cells,
    # so a sparse sheet with a value in a far column can't blow up into a dense width-XFD grid.
    return "".join(f'<p class="row">{html.escape(line)}</p>' for line in b.table_lines())


def _content_html(anon: ExtractedContent) -> str:
    body: list[str] = ["<h1>Anonymized Document</h1>"]
    rendered = False
    for b in anon.blocks:
        if b.type == BlockType.table and b.cells:
            body.append(_table_html(b))
            rendered = True
        elif b.type == BlockType.heading and b.text:
            body.append(f"<h2>{html.escape(b.text)}</h2>")
            rendered = True
        elif b.text:
            body.append(_paragraph_html(b))
            rendered = True
    if not rendered:
        body.append('<p class="muted">(no extractable content)</p>')
    return "<html><body>" + "".join(body) + "</body></html>"


def render_content_pdf(anon: ExtractedContent) -> bytes:
    """Render approved anonymized content (layer 3) into a fresh PDF. Returns bytes only."""
    story = fitz.Story(
        html=_content_html(anon), user_css=_CSS, archive=fitz.Archive(str(_FONTS_DIR))
    )
    mediabox = fitz.paper_rect("a4")
    where = fitz.Rect(
        mediabox.x0 + _MARGIN, mediabox.y0 + _MARGIN, mediabox.x1 - _MARGIN, mediabox.y1 - _MARGIN
    )
    buf = io.BytesIO()
    writer = fitz.DocumentWriter(buf)
    more = 1
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()

    # Subset the embedded font so the download is ~68 KB instead of ~1.5 MB (full DejaVu).
    doc = fitz.open(stream=buf.getvalue(), filetype="pdf")
    try:
        try:
            doc.subset_fonts()
        except Exception:  # noqa: BLE001 — subsetting is an optimization; never fail the download
            pass
        return doc.tobytes(garbage=4, deflate=True)
    finally:
        doc.close()
