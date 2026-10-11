# Üçüncü taraf lisansları

Screenwall'ın kendi kodu GNU AGPL-3.0-only ile yayımlanıyor ([`LICENSE`](LICENSE)). Bu dosya,
sürüm dosyalarıyla gelen ya da Screenwall'ın kullandığı başlıca üçüncü taraf bileşenlerin
lisanslarını özetler. Bağlayıcı olan, her bileşenin kendi lisans metnidir; derlenmiş arayüzle
gelen paketlerin metinleri bu dosyanın sonunda ("Lisans metinleri"). Bağımlılıkların tam
listesi `backend/uv.lock` ve `frontend/package-lock.json` dosyalarında.

Sürümler v0.1.0'daki kilit dosyalarından alındı.

## Sürüm dosyalarının içinde gelenler

| Bileşen | Lisans | Nerede |
|---|---|---|
| DejaVu Sans, DejaVu Sans Bold | Bitstream Vera ve Arev yazı tipi lisansları; DejaVu değişiklikleri kamu malı | `backend/app/export/fonts/`, lisans metni [`LICENSE-DejaVu.txt`](backend/app/export/fonts/LICENSE-DejaVu.txt) |
| React 18.3.1, React DOM 18.3.1, scheduler 0.23.2 | MIT | derlenmiş arayüzün içinde (`frontend/dist`); lisans metni aşağıda |
| React Router 6.30.6 (react-router-dom, react-router, @remix-run/router 1.23.4) | MIT | derlenmiş arayüzün içinde; lisans metni aşağıda |
| TanStack Query 5.103.2 (@tanstack/react-query, @tanstack/query-core) | MIT | derlenmiş arayüzün içinde; lisans metni aşağıda |

## İlk açılışta indirilenler

Başlatıcı bunları `uv` ile, `backend/uv.lock` dosyasındaki sürümlerle kullanıcının veri
klasörüne kurar; sürüm dosyalarının içinde değiller.

| Bileşen | Lisans |
|---|---|
| PyMuPDF 1.27.2.3 | AGPL-3.0 (Artifex'in ayrıca ticari lisansı var) |
| presidio-analyzer 2.2.362 | MIT |
| spaCy 3.8.14 | MIT |
| spaCy modeli `en_core_web_sm` 3.8.0 | MIT |
| spaCy modeli `xx_ent_wiki_sm` 3.8.0 | MIT; eğitim verisi WikiNER (Nothman ve diğerleri), CC BY 4.0 |
| FastAPI 0.138.0 | MIT |
| Uvicorn | BSD-3-Clause |
| Pydantic, pydantic-settings | MIT |
| python-multipart | Apache-2.0 |
| httpx | BSD-3-Clause |
| python-docx | MIT |
| openpyxl | MIT |
| langdetect 1.0.9 | Apache-2.0 |

## Ayrıca kurulan programlar ve model

Screenwall bunları içermez; kuruluysa kullanır.

| Bileşen | Lisans | Not |
|---|---|---|
| [Ollama](https://ollama.com) | MIT | Onay için zorunlu (denetçi); lokal LLM sohbeti de bunu kullanır |
| Qwen 3.5 4B (`qwen3.5:4b`) | Apache-2.0 | Ollama kütüphanesindeki modelin lisans katmanından |
| [uv](https://docs.astral.sh/uv/) | MIT ya da Apache-2.0 | Başlatıcı yoksa kendisi kurar |
| [Tesseract](https://github.com/tesseract-ocr/tesseract) | Apache-2.0 | İsteğe bağlı, taranmış PDF sayfaları için |
| Claude Code CLI, Codex CLI | kendi kullanım koşulları | İsteğe bağlı bulut sohbeti; sizin oturumunuzla çalışır |

## Lisans metinleri

MIT lisansı, telif satırının ve izin metninin yazılımın her kopyasıyla birlikte gelmesini ister.
Derlenmiş arayüzde (`frontend/dist`) bulunan paketlerin lisans metinleri aşağıda,
`frontend/node_modules` altındaki dosyalardan aynen alındı. Aynı ailedeki paketlerin lisans
dosyaları birebir aynı olduğu için her metin bir kez verildi. `loose-envify` ve `js-tokens`
yalnız derleme sırasında kullanılır; derlenmiş arayüze girmez.

### React, React DOM, scheduler

`react/LICENSE` (`react-dom` ve `scheduler` paketlerindeki `LICENSE` dosyaları aynı):

```text
MIT License

Copyright (c) Facebook, Inc. and its affiliates.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### React Router, react-router-dom, @remix-run/router

`react-router/LICENSE.md` (`react-router-dom` ve `@remix-run/router` paketlerindeki
`LICENSE.md` dosyaları aynı):

```text
MIT License

Copyright (c) React Training LLC 2015-2019
Copyright (c) Remix Software Inc. 2020-2021
Copyright (c) Shopify Inc. 2022-2023

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### TanStack Query (@tanstack/react-query, @tanstack/query-core)

`@tanstack/query-core/LICENSE` (`@tanstack/react-query` paketindeki `LICENSE` dosyası aynı):

```text
MIT License

Copyright (c) 2021-present Tanner Linsley

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
