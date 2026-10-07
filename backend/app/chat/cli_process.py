"""Run one CLI child process safely. Split out of chat/cli.py; the behaviour is unchanged.

  - no shell: the caller passes argv, and document content travels only through stdin;
  - a filtered child environment (no API keys, proxies, project hooks or debug flags) and a fixed
    PATH, so a Finder-launched app still finds the CLI;
  - non-blocking, bounded streams (one combined output limit) under a deadline;
  - the child runs in its own process group, which is killed afterwards in every case, so no
    descendant outlives the call;
  - only CliError codes (the contract's cli_* ErrorCodes) leave, never CLI stderr.

POSIX only (`supported`): the process-group kill (os.killpg, SIGKILL, start_new_session),
non-blocking pipes under `selectors` and the fixed PATH have no Windows equivalent here. On
Windows the CLI providers report "unsupported_os" (chat/providers.py) and `run` refuses before
anything is spawned.
"""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from pathlib import Path

# The only codes that may leave the CLI layer (contract ErrorCode, frontend/src/api/contract.ts).
ERROR_CODES = frozenset(
    {
        "cli_not_found",
        "cli_upgrade_required",
        "cli_login_required",
        "cli_timeout",
        "cli_output_limit",
        "cli_failed",
        "cli_unsafe_output",
    }
)
_CHUNK = 8192


class CliError(Exception):
    """Only these fixed codes may cross the HTTP boundary; never CLI stderr."""

    def __init__(self, code: str):
        # Anything outside the contract collapses to the generic failure code.
        self.code = code if code in ERROR_CODES else "cli_failed"
        super().__init__(self.code)


def supported() -> bool:
    """False on Windows: `run` needs POSIX process groups and selectable pipes."""
    return os.name != "nt"


def environment() -> dict[str, str]:
    # Preserve account discovery, not API secrets, proxies, project hooks or debug flags.
    env = {
        k: os.environ[k]
        for k in ("HOME", "USER", "LOGNAME", "TMPDIR", "CODEX_HOME")
        if k in os.environ
    }
    env.update(
        {
            "PATH": f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
            "LANG": "en_US.UTF-8",
            "NO_COLOR": "1",
            "RUST_LOG": "off",
            "CLAUDE_CODE_DISABLE_ATTACHMENTS": "1",
            "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
            "CLAUDE_CODE_DISABLE_ADVISOR_TOOL": "1",
            "CLAUDE_CODE_DISABLE_AGENT_VIEW": "1",
            "CLAUDE_CODE_DISABLE_ARTIFACT": "1",
            "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
            "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1",
            "CLAUDE_CODE_DEBUG_LOGS_DIR": os.devnull,
            "CLAUDE_CODE_DEBUG_LOG_LEVEL": "error",
        }
    )
    return env


class _Pipes:
    """Non-blocking stdin writer and stdout/stderr reader over one selector, output bounded."""

    def __init__(self, proc: subprocess.Popen, selector: selectors.BaseSelector, stdin: str,
                 limit: int) -> None:
        self.selector = selector
        self.output = {"out": bytearray(), "err": bytearray()}
        self.pending = memoryview(stdin.encode())
        self.limit = limit
        for pipe, name in ((proc.stdout, "out"), (proc.stderr, "err")):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        if self.pending:
            os.set_blocking(proc.stdin.fileno(), False)
            selector.register(proc.stdin, selectors.EVENT_WRITE, "in")
        else:
            proc.stdin.close()

    def pump(self, deadline: float) -> None:
        """Until every stream is closed; raises on the deadline or the output limit."""
        while self.selector.get_map():
            if time.monotonic() >= deadline:
                raise CliError("cli_timeout")
            for key, _ in self.selector.select(min(0.1, max(0, deadline - time.monotonic()))):
                if key.data == "in":
                    self._write(key)
                else:
                    self._read(key)

    def text(self, name: str) -> str:
        return self.output[name].decode("utf-8", "replace")

    def _write(self, key: selectors.SelectorKey) -> None:
        try:
            self.pending = self.pending[os.write(key.fd, self.pending[:_CHUNK]) :]
        except BrokenPipeError:
            self.pending = memoryview(b"")
        if not self.pending:
            self._close(key)

    def _read(self, key: selectors.SelectorKey) -> None:
        chunk = os.read(key.fd, _CHUNK)
        if not chunk:
            self._close(key)
            return
        self.output[key.data].extend(chunk)
        if sum(map(len, self.output.values())) > self.limit:
            raise CliError("cli_output_limit")

    def _close(self, key: selectors.SelectorKey) -> None:
        self.selector.unregister(key.fileobj)
        key.fileobj.close()


def _spawn(argv: list[str], cwd: str) -> subprocess.Popen:
    try:
        return subprocess.Popen(
            argv,
            cwd=cwd,
            env=environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError:
        raise CliError("cli_not_found") from None


def _reap(proc: subprocess.Popen, selector: selectors.BaseSelector) -> None:
    # Even a completed parent can leave a child behind. Never retain agent workers.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    proc.wait()
    selector.close()
    for pipe in (proc.stdin, proc.stdout, proc.stderr):
        pipe.close()


def run(
    argv: list[str], *, cwd: str, stdin: str = "", timeout: float = 60, limit: int = 512_000
) -> tuple[int, str, str]:
    """Bound all streams and kill the process group on timeout, including descendants."""
    if not supported():  # last line of defence; the providers stop earlier (unsupported_os)
        raise CliError("cli_failed")
    proc = _spawn(argv, cwd)
    selector = selectors.DefaultSelector()
    deadline = time.monotonic() + timeout
    try:
        pipes = _Pipes(proc, selector, stdin, limit)
        pipes.pump(deadline)
        try:
            code = proc.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise CliError("cli_timeout") from None
        return code, pipes.text("out"), pipes.text("err")
    finally:
        _reap(proc, selector)
