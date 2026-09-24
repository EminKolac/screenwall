"""Local filesystem storage backend over the 5 isolated layers (Architecture.md §6).

Files live at <root>/<layer>/<document_id>/<name>. Directories are created 0700 and files 0600:
only the user running the app can read documents, mappings or reports. Writes are atomic (temp
file + rename). Secure deletion overwrites then unlinks all layers for a document; on SSD/APFS the
overwrite is best-effort only (see SECURITY.md §5 — the production guarantee is crypto-shredding).
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from app.storage.base import StorageLayer

_DIR_MODE = 0o700
_FILE_MODE = 0o600


def _secure_overwrite(path: Path) -> None:
    try:
        size = path.stat().st_size
        with open(path, "r+b") as f:
            f.write(os.urandom(size))
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        pass  # best-effort; deletion still proceeds


def _private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=_DIR_MODE)
    try:
        os.chmod(path, _DIR_MODE)
    except OSError:
        pass


def _write_private(path: Path, data: bytes) -> None:
    """Atomic write of a 0600 file: the temp file is created with the final permissions, so the
    content is never readable by others, not even for a moment."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _FILE_MODE)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.chmod(tmp, _FILE_MODE)  # an existing temp file keeps its old mode otherwise
    os.replace(tmp, path)


class LocalStorageBackend:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, layer: StorageLayer, document_id: str, name: str) -> Path:
        _private_dir(self.root)
        _private_dir(self.root / layer.value)
        d = self.root / layer.value / document_id
        _private_dir(d)
        return d / name

    def write_bytes(self, layer: StorageLayer, document_id: str, name: str, data: bytes) -> str:
        p = self._path(layer, document_id, name)
        _write_private(p, data)
        return str(p)

    def read_bytes(self, layer: StorageLayer, document_id: str, name: str) -> bytes:
        return (self.root / layer.value / document_id / name).read_bytes()

    def write_json(self, layer: StorageLayer, document_id: str, name: str, obj: object) -> str:
        p = self._path(layer, document_id, name)
        _write_private(p, json.dumps(obj, ensure_ascii=False).encode("utf-8"))
        return str(p)

    def read_json(self, layer: StorageLayer, document_id: str, name: str) -> object:
        path = self.root / layer.value / document_id / name
        return json.loads(path.read_text(encoding="utf-8"))

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
