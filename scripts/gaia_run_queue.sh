#!/usr/bin/env bash
# Works open GitHub issues, grouped into PR-sized batches by
# scripts/gaia_group_issues.py (milestone, else topic label, else solo;
# P0s split into their own earlier batch; capped at 4 issues/PR), through
# a real PR lifecycle per batch:
#
#   branch -> orchestrator resolves the whole batch together -> local
#   pre-flight gate -> open ONE PR (Closes #a, #b, #c) -> request Copilot
#   review -> wait -> ONE revision round addressing Copilot's comments ->
#   wait for GitHub Actions checks green -> squash-merge -> every issue in
#   the batch closes via "Closes #N", plus a scientist-facing close
#   comment written by the gaia-lab-notebook agent on each issue and (if
#   the batch belongs to a milestone) a progress note on that milestone's
#   epic tracker -- the epic itself is never closed by this script.
#
# Any failure at any stage leaves the PR/issues OPEN for a human and does
# NOT merge. Exactly one revision round is attempted.
#
# Requires: branch protection on main must actually allow this token to
# merge (or the merge step will just fail loudly, which is fine); jq.
#
# Cron example (every 30 min, single instance via flock):
#   */30 * * * * flock -n /tmp/gaia_run_queue.lock /path/to/scripts/gaia_run_queue.sh >> $HOME/gwl-space-time-smooth/.gaia-runs/cron.log 2>&1
set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/gwl-space-time-smooth}"
LOG_DIR="$REPO_DIR/.gaia-runs"
COPILOT_REVIEWER="copilot-pull-request-reviewer[bot]"   # verify this login on your org once by hand
REVIEW_WAIT_TRIES=40      # 40 * 30s = 20 min max wait for Copilot's first pass
REVIEW_WAIT_INTERVAL=30

: "${ANTHROPIC_API_KEY:?ANTHROPIC_API_KEY must be set}"

cd "$REPO_DIR"
mkdir -p "$LOG_DIR"
REPO_SLUG="$(gh repo view --json nameWithOwner -q .nameWithOwner)"

abandon_branch() {
  local branch="$1"
  git checkout main
  git branch -D "$branch" 2>/dev/null || true
  git push origin --delete "$branch" 2>/dev/null || true
}

