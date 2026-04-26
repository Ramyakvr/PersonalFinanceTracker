APP := app

.PHONY: help install migrate seed build dev run test lint check scheduler setup

help:
	@echo "Targets:"
	@echo "  make install    - uv sync dependencies"
	@echo "  make migrate    - apply Django migrations"
	@echo "  make seed       - seed defaults (User, Profile, Categories)"
	@echo "  make build      - compile Tailwind once (minified)"
	@echo "  make dev        - Django + Tailwind watcher (recommended)"
	@echo "  make run        - Django runserver only"
	@echo "  make test       - pytest"
	@echo "  make lint       - ruff check + format --check"
	@echo "  make check      - Django system checks"
	@echo "  make scheduler  - django-q cluster (snapshots, FX refresh)"
	@echo "  make setup      - install + migrate + seed + build (first run)"

install:
	cd $(APP) && uv sync

migrate:
	cd $(APP) && uv run python manage.py migrate

seed:
	cd $(APP) && uv run python manage.py seed

build:
	cd $(APP) && ./bin/tailwindcss -i static/css/tailwind.css -o static/css/tailwind.out.css --minify

dev:
	cd $(APP) && ./scripts/dev.sh

run:
	cd $(APP) && uv run python manage.py runserver

test:
	cd $(APP) && uv run pytest

lint:
	cd $(APP) && uv run ruff check . && uv run ruff format --check .

check:
	cd $(APP) && uv run python manage.py check

scheduler:
	cd $(APP) && uv run python manage.py qcluster

setup: install migrate seed build
