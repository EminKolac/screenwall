"""Chat providers (status + error mapping), the factory and the chat settings."""
from __future__ import annotations

import httpx
import pytest

from app.chat import cli
from app.chat.base import ChatError
from app.chat.factory import PROVIDER_IDS, build_provider
from app.chat.providers import ClaudeCliProvider, CodexCliProvider, OllamaChatProvider
from app.chat.schemas import ProviderStatus
from app.config import Settings, get_settings
from tests import posix_only
from tests.fixtures.fake_cli import PROVIDER_BINARY, install_fake_cli

STATUS_KEYS = set(ProviderStatus.model_fields)


def _ollama(monkeypatch, handler, model: str = "qwen3.5:4b") -> OllamaChatProvider:
    monkeypatch.setattr(OllamaChatProvider, "transport", httpx.MockTransport(handler))
    return OllamaChatProvider("http://localhost:11434/", model)


def _tags(*names: str):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        assert request.extensions["timeout"]["connect"] == 2.0  # the 2 s status probe
        return httpx.Response(200, json={"models": [{"name": n, "model": n} for n in names]})

    return handler


# ------------------------------------------------------------------ Ollama


def test_ollama_status_available(monkeypatch):
    status = _ollama(monkeypatch, _tags("nomic-embed-text:latest", "qwen3.5:4b")).status()
    assert set(status) == STATUS_KEYS
    assert status["available"] is True and status["problem"] is None
    assert status["id"] == "ollama" and status["local"] is True
    assert status["label"] == "Lokal LLM (Ollama)" and status["model"] == "qwen3.5:4b"
    assert status["installed"] is None and status["login_command"] is None


def test_ollama_status_accepts_the_implicit_latest_tag(monkeypatch):
    assert _ollama(monkeypatch, _tags("llama3:latest"), model="llama3").status()["available"]


def test_ollama_status_model_missing(monkeypatch):
    status = _ollama(monkeypatch, _tags("llama3:latest")).status()
    assert status["available"] is False and status["problem"] == "model_missing"


@pytest.mark.parametrize("failure", ["connect", "http_500", "garbage"])
def test_ollama_status_unreachable(monkeypatch, failure):
    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "connect":
            raise httpx.ConnectError("connection refused", request=request)
        if failure == "http_500":
            return httpx.Response(500)
        return httpx.Response(200, content=b"<html>not json</html>")

    status = _ollama(monkeypatch, handler).status()
    assert status["available"] is False and status["problem"] == "ollama_unreachable"


def test_ollama_never_uses_proxy_environment(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
    with OllamaChatProvider("http://localhost:11434", "m")._client(1.0) as client:
        assert client.trust_env is False


def test_ollama_chat_success_and_body(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "cevap [S1]"}})

    provider = _ollama(monkeypatch, handler)
    messages = [{"role": "user", "content": "Kira?"}]
    assert provider.chat("SYSTEM", messages, "ignored-model") == "cevap [S1]"
    [request] = seen
    assert request.url.path == "/api/chat"
    assert request.content == provider.render("SYSTEM", messages, "ignored-model").encode("utf-8")


@pytest.mark.parametrize(
    "response,code",
    [
        ("connect", "ollama_unreachable"),
        ("timeout", "ollama_unreachable"),
        (httpx.Response(404, json={"error": 'model "x" not found, try pulling it first'}),
         "model_missing"),
        (httpx.Response(500, json={"error": "boom"}), "provider_unavailable"),
        (httpx.Response(200, content=b"not json"), "provider_unavailable"),
        (httpx.Response(200, json={"message": {"content": 42}}), "provider_unavailable"),
    ],
)
def test_ollama_chat_failures_are_fixed_codes(monkeypatch, response, code):
    def handler(request: httpx.Request) -> httpx.Response:
        if response == "connect":
            raise httpx.ConnectError("connection refused", request=request)
        if response == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        return response

    with pytest.raises(ChatError) as err:
        _ollama(monkeypatch, handler).chat("S", [{"role": "user", "content": "q"}], "m")
    assert err.value.code == code


# ------------------------------------------------------------------ CLI providers


@pytest.fixture
def fakes(tmp_path, monkeypatch):
    installed = {p: install_fake_cli(tmp_path / "bin", b) for p, b in PROVIDER_BINARY.items()}
    monkeypatch.setattr(cli, "executable", lambda provider: str(installed[provider].path))
    return installed


