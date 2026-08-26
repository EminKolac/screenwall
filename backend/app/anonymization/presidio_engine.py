"""Concrete Presidio anonymization engine (Phase 3).

Runs each block through BOTH language analyzers (en + tr) so English predefined recognizers and
Turkish custom/NER recognizers all contribute regardless of the block's detected language — the
union maximizes recall (the safe direction). Overlapping spans are resolved deterministically
(`resolve_spans`) and replaced with deterministic `<TYPE_n>` placeholders via a shared mapper.
Structure is preserved (paragraph text / table cells edited in place).
"""
from __future__ import annotations

import re
import threading

from app.anonymization.engine import (
    AnonymizationEngine,
    AnonymizationOutput,
    EntitySpan,
    resolve_spans,
)
from app.anonymization.nlp import get_analyzer
from app.anonymization.placeholders import PlaceholderMapper
from app.anonymization.privacy_filter import get_privacy_filter
from app.extraction.base import BlockType, ExtractedContent
from app.models.document import Language

_TYPE_TO_PLACEHOLDER = {
    "PERSON": "PERSON", "EMAIL_ADDRESS": "EMAIL", "PHONE_NUMBER": "PHONE",
    "ORGANIZATION": "ORG", "LOCATION": "LOCATION", "CREDIT_CARD": "CARD",
    "IBAN_CODE": "IBAN", "IP_ADDRESS": "IP", "URL": "URL", "DATE_TIME": "DATE",
    "NRP": "NRP", "US_SSN": "SSN", "US_DRIVER_LICENSE": "DL",
    "TR_TCKN": "TCKN", "TR_VKN": "VKN", "TR_GSM": "PHONE", "TR_PHONE": "PHONE",
    "TR_IBAN": "IBAN", "TR_PLATE": "PLATE", "TR_PASSPORT": "PASSPORT",
    "UK_PHONE": "PHONE", "PASSPORT": "PASSPORT", "DRIVER_LICENSE": "DL", "SENSITIVE": "SENSITIVE",
    # Families fed by the Privacy Filter label map (privacy_filter._LABEL_MAP folds the model's
    # taxonomy into platform entity types, so both detectors share the same <TYPE_n> families).
    "ACCOUNT": "ACCOUNT", "SECRET": "SECRET", "USERNAME": "USERNAME", "PLATE": "PLATE",
    # The TR pattern recognizers for the same two families MUST fold into them as well: without
    # these two rows `_ph_type` falls back to the raw entity type and the same account number
    # would land in <TR_ACCOUNT_n> when Presidio finds it but <ACCOUNT_n> when the Privacy Filter
    # does — two families for one value, breaking the "same value = same token" guarantee.
    "TR_ACCOUNT": "ACCOUNT", "SECRET_KEY": "SECRET",
    # Deney döngüsü Faz 2 iter 1: yeni TR_SALARY_BAND tanıyıcısı için özel bir placeholder ailesi
    # yok (Privacy Filter'ın taksonomisinde de karşılığı yok) — kendi ailesine düşer, fallback'e
    # bırakılmaz (fallback ham entity_type'ı kullanır, tutarsız görünürdü).
    "TR_SALARY_BAND": "SALARY",
    # Faz 2 iter 2: yapısal (A.Ş./Ltd. Şti.) şirket unvanı tanıyıcısı, genel ORG ailesine düşer —
    # bir okuyucu için gerçek bir organizasyon adı, ister NER ister pattern ile bulunmuş olsun
    # aynı görünmeli.
    "TR_COMPANY": "ORG",
    # Faz 2 iter 3: yapısal adres tanıyıcısı — genel LOCATION ailesine düşer (tutarlılık:
    # adres, ister NER ister pattern ile bulunmuş olsun aynı <LOCATION_n> ailesinde görünmeli).
    "TR_ADDRESS": "LOCATION",
    # Faz 2 iter 4: holdout doğrulamasında bulunan HEALTH/DISABILITY boşluğu — özel nitelikli
    # kişisel veri (KVKK m.6), tek genel SENSITIVE ailesine düşer.
    "TR_DISABILITY": "SENSITIVE", "TR_HEALTH": "SENSITIVE",
    # Deney v5: etiket-bağlamlı kişi tanıyıcısı — PERSON ailesine katlanır (tip ayrımı yalnız
    # ortografik kuralların NER'i hedeflemesi için; okuyucuya tek <PERSON_n> ailesi görünür).
    "TR_PERSON_CTX": "PERSON",
}


def _ph_type(entity_type: str) -> str:
    return _TYPE_TO_PLACEHOLDER.get(entity_type, entity_type)


def _source_cat(source: str) -> str:
    """Group an EntitySpan.source into a detection-stage label for per-stage reporting."""
    return "presidio" if source in ("en", "tr") else (source or "presidio")


def _tally(by_source: dict[str, int], kept: list[EntitySpan]) -> None:
    for s in kept:
        cat = _source_cat(s.source)
        by_source[cat] = by_source.get(cat, 0) + 1


