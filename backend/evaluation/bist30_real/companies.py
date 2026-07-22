"""Verified BIST-30 (XU030) constituent list used by the benchmark corpus.

Verification (2026-07-22): two independent public component lists agreed on the identical
30-ticker set — Midas (getmidas.com/canli-borsa/xu030-bist-30-hisseleri) and CNN Türk Finans
(finans.cnnturk.com/canli-borsa/bist-30-hisseleri, "19 Temmuz 18:10" snapshot). The two
post-2025 additions (DSTKF, TRALT) were additionally confirmed against Borsa İstanbul data via
the Fintables symbol registry. The index is rebalanced quarterly; re-verify before reusing.
"""
from __future__ import annotations

VERIFIED_ON = "2026-07-22"
SOURCES = [
    "https://www.getmidas.com/canli-borsa/xu030-bist-30-hisseleri",
    "https://finans.cnnturk.com/canli-borsa/bist-30-hisseleri",
]

# ticker -> company name
BIST30: dict[str, str] = {
    "AEFES": "Anadolu Efes",
    "AKBNK": "Akbank",
    "ASELS": "Aselsan",
    "ASTOR": "Astor Enerji",
    "BIMAS": "BİM Birleşik Mağazalar",
    "DSTKF": "Destek Finans Faktoring",
    "EKGYO": "Emlak Konut GYO",
    "ENKAI": "Enka İnşaat",
    "EREGL": "Ereğli Demir ve Çelik",
    "FROTO": "Ford Otosan",
    "GARAN": "Garanti BBVA",
    "GUBRF": "Gübre Fabrikaları",
    "ISCTR": "Türkiye İş Bankası (C)",
    "KCHOL": "Koç Holding",
    "KRDMD": "Kardemir (D)",
    "MGROS": "Migros Ticaret",
    "PETKM": "Petkim",
    "PGSUS": "Pegasus Hava Taşımacılığı",
    "SAHOL": "Sabancı Holding",
    "SASA": "SASA Polyester",
    "SISE": "Şişecam",
    "TAVHL": "TAV Havalimanları",
    "TCELL": "Turkcell",
    "THYAO": "Türk Hava Yolları",
    "TOASO": "Tofaş",
    "TRALT": "Türk Altın İşletmeleri",
    "TTKOM": "Türk Telekom",
    "TUPRS": "Tüpraş",
    "VAKBN": "VakıfBank",
    "YKBNK": "Yapı Kredi",
}