wait_for_copilot_review() {
  local pr_number="$1" logfile="$2"
  for ((i = 0; i < REVIEW_WAIT_TRIES; i++)); do
    body="$(gh api "repos/${REPO_SLUG}/pulls/${pr_number}/reviews" \
      --jq "[.[] | select(.user.login == \"${COPILOT_REVIEWER}\")] | last")"
    if [ -n "$body" ] && [ "$body" != "null" ]; then
      echo "$body"
      return 0
    fi
    sleep "$REVIEW_WAIT_INTERVAL"
  done
  echo "  no Copilot review received within timeout" >> "$logfile"
  return 1
}

epic_for_milestone() {
  local milestone="$1"
  [ -z "$milestone" ] && return 0
  gh issue list --label epic --state open --json number,milestone \
    --jq ".[] | select(.milestone.title == \"${milestone}\") | .number" | head -1
}

git checkout main
git pull --ff-only origin main

while IFS= read -r batch_json; do
  [ -z "$batch_json" ] && continue

  branch="$(jq -r .branch <<<"$batch_json")"
  key="$(jq -r .key <<<"$batch_json")"
  milestone="$(jq -r '.milestone // empty' <<<"$batch_json")"
  readable_key="${key#milestone:}"; readable_key="${readable_key#topic:}"; readable_key="${readable_key#solo:}"
  numbers="$(jq -r '.issues[].number' <<<"$batch_json")"
  numbers_csv="$(jq -r '[.issues[].number] | map("#" + (. | tostring)) | join(", ")' <<<"$batch_json")"
  issue_bullets="$(jq -r '.issues[] | "- #\(.number): \(.title)"' <<<"$batch_json")"
  closes_lines="$(jq -r '.issues[] | "Closes #\(.number)"' <<<"$batch_json")"

  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  logfile="$LOG_DIR/batch-$(jq -r '.issues[0].number' <<<"$batch_json")-${ts}.log"
  echo "=== [${readable_key}] ${numbers_csv} -> ${logfile} ===" | tee -a "$logfile"

  git checkout main
  git pull --ff-only origin main

  existing_pr="$(gh pr list --head "$branch" --state open --json number -q '.[0].number' || true)"
  if [ -n "$existing_pr" ]; then
    echo "  PR #$existing_pr already open for ${numbers_csv}; skipping (re-run manually if it needs attention)" | tee -a "$logfile"
    continue
  fi

  git checkout -B "$branch" main

  impl_prompt="Use the gaia orchestrator to resolve this batch of related GitHub issues in
${REPO_SLUG}, grouped under '${readable_key}':

${issue_bullets}

Follow /gaia:ground-rules. These are related -- solve them together as one coherent
change where that makes sense, rather than as unrelated patches stapled together.
Make the minimal correct change (code, tests, and/or docs) for the whole batch.
Do not commit -- leave the working tree dirty for the pipeline to check."

  if ! claude -p "$impl_prompt" \
      --permission-mode acceptEdits \
      --dangerously-skip-permissions \
      >> "$logfile" 2>&1; then
    echo "  orchestrator failed on ${numbers_csv}; discarding" | tee -a "$logfile"
    abandon_branch "$branch"
    continue
  fi

  if git diff --quiet && git diff --cached --quiet; then
    echo "  no changes produced for ${numbers_csv}; skipping" | tee -a "$logfile"
    abandon_branch "$branch"
    continue
  fi

  echo "  pre-flight gate: pixi run test && pixi run check-dois" | tee -a "$logfile"
  if ! { pixi run test >> "$logfile" 2>&1 && pixi run check-dois >> "$logfile" 2>&1; }; then
    echo "  pre-flight gate FAILED for ${numbers_csv}; discarding, issues stay open" | tee -a "$logfile"
    abandon_branch "$branch"
    continue
  fi
  quarto render docs/twin --to html >> "$logfile" 2>&1 || {
    echo "  quarto render failed for ${numbers_csv}; discarding" | tee -a "$logfile"
    abandon_branch "$branch"
    continue
  }

  git add -A
  git commit -m "gaia: resolve ${numbers_csv} (${readable_key})

Automated change by the gaia orchestrator. Local test + check-dois gates
and the quarto book render passed before opening this PR.

Co-Authored-By: Claude <noreply@anthropic.com>"
  git push -u origin "$branch"

  pr_body="$(claude -p "Use the gaia-lab-notebook agent to write a clear, scientist-facing pull
request description for the change on branch ${branch} in ${REPO_DIR}, which together
resolves this batch of related issues (grouped under '${readable_key}'):

${issue_bullets}

Read the actual diff (git diff main...${branch}) -- don't guess. Explain in plain
language: what was wrong across these issues, what changed, and what it means
scientifically. No filler, no restating the diff line by line. End the body with
these literal lines, one per issue:
${closes_lines}" --permission-mode acceptEdits --dangerously-skip-permissions 2>>"$logfile")"

  pr_number="$(gh pr create --base main --head "$branch" \
    --title "gaia: ${readable_key} (${numbers_csv})" \
    --body "$pr_body" \
    --json number -q .number 2>>"$logfile" || gh pr view "$branch" --json number -q .number)"
  echo "  opened PR #$pr_number for ${numbers_csv}" | tee -a "$logfile"

  gh api "repos/${REPO_SLUG}/pulls/${pr_number}/requested_reviewers" \
    -f "reviewers[]=${COPILOT_REVIEWER}" >> "$logfile" 2>&1 \
    || echo "  could not request Copilot review via API; add it once by hand and re-run" | tee -a "$logfile"

  echo "  waiting for Copilot's review..." | tee -a "$logfile"
  if ! review="$(wait_for_copilot_review "$pr_number" "$logfile")"; then
    echo "  leaving PR #$pr_number open for a human; no Copilot review yet" | tee -a "$logfile"
    continue
  fi
  echo "$review" >> "$logfile"

  review_comments="$(gh api "repos/${REPO_SLUG}/pulls/${pr_number}/comments" --jq '.[] | "- \(.path):\(.line // .original_line): \(.body)"')"

  revise_prompt="Use the gaia orchestrator to address this Copilot code review on PR #${pr_number}
(branch ${branch}, resolving ${numbers_csv}) in ${REPO_DIR}.

Review summary:
${review}

Inline comments:
${review_comments}

Make the changes the review actually calls for -- don't pad the diff. If a comment is
wrong or out of scope, leave a note explaining why instead of blindly complying.
Do not commit -- leave the working tree dirty."

  claude -p "$revise_prompt" \
    --permission-mode acceptEdits \
    --dangerously-skip-permissions \
    >> "$logfile" 2>&1 || echo "  revision pass errored; continuing to gate check" | tee -a "$logfile"

  if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "  re-running gate after revision" | tee -a "$logfile"
    if pixi run test >> "$logfile" 2>&1 && pixi run check-dois >> "$logfile" 2>&1; then
      git add -A
      git commit -m "gaia: address Copilot review on #${pr_number}

Co-Authored-By: Claude <noreply@anthropic.com>"
      git push
    else
      echo "  revision broke the gate for ${numbers_csv}; leaving PR #$pr_number open for a human" | tee -a "$logfile"
      continue
    fi
  else
    echo "  no revision needed/produced" | tee -a "$logfile"
  fi

  echo "  waiting for GitHub Actions checks..." | tee -a "$logfile"
  if ! gh pr checks "$pr_number" --watch --fail-fast >> "$logfile" 2>&1; then
    echo "  checks did not pass on PR #$pr_number; leaving open for a human" | tee -a "$logfile"
    continue
  fi

  close_message="$(claude -p "Use the gaia-lab-notebook agent to write a short, clear message for a
research scientist explaining that this batch of related issues has just been resolved
and merged via PR #${pr_number} in ${REPO_DIR} (grouped under '${readable_key}'):

${issue_bullets}

Read the actual diff on that branch -- don't guess. Plain language: what was wrong,
what changed, what it means for the science/results. This will be posted as the
closing comment on each issue in the batch." \
    --permission-mode acceptEdits --dangerously-skip-permissions 2>>"$logfile")"

  gh pr merge "$pr_number" --squash --delete-branch --body "$close_message" >> "$logfile" 2>&1
  while IFS= read -r number; do
    [ -z "$number" ] && continue
    gh issue comment "$number" --body "$close_message"
  done <<< "$numbers"
  echo "  merged PR #$pr_number, closed ${numbers_csv}" | tee -a "$logfile"

  if [ -n "$milestone" ]; then
    epic_number="$(epic_for_milestone "$milestone")"
    if [ -n "$epic_number" ]; then
      gh issue comment "$epic_number" --body "Sub-issues ${numbers_csv} resolved via PR #${pr_number} (squash-merged, Copilot-reviewed, checks green). Epic left open for your own review." \
        || echo "  could not comment on epic #$epic_number" | tee -a "$logfile"
    fi
  fi
done < <(python3 "$REPO_DIR/scripts/gaia_group_issues.py")