def _allow_ranges(text: str, allow_terms: list[str]) -> list[tuple[int, int]]:
    """Allow-terimlerinin metindeki eşleşme aralıkları. deny-list ile AYNI whitespace-esnek +
    case-insensitive desen (presidio_engine.py:~161) — tutarlılık için birebir aynı kural."""
    ranges: list[tuple[int, int]] = []
    for term in allow_terms:
        parts = term.split()
        if not parts:
            continue
        pattern = r"\s+".join(re.escape(p) for p in parts)
        for m in re.finditer(pattern, text, re.IGNORECASE):
            ranges.append((m.start(), m.end()))
    return ranges


_PLACEHOLDER_RE = re.compile(r"<[A-Z]+_\d+>")


def _norm_projection(text: str) -> tuple[str, list[int]]:
    """Metnin normalize izdüşümü + izdüşüm karakteri → orijinal indeks haritası.

    Normalizasyon: casefold + NFKD ayrıştırma + birleştirici imlerin ve TÜM boşlukların atılması.
    Böylece "Bağdat Caddesi No 145", "BağdatCaddesiNo145", "BAĞDAT CADDESI NO 145" (ASCII I!) ve
    "bağdatcaddesino145" (i + birleştirici nokta) AYNI izdüşüme düşer — stres testinin
    `format_variants` senaryosundaki dört yazımın dördü (ölçüldü, üçü sızıyordu)."""
    import unicodedata
    proj: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(text):
        for c in unicodedata.normalize("NFKD", ch.casefold()):
            if unicodedata.combining(c) or c.isspace():
                continue
            # Türkçe I/ı tuzağı (ölçüldü): "KADIKÖY"deki ASCII I, Türkçede ı'dır ama locale'siz
            # casefold I→i verir; orijinal "Kadıköy" ise ı içerir → "kadiköy" ≠ "kadıköy" ve
            # varyant kaçar. İzdüşümde i-ailesi tek karaktere katlanır (yalnız ARAMA için —
            # metnin kendisi değişmez, maskelenen aralık orijinal yazımıyla haritaya girer).
            proj.append("i" if c == "ı" else c)
            idx.append(i)
    return "".join(proj), idx


def _is_allowed(span: EntitySpan, allow_ranges: list[tuple[int, int]]) -> bool:
    """Span, herhangi bir allow-eşleşmesiyle ÇAKIŞIYORSA bastırılır. Tam eşleşme şartı YOK —
    "Genel Kurul" allow-terimken NER "Genel Kurul Toplantısı"nı tek span olarak yakalasa bile
    o span allow-terimi içeriyor demektir ve yine bastırılmalıdır (aksi halde allow-listenin
    kapsamı NER'in tam olarak nasıl segment ettiğine bağlı kalır, kırılgan olur)."""
    return any(span.start < b and a < span.end for a, b in allow_ranges)


# İstatistiksel (spaCy NER) türler — yapısal/deterministik tanıyıcıların ürettiği türlerden
# ayrılır. spaCy her tahmine sabit 0.85 verir (bkz. PLAN.md §16.0), yani skor bu türler için bir
# güven sinyali TAŞIMAZ; bu yüzden aşağıdaki ortografik kapı skora değil, metnin kendisine bakar.
_STATISTICAL_NER_TYPES = frozenset({"PERSON", "LOCATION", "ORGANIZATION", "NRP"})


def _is_lowercase_initial_ner(span: EntitySpan, text: str) -> bool:
    """Türkçe/İngilizce özel isim KÜÇÜK harfle başlamaz — böyle bir NER span'i yanlış pozitiftir.

    Ölçülen gerekçe: `xx_ent_wiki_sm` Türkçe'de sıradan fiil/isim öbeklerini özel isim sanıyor
    ("hükümleri saklıdır", "mutabık kalınarak", "seçilmek mümkündür" → hepsi PERSON, 0.85). Bu
    öbeklerin ortak, makinece kesin ayırt edilebilir özelliği küçük harfle başlamaları: Türkçe
    ortografisinde özel isim istisnasız büyük harfle başlar, dolayısıyla bu kural yanlış NEGATİF
    üretemez — gerçek bir ad zaten büyük harfle yazılır.

    Kapsam BİLİNÇLİ olarak yalnız istatistiksel NER türleri: yapısal tanıyıcılar (IBAN, TCKN,
    e-posta, SECRET_KEY...) küçük harfle başlayabilir ve orada büyük/küçük harf bir ad sinyali
    değildir. Ayrıca YALNIZ span'in İLK karakterine bakar — "Vergi Usul Kanunu hükümleri" gibi
    büyük harfle başlayıp küçük harfe taşan span'ler bu kapıdan geçer (onların kırpılması ayrı bir
    problem, burada çözülmüyor).
    """
    if span.entity_type not in _STATISTICAL_NER_TYPES:
        return False
    surface = text[span.start:span.end].lstrip()
    if not surface:
        return False
    first = surface[0]
    return first.isalpha() and first.islower()


