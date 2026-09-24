"""Chunking, BM25 retrieval, source numbering/labels and citation validation (chat/retrieval.py)."""
from __future__ import annotations

import re

import pytest

from app.chat import retrieval
from app.chat.base import ChatError

PLACEHOLDER = re.compile(r"<[A-Z][A-Z0-9_]*_\d+>")


def _filler(words: int, seed: str = "genel") -> str:
    return " ".join(f"{seed}{i % 7}" for i in range(words))


def test_chunks_pack_whole_lines_within_the_bound():
    lines = [f"Satır {i}: " + _filler(20) for i in range(60)]
    chunks = retrieval.chunk_text("\n".join(lines))
    assert len(chunks) > 1
    assert all(len(c) <= retrieval.CHUNK_CHARS for c in chunks)
    assert "\n".join(chunks).splitlines() == lines  # nothing lost, nothing reordered


@pytest.mark.parametrize(
    "line",
    [
        # ~8k chars with spaces: cut at whitespace.
        " ".join(f"<US_BANK_NUMBER_{i}>" if i % 3 == 0 else "kelime" for i in range(700)),
        # ~5k chars of glued placeholders, no whitespace: the hard cut lands inside one.
        "".join(f"<PERSON_{i}>" for i in range(420)),
    ],
)
def test_long_lines_never_split_a_placeholder(line):
    chunks = retrieval.chunk_text(line)
    assert len(chunks) > 1
    assert all(len(c) <= retrieval.CHUNK_CHARS for c in chunks)
    assert PLACEHOLDER.findall(" ".join(chunks)) == PLACEHOLDER.findall(line)
    for chunk in chunks:  # no dangling "<PERSO" or "_12>" fragments at the edges
        assert chunk.count("<") == chunk.count(">") == len(PLACEHOLDER.findall(chunk))
    if " " not in line:
        assert "".join(chunks) == line


def test_excerpt_is_bounded_and_ends_cleanly():
    text = "a" * 395 + " <PERSON_12> devam eden metin"
    out = retrieval.excerpt(text)
    assert len(out) <= retrieval.EXCERPT_CHARS
    assert out.endswith("…") and "<PERS" not in out
    assert retrieval.excerpt("kısa metin") == "kısa metin"


def _docs():
    contract = "\n".join(
        [_filler(150)] * 2
        + ["Kira bedeli aylık 25.000 TL olup <PERSON_1> tarafından ödenecektir."]
        + [_filler(150)] * 2
    )
    other = "\n".join([_filler(150, "diger")] * 3 + ["Fatura <ORG_1> adına kesilmiştir."])
    return [("doc-b", "Sozlesme.docx", contract), ("doc-a", "Fatura.pdf", other)]


def test_bm25_ranks_the_relevant_chunk_first_and_numbers_sources():
    sources = retrieval.retrieve(_docs(), "Kira bedeli ne kadar?")
    assert [s.id for s in sources] == [f"S{i}" for i in range(1, len(sources) + 1)]
    assert len(sources) <= retrieval.TOP_K
    best = sources[0]
    assert "Kira bedeli" in best.text
    assert best.doc_id == "doc-b" and best.doc_index == 1
    assert best.label == f"Sozlesme.docx · Parça {best.part}"
    assert best.unit_id == "context"
    public = best.public()
    assert set(public) == {"id", "doc_id", "unit_id", "label", "excerpt"}
    assert len(public["excerpt"]) <= retrieval.EXCERPT_CHARS


def test_top_k_is_eight():
    text = "\n".join(_filler(170, f"k{i}") for i in range(30))
    sources = retrieval.retrieve([("d", "f.pdf", text)], "k1 k2")
    assert len(sources) == 8


def test_matching_ignores_case_and_turkish_diacritics():
    docs = [
        ("d", "f.docx", "\n".join([_filler(160), "İSTANBUL ŞUBESİ açılışı ertelendi.",
                                     _filler(160)]))
    ]
    for query in ("istanbul subesi", "İstanbul şubesi", "ISTANBUL SUBESI"):
        assert "İSTANBUL" in retrieval.retrieve(docs, query)[0].text


def test_prompt_names_sources_by_position_never_by_filename():
    sources = retrieval.retrieve(_docs(), "kira")
    prompt = retrieval.system_prompt(sources)
    assert "Sozlesme.docx" not in prompt and "Fatura.pdf" not in prompt
    for s in sources:
        assert f"[{s.id}] document {s.doc_index}, part {s.part}\n{s.text}" in prompt
    assert "Never try to guess, reconstruct or reveal" in prompt
    assert "[S1]" in prompt and "language of the user's question" in prompt


def test_empty_context_yields_no_sources():
    assert retrieval.retrieve([("d", "f.pdf", "  \n\n ")], "soru") == []


def _sources(n: int = 3):
    text = "\n".join(_filler(170, f"p{i}") for i in range(n))
    return retrieval.retrieve([("d", "f.pdf", text)], "x")


def test_citations_known_markers_pass():
    sources = _sources()
    cited = retrieval.cited_sources("Cevap [S1] ve [S3].", sources)
    assert [s.id for s in cited] == ["S1", "S3"]


@pytest.mark.parametrize("answer", ["Kaynak yok.", "Bkz. [S9].", "Bkz. [S1] ve [S4].", "[S01]"])
def test_citations_missing_or_unknown_are_rejected(answer):
    with pytest.raises(ChatError) as err:
        retrieval.cited_sources(answer, _sources())
    assert err.value.code == "invalid_citations"


def test_grouped_citations_are_normalized():
    assert retrieval.normalize_citations("A [S1, S2] B [S3; S1]") == "A [S1][S2] B [S3][S1]"
    assert retrieval.normalize_citations("[S1]") == "[S1]"
    assert retrieval.strip_citations("Önceki cevap [S2] ve [S1, S3].") == "Önceki cevap  ve ."


def test_loose_citation_forms_are_normalized():
    assert retrieval.normalize_citations("A [s1] B [S01] C [S02, s3]") == "A [S1] B [S1] C [S2][S3]"
    # Ranges and anything that is not a list of ids stay as they are, so validation rejects them.
    assert retrieval.normalize_citations("[S1-S3]") == "[S1-S3]"
    assert retrieval.normalize_citations("[bkz. S1]") == "[bkz. S1]"
    with pytest.raises(ChatError):
        retrieval.cited_sources("Bkz. [S1-S3].", _sources())
