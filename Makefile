.PHONY: dev dev-build down logs backend-shell web-shell frontend-shell migrate makemigrations createsuperuser test test-backend test-frontend test-sandbox test-coverage lint lint-backend lint-frontend typecheck check format build build-production clean tauri-dev tauri-build tauri-android-dev tauri-ios-dev tauri-android-build tauri-ios-build

# ─── Local Development ────────────────────────────────────────────────

dev:
	docker compose -f infra/docker-compose.local.yml up

dev-build:
	docker compose -f infra/docker-compose.local.yml up --build

down:
	docker compose -f infra/docker-compose.local.yml down

logs:
	docker compose -f infra/docker-compose.local.yml logs -f

# ─── Shell Access ─────────────────────────────────────────────────────

backend-shell:
	docker compose -f infra/docker-compose.local.yml exec django bash

web-shell:
	docker compose -f infra/docker-compose.local.yml exec web sh

frontend-shell:
	docker compose -f infra/docker-compose.local.yml exec web sh

# ─── Database ─────────────────────────────────────────────────────────

migrate:
	cd packages/backend && uv run manage.py migrate

makemigrations:
	cd packages/backend && uv run manage.py makemigrations

createsuperuser:
	cd packages/backend && uv run manage.py createsuperuser

# ─── Testing ──────────────────────────────────────────────────────────

test: test-backend test-frontend test-sandbox

test-backend:
	cd packages/backend && uv run pytest

test-frontend:
	cd packages/frontend && npm run test:unit

test-sandbox:
	cd packages/sandbox && uv run pytest

test-coverage:
	cd packages/backend && uv run pytest --cov --cov-report=term-missing --cov-fail-under=100
	cd packages/frontend && npx vitest run --coverage
	cd packages/sandbox && uv run pytest --cov --cov-report=term-missing --cov-fail-under=100

# ─── Linting & Formatting ────────────────────────────────────────────

lint: lint-backend lint-frontend

lint-backend:
	cd packages/backend && uv run ruff check . && uv run ruff format --check .

lint-frontend:
	cd packages/frontend && npm run lint

typecheck:
	cd packages/backend && uv run mypy .
	cd packages/frontend && npm run check

check:
	cd packages/frontend && npm run check

format:
	cd packages/backend && uv run ruff format .
	cd packages/frontend && npm run format

# ─── Build ────────────────────────────────────────────────────────────

build:
	cd packages/frontend && npm run build

build-production:
	docker compose -f infra/docker-compose.production.yml build

# ─── Tauri (Desktop & Mobile) ────────────────────────────────────────

tauri-dev:
	cd packages/frontend && npm run tauri:dev

tauri-build:
	cd packages/frontend && npm run tauri:build

tauri-android-dev:
	cd packages/frontend && npm run tauri:dev:android

tauri-ios-dev:
	cd packages/frontend && npm run tauri:dev:ios

tauri-android-build:
	cd packages/frontend && npm run tauri:build:android

tauri-ios-build:
	cd packages/frontend && npm run tauri:build:ios

# ─── Cleanup ──────────────────────────────────────────────────────────

clean:
	docker compose -f infra/docker-compose.local.yml down -v --remove-orphans
