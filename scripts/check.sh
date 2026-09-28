#!/usr/bin/env bash
# Run the same gates as .github/workflows/ci.yml: format, lint, types, tests.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# Linked worktrees have no .venv of their own, so fall back to the main
# checkout's, which sits next to the shared git directory.
main_checkout="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"

if [[ -x .venv/bin/python ]]; then
  python=.venv/bin/python
elif [[ -x "$main_checkout/.venv/bin/python" ]]; then
  python="$main_checkout/.venv/bin/python"
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
