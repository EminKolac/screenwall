"""Where Ollama may run: this computer, unless the user explicitly allows a remote host.

OLLAMA_BASE_URL feeds two paths: the pre-approval auditor, which receives masked but NOT yet
approved text, and post-approval chat. Both used to treat any URL as local, so a remote host got
that text over plain HTTP while the UI said "Bu bilgisayar". The URL is now checked before any
request. A non-loopback host needs `ollama_allow_remote`: without it the auditor fails closed
(documents go to review) and Ollama chat is unavailable; with it, Ollama chat is a remote
destination behind the consent preview. Ollama "cloud" models (`gpt-oss:120b-cloud`, `x:cloud`)
are served by ollama.com through the local daemon, so a loopback URL is not enough: those names
are refused in every mode.
"""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

LOCAL_DESTINATION = "Bu bilgisayar"
# Reason codes (logged and tested, never shown raw).
REMOTE_HOST = "remote_host"
CLOUD_MODEL = "cloud_model"


def _hostname(url: str) -> str | None:
    """Lower-cased host without brackets or credentials; None unless the URL is http(s)."""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    return parts.hostname


def is_loopback_url(url: str) -> bool:
    """True only for localhost, 127.0.0.0/8 and ::1 (an IPv4-mapped loopback included)."""
    host = _hostname(url)
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:  # any other name, however local it sounds, may resolve elsewhere
        return False
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_loopback


def is_cloud_model(model: str) -> bool:
    name = (model or "").strip().lower()
    name = name.removesuffix(":latest")
    return name.endswith(("-cloud", ":cloud"))


def refusal(base_url: str, model: str, allow_remote: bool) -> str | None:
    """None when this endpoint and model may be used; otherwise the reason code."""
    if is_cloud_model(model):
        return CLOUD_MODEL
    if not allow_remote and not is_loopback_url(base_url):
        return REMOTE_HOST
    return None


def destination(base_url: str) -> str:
    """Where chat text goes, as the consent dialog names it: this computer, or the remote
    host and port (never the URL's credentials or path)."""
    if is_loopback_url(base_url):
        return LOCAL_DESTINATION
    host = _hostname(base_url) or "?"
    if ":" in host:
        host = f"[{host}]"
    try:
        port = urlsplit(base_url.strip()).port
    except ValueError:
        port = None
    return f"Uzak Ollama ({host}:{port})" if port else f"Uzak Ollama ({host})"
