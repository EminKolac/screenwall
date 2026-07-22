"""Runtime egress guard: prove the pipeline makes ZERO non-local network calls.

Patches `socket.socket.connect` (which every stdlib/httpx/urllib TCP path ultimately hits) so any
attempt to reach a non-loopback address raises `BlockedEgress` AND is recorded. Loopback and unix
sockets stay allowed (Ollama et al. are local by design; the benchmark auditor config skips even
those). This turns the platform's "no external calls before approval" invariant from a code-review
claim into a measured property of every benchmark run.
"""
from __future__ import annotations

import socket
from contextlib import contextmanager

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


class BlockedEgress(ConnectionError):
    pass


def _is_local(address) -> bool:
    if not isinstance(address, tuple):  # AF_UNIX path
        return True
    host = str(address[0])
    return host in _LOOPBACK or host.startswith("127.")


@contextmanager
def egress_guard(log: list[str]):
    """Block + record every non-loopback connect attempt inside the context."""
    original = socket.socket.connect

    def guarded(self, address):  # noqa: ANN001 — matches socket.socket.connect
        if not _is_local(address):
            log.append(str(address))
            raise BlockedEgress(f"external egress blocked during benchmark: {address}")
        return original(self, address)

    socket.socket.connect = guarded
    try:
        yield log
    finally:
        socket.socket.connect = original
