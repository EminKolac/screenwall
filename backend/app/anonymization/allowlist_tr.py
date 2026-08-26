"""Türkçe kurumsal/hukuki/muhasebe allow-list — GoldBench'in "her koşulda maskeleme" bulgusuna
karşı ana savunma.

GoldBench 12 belgelik ilk koşuda 24/24 sıradan iş teriminin ("Genel Kurul", "Fatura Dönemi",
"Risk Değerlendirmesi"…) maskelendiğini ölçtü — over_masking_rate = 1.0. Bu liste, projenin
`evaluation/goldbench/templates.py:NO_MASK_TERMS` tohum listesinin gerçek-dünya ölçekli hâlidir.

Neden bir sözlük ve neden bir etiket-indirimi DEĞİL: `low_score_entity_names` (nlp.py) tüm bir
NER ailesini (örn. LOCATION) köreltir — gerçek adres tespitini de birlikte götürür. Allow-list
yalnızca LİSTEDEKİ belirli terimleri bastırır; hiçbir gerçek PII'nin recall'una dokunmaz. Bu yüzden
kalibrasyonun en düşük riskli aracıdır ve öncelik ondadır.

Kaynak: yaygın Türkçe kurumsal/hukuki/muhasebe terminolojisi (KVKK/TTK/VUK sözlüğü, şirket genel
kurul/yönetim kurulu dili, standart sözleşme maddeleri, muhasebe/finans terimleri). Listeler
büyük/küçük harf ve boşluk-esnek eşleşir (bkz. `presidio_engine.py`'deki uygulama noktası).
"""
from __future__ import annotations

# Şirket / kurumsal yönetim
_CORPORATE = [
    "Genel Kurul", "Yönetim Kurulu", "Denetim Kurulu", "Faaliyet Raporu",
    "Olağan Genel Kurul", "Olağanüstü Genel Kurul", "Yönetim Kurulu Kararı",
    "İcra Kurulu", "Murahhas Üye", "Bağımsız Üye", "Bağımsız Denetim",
    "Kurumsal Yönetim İlkeleri", "Esas Sözleşme", "Ticaret Sicili", "Ticaret Sicil Gazetesi",
    "Sermaye Piyasası Kurulu", "Kamuyu Aydınlatma Platformu", "Pay Sahipleri",
]

# Sözleşme / hukuk
_LEGAL = [
    "Sözleşme Bedeli", "Teslim Tarihi", "Ödeme Planı", "Cayma Hakkı", "Fesih Bildirimi",
    "Mücbir Sebep", "Gizlilik Sözleşmesi", "Rekabet Yasağı", "Uyuşmazlık Çözümü",
    "Yetkili Mahkeme", "Tahkim Şartı", "Temerrüt Faizi", "Kesin Teminat", "Geçici Teminat",
    "İhtarname", "Protokol", "Ek Protokol", "Taraflar Arasında", "İşbu Sözleşme",
    "Hizmet Sözleşmesi", "Kira Sözleşmesi", "Satış Sözleşmesi", "İş Sözleşmesi",
]

# Muhasebe / finans
_FINANCE = [
    "Fatura Dönemi", "Gider Pusulası", "Vergi Matrahı", "Katma Değer Vergisi",
    "Gelir Vergisi", "Kurumlar Vergisi", "Stopaj", "Amortisman", "Bilanço",
    "Gelir Tablosu", "Nakit Akış Tablosu", "Bağımsız Denetim Raporu", "Mizan",
    "Cari Hesap Ekstresi", "Hesap Özeti", "Ödeme Bildirimi", "Tahsilat Makbuzu",
    "Kredi Notu", "Risk Değerlendirmesi", "Teminat Mektubu",
]

# İnsan kaynakları / özlük
_HR = [
    "İş Sağlığı ve Güvenliği", "Yıllık İzin", "Kıdem Tazminatı", "İhbar Tazminatı",
    "Performans Değerlendirmesi", "Disiplin Yönetmeliği", "Özlük Dosyası",
    "İş Sözleşmesi Feshi", "Deneme Süresi", "Fazla Mesai", "Sosyal Güvenlik Kurumu",
    "Bordro", "Ücret Bordrosu", "Kalite Kontrol", "Kalite Yönetim Sistemi",
]

# Kamu / idari
_PUBLIC = [
    "Başvuru Dilekçesi", "İlgili Makam", "Yetkili Kurum", "Resmi Gazete",
    "Kamu İhale Kurumu", "Valilik", "Kaymakamlık", "Belediye Meclisi",
    "İmar Planı", "Ruhsat Başvurusu", "Bilgi Edinme Başvurusu",
]

TR_ALLOWLIST: frozenset[str] = frozenset(_CORPORATE + _LEGAL + _FINANCE + _HR + _PUBLIC)


def default_allow_list() -> list[str]:
    """Sabit Türkçe sözlük, alfabetik ve yinelenmesiz."""
    return sorted(TR_ALLOWLIST)
