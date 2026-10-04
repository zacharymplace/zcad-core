#!/usr/bin/env bash
# Run the test suite on a Python version other than the project's own (3.11).
#   scripts/check-python.sh 3.12              the full suite on Python 3.12
#   scripts/check-python.sh 3.12 -k stack     anything after the version goes to pytest
# The package says it supports 3.11 and later, but the gate and the CI workflow
# run only 3.11, and GitHub Actions is disabled for this account, so a newer
# version is tested only when this is run. Each version gets its own environment,
# .venv-py<version>, beside the main checkout's .venv and shared by its worktrees;
# delete the directory to start it again. Needs uv, or python<version> on the PATH.
# Only the tests run: ruff and mypy check the source, not the interpreter.
set -euo pipefail

version="${1:-}"

if [[ ! "$version" =~ ^3\.[0-9]+$ ]]; then
  echo "usage: $0 <python version, such as 3.12> [pytest arguments]" >&2
  exit 2
fi

shift

# The repository from this script's location, as check.sh does, and the main
# checkout, which holds the environments.
cd "$(dirname "${BASH_SOURCE[0]}")/.."
repo="$PWD"
main_checkout="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
venv="$main_checkout/.venv-py$version"

# A hook exports GIT_DIR and friends, which a test that runs git would obey.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR GIT_OBJECT_DIRECTORY \
  GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_NAMESPACE GIT_PREFIX

if [[ ! -x "$venv/bin/python" ]]; then
  echo "==> creating $venv (Python $version)"

  if command -v uv >/dev/null 2>&1; then
    uv venv --python "$version" "$venv"
  elif command -v "python$version" >/dev/null 2>&1; then
    "python$version" -m venv "$venv"
  else
    echo "check-python: neither uv nor python$version is on the PATH" >&2
    echo "(install uv: https://docs.astral.sh/uv/)" >&2
    exit 1
  fi
fi

# From pyproject.toml, so the dependencies cannot drift from the project's. Not
# editable: the tests import the checkout's src/ (pytest's pythonpath), which is
# this checkout's even when the environment is shared.
echo "==> installing the dependencies"

if command -v uv >/dev/null 2>&1; then
  uv pip install --quiet --python "$venv/bin/python" "$repo[dev]"
else
  "$venv/bin/python" -m pip install --quiet "$repo[dev]"
fi

"$venv/bin/python" - <<'PY'
import importlib.metadata as metadata
import sys

libraries = ("cadquery", "cadquery-ocp", "numpy", "scipy", "pytest")
versions = ", ".join(f"{name} {metadata.version(name)}" for name in libraries)
print(f"==> Python {sys.version.split()[0]}: {versions}")
PY

echo "==> pytest on Python $version"
# Geometry tests are CPU-bound and independent, as in check.sh.
exec "$venv/bin/python" -m pytest -q -n auto "$@"