def _is_implausible_person_ner(span: EntitySpan, text: str) -> bool:
    """Deney v5 — PERSON'a özgü iki ek ortografik kural (bağımsız probda 21 FP'nin 11'i):

    1) TEK kelimelik istatistiksel PERSON span'i elenir. spaCy'nin sabit 0.85'i kanıt taşımaz ve
       tek kelimelik tahminleri probda sistematik yanlış pozitif ("Konsolide", "Tahakkuk",
       "Zimmet", "Encümen"…). Meşru tek-kelime vakaları başka mekanizmalar kapsıyor (ölçüldü):
       soyadın tek başına geçişi SOYAD YAYILIMI ile (belgede tam ad bir kez maskelendiyse),
       etiketli adlar `_person_context_recognizer` ile; ayrıca holdout'taki tek-kelime PERSON
       kaçışları spaCy tarafından ZATEN yakalanmıyordu — bu kural mevcut recall'dan bir şey
       almıyor, sadece gürültüyü kesiyor (holdout ile doğrulanır).
    2) İçinde küçük harfle başlayan (≥3 harfli) kelime taşıyan çok-kelimeli PERSON elenir —
       gerçek bir Türkçe/İngilizce ad tamamı büyük harflidir; "Dönem Karı dağıtımı genel
       kurulda görüşülecektir" gibi span'ler ad değil cümle parçasıdır.

    Kapsam BİLİNÇLİ olarak yalnız PERSON: LOCATION'da tek kelime meşru ve yaygın ("Kadıköy",
    "İstanbul" — gold LOCATION mention'larının tamamı tek kelimelik, elenirse recall sıfırlanır).
    """
    if span.entity_type != "PERSON" or span.source not in ("en", "tr"):
        return False
    words = text[span.start:span.end].split()
    if len(words) == 1:
        return True
    return any(w[0].isalpha() and w[0].islower() for w in words if len(w) >= 3)


# Serialize access to the shared cached AnalyzerEngine across threads/requests.
_ANALYZE_LOCK = threading.Lock()


