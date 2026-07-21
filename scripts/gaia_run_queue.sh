#!/usr/bin/env bash
# Works open GitHub issues, grouped into PR-sized batches by
# scripts/gaia_group_issues.py (milestone, else topic label, else solo;
# P0s split into their own earlier batch; capped at 4 issues/PR), through
# a real PR lifecycle per batch:
#
#   branch -> orchestrator resolves the whole batch together -> local
#   pre-flight gate -> open ONE PR (Closes #a, #b, #c) -> request Copilot
#   review -> wait -> revise-and-re-review, up to REVIEW_MAX_ROUNDS times,
#   stopping early once Copilot has nothing new to say -> wait for GitHub
#   Actions checks green -> squash-merge -> every issue in the batch closes
#   via "Closes #N", plus a scientist-facing close comment written by the
#   gaia-lab-notebook agent on each issue and (if the batch belongs to a
#   milestone) a progress note on that milestone's epic tracker -- the epic
#   itself is never closed by this script.
#
# Copilot's code review NEVER submits an "Approve" state -- only ever
# COMMENTED -- so "converged" means its inline comments stopped changing
# between rounds, not that it approved. The merge step therefore relies on
# main's ruleset having a bypass_actor entry for this token (bypass_mode
# pull_request, so direct-push protections on main still apply to it) --
# without that, the required-approving-review rule blocks the merge forever.
#
# Any failure at any stage leaves the PR/issues OPEN for a human and does
# NOT merge.
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
REVIEW_WAIT_TRIES=40      # 40 * 30s = 20 min max wait for each Copilot pass
REVIEW_WAIT_INTERVAL=30
REVIEW_MAX_ROUNDS=3       # cap on revise-and-re-review rounds; see the convergence note above

: "${ANTHROPIC_API_KEY:?ANTHROPIC_API_KEY must be set}"

cd "$REPO_DIR"
mkdir -p "$LOG_DIR"
REPO_SLUG="$(gh repo view --json nameWithOwner -q .nameWithOwner)"

# Every failure path below calls this: it prints WHY inline (exit code + the tail of the actual
# claude/pixi/quarto output) so a failure is diagnosable from the console alone, not only by
# separately opening $logfile on whatever box this ran on.
report_failure() {
  local msg="$1" logfile="$2" exit_code="${3:-?}"
  {
    echo ""
    echo "  !!! $msg (exit $exit_code)"
    echo "  --- last 40 lines of $logfile ---"
    tail -n 40 "$logfile" 2>/dev/null | sed 's/^/  | /'
    echo "  --- end of tail; full log at $logfile ---"
  } | tee -a "$logfile"
}

abandon_branch() {
  local branch="$1" logfile="$2"
  {
    echo "  abandoning branch ${branch}:"
    git diff --stat 2>&1
    git checkout main 2>&1
    git branch -D "$branch" 2>&1 || true
    git push origin --delete "$branch" 2>&1 || true
  } >> "$logfile" 2>&1
}

