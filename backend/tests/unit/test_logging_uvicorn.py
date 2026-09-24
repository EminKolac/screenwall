"""uvicorn's loggers must pass through the PII redaction filter too.

uvicorn installs its own handlers ("uvicorn" for itself and "uvicorn.error", "uvicorn.access" for
the request lines) and neither propagates to the root logger, so a filter on the root handlers
never saw an access line's query string or an ASGI exception's traceback. The fixture rebuilds
uvicorn's default layout (uvicorn.config.LOGGING_CONFIG) by hand: dictConfig would close pytest's
own handlers.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

import pytest
from uvicorn.logging import AccessFormatter, DefaultFormatter

from app.security.logging import PIIRedactionFilter, configure_pii_safe_logging

NAMES = ("uvicorn", "uvicorn.error", "uvicorn.access")
EMAIL = "ayse.kaya@example.com"
TCKN = "10000000146"


@pytest.fixture
def uvicorn_logs():
    saved = {n: logging.getLogger(n) for n in NAMES}
    state = {n: (lg.handlers[:], lg.filters[:], lg.propagate, lg.level) for n, lg in saved.items()}
    streams = {"error": io.StringIO(), "access": io.StringIO()}
    default = logging.StreamHandler(streams["error"])
    default.setFormatter(DefaultFormatter("%(levelprefix)s %(message)s", use_colors=False))
    access = logging.StreamHandler(streams["access"])
    access.setFormatter(AccessFormatter(
        '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False))
    layout = {"uvicorn": ([default], False), "uvicorn.error": ([], True),
              "uvicorn.access": ([access], False)}
    for name, (handlers, propagate) in layout.items():
        saved[name].handlers = handlers
        saved[name].propagate = propagate
        saved[name].setLevel(logging.INFO)
    yield streams
    for name, (handlers, filters, propagate, level) in state.items():
        saved[name].handlers, saved[name].filters = handlers, filters
        saved[name].propagate = propagate
        saved[name].setLevel(level)


def test_uvicorn_error_and_access_lines_are_redacted(uvicorn_logs):
    configure_pii_safe_logging()
    configure_pii_safe_logging()  # idempotent: one filter per handler
    logging.getLogger("uvicorn.error").error("upload from %s failed (%s)", EMAIL, TCKN)
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "127.0.0.1:50000", "GET", f"/api/documents?who={EMAIL}",
        "1.1", 200)
    error, access = uvicorn_logs["error"].getvalue(), uvicorn_logs["access"].getvalue()
    assert EMAIL not in error and TCKN not in error and "<EMAIL_REDACTED>" in error
    assert EMAIL not in access
    # The access formatter still gets its five arguments: the line is intact, just redacted.
    assert '127.0.0.1:50000 - "GET /api/documents?who=<EMAIL_REDACTED> HTTP/1.1" 200' in access
    for name in ("uvicorn", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            assert sum(isinstance(f, PIIRedactionFilter) for f in handler.filters) == 1


def test_uvicorn_exception_tracebacks_are_redacted(uvicorn_logs):
    configure_pii_safe_logging()
    try:
        raise ValueError(f"bad cell {EMAIL}")
    except ValueError:
        logging.getLogger("uvicorn.error").exception("Exception in ASGI application")
    out = uvicorn_logs["error"].getvalue()
    assert "Traceback" in out and "ValueError: bad cell <EMAIL_REDACTED>" in out
    assert EMAIL not in out


def test_start_script_sets_a_private_umask_before_it_writes_anything():
    script = (Path(__file__).resolve().parents[3] / "start.sh").read_text(encoding="utf-8")
    lines = [line.strip() for line in script.splitlines()]
    assert "umask 077" in lines
    first_write = next(i for i, line in enumerate(lines)
                       if not line.startswith("#") and ("mkdir" in line or ">" in line))
    assert lines.index("umask 077") < first_write
