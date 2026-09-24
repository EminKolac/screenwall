"""Append-only record of every send to a cloud chat provider (plan §5.6).

One JSON line per send, written after the consent check and before the provider is called: time,
provider, model, document ids, the consented preview_hash and the size of the text. It holds no
content at all (no question, source, answer or filename), so the record itself is not personal
data. If the line cannot be written the send does not happen.
"""
from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings

FILE_NAME = "chat_dispatches.jsonl"
_DIR_MODE = 0o700
_FILE_MODE = 0o600


def log_path(settings: Settings) -> Path:
    return Path(settings.storage_root) / FILE_NAME


def record(settings: Settings, *, provider: str, model: str, doc_ids: Sequence[str],
           preview_hash: str, chars: int) -> None:
    path = log_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True, mode=_DIR_MODE)
    line = json.dumps(
        {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "provider": provider,
            "model": model,
            "doc_ids": sorted(doc_ids),
            "preview_hash": preview_hash,
            "chars": chars,
        },
        separators=(",", ":"),
    )
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, _FILE_MODE)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(line + "\n")
