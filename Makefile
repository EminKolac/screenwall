# Fable - common commands. Run from the repository root: make <target>
.PHONY: test scorecard scorecard-full dev

TAG ?= fast
FULL_TAG ?= full

test: ## backend tests (pytest) + frontend unit tests (vitest)
	cd backend && uv run pytest -q
	cd frontend && npx vitest run

scorecard: ## fast scorecard: heuristic auditor only, no real documents
	cd backend && uv run python -m evaluation.scorecard --llm off --real 0 --tag $(TAG)

scorecard-full: ## full scorecard: live Qwen auditor via Ollama + 30 real BIST-10 PDFs
	cd backend && uv run python -m evaluation.scorecard --llm on --real 30 --tag $(FULL_TAG)

dev: ## start Ollama + backend + frontend in the background (start.sh)
	bash start.sh
