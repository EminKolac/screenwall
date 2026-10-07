"""Skip markers for tests that only mean something on POSIX, so a Windows CI run stays honest.

- FAKE_CLI: the fake `claude` / `codex` executables (tests/fixtures/fake_cli) are shebang
  scripts, and app/chat/cli_process.py needs POSIX process groups and selectable pipes. On
  Windows the CLI providers report "unsupported_os" instead (tests/unit/test_chat_windows_guard.py
  covers that on every OS).
- FILE_MODES: 0600/0700 permission bits and symlinks; Windows has neither in this form.
"""
from __future__ import annotations

import os

import pytest

WINDOWS = os.name == "nt"

FAKE_CLI = pytest.mark.skipif(
    WINDOWS, reason="POSIX-only: fake CLI shebang scripts and chat/cli_process.py process groups"
)
FILE_MODES = pytest.mark.skipif(
    WINDOWS, reason="POSIX-only: 0600/0700 file modes and symlinks"
)
