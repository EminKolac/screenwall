"""app/chat/cli.py against fake `claude` / `codex` executables (tests/fixtures/fake_cli).

The real CLIs are never started: `cli.executable` is pointed at the fakes, which record argv,
cwd, environment, process ids and the exact stdin bytes of every invocation.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

import pytest

from app.chat import cli
from tests.fixtures.fake_cli import PROVIDER_BINARY, install_fake_cli, process_gone

PROVIDERS = sorted(cli.CLI_PROVIDERS)
SYSTEM = "SYNTHETIC-INSTRUCTIONS answer from [S1] only. <PERSON_1> signed."
MESSAGES = [{"role": "user", "content": "SYNTHETIC-QUESTION kim imzaladı?"}]
ANSWERS = {
    "claude_cli": "Sözleşmeyi <PERSON_1> imzaladı [S1].",
    "codex_cli": "The agreement was signed by <PERSON_1> [S1].",
}


@pytest.fixture
def fakes(tmp_path, monkeypatch):
    installed = {
        provider: install_fake_cli(tmp_path / "bin", binary)
        for provider, binary in PROVIDER_BINARY.items()
    }
    monkeypatch.setattr(cli, "executable", lambda provider: str(installed[provider].path))
    return installed


def _complete(provider: str, timeout: float = 30, model: str = "") -> str:
    config = {"provider": provider, "model": model, "timeout": timeout}
    return cli.complete(config, SYSTEM, MESSAGES)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_success_realistic_stream_content_only_on_stdin(provider, fakes):
    assert _complete(provider) == ANSWERS[provider]

    [call] = fakes[provider].chat_calls()
    # Content only through the stdin envelope, byte for byte; never in argv.
    assert fakes[provider].stdin_bytes(call) == cli.envelope(SYSTEM, MESSAGES).encode("utf-8")
    assert "SYNTHETIC" not in " ".join(call["argv"])
    # A fresh, empty, private temp dir that is gone afterwards; own process group.
    assert Path(call["cwd"]).name.startswith("fable-chat-")
    assert call["cwd_listing"] == []
    assert not os.path.exists(call["cwd"])
    assert call["pgid"] == call["pid"]
    checks = [c for c in fakes[provider].calls() if c is not call and c["stdin"] == ""]
    assert len(checks) == 3  # --version, --help, auth/login status
    assert all(Path(c["cwd"]).name.startswith("fable-cli-check-") for c in checks)


def test_claude_safety_flags(fakes):
    _complete("claude_cli")
    argv = fakes["claude_cli"].chat_calls()[0]["argv"]
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert argv[argv.index("--mcp-config") + 1] == '{"mcpServers":{}}'
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    for flag in ("--print", "--safe-mode", "--restricted", "--strict-mcp-config",
                 "--no-session-persistence", "--disable-slash-commands", "--no-chrome"):
        assert flag in argv


def test_codex_safety_flags(fakes):
    _complete("codex_cli")
    [call] = fakes["codex_cli"].chat_calls()
    argv = call["argv"]
    assert argv[0] == "exec" and argv[-1] == "-"
    for flag in ("--ignore-user-config", "--ignore-rules", "--ephemeral", "--json"):
        assert flag in argv
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert "features.shell_tool=false" in argv and 'web_search="disabled"' in argv
    # -C is the same empty temp dir the process runs in (macOS: /var -> /private/var).
    assert os.path.realpath(argv[argv.index("-C") + 1]) == os.path.realpath(call["cwd"])


@pytest.mark.parametrize("provider", PROVIDERS)
def test_tool_use_is_rejected(provider, fakes):
    fakes[provider].set("tool_use")
    with pytest.raises(cli.CliError) as err:
        _complete(provider)
    assert err.value.code == "cli_unsafe_output"


def test_claude_with_tools_enabled_is_rejected(fakes):
    fakes["claude_cli"].set("tools_enabled")
    with pytest.raises(cli.CliError) as err:
        _complete("claude_cli")
    assert err.value.code == "cli_unsafe_output"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_timeout_kills_the_whole_process_group(provider, fakes):
    fakes[provider].set("timeout")
    started = time.monotonic()
    with pytest.raises(cli.CliError) as err:
        _complete(provider, timeout=3)
    assert err.value.code == "cli_timeout"
    assert time.monotonic() - started < 20
    pids = fakes[provider].pids()
    assert process_gone(pids["child"])
    assert process_gone(pids["grandchild"])  # a descendant is killed too, not orphaned


@pytest.mark.parametrize("provider", PROVIDERS)
def test_output_limit(provider, fakes):
    fakes[provider].set("flood")
    with pytest.raises(cli.CliError) as err:
        _complete(provider)
    assert err.value.code == "cli_output_limit"


@pytest.mark.parametrize(
    "mode,code", [("logged_out", "cli_login_required"), ("old_help", "cli_upgrade_required")]
)
@pytest.mark.parametrize("provider", PROVIDERS)
def test_failed_preflight_never_sends_content(provider, mode, code, fakes):
    fakes[provider].set(mode)
    with pytest.raises(cli.CliError) as err:
        _complete(provider)
    assert err.value.code == code
    assert fakes[provider].chat_calls() == []
    assert all("SYNTHETIC" not in c["stdin"] for c in fakes[provider].calls())


@pytest.mark.parametrize("provider", PROVIDERS)
def test_not_installed(provider, monkeypatch):
    monkeypatch.setattr(cli, "executable", lambda _: None)
    with pytest.raises(cli.CliError) as err:
        _complete(provider)
    assert err.value.code == "cli_not_found"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_nonzero_exit_never_exposes_stderr(provider, fakes):
    fakes[provider].set("exit_error")
    with pytest.raises(cli.CliError) as err:
        _complete(provider)
    assert err.value.code == "cli_failed"
    assert "CANARY" not in str(err.value) and "CANARY" not in repr(err.value.args)


@pytest.mark.parametrize(
    "provider,mode", [("codex_cli", "turn_failed"), ("claude_cli", "error_result")]
)
def test_failed_turn_is_not_an_answer(provider, mode, fakes):
    fakes[provider].set(mode)
    with pytest.raises(cli.CliError) as err:
        _complete(provider)
    assert err.value.code == "cli_failed"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_environment_filtering(provider, fakes, monkeypatch):
    secrets = {
        "OPENAI_API_KEY": "sk-canary-openai-key",
        "ANTHROPIC_API_KEY": "sk-ant-canary-key",
        "CLAUDE_CODE_OAUTH_TOKEN": "canary-oauth-token",
        "HTTPS_PROXY": "http://canary-proxy.invalid:8080",
        "NODE_OPTIONS": "--require /tmp/canary-hook.js",
    }
    for key, value in secrets.items():
        monkeypatch.setenv(key, value)
    assert _complete(provider) == ANSWERS[provider]
    calls = fakes[provider].calls()
    assert len(calls) == 4
    for call in calls:  # every child: version/help/auth checks and the chat call
        env = call["env"]
        assert not set(secrets) & set(env)
        assert not any("canary" in value for value in env.values())
        assert env["PATH"].endswith("/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin")
        assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"


def test_status_returns_no_account_details(fakes):
    result = cli.status("claude_cli")
    assert result["installed"] and result["compatible"] and result["authenticated"]
    assert result["version"] == "2.1.280"
    assert "canary" not in repr(result) and "org-" not in repr(result)
    codex = cli.status("codex_cli")
    assert codex["authenticated"] and codex["version"] == "0.154.0"


def test_model_cannot_become_an_argument():
    for model in ("--resume", "$(touch /tmp/never)", "model\n--dangerously-bypass", "-x"):
        with pytest.raises(cli.CliError) as err:
            cli.command("codex_cli", "/binary", "/empty", model)
        assert err.value.code == "cli_failed"
    assert cli.command("claude_cli", "/binary", "/empty", "sonnet")[-2:] == ["--model", "sonnet"]


def test_error_codes_are_exactly_the_contract_cli_codes():
    contract = Path(__file__).resolve().parents[3] / "frontend/src/api/contract.ts"
    if not contract.exists():
        pytest.skip("frontend contract not present")
    block = contract.read_text(encoding="utf-8").split("export type ErrorCode", 1)[1]
    declared = set(re.findall(r'"(cli_[a-z_]+)"', block.split(";", 1)[0]))
    assert declared == set(cli.ERROR_CODES)
    assert cli.CliError("cli_invalid_model").code == "cli_failed"  # nothing else leaks out


@pytest.mark.parametrize("output", ["", "not json", "{}", "null", "[]"])
def test_invalid_output_is_safe(output):
    for provider in PROVIDERS:
        with pytest.raises(cli.CliError):
            cli.parse(provider, output)
