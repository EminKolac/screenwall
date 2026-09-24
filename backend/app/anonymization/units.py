"""Text units: the paragraphs and table cells the engine masks one by one.

A unit id is the block id for a text block and "<block_id>:r<row>c<col>" for a table cell. Two cells
with the same coordinates get a stable "#<n>" suffix. `reserve_unit_id` is the ONE place that
assigns ids, shared by the engine (edit keys) and the review payload (`iter_units`), so both always
name the same unit the same way.
"""
from __future__ import annotations

from collections.abc import Iterator

from app.extraction.base import Block, BlockType, ExtractedContent, TableCell


def cell_id(block: Block, row: int, col: int) -> str:
    return f"{block.block_id}:r{row}c{col}"


def reserve_unit_id(taken: set[str], base: str) -> str:
    """`base`, or `base#2`, `base#3`, ... when taken; the id is added to `taken`."""
    uid, n = base, 1
    while uid in taken:
        n += 1
        uid = f"{base}#{n}"
    taken.add(uid)
    return uid


def iter_units(content: ExtractedContent
               ) -> Iterator[tuple[str, Block, TableCell | None, str]]:
    """(unit_id, block, cell_or_None, text) in the exact order and naming the engine uses."""
    taken: set[str] = set()
    for block in content.blocks:
        if block.type == BlockType.table:
            for cell in block.cells:
                uid = reserve_unit_id(taken, cell_id(block, cell.row, cell.col))
                yield uid, block, cell, cell.text
        else:
            yield reserve_unit_id(taken, block.block_id), block, None, block.text
