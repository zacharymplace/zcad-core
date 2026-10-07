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

# The CAD files (STEP, GLB, 3MF, zip) go through Git LFS, as evidence's
# .gitattributes says. Without git-lfs, git would commit them whole where a
# pointer belongs, so refuse rather than back up a repository LFS cannot read.
if [[ -f "$evidence/.gitattributes" ]] &&
  grep -q 'filter=lfs' "$evidence/.gitattributes" &&
  ! git -C "$evidence" lfs version >/dev/null 2>&1; then
  echo "backup-evidence: evidence/ stores its CAD files with Git LFS, and git-lfs" >&2
  echo "is not installed. Install it (brew install git-lfs), run" >&2
  echo "'git -C evidence lfs install --local', then run this again." >&2
  exit 1
fi

# GitHub refuses any file over 100 MB that is not in LFS, which would fail the
# push after the commit. Overridable so the tests need no 95 MB file.
limit_bytes="${EVIDENCE_GIT_FILE_LIMIT_BYTES:-95000000}"

# A template every file command writes (a capture, a board, a housing) carries
# a needs_review line until it is filled in. Backing one up would record example
# readings as evidence, so refuse while any new or changed file still has one.
unreviewed=()
oversized=()

while IFS= read -r -d '' path; do
  # --modified lists deleted files too, which have nothing to check.
  [[ -f "$evidence/$path" ]] || continue

  if [[ "$path" == *.json ]] && grep -q '"needs_review"' "$evidence/$path"; then
    unreviewed+=("$path")
  fi

  if (( $(wc -c <"$evidence/$path") > limit_bytes )) &&
    [[ "$(git -C "$evidence" check-attr filter -- "$path")" != *": filter: lfs" ]]; then
    oversized+=("$path")
  fi
done < <(git -C "$evidence" ls-files -z --others --modified --exclude-standard)

if (( ${#unreviewed[@]} )); then
  echo "backup-evidence: not backing up; these still say needs_review:" >&2
  printf '  %s\n' "${unreviewed[@]}" >&2
  echo "Fill each in and delete its needs_review line, or move it out of" >&2
  echo "evidence/, then run this again." >&2
  exit 1
fi

if (( ${#oversized[@]} )); then
  echo "backup-evidence: not backing up; these are too large for git and not in LFS:" >&2
  printf '  %s\n' "${oversized[@]}" >&2
  echo "Track their type with 'git -C evidence lfs track \"*.<ext>\"', then run" >&2
  echo "this again." >&2
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
