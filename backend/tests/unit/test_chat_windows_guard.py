"""Windows guard for the Claude / Codex CLI chat providers (runs on every OS).

chat/cli_process.py kills a process group (os.killpg, SIGKILL) and pumps pipes with `selectors`;
neither works on Windows. There the two providers must say "unsupported_os" without looking up,
spawning or killing anything, refuse a consent preview, and refuse a send. `os.name` is
monkeypatched to "nt", and every POSIX-only primitive is replaced by a tripwire.
"""
from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import chat as chat_api
from app.chat import cli, cli_process
from app.chat.base import ChatError
from app.chat.factory import build_provider
from app.chat.providers import UNSUPPORTED_OS, ClaudeCliProvider, CodexCliProvider
from app.chat.schemas import ProviderStatus
from app.config import get_settings

PROVIDERS = [ClaudeCliProvider, CodexCliProvider]
MESSAGES = [{"role": "user", "content": "SYNTHETIC soru [S1]?"}]


def _tripwire(name: str):
    def fail(*_a, **_k):
        raise AssertionError(f"{name} must not be reached on Windows")

    return fail


@pytest.fixture
def windows(monkeypatch):
    """os.name == "nt", with every process / pipe primitive turned into a tripwire."""
    monkeypatch.setattr(cli_process.os, "killpg", _tripwire("os.killpg"), raising=False)
    monkeypatch.setattr(cli_process.selectors, "DefaultSelector", _tripwire("selectors"))
    monkeypatch.setattr(cli_process.subprocess, "Popen", _tripwire("subprocess.Popen"))
    monkeypatch.setattr(cli, "executable", _tripwire("cli.executable"))  # not even a lookup
    monkeypatch.setattr(cli, "status", _tripwire("cli.status"))
    monkeypatch.setattr(cli, "complete", _tripwire("cli.complete"))
    monkeypatch.setattr(os, "name", "nt")  # set last, so teardown restores it first


def test_supported_follows_os_name(monkeypatch):
    assert cli_process.supported() is (os.name != "nt")
    monkeypatch.setattr(os, "name", "nt")
    assert cli_process.supported() is False
    monkeypatch.setattr(os, "name", "posix")
    assert cli_process.supported() is True


@pytest.mark.parametrize("cls", PROVIDERS)
def test_status_is_unsupported_os_without_touching_a_cli(cls, windows):
    status = cls("some-model", 60).status()
    assert set(status) == set(ProviderStatus.model_fields)
    assert status["problem"] == UNSUPPORTED_OS == "unsupported_os"
    assert status["available"] is False and status["local"] is False
    # Nothing was probed, so nothing is claimed about the CLI either way.
    assert status["installed"] is None and status["compatible"] is None
    assert status["authenticated"] is None and status["version"] is None
    assert status["login_command"] is None  # logging in would not help
    assert status["model"] == "some-model"


@pytest.mark.parametrize("cls", PROVIDERS)
def test_no_preview_and_no_send(cls, windows):
    provider = cls()
    with pytest.raises(ChatError) as err:
        provider.render("SYS", MESSAGES)
    assert err.value.code == "provider_unavailable"
    with pytest.raises(ChatError) as err:
        provider.chat("SYS", MESSAGES, "")
    assert err.value.code == "provider_unavailable"


def test_the_process_runner_refuses_before_spawning(windows, tmp_path):
    with pytest.raises(cli.CliError) as err:
        cli_process.run(["claude", "--version"], cwd=str(tmp_path), stdin="SYNTHETIC")
    assert err.value.code == "cli_failed"


def test_ollama_is_unaffected(windows):
    provider = build_provider("ollama", get_settings())
    assert provider.render("SYS", MESSAGES).startswith("{")  # no CLI involved at all


# ------------------------------------------------------------------ through the HTTP API


@pytest.fixture
def api_on_windows(monkeypatch):
    """The API with the guard switched on through `cli_process.supported` (os.name itself stays
    real here: TestClient runs the app in another thread)."""
    monkeypatch.setattr(cli_process, "supported", lambda: False)
    monkeypatch.setattr(cli_process.subprocess, "Popen", _tripwire("subprocess.Popen"))
    monkeypatch.setattr(cli, "executable", _tripwire("cli.executable"))
    app = FastAPI()
    app.include_router(chat_api.router)
    return TestClient(app)


def test_providers_endpoint_reports_unsupported_os(api_on_windows):
    body = api_on_windows.get("/api/chat/providers").json()
    by_id = {p["id"]: p for p in body["providers"]}
    assert by_id["claude_cli"]["problem"] == "unsupported_os"
    assert by_id["codex_cli"]["problem"] == "unsupported_os"
    assert not by_id["claude_cli"]["available"] and not by_id["codex_cli"]["available"]
    assert by_id["ollama"]["problem"] != "unsupported_os"


@pytest.mark.parametrize("provider", ["claude_cli", "codex_cli"])
def test_preview_and_send_are_503_and_nothing_is_recorded(api_on_windows, provider):
    from app.models.document import Document, DocumentStatus, FileKind
    from app.services.deps import get_repository

    repo = get_repository()
    repo.save_document(Document(id="d1", filename="f.docx", kind=FileKind.docx,
                                status=DocumentStatus.APPROVED))
    repo.save_chat_context("d1", "Kira bedeli 25.000 TL, <PERSON_1> öder.")
    body = {"doc_ids": ["d1"], "question": "Kira ne kadar?", "provider": provider}
    r = api_on_windows.post("/api/chat/preview", json=body)
    assert r.status_code == 503 and r.json() == {"detail": "provider_unavailable"}
    r = api_on_windows.post("/api/chat", json={**body, "preview_hash": "0" * 64})
    assert r.status_code == 503 and r.json() == {"detail": "provider_unavailable"}
    # No cloud send happened, so no dispatch line may claim one did.
    assert not (get_settings().storage_root / "chat_dispatches.jsonl").exists()
