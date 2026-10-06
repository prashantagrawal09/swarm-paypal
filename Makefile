# Developer shortcuts. Run `make help` for the list.

PY := backend/.venv/bin
.DEFAULT_GOAL := help

.PHONY: help setup hooks db-up db-down migrate seed negotiate backend frontend test lint format check smoke smoke-sim

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: hooks ## Create the Python venv, install backend + frontend dependencies
	cd backend && python3.11 -m venv .venv && .venv/bin/pip install -q --upgrade pip \
		&& .venv/bin/pip install -q -e ".[dev]" \
		&& .venv/bin/pip install -q --no-deps -r requirements-toolkit.txt
	cd frontend && npm install

hooks: ## Point git at the repo's hooks (.githooks)
	git config core.hooksPath .githooks
	chmod +x .githooks/*

db-up: ## Start Postgres in Docker (port 5434)
	docker compose up -d --wait

db-down: ## Stop Postgres
	docker compose down

migrate: ## Apply database migrations
	cd backend && .venv/bin/alembic upgrade head

seed: ## Wipe the database and seed the Tiong Bahru demo world
	cd backend && .venv/bin/python -m app.seed.seed

negotiate: ## Play Monday + Tuesday of a Swarm week and print the agent negotiation
	cd backend && .venv/bin/python -m app.cli negotiate

backend: ## Run the API with auto-reload on :8000
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

frontend: ## Run the web app on :3000
	cd frontend && npm run dev

test: ## Run backend tests
	cd backend && .venv/bin/pytest

lint: ## Lint and type-check backend and frontend
	cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy app scripts
	cd frontend && npm run -s lint && npm run -s typecheck && npm run -s format:check

format: ## Auto-format backend and frontend
	cd backend && .venv/bin/ruff check --fix . && .venv/bin/ruff format .
	cd frontend && npm run -s format

check: lint test ## Everything CI runs

smoke: ## PayPal sandbox smoke test (needs .env credentials, approve in browser when asked)
	cd backend && .venv/bin/python scripts/paypal_smoke.py

smoke-sim: ## Same smoke test against the simulated PayPal client (no credentials needed)
	cd backend && .venv/bin/python scripts/paypal_smoke.py --simulated
