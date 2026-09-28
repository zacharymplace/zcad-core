#!/usr/bin/env bash
# Commit and push evidence/ to its private backup repository
# (zacharymplace/zcad-core-evidence). Does nothing when evidence is unchanged.
set -euo pipefail

# evidence/ lives only in the main checkout, which sits next to the shared git
# directory, so linked worktrees back up the same copy.
main_checkout="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
evidence="$main_checkout/evidence"

if [[ ! -d "$evidence/.git" ]]; then
  echo "backup-evidence: $evidence is not a git repository" >&2
  exit 1
fi

git -C "$evidence" add -A

if git -C "$evidence" diff --cached --quiet; then
  echo "backup-evidence: no new evidence"
  exit 0
fi

git -C "$evidence" commit -q -m "Record evidence as of $(date -u +%Y-%m-%dT%H:%M:%SZ)"
git -C "$evidence" push -q
echo "backup-evidence: pushed $(git -C "$evidence" rev-parse --short HEAD)"
