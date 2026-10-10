# Screenwall - common commands. Run from the repository root: make <target>
.PHONY: test scorecard scorecard-full dev release smoke-release

TAG ?= fast
FULL_TAG ?= full
VERSION ?=

test: ## backend tests (pytest) + frontend unit tests (vitest)
	cd backend && uv run pytest -q
	cd frontend && npx vitest run

scorecard: ## fast scorecard: heuristic auditor only, no real documents
	cd backend && uv run python -m evaluation.scorecard --llm off --real 0 --tag $(TAG)

scorecard-full: ## full scorecard: live Qwen auditor via Ollama + 30 real BIST-10 PDFs
	cd backend && uv run python -m evaluation.scorecard --llm on --real 30 --tag $(FULL_TAG)

dev: ## start Ollama + backend + frontend in the background (start.sh)
	bash start.sh

release: ## macOS release into dist/: Screenwall-macOS.dmg (on a Mac), zip, installer, SHA256SUMS (packaging/build_release.sh): make release VERSION=0.1.0
	bash packaging/build_release.sh $(VERSION)

smoke-release: ## smoke-test dist/ as CI does: start the zip and the dmg's app, run smoke_test.py (packaging/smoke_release.sh; port 8765 must be free)
	bash packaging/smoke_release.sh all
