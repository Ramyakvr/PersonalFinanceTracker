#!/usr/bin/env bash
# Run Django dev server and Tailwind watcher side-by-side.
# Ctrl-C once to stop both.

set -euo pipefail

cd "$(dirname "$0")/.."

cleanup() {
  jobs -p | xargs -r kill 2>/dev/null || true
}
trap cleanup EXIT

./bin/tailwindcss -i static/css/tailwind.css -o static/css/tailwind.out.css --watch &
uv run python manage.py runserver &

wait
