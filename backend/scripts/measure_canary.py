"""Hızlı kanarya tespit ölçümü — deney döngüsü için (BIST koşusu saatler sürüyor, döngüde
kullanılamaz).

    uv run python scripts/measure_canary.py

Kanarya kataloğunun (evaluation/bist30/canary.py) her değerini İKİ bağlamda ölçer:

  bare      — `inject.py::carrier_text()` ile birebir aynı: "<marker> <value>", bağlam kelimesi
              YOK. BIST canary track'inin gerçekte ölçtüğü şey budur (D1 taramasındaki 136
              isabetin kaynağı burada bulundu).
  contextual— "<context> <value>": gerçek belgelerde bir hesap numarasının yanında neredeyse her
              zaman "Müşteri No" gibi bir etiket bulunur.

İkisini AYRI raporlamak şart: yalnız `bare`e bakmak bağlam-kapılı tanıcıları (TR_ACCOUNT gibi)
haksız yere başarısız gösterir; yalnız `contextual`a bakmak ise gerçek bir boşluğu gizler.

Ayrıca `over_mask_probe`: kanarya İÇERMEYEN sıradan Türkçe iş metinlerinde kaç maskeleme
yapıldığını sayar — bir tanıyıcıyı gevşetmenin bedelini aynı koşuda görmek için (aksi halde
recall'u yükseltip aşırı-maskelemeyi sessizce geri getirmek mümkün).

Deterministik: aynı kod → aynı sayı. Ağ yok, disk yok.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Kanarya taşımayan, sıradan Türkçe kurumsal/finansal cümleler — hiçbiri maskelenmemeli.
#
# KASITLI OLARAK allow-list'te OLMAYAN terimlerden kuruldu. Gerekçe (bu oturumda ölçüldü):
# GoldBench'in 11 NO_MASK teriminin 11'i de `allowlist_tr.TR_ALLOWLIST` içinde — yani GoldBench'in
# `over_masking_rate = 0.000` skoru, allow-list'in TAM O terimleri kapsamasının bir sonucu, aşırı-
# maskelemenin çözüldüğünün kanıtı DEĞİL. Bu prob o kör noktayı ölçer.
#
# Her terim HEM cümle başında HEM cümle ortasında geçiyor: ilk taslakta tüm yanlış pozitifler
# cümle başındaydı ve bu, "büyük harf = özel isim" sinyalini ölçülemez kılıyordu (Türkçede özel
# isim istisnasız büyük harfle başlar, ama cümlenin ilk kelimesi de öyle — ikisi karışırsa
# büyük/küçük harfe dayanan hiçbir iyileştirme dürüstçe ölçülemez).
OVER_MASK_PROBE = [
    # cümle başı
    "Şirket merkezi ticaret siciline tescil edilmiştir.",
    "Konsolide finansal tablolar hazırlanmıştır.",
    "Faaliyet raporu bağımsız denetimden geçmiştir.",
    "Vergi Usul Kanunu hükümleri saklıdır.",
    # aynı terimler cümle ortasında
    "İlgili şirket merkezi ticaret siciline tescil edilmiştir.",
    "Ekte sunulan konsolide finansal tablolar hazırlanmıştır.",
    "Bu dönem faaliyet raporu bağımsız denetimden geçmiştir.",
    "Söz konusu işlemde Vergi Usul Kanunu hükümleri saklıdır.",
    # yalın iş dili — hiçbir özel isim yok
    "İş bu tutanak iki nüsha olarak düzenlenmiştir.",
    "Ödeme planı taraflarca mutabık kalınarak belirlenmiştir.",
    "Görev süresi üç yıldır ve yeniden seçilmek mümkündür.",
    "Toplantı nisabı sağlanamadığı için ertelenmiştir.",
    # Deney v5 genişletmesi (12→40): allow-list DIŞI terimlerle, farklı alanlardan. Kural aynen
    # geçerli: bu cümlelerdeki HİÇBİR terim allow-list'e EKLENEMEZ — prob, allow-list'in
    # kapsamadığı dünyada genellemeyi ölçer; eklemek ölçümü imha eder (§16.2 dersi).
    # — finans/muhasebe
    "Amortisman gideri dönem sonunda kayıtlara alınmıştır.",
    "Bilanço aktif toplamı geçen yıla göre artmıştır.",
    "Tahakkuk eden faiz tutarı hesaplara yansıtılmıştır.",
    "Serbest nakit akışı projeksiyonu güncellenmiştir.",
    "Özkaynak değişimleri ilgili tabloda gösterilmiştir.",
    "Dönem Karı dağıtımı genel kurulda görüşülecektir.",
    # — hukuk/idare
    "Tebligat usulüne uygun olarak yapılmıştır.",
    "İtiraz süresi kararın tebliğinden itibaren başlar.",
    "Yürütmeyi durdurma talebi reddedilmiştir.",
    "Islah dilekçesi süresi içinde sunulmuştur.",
    "Temyiz Kanun yoluna başvuru hakkı saklıdır.",
    "Delil listesi duruşmada mahkemeye ibraz edilmiştir.",
    # — İK/kurumsal
    "Performans değerlendirmesi yılda iki kez yapılır.",
    "İşe alım süreci üç aşamadan oluşmaktadır.",
    "Zimmet tutanağı personel dosyasına eklenmiştir.",
    "Fazla mesai ücretleri bordroya yansıtılmıştır.",
    "Oryantasyon programı ilk hafta tamamlanır.",
    "Disiplin Kurulu kararı yazılı olarak bildirilir.",
    # — kamu/işlem
    "Başvuru formu eksiksiz doldurulmalıdır.",
    "Harç bedeli vezneye yatırılmıştır.",
    "Ruhsat yenileme işlemi tamamlanmıştır.",
    "Encümen kararı ilgili birime gönderilmiştir.",
    "Askı süresi otuz gün olarak belirlenmiştir.",
    "İmar Durumu belgesi ektedir.",
    # — genel iş yazışması
    "Toplantı gündemi ekte sunulmuştur.",
    "Karar defteri notere tasdik ettirilmiştir.",
    "Yetki devri yazılı onayla yapılır.",
    "Arşiv düzenlemesi ay sonuna kadar bitirilecektir.",
]


def main() -> int:
    from app.anonymization.presidio_engine import PresidioEngine
    from evaluation.bist30.canary import catalog_by_id

    engine = PresidioEngine()
    cat = catalog_by_id()

    def detected(text: str, value: str) -> bool:
        """Değerin PII taşıyan her karakteri span'lerin BİRLEŞİMİ tarafından kapsanıyor mu?

        DÜZELTME (ölçümle bulundu): ilk sürüm "tek bir span tüm değeri kapsamalı" diyordu ve bu
        yanlış kaçış raporluyordu — Privacy Filter açıkken "Jonathan Whitfield" İKİ ayrı PERSON
        span'i ("Jonathan" + "Whitfield") olarak dönüyor, aradaki boşluk kapsanmıyor. Değer
        tamamen maskeleniyor olmasına rağmen metrik bunu "kaçtı" sayıyordu; bu yanlış sinyalle
        neredeyse "PF tespiti kötüleştiriyor" sonucuna varılacaktı. Gizlilik açısından önemli
        olan, açıkta PII KARAKTERİ kalmaması; span'lerin kaç parça olduğu değil. Boşluklar PII
        taşımaz, o yüzden kapsama şartından muaf tutulur.
        """
        start = text.find(value)
        if start < 0:
            return False
        spans = engine.detect(text)
        for i in range(start, start + len(value)):
            if text[i].isspace():
                continue
            if not any(s.start <= i < s.end for s in spans):
                return False
        return True

    rows = []
    for cid, c in sorted(cat.items()):
        bare = f"Ref0007 {c.value}"
        ctx = f"{c.context} {c.value}" if c.context else bare
        rows.append({
            "cid": cid, "family": c.expected_family, "critical": c.critical,
            "bare": detected(bare, c.value), "contextual": detected(ctx, c.value),
        })

    crit = [r for r in rows if r["critical"]]
    over = sum(len(engine.detect(t)) for t in OVER_MASK_PROBE)

    out = {
        "canaries": len(rows),
        "bare_missed": sum(1 for r in rows if not r["bare"]),
        "bare_missed_critical": sum(1 for r in crit if not r["bare"]),
        "contextual_missed": sum(1 for r in rows if not r["contextual"]),
        "contextual_missed_critical": sum(1 for r in crit if not r["contextual"]),
        "over_mask_spans": over,
        "bare_missed_ids": sorted(r["cid"] for r in rows if not r["bare"]),
        "contextual_missed_ids": sorted(r["cid"] for r in rows if not r["contextual"]),
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
