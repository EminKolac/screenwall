"""Build a PDF carrier: page 1 has a native text layer with canaries; page 2 is an image-only page
(canaries rendered to a raster with NO text layer) that forces the extractor's OCR path. Returns
(bytes, filename, placements)."""
from __future__ import annotations

import fitz  # PyMuPDF

from app.export.render_pdf import _FONTS_DIR
from evaluation.bist30.canary import catalog_by_id
from evaluation.bist30.harness import Markers, Placement, make_placement

_FONT = str(_FONTS_DIR / "DejaVuSans.ttf")  # embeds Turkish glyphs so page-1 text is faithful
_TEXT_CIDS = ("prs_tr", "prs_en", "gsm_tr", "eml", "adr", "iban", "card", "tckn", "acct",
              "ip", "secret", "url_tok", "plate")
_OCR_CIDS = ("prs_en", "eml", "iban", "tckn", "card")  # ASCII-friendly → clean render for OCR


def build_pdf(mk: Markers) -> tuple[bytes, str, list[Placement]]:
    cat = catalog_by_id()
    placements: list[Placement] = []
    doc = fitz.open()

    # Page 1 — native text layer.
    p1 = doc.new_page()
    y = 60.0
    for cid in _TEXT_CIDS:
        pl = make_placement(mk, cat[cid], "pdf", "text")
        p1.insert_text((50, y), pl.carrier_text(), fontsize=11, fontfile=_FONT, fontname="djv")
        placements.append(pl)
        y += 24

    # Page 2 — render canaries to an image, then place that image full-page (no text layer → OCR).
    tmp = fitz.open()
    tp = tmp.new_page()
    yy = 70.0
    ocr_pls: list[Placement] = []
    for cid in _OCR_CIDS:
        pl = make_placement(mk, cat[cid], "pdf", "ocr")
        tp.insert_text((60, yy), pl.carrier_text(), fontsize=16, fontfile=_FONT, fontname="djv")
        ocr_pls.append(pl)
        yy += 40
    png = tp.get_pixmap(dpi=200).tobytes("png")
    tmp.close()
    p2 = doc.new_page()
    p2.insert_image(p2.rect, stream=png)
    placements.extend(ocr_pls)

    fp = make_placement(mk, cat["prs_tr"], "pdf", "filename")
    placements.append(fp)
    filename = f"Yatirimci Sunumu {fp.value} {fp.marker}.pdf"

    out = doc.tobytes()
    doc.close()
    return out, filename, placements
