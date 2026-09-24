"""The analyzer registry: offline e-mail check, and no recognizer that never fired."""
from __future__ import annotations

import socket

import pytest

from app.anonymization.analyzer import _UNUSED, OfflineEmailRecognizer, get_analyzer


def test_email_tld_check_never_touches_the_network(monkeypatch) -> None:
    def refuse(*_args, **_kwargs):
        raise AssertionError("the e-mail recognizer tried to reach the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    recognizer = OfflineEmailRecognizer()
    assert recognizer.validate_result("ayse.kaya@example.com") is True
    assert recognizer.validate_result("ayse.kaya@ornekposta.com.tr") is True
    assert recognizer.validate_result("ayse@host.notarealtldxyz") is False


@pytest.mark.parametrize("language", ["en", "tr"])
def test_registry_uses_the_offline_email_recognizer_only(language: str) -> None:
    recognizers = get_analyzer().registry.get_recognizers(language=language, all_fields=True)
    emails = [r for r in recognizers if r.supported_entities == ["EMAIL_ADDRESS"]]
    assert emails and all(isinstance(r, OfflineEmailRecognizer) for r in emails)
    assert not {r.name for r in recognizers} & _UNUSED
