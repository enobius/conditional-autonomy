#!/usr/bin/env bash
# Data-only PR retrieval. Runs solely from the trusted revision, never PR code.
set -euo pipefail
ulimit -f 4096
[[ "$PR_NUMBER" =~ ^[1-9][0-9]{0,9}$ ]] || exit 1
[[ "$SHADOW_BASE_SHA" =~ ^[0-9a-f]{40}$ && "$SHADOW_HEAD_SHA" =~ ^[0-9a-f]{40}$ ]] || exit 1
[[ "$SHADOW_BASE_SHA" != "$SHADOW_HEAD_SHA" && "$SHADOW_BASE_SHA" != 0000000000000000000000000000000000000000 && "$SHADOW_HEAD_SHA" != 0000000000000000000000000000000000000000 ]] || exit 1
scratch=$(mktemp -d "$RUNNER_TEMP/shadow-fetch.XXXXXX")
mkdir -- "$SHADOW_FETCH_DEST"
observe() {
    gh pr view "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" \
        --json number,baseRefName,baseRefOid,headRefOid,isCrossRepository,state > "$1"
}
check_pin() {
    python -m tools.claude_shadow_workflow verify-pilot-pr --before "$1" \
        --expected-pr "$PR_NUMBER" --expected-base "$SHADOW_BASE_SHA" --expected-head "$SHADOW_HEAD_SHA" "${@:2}"
}
observe "$scratch/before.json"
check_pin "$scratch/before.json"
compare="repos/$GITHUB_REPOSITORY/compare/$SHADOW_BASE_SHA...$SHADOW_HEAD_SHA"
gh api "$compare" > "$scratch/compare.json"
gh api -H 'Accept: application/vnd.github.v3.diff' "$compare" > "$SHADOW_FETCH_DEST/diff.patch"
merge_base=$(python -m tools.claude_shadow_workflow verify-compare --compare "$scratch/compare.json" --expected-base "$SHADOW_BASE_SHA" --diff "$SHADOW_FETCH_DEST/diff.patch")
observe "$scratch/after.json"
check_pin "$scratch/after.json" --merge-base "$merge_base" > "$scratch/accepted.json"
mv -- "$scratch/accepted.json" "$SHADOW_FETCH_DEST/snapshot.json"