@pytest.mark.parametrize(
    "cls,label,login",
    [
        (ClaudeCliProvider, "Claude", "claude auth login"),
        (CodexCliProvider, "ChatGPT (Codex CLI)", "codex login"),
    ],
)
@posix_only.FAKE_CLI
def test_cli_status_available(cls, label, login, fakes):
    status = cls("some-model", 60).status()
    assert set(status) == STATUS_KEYS
    assert status["available"] is True and status["problem"] is None
    assert status["local"] is False and status["label"] == label
    assert status["installed"] and status["compatible"] and status["authenticated"]
    assert status["version"] in ("2.1.280", "0.154.0")
    assert status["login_command"] == login and status["model"] == "some-model"
    assert "canary" not in repr(status) and "org-" not in repr(status)  # no account details


@pytest.mark.parametrize(
    "mode,problem,field",
    [("logged_out", "cli_login_required", "authenticated"),
     ("old_help", "cli_upgrade_required", "compatible")],
)
@pytest.mark.parametrize("provider_id", sorted(PROVIDER_BINARY))
@posix_only.FAKE_CLI
def test_cli_status_problems(provider_id, mode, problem, field, fakes):
    fakes[provider_id].set(mode)
    status = build_provider(provider_id, get_settings()).status()
    assert status["available"] is False and status["problem"] == problem
    assert status[field] is False and status["installed"] is True
    assert status["model"] is None  # "" = the CLI's own default


@posix_only.FAKE_CLI  # Windows: unsupported_os before any lookup
def test_cli_status_not_installed(monkeypatch):
    monkeypatch.setattr(cli, "executable", lambda _: None)
    status = ClaudeCliProvider().status()
    assert status["problem"] == "cli_not_found" and status["installed"] is False
    assert status["compatible"] is None and status["authenticated"] is None
    assert status["login_command"] == "claude auth login"


@posix_only.FAKE_CLI
def test_cli_status_survives_a_hanging_cli(monkeypatch):
    def hang(_):
        raise cli.CliError("cli_timeout")

    monkeypatch.setattr(cli, "status", hang)
    status = CodexCliProvider().status()
    assert status["available"] is False and status["problem"] == "cli_timeout"


@posix_only.FAKE_CLI  # Windows: render refuses (provider_unavailable)
def test_cli_provider_render_is_the_stdin_envelope():
    messages = [{"role": "user", "content": "Kira ne kadar?"}]
    assert ClaudeCliProvider().render("SYS", messages) == cli.envelope("SYS", messages)


@posix_only.FAKE_CLI
def test_cli_provider_unexpected_failure_is_cli_failed(monkeypatch):
    def broken(*_a, **_k):
        raise OSError("disk full: /private/var/secret-path")

    monkeypatch.setattr(cli, "complete", broken)
    with pytest.raises(cli.CliError) as err:
        ClaudeCliProvider().chat("S", [], "")
    assert err.value.code == "cli_failed" and "secret" not in str(err.value)


# ------------------------------------------------------------------ factory + settings


def test_factory_builds_each_provider_from_settings(monkeypatch):
    monkeypatch.setenv("CHAT_CLAUDE_MODEL", "sonnet")
    monkeypatch.setenv("CHAT_CODEX_MODEL", "gpt-5.1-codex")
    monkeypatch.setenv("CHAT_CLI_TIMEOUT_S", "45")
    get_settings.cache_clear()
    settings = get_settings()
    built = {pid: build_provider(pid, settings) for pid in PROVIDER_IDS}
    assert isinstance(built["ollama"], OllamaChatProvider)
    assert built["ollama"].model == settings.chat_ollama_model
    assert isinstance(built["claude_cli"], ClaudeCliProvider)
    assert (built["claude_cli"].model, built["claude_cli"].timeout) == ("sonnet", 45)
    assert isinstance(built["codex_cli"], CodexCliProvider)
    assert built["codex_cli"].model == "gpt-5.1-codex"
    assert {p.destination for p in built.values()} == {
        "Bu bilgisayar", "Anthropic (Claude)", "OpenAI (ChatGPT)"
    }
    with pytest.raises(ChatError) as err:
        build_provider("openai", settings)
    assert err.value.code == "provider_unavailable"


def test_cli_timeout_setting_is_bounded():
    assert build_provider("claude_cli", Settings(chat_cli_timeout_s=0)).timeout == 5
    assert build_provider("codex_cli", Settings(chat_cli_timeout_s=10_000)).timeout == 600


def test_chat_settings_defaults_and_validation(monkeypatch):
    settings = Settings()
    assert settings.chat_default_provider == "ollama"
    assert (settings.chat_claude_model, settings.chat_codex_model) == ("", "")
    assert settings.chat_cli_timeout_s == 60
    assert not hasattr(settings, "chat_provider")  # the unused field is gone
    monkeypatch.setenv("CHAT_PROVIDER", "ollama")  # a stale .env line is ignored, not an error
    assert Settings(chat_default_provider="codex_cli").chat_default_provider == "codex_cli"
    with pytest.raises(ValueError):
        Settings(chat_default_provider="openai")
