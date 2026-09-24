"""Install the fake `claude` / `codex` executables into a temp dir for Fable's chat tests.

The scripts are copied with a shebang pointing at the running interpreter (the child
environment's PATH is fixed by app/chat/cli.py, so `/usr/bin/env python3` cannot be relied on)
and made executable. Point `app.chat.cli.executable` at `FakeCli.path` with monkeypatch.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
PROVIDER_BINARY = {"claude_cli": "claude", "codex_cli": "codex"}


class FakeCli:
    def __init__(self, directory: Path, name: str) -> None:
        self.directory = directory
        self.name = name
        self.path = directory / name

    def set(self, mode: str = "success", **extra: object) -> None:
        scenario = {"mode": mode, **extra}
        (self.directory / f"{self.name}.scenario.json").write_text(
            json.dumps(scenario, ensure_ascii=False), encoding="utf-8"
        )

    def calls(self) -> list[dict]:
        log = self.directory / f"{self.name}.calls.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def chat_calls(self) -> list[dict]:
        """Invocations that were real chat calls (not --version / --help / auth checks)."""
        return [c for c in self.calls() if "--print" in c["argv"] or c["argv"][-1:] == ["-"]]

    @staticmethod
    def stdin_bytes(call: dict) -> bytes:
        return base64.b64decode(call["stdin_b64"])

    def pids(self, wait: float = 5.0) -> dict:
        path = self.directory / f"{self.name}.pids.json"
        deadline = time.monotonic() + wait
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        return json.loads(path.read_text(encoding="utf-8"))


def install_fake_cli(directory: Path, name: str, mode: str = "success", **extra: object) -> FakeCli:
    directory.mkdir(parents=True, exist_ok=True)
    body = (SOURCE / name).read_text(encoding="utf-8").split("\n", 1)[1]
    target = directory / name
    target.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    os.chmod(target, 0o700)
    fake = FakeCli(directory, name)
    fake.set(mode, **extra)
    return fake


def process_gone(pid: int, wait: float = 10.0) -> bool:
    """True once `pid` no longer exists (killed and reaped)."""
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:  # the pid now belongs to someone else's process
            return True
        time.sleep(0.05)
    return False
