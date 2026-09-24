"""Lock an existing store down at startup: directories 0700, files 0600.

New writes are already private (storage/local.py creates 0700 directories and 0600 files), but
`mkdir(mode=0o700, exist_ok=True)` never tightens what exists, and stores written by earlier
versions have 0755 directories and 0644 files in all five layers. This pass fixes the storage
root, every layer tree and the app's own files at the root (user settings, the cloud-send log).

It never follows a symlink and never changes one: a link inside the store may point anywhere, and
chmod through it would change a file that is not the store's. Nothing outside the root and the
layer trees is touched (the root may hold unrelated data, e.g. evaluation corpora). Only counts
are reported, never names.
"""
from __future__ import annotations

import os
import stat
from collections.abc import Iterable
from pathlib import Path

DIR_MODE = 0o700
FILE_MODE = 0o600


def _tighten(path: str, mode: int, counts: dict[str, int], kind: str) -> None:
    """chmod `path` to `mode` unless it is a symlink or already has it; count the change."""
    try:
        st = os.lstat(path)
    except OSError:
        return
    if stat.S_ISLNK(st.st_mode):
        counts["symlinks"] += 1
        return
    if stat.S_IMODE(st.st_mode) == mode:
        return
    try:
        if os.chmod in os.supports_follow_symlinks:
            os.chmod(path, mode, follow_symlinks=False)  # no race with a swapped-in link
        else:
            os.chmod(path, mode)
    except (OSError, NotImplementedError):
        counts["errors"] += 1
        return
    counts[kind] += 1


def _tighten_tree(top: Path, counts: dict[str, int]) -> None:
    if top.is_symlink():
        counts["symlinks"] += 1
        return
    if not top.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(top, followlinks=False):
        _tighten(dirpath, DIR_MODE, counts, "dirs")
        for name in dirnames:  # a symlinked directory is listed here but never walked into
            if os.path.islink(os.path.join(dirpath, name)):
                counts["symlinks"] += 1
        for name in filenames:
            _tighten_file(os.path.join(dirpath, name), counts)


def _tighten_file(path: str, counts: dict[str, int]) -> None:
    try:
        st = os.lstat(path)
    except OSError:
        return
    if stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode):
        _tighten(path, FILE_MODE, counts, "files")


def lock_down_store(root: Path, layers: Iterable[str]) -> dict[str, int]:
    """Idempotent. Returns {"dirs", "files"} tightened, "symlinks" skipped, chmod "errors"."""
    counts = {"dirs": 0, "files": 0, "symlinks": 0, "errors": 0}
    root, layers = Path(root), tuple(layers)
    if root.is_symlink() or not root.is_dir():
        counts["symlinks"] += int(root.is_symlink())
        return counts
    _tighten(str(root), DIR_MODE, counts, "dirs")
    for layer in layers:
        _tighten_tree(root / layer, counts)
    with os.scandir(root) as entries:  # the app's own files at the top, not subdirectories
        for entry in entries:
            if entry.name not in layers and not entry.is_dir(follow_symlinks=False):
                _tighten_file(entry.path, counts)
    return counts
