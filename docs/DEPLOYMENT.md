# Deployment & setup

Screenwall is a **single-user application for one computer**. The server listens on
`127.0.0.1` only and has no user accounts: the session cookie and the Host/Origin/CSRF checks
(`backend/app/security/web.py`) keep other web pages and DNS-rebinding tricks out. In the
packaged app the launcher also sets a per-start launch token (below), so other accounts on the
same computer, which reach `127.0.0.1` too, get no session. Programs running as the same user
are not kept out: they can read the token file, and the data folder, directly. Development mode
(`start.sh`) has no launch token: there any local program can open a session. Do **not** bind it
to `0.0.0.0`, put it behind a reverse proxy or expose it on a network: anyone who gets a session
can read the review screen, which shows the original text in mapping mode. There is no supported
multi-user or server deployment.

The packaged app is released for **macOS only** (Apple Silicon and Intel, macOS 14 or later).
Windows is not supported: there is no Windows package and no Windows CI job (the old Windows
launcher is kept in `archive/packaging-windows-2026-10-07/`).

There are two ways to run it:

| | Packaged app (release zip) | Development (`start.sh`) |
|---|---|---|
| For | users | working on the code |
| Processes | one server serves the API and the built UI | backend + Vite dev server |
| URL | `http://127.0.0.1:8765` (`SCREENWALL_PORT`) | `http://localhost:5174` (API on `:8000`) |
| Data | `SCREENWALL_HOME/data` | `backend/data` |

The two modes use different data folders; nothing is copied between them.

## Requirements

- **Ollama with `qwen3.5:4b` — required.** The local auditor decides approval. A document is
  approved only when a working LLM audited its current text (`pipeline/runner.py` `route`,
  `review/approval.py`). Without Ollama every document stops in review with the reason
  `auditor_unavailable`, `POST /api/documents/{id}/approve` returns `503 ollama_unreachable`,
  and download and chat, which need an approved document, stay closed. Ollama itself needs
  macOS 14 (Sonoma) or later; on Intel Macs it runs on the CPU only, so audits are slower. The
  model is about 3.4 GB and the same weights serve the auditor and local chat.
  The auditor sends the whole masked document in one `/api/chat` call with a fixed 120 s
  timeout (`audit/ollama_provider.py`; `audit/factory.py` does not override it and there is no
  setting). A timeout fails closed like any other provider error: the document stays in review
  with `auditor_unavailable`, and manual approval, which re-audits, returns
  `503 ollama_unreachable`. A document whose audit always takes longer than 120 s therefore
  cannot be approved; this is a failure, not just slowness.
- **uv** and Python 3.11–3.12 (`backend/pyproject.toml`; the launcher installs 3.12 through uv).
  The spaCy models are pinned as URL dependencies, so `uv sync` installs them; there is no
  separate `spacy download` step.
- **Node.js 18 or later**, only for development and for building the UI (CI uses Node 22).
- **Tesseract, optional**, for scanned PDF pages. `GET /api/health` reports `ocr.available`.

## 1. Packaged app

### What the launcher does

`packaging/macos/Screenwall.command`:

1. `SCREENWALL_HOME` is the base folder, by default `~/Library/Application Support/Screenwall`.
   It holds `data/` (`STORAGE_ROOT`), `venv/` (`UV_PROJECT_ENVIRONMENT`) and `logs/`, created
   with owner-only permissions.
2. Finds `uv` on `PATH` or in `~/.local/bin`, otherwise installs it with the official installer
   and `UV_NO_MODIFY_PATH=1`.
3. Runs `uv sync --frozen --no-dev --python 3.12` in `app/backend`.
4. Unless `SCREENWALL_SKIP_OLLAMA=1`: starts Ollama if it is installed but not running; if it is
   missing, prints Turkish guidance, opens https://ollama.com/download and continues (the app
   runs, but nothing can be approved); pulls `AUDITOR_MODEL` (default `qwen3.5:4b`) with visible
   progress when it is missing.
5. Makes Tesseract findable: adds `/opt/homebrew/bin` (Apple Silicon Homebrew) and
   `/usr/local/bin` (Intel Homebrew) to `PATH`.
