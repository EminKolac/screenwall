"""Yüzey-biçimi tabanlı bağlam artırıcı — `xx_ent_wiki_sm`'in lemmatizer'ı olmadığı için gerekli.

Kök neden (ölçüldü): Presidio'nun varsayılan `LemmaContextAwareEnhancer`'ı bağlam kelimesini
`nlp_artifacts.lemmas` üzerinden arar. `en_core_web_sm`'in lemmatizer'ı var, ama Türkçe için
kullanılan çok-dilli NER modeli `xx_ent_wiki_sm` YOK — her token'ın lemma'sı boş string döner:

    >>> nlp("hesap numarasi")[0].lemma_
    ''

Bu yüzden "Müşteri **hesap** no 8842-556310-04" gibi bağlam kelimesi tam bitişikken bile artış hiç
tetiklenmiyordu: `_add_n_words` gerçek kelime yerine boş string topluyor, `_find_supportive_word_in_
context` de boş stringde "hesap"ı bulamıyordu. Etkilenen HER düşük-skorlu Türkçe tanıyıcı (TR_VKN
0.2, TR_PHONE 0.3, TR_ACCOUNT 0.25, genel SECRET_KEY 0.15) eşiğin (0.4) altında sabit kalıyor ve
hiçbir zaman maskelenmiyordu — bağlam artışı olmadan asla tetiklenemezler.

Çözüm: lemma yerine ham token yüzey biçimini (`token.text.lower()`) kullanan bir alt sınıf.
İngilizce'yi ETKİLEMEZ — orada zaten çalışan lemma tabanlı akışın üstüne binmez, sadece lemma
listesi TAMAMEN boşsa (dilde lemmatizer yoksa) yüzey biçimine düşer.

Bilinen sınır (dürüstlük kaydı): yüzey biçimi eşleşmesi Türkçe'nin sondan eklemeli yapısını
normalize etmez — "hesap" bağlam kelimesi "hesabınız" içinde alt-dizge olarak GEÇMEZ (ünsüz
yumuşaması: p→b). Gerçek bir kök bulma (stemming) çözümü kapsam dışı; bu, "hiç çalışmıyordu"
durumundan "çoğu durumda çalışıyor" durumuna geçiren en küçük güvenli müdahale.
"""
from __future__ import annotations

from presidio_analyzer.context_aware_enhancers import LemmaContextAwareEnhancer
from presidio_analyzer.nlp_engine import NlpArtifacts


class SurfaceFormContextAwareEnhancer(LemmaContextAwareEnhancer):
    """`_extract_surrounding_words`'ü ezer: lemma boşsa ham kelimeye düşer.

    Üst sınıfın stopword/keyword filtrelemesi ATLANIR (o filtre `nlp_engine.is_stopword` üstünden
    lemma diline bağlı çalışıyor ve lemmasız dilde anlamsız hale geliyor). Bunun bedeli: bağlam
    penceresinde bağlaçlar gibi "önemsiz" kelimeler de aday olarak durur — ama zararsızdır, çünkü
    `_find_supportive_word_in_context` yalnız tanıyıcının KENDİ context listesindeki kelimelerle
    eşleşmeyi arar; fazladan aday kelime yanlış eşleşme YARATMAZ, sadece filtrelenmemiş kalır.
    """

    def _extract_surrounding_words(
        self, nlp_artifacts: NlpArtifacts, word: str, start: int,
    ) -> list[str]:
        if not nlp_artifacts.tokens:
            return [""]

        tokens = list(nlp_artifacts.tokens)
        token_index = self._find_index_of_match_token(
            word, start, nlp_artifacts.tokens, nlp_artifacts.tokens_indices)

        lo = max(0, token_index - self.context_prefix_count)
        hi = min(len(tokens), token_index + self.context_suffix_count + 1)
        return [tokens[i].text.lower() for i in range(lo, hi) if i != token_index] or [""]
