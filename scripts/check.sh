#!/usr/bin/env bash
# Run the same gates as .github/workflows/ci.yml: format, lint, types, tests.
#   --fast  skip tests marked slow (those that load vendor STEP models from
#           evidence/). The pre-push hook always runs the full suite, since
#           evidence/ is local and nothing else runs those tests.
set -euo pipefail

pytest_args=(-q)

case "${1:-}" in
  "") ;;
  --fast) pytest_args+=(-m "not slow") ;;
  *)
    echo "usage: $0 [--fast]" >&2
    exit 2
    ;;
esac

# Resolve the repository from this script's location, not the caller's working
# directory, which may be evidence/ itself (a separate repository). Not from
# `git rev-parse --show-toplevel`: a hook runs with GIT_DIR set and no work
# tree, so in a linked worktree that answers with the current directory.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

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
"$python" -m ruff format --check src tests scripts examples

echo "==> ruff check"
"$python" -m ruff check src tests scripts examples

echo "==> mypy"
"$python" -m mypy src scripts tests examples

echo "==> pytest ${pytest_args[*]:1}"
"$python" -m pytest "${pytest_args[@]}"