6. If `http://127.0.0.1:PORT/health` already answers, only opens the browser.
7. Otherwise writes a new random launch token (32 bytes, hex) to `SCREENWALL_HOME/launch-token`
   (owner-only: `umask 077`) and starts, in
   `app/backend`:
   `uv run --frozen --no-dev uvicorn app.main:app --host 127.0.0.1 --port PORT`
   with `STORAGE_ROOT`, `UI_DIST=<absolute app/frontend/dist>`,
   `CORS_ALLOW_ORIGINS=http://127.0.0.1:PORT,http://localhost:PORT` and
   `LAUNCH_TOKEN_FILE=<that file>`. The file, not the environment, carries the token, so no
   process listing shows it.
8. Waits up to 90 seconds for `/health`, then opens `http://127.0.0.1:PORT/#k=<token>` unless
   `SCREENWALL_NO_BROWSER=1`. The UI reads the token from the fragment (which never reaches the
   server or a log), removes it from the address bar and sends it once, as `X-Launch-Token`, to
   `GET /api/session`; a new session is issued only with it (`401 launch_token_required`
   otherwise). The "already running" case of step 6 opens the same address with the token from
   the file. The window stays open while the server runs; Ctrl+C or closing the window stops the
   server. Ollama keeps running.

With `SCREENWALL_NO_BROWSER=1`, open `http://127.0.0.1:PORT/#k=` followed by the content of
`SCREENWALL_HOME/launch-token`. A bookmark of `http://127.0.0.1:PORT` works while the session
cookie lives (12 hours, same server run); after that, start the launcher again. Keep
`SCREENWALL_HOME` inside your own user folder: anyone who can read `launch-token` can open a
session while the server runs.

Launcher variables:

| Variable | Default | Meaning |
|---|---|---|
| `SCREENWALL_HOME` | see above | base folder for data, venv and logs |
| `SCREENWALL_PORT` | `8765` | server port |
| `SCREENWALL_NO_BROWSER` | unset | `1` = do not open the browser |
| `SCREENWALL_SKIP_OLLAMA` | unset | `1` = skip the Ollama checks (CI) |
| `AUDITOR_MODEL` | `qwen3.5:4b` | model the launcher pulls; the backend reads it too |

Logs: the launcher appends to `SCREENWALL_HOME/logs/server.log`. Logs are never rotated or
removed.

Measured on an Apple Silicon Mac with a warm uv cache (no downloads): first start 29–33 s to
`/health`, later starts about 4 s. A clean machine also downloads uv, CPython 3.12 and about
70 MB of wheels (the spaCy models come from GitHub).

What has been checked: the zip was unpacked and the launcher run from a terminal, end to end,
on an Apple Silicon Mac (macOS 26); every release is also smoke-tested on GitHub's Apple
Silicon (`macos-latest`) and Intel (`macos-15-intel`) runners (below). Not yet checked by hand:
a Finder double-click with the Gatekeeper prompt, a zip downloaded from the internet
(quarantine attribute), macOS 14–15 and a real Intel Mac. On Intel the only test is that smoke
test, which runs without Ollama (`SCREENWALL_SKIP_OLLAMA=1`, `--expect-auditor unavailable`):
approval, PDF download and chat with Ollama have never run on an Intel Mac, and CI runs the
backend tests only on Ubuntu and Apple Silicon. Whether a CPU-only Intel Mac finishes an audit
within the 120 s timeout (see Requirements) is not measured; measure one approval on a real
Intel Mac before claiming that approval works there.

**Windows is not supported.** The backend still keeps its Windows guards (the Claude and Codex
chat providers report `unsupported_os` there, and POSIX-only tests skip), but nothing is built
or tested for Windows.

### Building a release

```bash
make release VERSION=0.1.0      # = bash packaging/build_release.sh 0.1.0
```

