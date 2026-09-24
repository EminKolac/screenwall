"""OLLAMA_BASE_URL is trusted as "this computer" only when it IS this computer.

The pre-approval auditor receives masked but not yet approved text, and chat receives approved
text: before this guard, a remote OLLAMA_BASE_URL received both over plain HTTP while the UI said
"Bu bilgisayar". Now a non-loopback host needs OLLAMA_ALLOW_REMOTE=true: without it the auditor
fails closed (review, `auditor_unavailable`) and chat is unavailable; with it chat is a remote
destination behind the consent gate. Ollama "cloud" models proxy to ollama.com and are refused.
No network: a fake Ollama answers through httpx's transport layer, and the proxy test uses two
throw-away servers on 127.0.0.1.
"""
from __future__ import annotations

import http.server
import json
import threading

import httpx
import pytest

from app.audit.factory import build_auditor
from app.audit.ollama_provider import OllamaProvider
from app.chat.base import ChatError
from app.chat.factory import build_provider
from app.chat.providers import OllamaChatProvider
from app.config import Settings
from app.models.document import DocumentStatus
from app.security.ollama import is_cloud_model, is_loopback_url
from tests.conftest import TR_PARA, make_docx

REMOTE = "http://gpu-box.invalid:11434"
CLEAN = json.dumps({"approved": True, "risk_level": "low", "remaining_sensitive_items": [],
                    "summary": "", "recommended_next_action": "approve"})


# ------------------------------------------------------------------ the policy itself


@pytest.mark.parametrize("url", [
    "http://localhost:11434", "http://127.0.0.1:11434", "http://127.8.9.10:11434/",
    "http://[::1]:11434", "https://LOCALHOST:11434", "http://localhost",
])
def test_loopback_urls(url):
    assert is_loopback_url(url)


@pytest.mark.parametrize("url", [
    REMOTE, "http://192.168.1.20:11434", "http://10.0.0.5:11434", "http://0.0.0.0:11434",
    "http://localhost.evil.example:11434", "http://localhost:11434@evil.example",
    "ftp://localhost:11434", "localhost:11434", "", "http://[::ffff:10.0.0.1]:11434",
])
def test_remote_or_malformed_urls_are_not_loopback(url):
    assert not is_loopback_url(url)


@pytest.mark.parametrize("model", ["gpt-oss:120b-cloud", "qwen3-coder:480b-cloud", "kimi:cloud",
                                   "GPT-OSS:20B-CLOUD", " deepseek-v3.1:671b-cloud ",
                                   "gpt-oss-cloud:latest"])
def test_cloud_models(model):
    assert is_cloud_model(model)


@pytest.mark.parametrize("model", ["qwen3.5:4b", "llama3", "cloudy:7b", "cloud", "cloud:latest"])
def test_local_models(model):
    assert not is_cloud_model(model)


# ------------------------------------------------------------------ the pre-approval auditor


@pytest.fixture
def fake_ollama(monkeypatch):
    """Answers every httpx request as a working Ollama would; records the URLs it saw."""
    state = {"seen": [], "model": "qwen3.5:4b"}

    def handle(_transport, request: httpx.Request) -> httpx.Response:
        state["seen"].append(str(request.url))
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": state["model"]}]})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": CLEAN}})

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    return state


def test_auditor_never_contacts_a_remote_ollama_and_fails_closed(fake_ollama):
    auditor = build_auditor(Settings(auditor_provider="ollama", ollama_base_url=REMOTE))
    res = auditor.audit("Temiz bir metin.")
    assert res.llm_ok is False and not res.approved
    assert fake_ollama["seen"] == []  # the masked, unapproved text never left the machine


def test_auditor_uses_a_remote_ollama_only_when_allowed(fake_ollama):
    settings = Settings(auditor_provider="ollama", ollama_base_url=REMOTE,
                        ollama_allow_remote=True)
    res = build_auditor(settings).audit("Temiz bir metin.")
    assert res.llm_ok is True and res.approved
    assert any(url.endswith("/api/chat") for url in fake_ollama["seen"])


def test_auditor_refuses_cloud_models_even_on_localhost(fake_ollama):
    fake_ollama["model"] = "gpt-oss:120b-cloud"
    settings = Settings(auditor_provider="ollama", auditor_model="gpt-oss:120b-cloud")
    res = build_auditor(settings).audit("Temiz bir metin.")
    assert res.llm_ok is False and not res.approved
    assert fake_ollama["seen"] == []
    assert OllamaProvider("http://localhost:11434", "x:cloud").is_available() is False


