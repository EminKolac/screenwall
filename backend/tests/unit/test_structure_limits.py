"""Structure rules for the review/approval layer (review hardening D).

No module over 300 lines and no function over 50 lines in the modules this layer owns; the dead
code the review listed stays gone; one function reserves unit ids for both the engine and the
review payload.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
OWNED = [
    *sorted((BACKEND / "app" / "review").glob("*.py")),
    *[BACKEND / "app" / "pipeline" / f"{n}.py" for n in ("runner", "queue", "orchestrator")],
    *[BACKEND / "app" / "api" / f"{n}.py" for n in ("documents", "system")],
    BACKEND / "app" / "storage" / "local.py",
    *[BACKEND / "app" / "services" / f"{n}.py"
      for n in ("storage_repository", "repository", "user_settings", "deps", "locks")],
    *[BACKEND / "app" / "anonymization" / f"{n}.py"
      for n in ("engine", "lists", "tables", "propagate", "spans", "types", "resolve", "gates",
                "units", "overrides", "detection")],
    BACKEND / "app" / "models" / "document.py",
]


@pytest.mark.parametrize("path", OWNED, ids=lambda p: str(p.relative_to(BACKEND)))
def test_module_and_function_sizes(path: Path) -> None:
    assert path.exists(), f"{path} is missing"
    source = path.read_text(encoding="utf-8")
    assert len(source.splitlines()) <= 300
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = node.end_lineno - node.lineno + 1
            assert length <= 50, f"{node.name} has {length} lines"


def test_the_dead_code_stays_gone() -> None:
    import app.models.document as document
    from app.pipeline.orchestrator import PipelineResult
    from app.review.reasons import REVIEW_REASONS

    assert not hasattr(document, "presidio_pass_status")
    assert not hasattr(document, "qwen_audit_status")
    assert not hasattr(document.Document, "clear_reasons")
    assert "current_iteration" not in document.Document.model_fields
    assert "allow_terms" not in document.Document.model_fields
    assert not hasattr(document.DocumentStatus, "display")
    assert not hasattr(PipelineResult, "anonymized") and not hasattr(PipelineResult, "mapping")
    assert "suggestions_pending" not in REVIEW_REASONS
    assert "no_text" not in REVIEW_REASONS  # the sentence lives once, in services/ingest.py


def test_one_function_reserves_unit_ids_for_engine_and_payload(monkeypatch) -> None:
    from app.anonymization import units
    from app.anonymization.engine import Engine
    from app.extraction.base import Block, BlockType, ExtractedContent, TableCell
    from app.models.document import FileKind, Language

    calls: list[str] = []
    real = units.reserve_unit_id

    def spy(taken: set[str], base: str) -> str:
        calls.append(base)
        return real(taken, base)

    monkeypatch.setattr(units, "reserve_unit_id", spy)
    cells = [TableCell(row=0, col=0, text="a"), TableCell(row=0, col=0, text="b")]
    content = ExtractedContent(kind=FileKind.xlsx, blocks=[
        Block(block_id="p", type=BlockType.paragraph, text="Merhaba."),
        Block(block_id="t", type=BlockType.table, cells=cells)])
    ids = [uid for uid, _b, _c, _t in units.iter_units(content)]
    assert ids == ["p", "t:r0c0", "t:r0c0#2"] and len(calls) == 3
    out = Engine().anonymize(content, Language.tr)
    assert list(out.edits) == ids and len(calls) == 6


def test_documents_drop_reasons_in_one_place() -> None:
    from app.models.document import Document, FileKind

    doc = Document(id="r", filename="a.pdf", kind=FileKind.pdf)
    doc.add_reason("a", "Bir.")
    doc.add_reason("b", "İki.")
    doc.drop_reasons("a")
    assert [r.code for r in doc.reasons] == ["b"] and doc.review_reason == ["İki."]
