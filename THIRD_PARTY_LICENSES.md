# Üçüncü taraf lisansları

Screenwall'ın kendi kodu GNU AGPL-3.0-only ile yayımlanıyor ([`LICENSE`](LICENSE)). Bu dosya,
sürüm dosyalarıyla gelen ya da Screenwall'ın kullandığı başlıca üçüncü taraf bileşenlerin
lisanslarını özetler. Bağlayıcı olan, her bileşenin kendi lisans metnidir. Bağımlılıkların tam
listesi `backend/uv.lock` ve `frontend/package-lock.json` dosyalarında.

Sürümler v0.1.0'daki kilit dosyalarından alındı.

## Sürüm dosyalarının içinde gelenler

| Bileşen | Lisans | Nerede |
|---|---|---|
| DejaVu Sans, DejaVu Sans Bold | Bitstream Vera ve Arev yazı tipi lisansları; DejaVu değişiklikleri kamu malı | `backend/app/export/fonts/`, lisans metni [`LICENSE-DejaVu.txt`](backend/app/export/fonts/LICENSE-DejaVu.txt) |
| React 18.3.1, React DOM 18.3.1, scheduler | MIT | derlenmiş arayüzün içinde (`frontend/dist`) |
| React Router 6.30.6 (react-router-dom, react-router, @remix-run/router) | MIT | derlenmiş arayüzün içinde |
| TanStack Query 5.103.2 (@tanstack/react-query, @tanstack/query-core) | MIT | derlenmiş arayüzün içinde |

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
| [Ollama](https://ollama.com) | MIT | Onay için zorunlu (denetçi); yerel sohbet de bunu kullanır |
| Qwen 3.5 4B (`qwen3.5:4b`) | Apache-2.0 | Ollama kütüphanesindeki modelin lisans katmanından |
| [uv](https://docs.astral.sh/uv/) | MIT ya da Apache-2.0 | Başlatıcı yoksa kendisi kurar |
| [Tesseract](https://github.com/tesseract-ocr/tesseract) | Apache-2.0 | İsteğe bağlı, taranmış PDF sayfaları için |
| Claude Code CLI, Codex CLI | kendi kullanım koşulları | İsteğe bağlı bulut sohbeti; sizin oturumunuzla çalışır |
