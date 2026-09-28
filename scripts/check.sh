#!/usr/bin/env bash
# Run the same gates as .github/workflows/ci.yml: format, lint, types, tests.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

if [[ -x .venv/bin/python ]]; then
  python=.venv/bin/python
else
  python=python3
fi

echo "==> ruff format --check"
"$python" -m ruff format --check src tests

echo "==> ruff check"
"$python" -m ruff check src tests

echo "==> mypy"
"$python" -m mypy src

echo "==> pytest"
"$python" -m pytest -q