Output in `dist/` (git-ignored): `Screenwall-macOS.zip`, `install-macos.sh` and
`SHA256SUMS.txt`. The zip has a top folder `Screenwall/` with `Screenwall.command`,
`OKU-BENI.txt`, `VERSION`, `app/backend/{app/, pyproject.toml, uv.lock}` (the PDF fonts and
their licence, `app/export/fonts/LICENSE-DejaVu.txt`, included) and the prebuilt
`app/frontend/dist/`. The script refuses a `uv.lock` that does not match `pyproject.toml`,
builds the UI in its own staging folder when `frontend/dist` is older than the sources, checks
the zip's entries (no caches, no Windows files) and moves earlier assets, including Windows
assets from older builds, to `dist/.previous/` instead of deleting them.

### CI and publishing

- `.github/workflows/ci.yml`: backend tests on Ubuntu and macOS, and frontend typecheck,
  vitest and build.
- `.github/workflows/release.yml` (tag `v*`): build → smoke test on `macos-latest` (Apple
  Silicon) and `macos-15-intel` (Intel) → draft release. The smoke job unpacks the zip with
  `ditto`, starts the launcher with `SCREENWALL_NO_BROWSER=1 SCREENWALL_SKIP_OLLAMA=1` and runs
  `packaging/smoke_test.py` (health, UI, launch token, session + CSRF, upload of a synthetic
  DOCX, at least one placeholder). `macos-15-intel` is GitHub's last Intel macOS image,
  announced as supported until August 2027; remove it from the matrix when it is retired.
- The same workflow runs on every pull request that touches `packaging/`, `backend/`,
  `frontend/` or the workflow itself, and by hand ("Run workflow", once the file is on the
  default branch). Those runs build and smoke-test but create no release. A tag whose smoke job
  fails on either runner gets no draft at all. Order: pull request with a green Release run,
  merge, then tag. The Release run must include a green `smoke (macos-15-intel)` job: that job
  is newer than the last Release run on the v0.1.0 pull request and has not run on GitHub yet.
- The draft must be published as a full release (not a prerelease). Until then the
  `releases/latest/download/<asset>` links in the README do not resolve. The README says so in
  one sentence under its download table and lists the first release on its roadmap; remove
  both in a separate commit right after the release is published (the README is not in the
  zip, so the release assets do not change).

The smoke test can also be run by hand against a running app:

```bash
cd backend && uv run python ../packaging/smoke_test.py --base-url http://127.0.0.1:8765 \
    --expect-auditor any \
    --launch-token-file "$HOME/Library/Application Support/Screenwall/launch-token"
```

Without `--launch-token-file` the test only works against a server that has no launch token
(development mode).

## 2. Development mode

```bash
cd backend && uv sync && cd ..
cd frontend && npm install && cd ..
bash start.sh     # Ollama (:11434) + uvicorn 127.0.0.1:8000 + Vite 127.0.0.1:5174
bash stop.sh      # stops the processes listening on 8000 and 5174; Ollama keeps running
```

`start.sh` pulls `qwen3.5:4b` in the background on the first run and writes logs to `.logs/`.
Vite serves the UI on 5174 with `strictPort` and proxies `/api` to `:8000`; the default
`CORS_ALLOW_ORIGINS` allows exactly that origin. Run the pieces by hand with
`uv run uvicorn app.main:app --host 127.0.0.1 --port 8000` in `backend/` and `npm run dev` in
`frontend/`.

## 3. Configuration

