"""Startup locks an existing store down: storage root and layer directories 0700, files 0600.

`mkdir(mode=0o700, exist_ok=True)` never tightens a directory that already exists, and a store
written by an older version has 0755 directories and 0644 files in all five layers. Symlinks are
neither changed nor followed, and only counts are logged.
"""
from __future__ import annotations

import logging
import os
import stat

import pytest
from fastapi.testclient import TestClient

from app.main import _LAYERS, app
from app.security.permissions import lock_down_store
from tests import posix_only

pytestmark = posix_only.FILE_MODES


def _mode(path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


@pytest.fixture
def loose_store(tmp_path, tmp_path_factory):
    """tmp_path is STORAGE_ROOT (conftest). Fill it like an old version would have."""
    outside = tmp_path_factory.mktemp("outside")
    target = outside / "shared.txt"
    target.write_text("not ours")
    os.chmod(target, 0o644)
    os.chmod(outside, 0o755)
    for layer in _LAYERS:
        doc = tmp_path / layer / "doc1"
        doc.mkdir(parents=True)
        (doc / "data.json").write_text("{}")
        os.chmod(doc / "data.json", 0o644)
        os.chmod(doc, 0o755)
        os.chmod(tmp_path / layer, 0o755)
    (tmp_path / "3_anonymized" / "doc1" / "link.txt").symlink_to(target)
    (tmp_path / "4_validation" / "outside").symlink_to(outside, target_is_directory=True)
    (tmp_path / "user_settings.json").write_text("{}")
    os.chmod(tmp_path / "user_settings.json", 0o644)
    os.chmod(tmp_path, 0o755)
    return tmp_path, outside, target


def test_startup_tightens_an_existing_store(loose_store, caplog):
    root, outside, target = loose_store
    with caplog.at_level(logging.INFO), TestClient(app):  # runs the lifespan
        pass
    assert _mode(root) == 0o700
    for layer in _LAYERS:
        assert _mode(root / layer) == 0o700
        assert _mode(root / layer / "doc1") == 0o700
        assert _mode(root / layer / "doc1" / "data.json") == 0o600
    assert _mode(root / "user_settings.json") == 0o600
    # Symlinks: not followed, their targets untouched.
    assert _mode(target) == 0o644 and _mode(outside) == 0o755
    assert "11 directories, 6 files made private (2 symlinks skipped" in caplog.text
    assert "doc1" not in caplog.text and "data.json" not in caplog.text  # counts only


def test_lock_down_is_idempotent_and_skips_symlinks(loose_store):
    root, outside, target = loose_store
    first = lock_down_store(root, _LAYERS)
    assert first["dirs"] == 1 + 2 * len(_LAYERS)  # root, each layer, each document directory
    assert first["files"] == len(_LAYERS) + 1  # one per layer + user_settings.json
    assert first["symlinks"] == 2
    again = lock_down_store(root, _LAYERS)
    assert (again["dirs"], again["files"]) == (0, 0)
    assert _mode(target) == 0o644 and _mode(outside) == 0o755


def test_a_symlinked_layer_is_not_followed(tmp_path, tmp_path_factory):
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    (elsewhere / "doc").mkdir()
    (elsewhere / "doc" / "x.json").write_text("{}")
    os.chmod(elsewhere / "doc" / "x.json", 0o644)
    (tmp_path / "3_anonymized").symlink_to(elsewhere, target_is_directory=True)
    counts = lock_down_store(tmp_path, _LAYERS)
    assert counts["symlinks"] == 1
    assert _mode(elsewhere / "doc" / "x.json") == 0o644
