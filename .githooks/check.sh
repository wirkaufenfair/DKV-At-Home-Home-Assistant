#!/bin/sh
# Lokale Pruefung vor Commit und Push: Ruff, dann alle Tests (inklusive der
# Waechter fuer Doku, Blaupause und Metadaten). Dauert wenige Sekunden.
# Gleiche Befehle wie in .github/workflows/ci.yml (Jobs "lint" und "tests").
# Nicht lokal pruefbar: hassfest, Markdown-Lint, actionlint und die Tests
# unter tests/ha (laufen nur unter Linux/macOS), die laufen in der CI.
set -e

cd "$(git rev-parse --show-toplevel)"

echo "[check] ruff"
python -m ruff check custom_components tests

echo "[check] tests"
python -m pytest tests -q
