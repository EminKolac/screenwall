"""Local filesystem storage backend over the 5 isolated layers (Architecture.md §6).

Files live at <root>/<layer>/<document_id>/<name>. Directories are created 0700 and files 0600:
only the user running the app can read documents, mappings or reports. Writes are atomic (a unique
temp file + rename, `write_private`). Secure deletion overwrites then unlinks all layers for a
document; on SSD/APFS the overwrite is best-effort only (see SECURITY.md §5 — the production
guarantee is crypto-shredding).
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
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


def write_private(path: Path, data: bytes) -> None:
    """Atomic write of a 0600 file, shared by every writer (storage layers, user settings).

    The temp file is UNIQUE (mkstemp in the target's directory, created 0600, so the content is
    never readable by others, not even for a moment): concurrent writers of one path never share or
    truncate each other's temp file, and a failure removes only this call's own temp file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


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
        write_private(p, data)
        return str(p)

    def read_bytes(self, layer: StorageLayer, document_id: str, name: str) -> bytes:
        return (self.root / layer.value / document_id / name).read_bytes()

    def write_json(self, layer: StorageLayer, document_id: str, name: str, obj: object) -> str:
        p = self._path(layer, document_id, name)
        write_private(p, json.dumps(obj, ensure_ascii=False).encode("utf-8"))
        return str(p)

    def read_json(self, layer: StorageLayer, document_id: str, name: str) -> object:
        path = self.root / layer.value / document_id / name
        return json.loads(path.read_text(encoding="utf-8"))

    def exists(self, layer: StorageLayer, document_id: str, name: str) -> bool:
        return (self.root / layer.value / document_id / name).exists()

    def delete_document(self, document_id: str, *, secure: bool = True) -> None:
        """Every layer of the document. The record (layer 4, document.json) goes LAST and only
        when every other layer is gone: a layer that survives raises OSError, so the document
        stays listed and the delete can be retried instead of leaving raw data behind unseen."""
        last = StorageLayer.VALIDATION
        for layer in [*(lyr for lyr in StorageLayer if lyr != last), last]:
            d = self.root / layer.value / document_id
            if not d.exists():
                continue
            if secure:
                for f in d.rglob("*"):
                    if f.is_file():
                        _secure_overwrite(f)
            shutil.rmtree(d, ignore_errors=True)
            if d.exists():
                raise OSError(f"could not delete the {layer.value} layer")
