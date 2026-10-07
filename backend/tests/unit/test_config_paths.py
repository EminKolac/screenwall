"""Settings paths do not depend on the working directory (a launcher may start from "/")."""
from __future__ import annotations

from pathlib import Path

import pytest

from app import config
from app.config import BACKEND_DIR, Settings


def test_backend_dir_is_the_backend_folder():
    assert (BACKEND_DIR / "app" / "config.py").is_file()
    assert (BACKEND_DIR / "pyproject.toml").is_file()


def test_env_file_is_absolute_backend_env():
    env_file = Path(Settings.model_config["env_file"])
    assert env_file.is_absolute() and env_file == BACKEND_DIR / ".env"


def test_default_storage_root_is_backend_data_from_any_cwd(monkeypatch, tmp_path):
    monkeypatch.delenv("STORAGE_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    assert Settings(_env_file=None).storage_root == BACKEND_DIR / "data"


@pytest.mark.parametrize("value", ["data", "./data", "nested/store"])
def test_a_relative_storage_root_is_anchored_to_backend(monkeypatch, tmp_path, value):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STORAGE_ROOT", value)
    root = Settings(_env_file=None).storage_root
    assert root.is_absolute() and root == BACKEND_DIR / value
    assert Settings(storage_root=Path(value)).storage_root == BACKEND_DIR / value


def test_absolute_and_home_paths_are_kept(monkeypatch, tmp_path):
    assert Settings(storage_root=tmp_path / "store").storage_root == tmp_path / "store"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Path.home() on Windows
    assert Settings(storage_root=Path("~/sw")).storage_root == tmp_path / "sw"


def test_ui_dist_is_optional_and_anchored(monkeypatch, tmp_path):
    monkeypatch.delenv("UI_DIST", raising=False)
    assert Settings(_env_file=None).ui_dist is None
    assert Settings(_env_file=None).ui_index() is None
    assert Settings(ui_dist=Path("../frontend/dist")).ui_dist == BACKEND_DIR / "../frontend/dist"
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setenv("UI_DIST", str(tmp_path))
    settings = Settings(_env_file=None)
    assert settings.ui_dist == tmp_path and settings.ui_index() == tmp_path / "index.html"


def test_max_iterations_bounds_match_the_docstring():
    assert "1..2" in (config.__doc__ or "")
    assert Settings(max_iterations=1).max_iterations == 1
    assert Settings(max_iterations=2).max_iterations == 2
    for bad in (0, 3):
        with pytest.raises(ValueError):
            Settings(max_iterations=bad)
