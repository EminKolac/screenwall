"""User settings file (review hardening C13, B4 for its writer).

An invalid field falls back to its default alone and only its NAME is logged; a file that cannot
be read is never overwritten; `update_user_settings` holds the lock across the whole
read-modify-write, so concurrent global decisions cannot lose each other's terms.
"""
from __future__ import annotations

import json
import logging
import threading

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services import user_settings as us

client = TestClient(app)


def _path():
    return get_settings().storage_root / "user_settings.json"


def test_an_invalid_field_drops_only_that_field(caplog) -> None:
    _path().write_text(json.dumps({"default_mode": "bogus-mode-value",
                                   "always_mask": ["Gizli Fon"], "never_mask": 7}), "utf-8")
    with caplog.at_level(logging.WARNING):
        prefs = us.load_user_settings(get_settings())
    assert prefs.always_mask == ["Gizli Fon"]
    assert prefs.default_mode == "mapping" and prefs.never_mask == []
    assert "default_mode" in caplog.text and "never_mask" in caplog.text
    assert "bogus-mode-value" not in caplog.text


def test_an_unreadable_file_is_never_overwritten() -> None:
    _path().write_text('{"always_mask": ["Gizli Fon"', "utf-8")  # torn JSON
    before = _path().read_bytes()
    assert us.load_user_settings(get_settings()).always_mask == []  # the app still starts
    with pytest.raises(us.UserSettingsUnreadable):
        us.update_user_settings(get_settings(), lambda p: p.model_copy(update={"always_mask": []}))
    r = client.put("/api/settings", json={"never_mask": ["Genel Kurul"]})
    assert r.status_code == 500 and r.json()["detail"] == "internal_error"
    assert _path().read_bytes() == before


def test_update_holds_the_lock_across_read_modify_write() -> None:
    settings = get_settings()

    def add(term: str) -> None:
        us.update_user_settings(settings, lambda p: us.with_always(p, term, "ORG"))

    threads = [threading.Thread(target=add, args=(f"Terim {i}",)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    prefs = us.load_user_settings(settings)
    assert sorted(prefs.always_mask) == sorted(f"Terim {i}" for i in range(12))
    assert set(prefs.always_mask_family.values()) == {"ORG"}


def test_update_waits_for_the_settings_lock() -> None:
    """Deterministic: while the lock is held, an update can neither read nor write."""
    settings = get_settings()
    done = threading.Event()

    def update() -> None:
        us.update_user_settings(settings, lambda p: us.with_always(p, "Gizli Fon"))
        done.set()

    with us._LOCK:
        t = threading.Thread(target=update)
        t.start()
        assert not done.wait(0.3)
        assert not _path().exists()
    t.join(10)
    assert done.is_set() and us.load_user_settings(settings).always_mask == ["Gizli Fon"]


def test_global_lists_stay_disjoint_and_keys_are_normalized() -> None:
    prefs = us.UserSettings(never_mask=["Kuzey Grubu"])
    prefs = us.with_always(prefs, "KUZEY  grubu", "ORG")
    assert prefs.never_mask == [] and prefs.always_mask == ["KUZEY grubu"]
    assert prefs.always_mask_family == {"KUZEY grubu": "ORG"}
    prefs = us.with_never(prefs, "kuzey grubu")
    assert prefs.always_mask == [] and prefs.always_mask_family == {}
    assert prefs.never_mask == ["kuzey grubu"]


def test_the_settings_writer_leaves_a_foreign_temp_file_alone() -> None:
    foreign = _path().with_name("user_settings.json.tmp")
    foreign.write_bytes(b"another writer")
    us.save_user_settings(get_settings(), us.UserSettings(always_mask=["Gizli Fon"]))
    assert foreign.read_bytes() == b"another writer"
    assert us.load_user_settings(get_settings()).always_mask == ["Gizli Fon"]