Settings come from environment variables and from **`backend/.env`**. The path is fixed
(`app/config.py`), whatever the working directory; environment variables win over the file.
The annotated template is `.env.example` at the repository root: copy it to `backend/.env`.
A relative `STORAGE_ROOT` or `UI_DIST` is resolved against `backend/`, not the working
directory, and `~` is expanded. Unknown names are ignored silently, so check the spelling.

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `development` | `development`, `production` or `test` |
| `STORAGE_ROOT` | `./data` (= `backend/data`) | the five storage layers, user settings, cloud-send log |
| `UI_DIST` | unset | built UI folder; when it holds `index.html` the server also serves the UI, and `CORS_ALLOW_ORIGINS` must name that origin |
| `MAX_UPLOAD_MB` | `50` | must be positive |
| `MAX_ITERATIONS` | `2` | 1 or 2: one detection pass plus at most one repair round. Any other value stops the app at startup |
| `ANONYMIZATION_MODE` | `mapping` | `mapping` keeps the original and the placeholder map (reviewable, reversible); `destructive` never writes them. Per-upload override and Ayarlar default |
| `AUDITOR_PROVIDER` | `ollama` | `mlx` and `llamacpp` pass validation but are not implemented: with them nothing can be approved |
| `AUDITOR_MODEL` | `qwen3.5:4b` | |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | used only when it is this computer, unless `OLLAMA_ALLOW_REMOTE=true` |
| `OLLAMA_ALLOW_REMOTE` | `false` | a remote host receives masked, not yet approved text; Ollama cloud models are always refused |
| `AUDITOR_RISK_APPROVE` | `low` | highest risk level the auditor may approve |
| `REQUIRE_LLM_AUDITOR` | `false` | approval needs a successful LLM audit either way; `true` only records a missing LLM as a fail-closed audit |
| `SPACY_EN_MODEL` | `en_core_web_sm` | another model must be installed into the venv first; changing it changes detection and is not measured |
| `SPACY_MULTILINGUAL_MODEL` | `xx_ent_wiki_sm` | |
| `ANONYMIZER_SCORE_THRESHOLD` | `0.4` | |
| `DENY_TERMS` / `ALLOW_TERMS` | empty | comma-separated always-mask / never-mask terms, on top of the seeded Turkish allow-list and the lists in Ayarlar |
| `TERM_LISTS` | `true` | `false` turns every list off (the scorecard runs this way) |
| `CHAT_DEFAULT_PROVIDER` | `ollama` | `ollama`, `claude_cli` or `codex_cli`; the choice in Ayarlar wins |
| `CHAT_OLLAMA_MODEL` | `qwen3.5:4b` | |
| `CHAT_CLAUDE_MODEL` / `CHAT_CODEX_MODEL` | empty | empty = the CLI's own default |
| `CHAT_CLI_TIMEOUT_S` | `60` | per CLI call |
| `CHAT_MAX_MESSAGE_CHARS` | `4000` | |
| `CORS_ALLOW_ORIGINS` | `http://localhost:5174,http://127.0.0.1:5174` | exactly the UI's origins; the packaged app uses `http://127.0.0.1:8765,http://localhost:8765` |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | allowed Host header names (port ignored) |
| `SESSION_REQUIRED` | `true` | only tests turn it off |
| `LAUNCH_TOKEN_FILE` | unset | packaged app: file holding the per-start launch token (16–256 characters of `A-Z a-z 0-9 _ -`); a new session then needs `X-Launch-Token`. An unreadable, empty or malformed file stops the app at startup. `LAUNCH_TOKEN` sets the value directly (tests) |
| `PROCESS_INLINE` | `false` | tests only |

Names from older versions that are now ignored: `CHAT_PROVIDER` (use `CHAT_DEFAULT_PROVIDER`)
and `USE_PRIVACY_FILTER` (the Privacy Filter stage is in `archive/privacy_filter/`).

## 4. Chat providers

- `ollama` (default): local, no consent step.
- `claude_cli` and `codex_cli`: cloud, through the user's own CLI login (`claude auth login`,
  `codex login`). Screenwall stores no API key. Every question first goes through
  `POST /api/chat/preview`, which returns the exact text that would leave the computer;
  `POST /api/chat` sends only with the matching `preview_hash`. Each send is recorded without
  content in `STORAGE_ROOT/chat_dispatches.jsonl`.

Chat only ever reads the approved, masked chat context (storage layer 5). See
[SECURITY.md](../SECURITY.md) and `backend/app/chat/service.py`.

## 5. Operations notes

- Storage: five layers under `STORAGE_ROOT`. On macOS and Linux the store is locked down to
  0700 directories and 0600 files at startup. `DELETE /api/documents/{id}` removes every layer
  of a document; on SSDs overwriting is not a guaranteed erase (see SECURITY.md).
- Logs pass through a PII-redacting filter and name documents by id.
- FastAPI's `/docs` and `/openapi.json` are still served on the same origin.
- Updating the packaged app: unpack the new zip (or rerun the install command, which moves the
  old folder aside). Data in `SCREENWALL_HOME` is kept.
