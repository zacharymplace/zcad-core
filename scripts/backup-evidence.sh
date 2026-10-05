#!/usr/bin/env bash
# Commit and push evidence/ to its private backup repository
# (zacharymplace/zcad-core-evidence). Does nothing when evidence is unchanged.
set -euo pipefail

# Resolve the repository from this script's location, not the caller's working
# directory, which may be evidence/ itself (a separate repository).
cd "$(dirname "${BASH_SOURCE[0]}")"

# evidence/ lives only in the main checkout, which sits next to the shared git
# directory, so linked worktrees back up the same copy.
main_checkout="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
evidence="$main_checkout/evidence"

if [[ ! -d "$evidence/.git" ]]; then
  echo "backup-evidence: $evidence is not a git repository" >&2
  exit 1
fi

# A template every file command writes (a capture, a board, a housing) carries
# a needs_review line until it is filled in. Backing one up would record example
# readings as evidence, so refuse while any new or changed file still has one.
unreviewed=()

while IFS= read -r -d '' path; do
  # --modified lists deleted files too, which have nothing to check.
  if [[ "$path" == *.json && -f "$evidence/$path" ]] &&
    grep -q '"needs_review"' "$evidence/$path"; then
    unreviewed+=("$path")
  fi
done < <(git -C "$evidence" ls-files -z --others --modified --exclude-standard)

if (( ${#unreviewed[@]} )); then
  echo "backup-evidence: not backing up; these still say needs_review:" >&2
  printf '  %s\n' "${unreviewed[@]}" >&2
  echo "Fill each in and delete its needs_review line, or move it out of" >&2
  echo "evidence/, then run this again." >&2
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
