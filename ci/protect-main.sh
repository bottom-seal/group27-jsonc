#!/bin/bash
# Turn on branch protection for main. Run once, as a repo admin, after a
# second code owner is listed in .github/CODEOWNERS (see the note there).
#
# Usage: ci/protect-main.sh [OWNER/REPO]     (default: the repo gh points at)
#
# What it sets:
# - changes reach main only through a PR, with 1 approval, which must come
#   from a code owner when the PR touches files that have one;
# - the PR must pass the checks "paths", "gate" and "self-test" on an
#   up-to-date branch;
# - a new push dismisses earlier approvals;
# - the rules apply to admins too; no force pushes, no deleting main.
set -euo pipefail
repo=${1:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}
gh api --method PUT "repos/$repo/branches/main/protection" --input - >/dev/null <<'JSON'
{
  "required_status_checks": {"strict": true, "contexts": ["paths", "gate", "self-test"]},
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "require_code_owner_reviews": true,
    "dismiss_stale_reviews": true
  },
  "restrictions": null,
  "required_conversation_resolution": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
echo "Branch protection is on for main in $repo:"
gh api "repos/$repo/branches/main/protection" --jq '{
  required_checks: .required_status_checks.contexts,
  approvals: .required_pull_request_reviews.required_approving_review_count,
  code_owner_review: .required_pull_request_reviews.require_code_owner_reviews,
  applies_to_admins: .enforce_admins.enabled
}'
