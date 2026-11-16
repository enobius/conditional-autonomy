#!/usr/bin/env bash
# Data-only PR retrieval. Runs solely from the trusted revision, never PR code.
set -euo pipefail
ulimit -f 4096
[[ "$PR_NUMBER" =~ ^[1-9][0-9]*$ ]] || exit 1
scratch=$(mktemp -d "$RUNNER_TEMP/shadow-fetch.XXXXXX")
mkdir -- "$SHADOW_FETCH_DEST"
gh pr view "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" --json baseRefName,baseRefOid,headRefOid,state > "$scratch/before.json"
jq -e '.baseRefName == "main" and .state == "OPEN" and (.baseRefOid | test("^[0-9a-f]{40}$")) and (.headRefOid | test("^[0-9a-f]{40}$"))' "$scratch/before.json" > /dev/null
base=$(jq -r .baseRefOid "$scratch/before.json")
head=$(jq -r .headRefOid "$scratch/before.json")
compare="repos/$GITHUB_REPOSITORY/compare/$base...$head"
gh api "$compare" > "$scratch/compare.json"
gh api -H 'Accept: application/vnd.github.v3.diff' "$compare" > "$SHADOW_FETCH_DEST/diff.patch"
merge_base=$(python -m tools.claude_shadow_workflow verify-compare --compare "$scratch/compare.json" --expected-base "$base" --diff "$SHADOW_FETCH_DEST/diff.patch")
[[ "$merge_base" =~ ^[0-9a-f]{40}$ ]] || exit 1
jq --arg sha "$merge_base" '. + {mergeBaseOid: $sha}' "$scratch/before.json" > "$SHADOW_FETCH_DEST/snapshot.json"