wait_for_copilot_review() {
  # $3 (optional): an ISO8601 "since" timestamp -- only accept a review SUBMITTED AFTER this. Needed
  # on every round after the first: dismiss_stale_reviews_on_push + copilot_code_review's
  # review_on_push retrigger a fresh review on every push, but the *previous* review is still "last"
  # until the new one lands -- without this filter, round 2+ would immediately re-return round 1's
  # stale review instead of waiting for Copilot to actually look at the revision.
  local pr_number="$1" logfile="$2" since="${3:-}"
  for ((i = 0; i < REVIEW_WAIT_TRIES; i++)); do
    # A transient gh api hiccup here must not kill the whole script mid-poll -- fall through to
    # the sleep-and-retry rather than let a single failed request propagate under `set -e`.
    body="$(gh api "repos/${REPO_SLUG}/pulls/${pr_number}/reviews" \
      --jq "[.[] | select(.user.login == \"${COPILOT_REVIEWER}\")] | last" 2>>"$logfile")" || body=""
    if [ -n "$body" ] && [ "$body" != "null" ]; then
      submitted_at="$(jq -r '.submitted_at // empty' <<<"$body")"
      if [ -z "$since" ] || [ -z "$submitted_at" ] || [[ "$submitted_at" > "$since" ]]; then
        echo "$body"
        return 0
      fi
    fi
    sleep "$REVIEW_WAIT_INTERVAL"
  done
  echo "  no (fresh) Copilot review received within timeout" >> "$logfile"
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

  # `cmd && rc=0 || rc=$?` (not a bare `cmd; rc=$?`) is required here: under `set -e`, a plain
  # failing command exits the script immediately, before a following `rc=$?` line ever runs.
  # Streamed through `tee` (not `>>` alone) so the orchestrator's work is visible on the console
  # live, before the pre-flight gate/commit/push below ever touch GitHub. `set -o pipefail` (from
  # the script's `set -euo pipefail`) keeps `orchestrator_rc` reflecting claude's exit code, not tee's.
  echo "  running gaia orchestrator on ${numbers_csv} (live below, also logged to $logfile)..." | tee -a "$logfile"
  claude -p "$impl_prompt" \
      --permission-mode acceptEdits \
      --dangerously-skip-permissions \
      2>&1 | tee -a "$logfile" && orchestrator_rc=0 || orchestrator_rc=$?
  if [ "$orchestrator_rc" -ne 0 ]; then
    report_failure "orchestrator failed on ${numbers_csv}; discarding" "$logfile" "$orchestrator_rc"
    abandon_branch "$branch" "$logfile"
    continue
  fi

  if git diff --quiet && git diff --cached --quiet; then
    echo "  no changes produced for ${numbers_csv}; skipping (see $logfile for what the orchestrator said)" | tee -a "$logfile"
    abandon_branch "$branch" "$logfile"
    continue
  fi

  echo "  pre-flight gate: pixi run test && pixi run check-dois" | tee -a "$logfile"
  { pixi run test >> "$logfile" 2>&1 && pixi run check-dois >> "$logfile" 2>&1; } && test_rc=0 || test_rc=$?
  if [ "$test_rc" -ne 0 ]; then
    report_failure "pre-flight gate FAILED for ${numbers_csv}; discarding, issues stay open" "$logfile" "$test_rc"
    abandon_branch "$branch" "$logfile"
    continue
  fi
  quarto render docs/twin --to html >> "$logfile" 2>&1 && quarto_rc=0 || quarto_rc=$?
  if [ "$quarto_rc" -ne 0 ]; then
    report_failure "quarto render failed for ${numbers_csv}; discarding" "$logfile" "$quarto_rc"
    abandon_branch "$branch" "$logfile"
    continue
  fi

  git add -A
  git commit -m "gaia: resolve ${numbers_csv} (${readable_key})

Automated change by the gaia orchestrator. Local test + check-dois gates
and the quarto book render passed before opening this PR.

Co-Authored-By: Claude <noreply@anthropic.com>"
  git push -u origin "$branch"

  # A bare `var="$(cmd)"` with no exit-code guard would, under `set -e`, silently kill the WHOLE
  # script (not just this batch) if `cmd` fails -- there is no later stage to report or recover.
  # Guard it, and fall back to a minimal body/message (still carrying the Closes lines) so a
  # lab-notebook drafting failure never blocks the actual PR from opening or merging.
  echo "  drafting PR description via gaia-lab-notebook (logged to $logfile)..." | tee -a "$logfile"
  pr_body="$(claude -p "Use the gaia-lab-notebook agent to write a clear, scientist-facing pull
request description for the change on branch ${branch} in ${REPO_DIR}, which together
resolves this batch of related issues (grouped under '${readable_key}'):

${issue_bullets}

Read the actual diff (git diff main...${branch}) -- don't guess. Explain in plain
language: what was wrong across these issues, what changed, and what it means
scientifically. No filler, no restating the diff line by line. End the body with
these literal lines, one per issue:
${closes_lines}" --permission-mode acceptEdits --dangerously-skip-permissions 2>>"$logfile")" \
    && pr_body_rc=0 || pr_body_rc=$?
  if [ "$pr_body_rc" -ne 0 ] || [ -z "$pr_body" ]; then
    report_failure "gaia-lab-notebook failed to draft the PR body for ${numbers_csv}; using a minimal body" "$logfile" "$pr_body_rc"
    pr_body="Automated change resolving ${numbers_csv} (${readable_key}). PR description drafting failed; see ${logfile}.

${closes_lines}"
  fi

  # Never trust the agent's prose to have transcribed every "Closes #N" line correctly -- append
  # any issue from this batch whose closing line the drafted body doesn't already contain. A
  # duplicate "Closes #N" is harmless to GitHub; a MISSING one silently breaks the whole point of
  # this pipeline (the issue stays open after merge), so the script guarantees it, not the LLM.
  missing_closes=""
  while IFS= read -r number; do
    [ -z "$number" ] && continue
    if ! grep -qiE "(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)[[:space:]]+#${number}([^0-9]|$)" <<<"$pr_body"; then
      missing_closes="${missing_closes}Closes #${number}
"
    fi
  done <<< "$numbers"
  if [ -n "$missing_closes" ]; then
    echo "  pr body was missing closing keywords for some issues; appending them" | tee -a "$logfile"
    pr_body="${pr_body}

${missing_closes}"
  fi

  pr_number="$(gh pr create --base main --head "$branch" \
    --title "gaia: ${readable_key} (${numbers_csv})" \
    --body "$pr_body" \
    --json number -q .number 2>>"$logfile" || gh pr view "$branch" --json number -q .number 2>>"$logfile")" \
    && pr_create_rc=0 || pr_create_rc=$?
  if [ "$pr_create_rc" -ne 0 ] || [ -z "$pr_number" ]; then
    report_failure "could not open (or find) a PR for ${numbers_csv}; branch ${branch} left pushed for manual follow-up" "$logfile" "$pr_create_rc"
    continue
  fi
  echo "  opened PR #$pr_number for ${numbers_csv}" | tee -a "$logfile"

  gh api "repos/${REPO_SLUG}/pulls/${pr_number}/requested_reviewers" \
    -f "reviewers[]=${COPILOT_REVIEWER}" >> "$logfile" 2>&1 \
    || echo "  could not request Copilot review via API; add it once by hand and re-run" | tee -a "$logfile"

  # Iterate-until-convergence, not one fixed round: Copilot's code review NEVER submits an
  # "Approve" state (confirmed empirically -- it only ever leaves a COMMENTED review), so waiting
  # for approval would hang forever. "Converged" here means Copilot has nothing NEW left to say --
  # tracked as a fingerprint of its inline comments, not the review's (permanently COMMENTED) state.
  # Merging past a merely-COMMENTED review relies on the repo's ruleset bypass_actor for this token
  # (scoped to bypass_mode=pull_request only -- direct-push protections on main still apply).
  gate_ok=1
  prev_comment_fingerprint=""
  round_since=""
  for ((review_round = 1; review_round <= REVIEW_MAX_ROUNDS; review_round++)); do
    echo "  waiting for Copilot's review (round ${review_round}/${REVIEW_MAX_ROUNDS})..." | tee -a "$logfile"
    if ! review="$(wait_for_copilot_review "$pr_number" "$logfile" "$round_since")"; then
      echo "  leaving PR #$pr_number open for a human; no Copilot review yet" | tee -a "$logfile"
      gate_ok=0
      break
    fi
    echo "$review" >> "$logfile"
    round_since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    review_comments="$(gh api "repos/${REPO_SLUG}/pulls/${pr_number}/comments" --jq '.[] | "- \(.path):\(.line // .original_line): \(.body)"' 2>>"$logfile")" || review_comments="(could not fetch inline comments; see $logfile)"
    comment_fingerprint="$(echo -n "$review_comments" | shasum -a 256 | cut -d' ' -f1)"

    if [ -z "$review_comments" ] || [ "$comment_fingerprint" = "$prev_comment_fingerprint" ]; then
      echo "  converged: Copilot has nothing new to say (round ${review_round})" | tee -a "$logfile"
      break
    fi
    if [ "$review_round" -eq "$REVIEW_MAX_ROUNDS" ]; then
      echo "  hit the ${REVIEW_MAX_ROUNDS}-round cap with unresolved Copilot comments; proceeding to the gate/merge step anyway (CI green + the bypass actor are the real gate here, not Copilot's approval, which never comes) -- see $logfile for what's still open" | tee -a "$logfile"
      break
    fi
    prev_comment_fingerprint="$comment_fingerprint"

    revise_prompt="Use the gaia orchestrator to address this Copilot code review on PR #${pr_number}
(branch ${branch}, resolving ${numbers_csv}) in ${REPO_DIR}. This is revision round ${review_round}.

Review summary:
${review}

Inline comments:
${review_comments}

Make the changes the review actually calls for -- don't pad the diff. If a comment is
wrong or out of scope, leave a note explaining why instead of blindly complying.
Do not commit -- leave the working tree dirty."

    echo "  running gaia orchestrator's revision pass on PR #${pr_number} round ${review_round} (live below, also logged to $logfile)..." | tee -a "$logfile"
    claude -p "$revise_prompt" \
      --permission-mode acceptEdits \
      --dangerously-skip-permissions \
      2>&1 | tee -a "$logfile" || echo "  revision pass errored; continuing to gate check" | tee -a "$logfile"

    if ! git diff --quiet || ! git diff --cached --quiet; then
      echo "  re-running gate after revision round ${review_round}" | tee -a "$logfile"
      if pixi run test >> "$logfile" 2>&1 && pixi run check-dois >> "$logfile" 2>&1; then
        git add -A
        git commit -m "gaia: address Copilot review round ${review_round} on #${pr_number}

Co-Authored-By: Claude <noreply@anthropic.com>"
        git push
      else
        echo "  revision broke the gate for ${numbers_csv}; leaving PR #$pr_number open for a human" | tee -a "$logfile"
        gate_ok=0
        break
      fi
    else
      echo "  no revision needed/produced this round" | tee -a "$logfile"
      break     # nothing changed and comments weren't empty -- no point looping again on the same diff
    fi
  done
  if [ "$gate_ok" -eq 0 ]; then
    continue
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
    --permission-mode acceptEdits --dangerously-skip-permissions 2>>"$logfile")" \
    && close_message_rc=0 || close_message_rc=$?
  if [ "$close_message_rc" -ne 0 ] || [ -z "$close_message" ]; then
    report_failure "gaia-lab-notebook failed to draft the close message for ${numbers_csv}; using a minimal message" "$logfile" "$close_message_rc"
    close_message="Resolved via PR #${pr_number}. Closing-message drafting failed; see ${logfile}."
  fi

  gh pr merge "$pr_number" --squash --delete-branch --body "$close_message" >> "$logfile" 2>&1 \
    && merge_rc=0 || merge_rc=$?
  if [ "$merge_rc" -ne 0 ]; then
    report_failure "merge of PR #${pr_number} failed for ${numbers_csv} -- PR left open, issues NOT closed" "$logfile" "$merge_rc"
    continue
  fi
  while IFS= read -r number; do
    [ -z "$number" ] && continue
    gh issue comment "$number" --body "$close_message" >> "$logfile" 2>&1 \
      || echo "  could not comment on issue #$number (already merged/closed via 'Closes #N', so this is cosmetic)" | tee -a "$logfile"
  done <<< "$numbers"
  echo "  merged PR #$pr_number, closed ${numbers_csv}" | tee -a "$logfile"

  if [ -n "$milestone" ]; then
    epic_number="$(epic_for_milestone "$milestone")" || epic_number=""
    if [ -n "$epic_number" ]; then
      gh issue comment "$epic_number" --body "Sub-issues ${numbers_csv} resolved via PR #${pr_number} (squash-merged, Copilot-reviewed, checks green). Epic left open for your own review." \
        || echo "  could not comment on epic #$epic_number" | tee -a "$logfile"
    fi
  fi
done < <(python3 "$REPO_DIR/scripts/gaia_group_issues.py")