class PresidioEngine(AnonymizationEngine):
    def __init__(self, score_threshold: float | None = None) -> None:
        self._threshold = score_threshold

    @property
    def threshold(self) -> float:
        if self._threshold is not None:
            return self._threshold
        from app.config import get_settings
        return get_settings().anonymizer_score_threshold

    def anonymize(
        self,
        content: ExtractedContent,
        language: Language,
        *,
        extra_deny_terms: list[str] | None = None,
        extra_allow_terms: list[str] | None = None,
    ) -> AnonymizationOutput:
        analyzer = get_analyzer()
        # Stage ② detector: None unless enabled+available; raises if required-but-unavailable so the
        # pipeline fails closed to human review (caught in runner.run_pipeline).
        detector = get_privacy_filter()
        mapper = PlaceholderMapper()
        deny = [t.strip() for t in (extra_deny_terms or []) if t and t.strip()]
        allow = [t.strip() for t in (extra_allow_terms or []) if t and t.strip()]
        total = 0
        by_source: dict[str, int] = {}
        new_blocks = []
        # Per-document detection cache. Real reports repeat the same strings constantly (running
        # headers, column labels, boilerplate): on a 428k-char annual report 52% of the 12k
        # block/cell analyses were of text already seen. Detection is a pure function of (text,
        # deny-list, allow-list), so reusing the spans is exact — and it roughly halves the spaCy
        # work. The mapper still runs per occurrence, so placeholder numbering and determinism
        # are unchanged. Both lists are fixed for the duration of one `anonymize()` call, so
        # keying the cache on `text` alone (not on deny/allow too) is safe.
        cache: dict[str, list[EntitySpan]] = {}
        # Varyant yayılımına aday yüzeyler: yüzey → yer tutucu ailesi. Yalnız aşağıdaki
        # `_PROPAGATION_TYPES` doldurur (gerekçe: yayılım bloğundaki yorum).
        prop_surfaces: dict[str, str] = {}
        # Deney v5 iter 4 — ≥2 kelimeli PERSON yüzeyleri AYRI havuzda: yalnız BOŞLUKSUZ (yapışık)
        # eş-yazımlara yayılırlar ("Jonathan Whitfield" → "jonathanwhitfield"; GoldBench stres
        # xlsx-format_variants-19'un sızdırdığı tek varyant buydu — dünkü motorda da sızıyordu,
        # izolasyonla doğrulandı). Kısıtların ikisi de ölçülmüş gerilemelerin dersi: (a) tek
        # kelimelik NER yüzeyi yayılamaz — "SÖZLEŞME"→LOCATION yanlış pozitifi belgedeki her
        # "sözleşme"ye bulaşmıştı; (b) boşluklu eş-yazım maskelenmez — "sözleşme bedeli" gibi düz
        # metin geçişleri yayılıma girseydi aşırı-maskeleme probundaki FP sınıfı geri gelirdi.
        # Çok-kelimeli bir adın YAPIŞIK yazımı ise düz metinde doğal olarak oluşmaz.
        prop_person: dict[str, str] = {}
        prop_surname: dict[str, str] = {}

        def _collect(src_text: str, kept: list[EntitySpan]) -> None:
            for s in kept:
                if s.entity_type in self._PROPAGATION_TYPES:
                    prop_surfaces[src_text[s.start:s.end]] = _ph_type(s.entity_type)
                elif s.entity_type in ("PERSON", "TR_PERSON_CTX"):
                    surface = src_text[s.start:s.end]
                    words = surface.split()
                    if len(words) >= 2:
                        prop_person[surface] = "PERSON"
                        # Deney v5 — SOYAD yayılımı: maskelenen çok-kelimeli adın son kelimesi
                        # aynı belgede TEK BAŞINA da geçebilir ("Şule Erdoğan" maskelenirken üç
                        # ayrı "Erdoğan" geçişi kaçıyordu — holdout teşhisi). Soyad adayı ≥5
                        # karakter olmalı; kabul şartları `_propagate_variants`'ta (boşluksuz +
                        # BÜYÜK harfle başlayan geçiş — küçük harfli sıradan kelime maskelenmez).
                        # ≥4: "Kurt" gibi 4 harfli gerçek soyadlar Türkçede yaygın — ≥5 eşiği
                        # holdout'ta ölçülen bir kaçış üretti ("Ş. Kurt" maskeliyken tek başına
                        # "Kurt" açık kaldı). Yayılım zaten üç korumayla sınırlı (boşluksuz +
                        # BÜYÜK harf başlangıcı + kelime sınırı), kısa eşik güvenli.
                        if len(words[-1]) >= 4:
                            prop_surname[words[-1]] = "PERSON"

        for block in content.blocks:
            if block.type == BlockType.table:
                new_cells = []
                by_row: dict[int, list] = {}
                for c in block.cells:
                    by_row.setdefault(c.row, []).append(c)
                premasked: dict[tuple[int, int], str] = {}
                for row_cells in by_row.values():
                    ordered = sorted(row_cells, key=lambda c: c.col)
                    texts = self._row_adjacency_premask(
                        ordered, mapper, deny, allow, analyzer, detector, cache)
                    for cell, text in zip(ordered, texts, strict=True):
                        premasked[(cell.row, cell.col)] = text
                for cell in block.cells:
                    src = premasked.get((cell.row, cell.col), cell.text)
                    text, kept = self._anon_text(
                        src, mapper, deny, allow, analyzer, detector, cache)
                    total += len(kept)
                    _tally(by_source, kept)
                    _collect(src, kept)
                    new_cells.append(cell.model_copy(update={"text": text}))
                # Drop the raw sheet name from the anonymized (layer-3) copy — it is un-audited PII;
                # the audited sheet name is carried separately as an anonymized heading block.
                new_blocks.append(block.model_copy(update={"cells": new_cells, "sheet": None}))
            else:
                text, kept = self._anon_text(
                    block.text, mapper, deny, allow, analyzer, detector, cache)
                total += len(kept)
                _tally(by_source, kept)
                _collect(block.text, kept)
                new_blocks.append(block.model_copy(update={"text": text}))
        out = content.model_copy(update={"blocks": new_blocks})
        # Deney v5 iter 2 — VARYANT YAYILIMI (son geçiş). Ölçülen boşluk: aynı değerin
        # boşluksuz/büyük-küçük/aksan-varyantlı yazımları ("BağdatCaddesiNo145…",
        # "BAĞDAT CADDESI NO 145 …" ASCII-I ile, "bağdatcaddesino145…" birleştirici noktayla)
        # regex tabanlı tanıyıcıların kelime-sınırı varsayımını kırıyor ve normal biçim
        # maskelenirken varyantlar açıkta kalıyordu (GoldBench stres `pdf-format_variants-06`,
        # kritik yanlış onay). Maskelenen her ≥8 karakterlik değerin normalize izdüşümü, çıktı
        # metninin izdüşümünde aranır ve eşleşme aynı yer tutucu ailesiyle maskelenir. ÇIKTI
        # üzerinde çalışmak bilinçli: zaten maskelenen geçişler yer tutucuya dönüştüğü için
        # yeniden eşleşmez, yalnız kaçak varyantlar kalır; yer tutucuların kendisine denk gelen
        # eşleşmeler ayrıca atlanır. Regex GEVŞETİLMEDİ — gevşetme aşırı-maskeleme riski taşırdı,
        # bu yol yalnız ZATEN PII olduğu kanıtlanmış değerlerin yazım varyantlarına dokunur.
        # YALNIZ deterministik tanıyıcılardan gelen yüzeyler yayılır — ölçülen gerileme: ilk
        # sürüm mapper'daki TÜM yüzeyleri yayıyordu ve NER'in tek seferlik bir yanlış pozitifi
        # ("SÖZLEŞME" başlığını LOCATION sanması) belgedeki HER "sözleşme" kelimesine bulaştı
        # (test_destructive_mode_never_persists_layers_1_2 yakaladı). Yapısal türlerde bu risk
        # yok: desen ancak gerçekten o biçimdeki değere uyar.
        surfaces = (
            [(fam, val, "any") for val, fam in prop_surfaces.items()
             if len(_norm_projection(val)[0]) >= 8]
            # PERSON yüzeyleri "glued": yalnız boşluksuz eş-yazım maskelenir (iter 4 yorumu,
            # yukarıda). ≥8 izdüşüm şartı burada da geçerli.
            + [(fam, val, "glued") for val, fam in prop_person.items()
               if len(_norm_projection(val)[0]) >= 8]
            # Soyadlar "surname": boşluksuz + BÜYÜK harfle başlayan geçiş şartı (izdüşüm ≥5 —
            # soyad tam adlardan kısa, 8 şartı onları tümden elerdi).
            + [(fam, val, "surname") for val, fam in prop_surname.items()
               if len(_norm_projection(val)[0]) >= 4]
        )
        if surfaces:
            var_blocks = []
            for block in out.blocks:
                if block.type == BlockType.table:
                    cells = [c.model_copy(update={"text": self._propagate_variants(
                        c.text, surfaces, mapper)}) for c in block.cells]
                    var_blocks.append(block.model_copy(update={"cells": cells}))
                else:
                    var_blocks.append(block.model_copy(update={"text": self._propagate_variants(
                        block.text, surfaces, mapper)}))
            out = out.model_copy(update={"blocks": var_blocks})
        return AnonymizationOutput(
            content=out,
            entity_count=total,
            placeholders_used=mapper.counts(),
            by_source=by_source,
            mapping=dict(mapper.mapping),
        )

    def _propagate_variants(self, text: str, surfaces, mapper) -> str:
        """Tek bir metin parçasında, maskelenmiş değerlerin normalize-izdüşüm varyantlarını
        bulur ve maskeler. `surfaces`: (aile, değer, mod) üçlüleri —
          "any"     yapısal türler, kısıtsız;
          "glued"   PERSON tam adı: yalnız BOŞLUKSUZ eş-yazım (iter 4 gerekçesi);
          "surname" soyad: boşluksuz + BÜYÜK harfle başlayan geçiş (küçük harfli sıradan kelime
                    maskelenmez — ortografik kapı dersiyle aynı ilke) + kelime sınırı (izdüşümde
                    komşu karakter harf olamaz; "erdoğangiller" içindeki "erdoğan" eşleşmez).
        Sağdan sola uygulanır ki ofsetler geçerli kalsın."""
        if not text:
            return text
        proj, idx = _norm_projection(text)
        if not proj:
            return text
        ph_ranges = [(m.start(), m.end()) for m in _PLACEHOLDER_RE.finditer(text)]
        hits: list[tuple[int, int, str]] = []  # (start, end, aile)
        for fam, val, mode in surfaces:
            needle = _norm_projection(val)[0]
            pos = proj.find(needle)
            while pos != -1:
                s_orig, e_orig = idx[pos], idx[pos + len(needle) - 1] + 1
                occurrence = text[s_orig:e_orig]
                ok = True
                if mode in ("glued", "surname") and any(ch.isspace() for ch in occurrence):
                    ok = False  # boşluklu eş-yazım — düz metin olabilir, maskelenmez
                if ok and mode == "surname":
                    if not occurrence[:1].isupper():
                        ok = False
                    # Kelime sınırı ORİJİNAL metinde denetlenir — izdüşümde DEĞİL (izdüşüm tüm
                    # boşlukları attığı için orada her kelime komşusuna yapışıktır; ilk sürüm bu
                    # yüzden hiçbir soyadı eşleştiremedi, ölçüldü).
                    if (s_orig > 0 and text[s_orig - 1].isalpha()) or \
                            (e_orig < len(text) and text[e_orig].isalpha()):
                        ok = False  # kelimenin ortası — soyad değil
                if ok and not any(s_orig < b and a < e_orig for a, b in ph_ranges):
                    hits.append((s_orig, e_orig, fam))
                pos = proj.find(needle, pos + 1)
        if not hits:
            return text
        # Çakışan bulguları ele (ilk gelen kalır), sağdan sola uygula.
        hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
        kept: list[tuple[int, int, str]] = []
        for h in hits:
            if all(h[1] <= k[0] or h[0] >= k[1] for k in kept):
                kept.append(h)
        for s, e, fam in sorted(kept, key=lambda h: -h[0]):
            token = mapper.placeholder_for(fam, text[s:e])
            text = text[:s] + token + text[e:]
        return text

    # Bitişiklik turunda kabul edilen türler — YALNIZ deterministik/yapısal desenler (regex/
    # checksum tabanlı, tek başına yüksek özgüllük). Test sırasında bulundu: istatistiksel NER
    # türlerini (PERSON, ORGANIZATION, LOCATION, NRP...) buraya dahil etmek yeni bir aşırı-
    # maskeleme kaynağı açıyor — iki alakasız kısa Türkçe kelime yan yana geldiğinde ("Ürün" +
    # "Adet") spaCy bunu PERSON sanabiliyor; satır-birleştirme sentetik bir bağlam yaratıyor ve
    # NER'in gerçek cümle yapısına dayanan güveni orada anlamsızlaşıyor. Yapısal türler bu riski
    # taşımaz: bir IBAN/telefon/kart deseni iki hücreye bölününce birleşince YİNE aynı geçerli
    # deseni oluşturur, rastgele bir eşleşme değildir.
    _ADJACENCY_SAFE_TYPES = frozenset({
        "TR_IBAN", "IBAN_CODE", "TR_TCKN", "TR_GSM", "TR_PHONE", "UK_PHONE",
        "CREDIT_CARD", "EMAIL_ADDRESS", "US_SSN", "IP_ADDRESS", "URL",
        "TR_ACCOUNT", "SECRET_KEY", "TR_PLATE", "TR_PASSPORT", "TR_VKN",
    })

    # Varyant yayılımına girebilen türler: bitişiklik-güvenli yapısal desenler + iki yapısal TR
    # tanıyıcısı (adres/şirket — desenleri ancak gerçekten o biçimdeki değere uyar). İstatistiksel
    # NER türleri BİLEREK dışarıda: ölçülen gerileme, NER'in tek seferlik bir yanlış pozitifinin
    # ("SÖZLEŞME" başlığı → LOCATION) belge genelindeki her eş-yazıma bulaşmasıydı.
    _PROPAGATION_TYPES = _ADJACENCY_SAFE_TYPES | {"TR_ADDRESS", "TR_COMPANY"}

    def _row_adjacency_premask(self, row_cells, mapper, deny, allow, analyzer, detector, cache):
        """Deney döngüsü Faz 2 — bitişiklik (adjacency) düzeltmesi: PII bir tablo satırında
        komşu hücrelere bölünmüşse (klasik XLSX split-run tuzağı — GoldBench stres testinde
        `split_run_pii` senaryosu bunu 3/6 kritik yanlış onayda kanıtladı), hücreler tek tek
        taranınca değer hiçbir dedektörü tetiklemez.

        YALNIZ tek başına HİÇBİR span üretmeyen ardışık hücreler birleştirilip taranır — zaten
        geçerli bir PII taşıyan bir hücreyi birleştirme havuzuna sokmak, onu yanındaki alakasız
        bir hücreyle kazayla kaynaştırıp FARKLI (yanlış) bir türe kaydırabilir (ölçüldü: "0532 764
        21 09" + "42" ayraçsız birleşince TR_GSM değil US_SSN eşleşti — regresyon testiyle
        yakalandı). Bu, tek hücreye sığan span'lerin normal per-hücre turunda zaten doğru
        işlendiğini bildiğimiz için güvenli bir sınırlama.

        Ayraçsız birleştirme: OOXML split-run bir değeri TAM ortadan böler, aradaki karaktere
        DOKUNMAZ (`_split_fragments` — GoldBench stres testi) — ayraçsız birleştirme bölünen
        değeri TAM olarak yeniden kurar; bir boşlukla birleştirmek boşluk-toleranssız desenleri
        (SECRET_KEY, TR_PASSPORT, URL) kırardı (ölçüldü, ilk sürümün regresyonu).

        Bilinçli kapsam dışı: satırlar-arası/bloklar-arası bitişiklik (tüm sayfayı birleştirmek
        yanlış-pozitif riskini çok artırır, tek satır en yaygın gerçek vaka)."""
        if len(row_cells) < 2:
            return [c.text for c in row_cells]
        texts = [c.text for c in row_cells]
        clean = [
            not (t.strip() and self._detect(t, deny, allow, analyzer, detector, cache))
            for t in texts
        ]
        out = list(texts)
        i, n = 0, len(texts)
        while i < n:
            if not clean[i]:
                i += 1
                continue
            j = i
            while j + 1 < n and clean[j + 1]:
                j += 1
            if j > i:  # en az 2 ardışık "temiz" (tek başına PII'siz) hücre
                self._merge_and_splice(texts, out, i, j, mapper, deny, allow, analyzer, detector)
            i = j + 1
        # Deney v5 iter 5 — KESİK-UÇ UZATMASI: hücre SONUNA dayanan yapısal bir span, değerin
        # kesilmiş ilk yarısı olabilir ("sk_live_9Qm2f" tek başına SECRET eşleşir ama gerçek
        # anahtar komşu hücrede devam eder — GoldBench stres xlsx-split_run_pii-00, kalan SON
        # kritik yanlış onay). Böyle bir hücre "temiz" sayılmadığı için yukarıdaki havuza
        # giremiyordu. Burada YALNIZ şu koşulla komşuyla birleştirilir: birleşik metindeki span
        # AYNI türde ve AYNI başlangıçta olmalı (yani kesik eşleşmenin UZAMASI olmalı) — serbest
        # bırakılsaydı, ölçülmüş SSN bozulması geri gelirdi ("0532 764 21 09"+"42" birleşiminde
        # farklı türde/başlangıçta sahte bir eşleşme; regresyon testi bunu sınıyor).
        for k in range(n - 1):
            if clean[k] or not clean[k + 1] or out[k] != texts[k] or out[k + 1] != texts[k + 1]:
                continue
            left = texts[k]
            edge = [s for s in self._detect(left, deny, allow, analyzer, detector, cache)
                    if s.entity_type in self._ADJACENCY_SAFE_TYPES and s.end == len(left)]
            if len(edge) != 1:
                continue
            e0 = edge[0]
            joined = left + texts[k + 1]
            for s in self._detect(joined, deny, allow, analyzer, detector, cache=None):
                if (s.entity_type == e0.entity_type and s.start == e0.start
                        and s.end > len(left)):
                    token = mapper.placeholder_for(
                        _ph_type(s.entity_type), joined[s.start:s.end])
                    out[k] = left[:s.start] + token
                    out[k + 1] = texts[k + 1][s.end - len(left):]
                    break
        return out

    def _merge_and_splice(self, texts, out, i, j, mapper, deny, allow, analyzer, detector):
        """`texts[i..j]` (dahil) ayraçsız birleştirilip taranır; hücre sınırını aşan span'ler
        `out` üzerine (yerinde) yazılır."""
        offsets: list[tuple[int, int]] = []
        pos = 0
        for k in range(i, j + 1):
            offsets.append((pos, pos + len(texts[k])))
            pos += len(texts[k])
        joined = "".join(texts[i:j + 1])
        spans = self._detect(joined, deny, allow, analyzer, detector, cache=None)
        per_cell: dict[int, list[tuple[int, int, str]]] = {}
        for s in spans:
            start_local = next((k for k, (a, b) in enumerate(offsets) if a <= s.start < b), None)
            end_local = next((k for k, (a, b) in enumerate(offsets) if a < s.end <= b), None)
            if start_local is None or end_local is None or start_local == end_local:
                continue
            if s.entity_type not in self._ADJACENCY_SAFE_TYPES:
                continue
            token = mapper.placeholder_for(_ph_type(s.entity_type), joined[s.start:s.end])
            for k in range(start_local, end_local + 1):
                a, b = offsets[k]
                lo, hi = max(s.start, a) - a, min(s.end, b) - a
                if lo < hi:
                    # Yalnız BAŞLANGIÇ hücresi token'ı taşır; aradaki/sondaki hücrelerde örtüşen
                    # parça boşaltılır — değer zaten ilk hücrede maskelendi, ikinci bir token
                    # gerekmiyor (bir tablo satırında "<SECRET_1>" gibi tek bir iz kalır).
                    per_cell.setdefault(k, []).append((lo, hi, token if k == start_local else ""))
        for k, repls in per_cell.items():
            text = texts[i + k]
            # sağdan sola: önceki değişiklikler sonraki ofsetleri kaydırmasın
            for lo, hi, repl in sorted(repls, key=lambda r: -r[0]):
                text = text[:lo] + repl + text[hi:]
            out[i + k] = text

    def detect(
        self, text: str, *,
        extra_deny_terms: list[str] | None = None,
        extra_allow_terms: list[str] | None = None,
    ) -> list[EntitySpan]:
        """Run all detection stages and return the resolved, non-overlapping spans on the ORIGINAL
        text — WITHOUT applying placeholders. This is the detection half of `anonymize`; the eval
        harness (`evaluation/`) scores THIS so metrics reflect the exact production detection path.
        """
        analyzer = get_analyzer()
        detector = get_privacy_filter()
        deny = [t.strip() for t in (extra_deny_terms or []) if t and t.strip()]
        allow = [t.strip() for t in (extra_allow_terms or []) if t and t.strip()]
        return self._detect(text, deny, allow, analyzer, detector)

    def _detect(self, text, deny, allow, analyzer, detector, cache=None) -> list[EntitySpan]:
        """Collect spans from every detection stage and resolve overlaps. Shared by `detect`
        (eval) and `_anon_text` (production) so the two can never drift apart.

        `cache` (optional, per-document) memoizes results by text — detection depends only on the
        text, deny-list and allow-list, all fixed within one document, so a hit is exact, not an
        approximation. Spans are offsets INTO `text`, so they stay valid for every occurrence.
        """
        if not text or not text.strip():
            return []
        if cache is not None:
            hit = cache.get(text)
            if hit is not None:
                return hit
        spans: list[EntitySpan] = []
        # Stage ① — Presidio (EN+TR). No swallowing: an analysis error propagates so the pipeline
        # fails closed (routes to human review) rather than returning under-anonymized text.
        with _ANALYZE_LOCK:
            for lang in ("en", "tr"):
                for r in analyzer.analyze(text=text, language=lang, score_threshold=self.threshold):
                    spans.append(EntitySpan(start=r.start, end=r.end, entity_type=r.entity_type,
                                            score=r.score, source=lang))
        # Deney v5 iter 1 — satır-kaydırma (line-wrap) turu. Ölçülen boşluk: PDF çıkarımı bir
        # değeri TEK blok içinde '\n' ile bölebiliyor ("https://portal.ornek.c\nom/r?token=…" —
        # GoldBench stres `pdf-split_run_pii-07`, kritik yanlış onay). Boşluk-toleranssız
        # desenler (URL, SECRET_KEY, e-posta) '\n' üzerinden eşleşemez. Çözüm: '\n' karakterleri
        # atılmış görünümde İKİNCİ bir analiz; yalnız (a) yapısal/deterministik türden olan ve
        # (b) gerçekten bir '\n' üzerinden geçen span'ler orijinal aralığa geri eşlenip eklenir —
        # (b) şartı olmadan bu tur, birinci turun bulduklarını çift eklerdi; (a) şartı, tablo
        # bitişikliğinde ölçülmüş dersin aynısı (istatistiksel NER'e sentetik bağlam üretmek yeni
        # yanlış pozitif kaynağı açıyor). NOT: bloklar-arası birleştirme BİLEREK yapılmıyor —
        # denendi ve DISCARD edildi: ayrı cümlelerin ayraçsız birleşimi sahte URL üretti
        # ("içerik."+"Ref0007" → "erik.Re" URL sanıldı); '\n' zaten blok İÇİ olduğu için bu tur
        # o riski taşımıyor (bkz. thoughts/EXPERIMENTS.md v5 iter 1).
        if "\n" in text:
            keep_pos = [i for i, ch in enumerate(text) if ch != "\n"]
            collapsed = "".join(text[i] for i in keep_pos)
            with _ANALYZE_LOCK:
                for lang in ("en", "tr"):
                    for r in analyzer.analyze(text=collapsed, language=lang,
                                              score_threshold=self.threshold):
                        if r.entity_type not in self._ADJACENCY_SAFE_TYPES:
                            continue
                        s_orig, e_orig = keep_pos[r.start], keep_pos[r.end - 1] + 1
                        seg = text[s_orig:e_orig]
                        if "\n" not in seg:
                            continue  # '\n' üzerinden geçmiyor → birinci tur zaten kapsıyor
                        # Gerçek satır-KAYDIRMA imzası: '\n' bir token'ın ORTASINA düşer, yani
                        # öncesinde cümle noktalaması olmaz. "açıklama.\nİkinci" gibi normal
                        # satır sonlarını daraltmak sahte birleşik token üretir ("açıklama.İkinci"
                        # → URL yanlış pozitifi — birim testi yakaladı, ölçüldü). Nokta/soru/
                        # iki-nokta vb. ile biten satırların birleşimi bu turdan elenir.
                        if any(seg[k] == "\n" and k > 0 and seg[k - 1] in ".!?:;,"
                               for k in range(len(seg))):
                            continue
                        spans.append(EntitySpan(start=s_orig, end=e_orig,
                                                entity_type=r.entity_type,
                                                score=r.score, source=lang))
        # Project deny-list — case-insensitive + whitespace-flexible ("500 Startups" also masks
        # "500 STARTUPS", "500  Startups", and the line-wrapped "500\nStartups").
        for term in deny:
            parts = term.split()
            if not parts:
                continue
            pattern = r"\s+".join(re.escape(p) for p in parts)
            for m in re.finditer(pattern, text, re.IGNORECASE):
                spans.append(EntitySpan(start=m.start(), end=m.end(), entity_type="SENSITIVE",
                                        score=1.0, source="deny"))
        # Stage ② — OpenAI Privacy Filter (local, contextual). Errors propagate (fail-closed) too.
        if detector is not None:
            spans.extend(detector.detect(text))
        # Allow-list filtering happens BEFORE resolve_spans, not after: eliminating a span
        # post-resolution can permanently lose a real PII span it had suppressed via overlap
        # (e.g. an allowed ORGANIZATION span that beat a TR_VKN span on overlap — removing it
        # afterward would NOT resurrect the VKN span). Filtering first lets resolve_spans correctly
        # promote the next-best candidate. Measured/verified during exploration — see PLAN.md §16.2.
        if allow:
            ranges = _allow_ranges(text, allow)
            if ranges:
                spans = [s for s in spans if not _is_allowed(s, ranges)]
        # Ortografik kapı — allow-list ile AYNI gerekçeyle `resolve_spans`'ten ÖNCE: küçük harfle
        # başlayan sahte bir PERSON span'i, çakışma yüzünden gerçek bir yapısal span'i bastırmış
        # olabilir; sonradan elemek onu geri getirmez, önce elemek `resolve_spans`'in doğru adayı
        # yükseltmesini sağlar.
        spans = [s for s in spans if not _is_lowercase_initial_ner(s, text)
                 and not _is_implausible_person_ner(s, text)]
        kept = resolve_spans(spans)
        if cache is not None:
            cache[text] = kept
        return kept

    def _anon_text(self, text, mapper, deny, allow, analyzer, detector, cache=None):
        kept = self._detect(text, deny, allow, analyzer, detector, cache)
        if not kept:
            return text, []
        out = text
        for s in sorted(kept, key=lambda s: -s.start):  # right-to-left keeps offsets valid
            token = mapper.placeholder_for(_ph_type(s.entity_type), text[s.start:s.end])
            out = out[: s.start] + token + out[s.end:]
        return out, kept
