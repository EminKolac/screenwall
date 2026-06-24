"""Extraction interfaces + fail-closed upload validation.

Codex Phase-2 review incorporated:
- `ExtractionFailed` makes parser errors fail closed (H2).
- `validate_upload` adds OOXML package-part checks + zip-bomb guards (H3) and typed reject codes
  so the API can map 413/415/400 (L1).
- `Block.bbox` + sparse table rendering avoid dense-grid allocation on far-coordinate cells (M3)
  and give PDF geometry for later reconstruction (H4).
"""
from __future__ import annotations

import io
import zipfile
from enum import Enum

from pydantic import BaseModel, Field

from app.models.document import FileKind, Language


class UploadRejected(ValueError):
    """Upload failed type/size/safety validation. `code` ∈ {invalid, unsupported, too_large}."""

    def __init__(self, message: str, code: str = "invalid") -> None:
        super().__init__(message)
        self.code = code


class ExtractionFailed(Exception):
    """A supported file could not be parsed (corrupt/encrypted). Routes to human review.
    Message is sanitized — it never contains document content."""


class BlockType(str, Enum):
    paragraph = "paragraph"
    heading = "heading"
    table = "table"


class TableCell(BaseModel):
    row: int
    col: int
    text: str = ""
    address: str = ""  # e.g. "B4" for XLSX


class Block(BaseModel):
    block_id: str
    type: BlockType = BlockType.paragraph
    text: str = ""
    cells: list[TableCell] = Field(default_factory=list)
    page: int | None = None
    sheet: str | None = None
    bbox: list[float] | None = None     # PDF geometry [x0,y0,x1,y1] for reconstruction
    location: str = ""
    language: Language | None = None    # per-block detection (incl. mixed/unknown)

    _MAX_TABLE_CELLS = 50_000

    def table_lines(self) -> list[str]:
        """Render table text from sparse cells grouped by row — no dense matrix allocation."""
        by_row: dict[int, list[TableCell]] = {}
        for i, c in enumerate(self.cells):
            if i >= self._MAX_TABLE_CELLS:
                break
            by_row.setdefault(c.row, []).append(c)
        lines: list[str] = []
        for r in sorted(by_row):
            cells = sorted(by_row[r], key=lambda c: c.col)
            lines.append(" | ".join(c.text for c in cells))
        return lines

    @property
    def rows(self) -> list[list[str]]:
        by_row: dict[int, dict[int, str]] = {}
        for c in self.cells:
            by_row.setdefault(c.row, {})[c.col] = c.text
        out: list[list[str]] = []
        for r in sorted(by_row):
            cols = by_row[r]
            width = max(cols) + 1
            out.append([cols.get(i, "") for i in range(width)])
        return out


class ExtractedContent(BaseModel):
    kind: FileKind
    blocks: list[Block] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)  # sanitized (no content)

    @property
    def plain_text(self) -> str:
        parts: list[str] = []
        for b in self.blocks:
            if b.type == BlockType.table:
                parts.extend(b.table_lines())
            elif b.text:
                parts.append(b.text)
        return "\n".join(parts)


class Extractor:
    kind: FileKind
    def extract(self, data: bytes, filename: str) -> ExtractedContent:  # pragma: no cover
        raise NotImplementedError("Implemented per-format in Phase 2.")


_MAGIC = {FileKind.pdf: b"%PDF", FileKind.docx: b"PK\x03\x04", FileKind.xlsx: b"PK\x03\x04"}
_OOXML_REQUIRED = {FileKind.docx: "word/document.xml", FileKind.xlsx: "xl/workbook.xml"}
_MAX_ZIP_ENTRIES = 2_000
_MAX_UNCOMPRESSED = 500 * 1024 * 1024  # 500 MB
_MAX_COMPRESSION_RATIO = 200


def kind_from_filename(filename: str) -> FileKind | None:
    lower = filename.lower()
    for ext, kind in ((".pdf", FileKind.pdf), (".docx", FileKind.docx), (".xlsx", FileKind.xlsx)):
        if lower.endswith(ext):
            return kind
    return None


def _validate_ooxml(data: bytes, kind: FileKind) -> None:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise UploadRejected(f"not a valid {kind.value} (corrupt zip)", code="invalid") from e
    infos = zf.infolist()
    names = {i.filename for i in infos}
    if "[Content_Types].xml" not in names or _OOXML_REQUIRED[kind] not in names:
        raise UploadRejected(f"missing required {kind.value} package parts", code="invalid")
    if len(infos) > _MAX_ZIP_ENTRIES:
        raise UploadRejected("archive has too many entries", code="invalid")
    total = sum(i.file_size for i in infos)
    compressed = sum(i.compress_size for i in infos) or 1
    if total > _MAX_UNCOMPRESSED or (total / compressed) > _MAX_COMPRESSION_RATIO:
        raise UploadRejected("archive failed zip-bomb safety check", code="invalid")


def validate_upload(data: bytes, filename: str, max_bytes: int) -> FileKind:
    """Validate extension + magic + size + (for OOXML) package parts & zip-bomb safety.
    Fails closed with a typed `code`. Deeper parser failures surface as `ExtractionFailed`."""
    if len(data) == 0:
        raise UploadRejected("empty file", code="invalid")
    if len(data) > max_bytes:
        raise UploadRejected(f"file exceeds {max_bytes} bytes", code="too_large")
    kind = kind_from_filename(filename)
    if kind is None:
        raise UploadRejected("unsupported extension (expected .pdf/.docx/.xlsx)", code="unsupported")
    if not data.startswith(_MAGIC[kind]):
        raise UploadRejected(f"content does not match {kind.value} (magic-byte mismatch)", code="invalid")
    if kind in _OOXML_REQUIRED:
        _validate_ooxml(data, kind)
    return kind