def test_a_remote_auditor_sends_the_document_to_review(fake_ollama, tmp_path):
    from app.pipeline.runner import run_pipeline
    from app.services.storage_repository import StorageDocumentRepository
    from app.storage.local import LocalStorageBackend

    settings = Settings(storage_root=tmp_path / "store", auditor_provider="ollama",
                        ollama_base_url=REMOTE)
    repo = StorageDocumentRepository(LocalStorageBackend(settings.storage_root))
    doc = run_pipeline(make_docx([TR_PARA]), "temiz.docx", settings, repo)
    assert doc.status == DocumentStatus.NEEDS_HUMAN_REVIEW
    assert "auditor_unavailable" in {r.code for r in doc.reasons}
    assert fake_ollama["seen"] == []


# ------------------------------------------------------------------ chat


def _chat(monkeypatch, url: str, model: str = "qwen3.5:4b", allow_remote: bool = False):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": model, "model": model}]})
        return httpx.Response(200, json={"message": {"content": "cevap [S1]"}})

    monkeypatch.setattr(OllamaChatProvider, "transport", httpx.MockTransport(handler))
    settings = Settings(ollama_base_url=url, chat_ollama_model=model,
                        ollama_allow_remote=allow_remote)
    return build_provider("ollama", settings), seen


@pytest.mark.parametrize("url,model", [(REMOTE, "qwen3.5:4b"),
                                       ("http://localhost:11434", "gpt-oss:120b-cloud")])
def test_chat_refuses_a_remote_host_or_a_cloud_model(monkeypatch, url, model):
    provider, seen = _chat(monkeypatch, url, model)
    status = provider.status()
    assert status["available"] is False and status["problem"] == "provider_unavailable"
    # No preview either: there is nothing it may send (the consent/dispatch path never starts).
    for call in (provider.chat, provider.render):
        with pytest.raises(ChatError) as err:
            call("S", [{"role": "user", "content": "q"}], "")
        assert err.value.code == "provider_unavailable"
    assert seen == []


def test_an_allowed_remote_ollama_is_a_remote_destination(monkeypatch):
    provider, seen = _chat(monkeypatch, REMOTE, allow_remote=True)
    status = provider.status()
    assert status["available"] is True and status["local"] is False  # consent gate applies
    assert provider.local is False
    assert "gpu-box.invalid:11434" in provider.destination
    assert provider.destination != "Bu bilgisayar"
    assert seen  # it may be contacted: the user allowed it


def test_the_local_ollama_is_still_this_computer(monkeypatch):
    provider, _seen = _chat(monkeypatch, "http://127.0.0.1:11434")
    assert provider.local is True and provider.destination == "Bu bilgisayar"
    assert provider.status()["available"] is True


def test_the_remote_destination_never_shows_credentials(monkeypatch):
    provider, _seen = _chat(monkeypatch, "http://user:s3cret@gpu-box.invalid:11434",
                            allow_remote=True)
    assert "s3cret" not in provider.destination and "user" not in provider.destination


# ------------------------------------------------------------------ no proxy for the auditor


def _serve(name: str, hits: dict, body: dict) -> http.server.ThreadingHTTPServer:
    class Handler(http.server.BaseHTTPRequestHandler):
        def _answer(self) -> None:
            hits[name] += 1
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = _answer

        def log_message(self, *_args) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_the_auditor_never_goes_through_a_proxy(monkeypatch):
    hits = {"ollama": 0, "proxy": 0}
    reply = {"models": [{"name": "m"}], "message": {"content": CLEAN}}
    ollama, proxy = _serve("ollama", hits, reply), _serve("proxy", hits, reply)
    try:
        for key in ("NO_PROXY", "no_proxy", "ALL_PROXY", "all_proxy"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy.server_port}")
        monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{proxy.server_port}")
        provider = OllamaProvider(f"http://127.0.0.1:{ollama.server_port}", "m")
        assert provider.is_available() is True
        assert "approved" in provider.complete("system", "user")
        assert hits == {"ollama": 2, "proxy": 0}
    finally:
        ollama.shutdown()
        proxy.shutdown()
