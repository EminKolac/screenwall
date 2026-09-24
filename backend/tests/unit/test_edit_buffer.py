"""EditBuffer must render exactly what successive plain string splices would produce, while
keeping every edit mapped to the original text."""
from __future__ import annotations

import random

from app.anonymization.spans import EditBuffer


def _splice(text: str, start: int, end: int, repl: str) -> str:
    return text[:start] + repl + text[end:]


def test_single_replacement_offsets() -> None:
    buf = EditBuffer("Sayın Ali Veli geldi")
    buf.apply(6, 14, "<PERSON_1>", "PERSON", "tr")
    assert buf.text() == "Sayın <PERSON_1> geldi"
    (e,) = buf.edits()
    assert (e.start, e.end) == (6, 14)
    assert (e.masked_start, e.masked_end) == (6, 16)
    assert buf.text()[e.masked_start:e.masked_end] == "<PERSON_1>"


def test_right_to_left_passes_keep_original_offsets() -> None:
    text = "Ali Veli ile Ayşe Kaya"
    buf = EditBuffer(text)
    buf.apply(13, 22, "<PERSON_1>", "PERSON", "tr")  # right-most first, as the engine does
    buf.apply(0, 8, "<PERSON_2>", "PERSON", "tr")
    assert buf.text() == "<PERSON_2> ile <PERSON_1>"
    a, b = buf.edits()
    assert text[a.start:a.end] == "Ali Veli"
    assert text[b.start:b.end] == "Ayşe Kaya"
    assert buf.text()[b.masked_start:b.masked_end] == "<PERSON_1>"


def test_later_pass_in_current_coordinates() -> None:
    text = "Kart 4111 1111 1111 1111 ve ali@example.com"
    buf = EditBuffer(text)
    buf.apply(5, 24, "<CARD_1>", "CREDIT_CARD", "en")
    cur = buf.text()
    s = cur.index("ali@")
    buf.apply(s, s + len("ali@example.com"), "<EMAIL_1>", "EMAIL_ADDRESS", "propagation:any")
    assert buf.text() == "Kart <CARD_1> ve <EMAIL_1>"
    e = buf.edits()[1]
    assert text[e.start:e.end] == "ali@example.com"


def test_empty_replacement_for_cell_continuation() -> None:
    buf = EditBuffer("9Qm2f rest")
    buf.apply_original(0, 5, "", "SECRET_KEY", "adjacency")
    assert buf.text() == " rest"
    (e,) = buf.edits()
    assert (e.masked_start, e.masked_end) == (0, 0)


def test_overlap_absorbs_previous_replacement() -> None:
    buf = EditBuffer("abc DEF ghi")
    buf.apply(4, 7, "<X_1>", "X", "a")  # "abc <X_1> ghi"
    cur = buf.text()
    buf.apply(2, 6, "<Y_1>", "Y", "b")  # overlaps "c <X" — pathological but must stay exact
    assert buf.text() == _splice(cur, 2, 6, "<Y_1>")
    (e,) = buf.edits()
    assert (e.start, e.end) == (2, 7)


def test_randomized_equivalence_with_plain_splicing() -> None:
    rng = random.Random(7)
    alphabet = "abcçğıİöşüXYZ 0123"
    for _ in range(3000):
        original = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        buf = EditBuffer(original)
        expected = original
        for _ in range(rng.randint(1, 6)):
            if not expected:
                break
            a = rng.randrange(0, len(expected))
            b = rng.randint(a + 1, min(len(expected), a + 8))
            repl = rng.choice(["<P_1>", "<LONGER_22>", "", "Z"])
            buf.apply(a, b, repl, "T", "s")
            expected = _splice(expected, a, b, repl)
            assert buf.text() == expected
        edits = buf.edits()
        # sorted, non-overlapping in original; masked slices equal replacement text
        for x, y in zip(edits, edits[1:], strict=False):
            assert x.end <= y.start
        rendered = buf.text()
        for e in edits:
            assert rendered[e.masked_start:e.masked_end] == e.text
        # literal text between edits is copied from the original unchanged
        prev_o, prev_m = 0, 0
        for e in edits:
            assert original[prev_o:e.start] == rendered[prev_m:e.masked_start]
            prev_o, prev_m = e.end, e.masked_end
        assert original[prev_o:] == rendered[prev_m:]
