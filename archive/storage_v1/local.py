"""Local filesystem storage backend over the 5 isolated layers (Architecture.md §6).

Files live at <root>/<layer>/<document_id>/<name>. Secure deletion overwrites then unlinks all
layers for a document; on SSD/APFS overwrite is best-effort only (see SECURITY.md §5 — the
production guarantee is crypto-shredding).
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from app.storage.base import StorageLayer


def _secure_overwrite(path: Path) -> None:
    try:
        size = path.stat().st_size
        with open(path, "r+b") as f:
            f.write(os.urandom(size))
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass  # best-effort; deletion still proceeds


class LocalStorageBackend:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, layer: StorageLayer, document_id: str, name: str) -> Path:
        d = self.root / layer.value / document_id
        d.mkdir(parents=True, exist_ok=True)
        return d / name

    def write_bytes(self, layer: StorageLayer, document_id: str, name: str, data: bytes) -> str:
        p = self._path(layer, document_id, name)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)  # atomic: no half-written files on crash/concurrency
        return str(p)

    def read_bytes(self, layer: StorageLayer, document_id: str, name: str) -> bytes:
        return (self.root / layer.value / document_id / name).read_bytes()

    def write_json(self, layer: StorageLayer, document_id: str, name: str, obj: object) -> str:
        p = self._path(layer, document_id, name)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)  # atomic write
        return str(p)

    def read_json(self, layer: StorageLayer, document_id: str, name: str) -> object:
        return json.loads((self.root / layer.value / document_id / name).read_text(encoding="utf-8"))

    def exists(self, layer: StorageLayer, document_id: str, name: str) -> bool:
        return (self.root / layer.value / document_id / name).exists()

    def delete_document(self, document_id: str, *, secure: bool = True) -> None:
        for layer in StorageLayer:
            d = self.root / layer.value / document_id
            if not d.exists():
                continue
            if secure:
                for f in d.rglob("*"):
                    if f.is_file():
                        _secure_overwrite(f)
            shutil.rmtree(d, ignore_errors=True)
