"""Regression: the heuristic auditor must flag residual API keys / secrets (base Presidio has no
SECRET recognizer), so an unmasked credential can never sit in an APPROVED export — while NOT
flagging ordinary financial prose (the auditor's convergence depends on staying low-false-positive).
Benchmark evidence: canary `secret` leaked into an approved DOCX/PDF export before this backstop.
"""
from __future__ import annotations

from app.audit.heuristic import HeuristicAuditor


def _audit(text: str):
    return HeuristicAuditor().audit(text)


def test_stripe_style_key_flagged():
    res = _audit("Erişim anahtarı sk_live_9Qm2fXbT7hVrN4KpLZ olarak tanımlıdır.")
    assert res.approved is False
    assert any(i.type == "SECRET" for i in res.remaining_sensitive_items)


def test_context_gated_bearer_token_flagged():
    res = _audit("Authorization: Bearer aZ39Kp7Qw12MtokenValue")
    assert res.approved is False


def test_aws_and_github_prefixes_flagged():
    assert _audit("key AKIAIOSFODNN7EXAMPLE end").approved is False
    assert _audit("token ghp_abcdefghij0123456789ABCDEFghijklmnopqr").approved is False


def test_ordinary_financial_prose_not_flagged():
    # No secrets/emails/IBANs/cards/TCKN/phones → must stay approved (no false positive).
    res = _audit("2024 Faaliyet Raporu. Toplam gelir 1.234.567 TL. Vergi Yapısı ve Dosya Adı.")
    assert res.approved is True


def test_placeholder_only_not_flagged():
    # A masked secret (placeholder) must not be re-flagged after stripping tokens.
    assert _audit("Anahtar: <SECRET_1> güvenli şekilde maskelendi.").approved is True
