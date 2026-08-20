#!/usr/bin/env bash
# Works open GitHub issues, grouped into PR-sized batches by
# scripts/gaia_group_issues.py (milestone, else topic label, else solo;
# P0s split into their own earlier batch; capped at 4 issues/PR), through
# a real PR lifecycle per batch:
#
#   branch -> orchestrator resolves the whole batch together -> local
#   pre-flight gate -> open ONE PR (Closes #a, #b, #c) -> ARBITRATION against
#   competing open gaia PRs -> request Copilot review -> wait ->
#   revise-and-re-review, up to REVIEW_MAX_ROUNDS times -> AUDITOR CONVERGENCE
#   GATE -> wait for GitHub Actions checks green -> squash-merge -> every issue
#   in the batch closes via "Closes #N", plus a scientist-facing close comment
#   written by the gaia-lab-notebook agent on each issue and (if the batch
#   belongs to a milestone) a progress note on that milestone's epic tracker --
#   the epic itself is never closed by this script.
#
# COLLISION ARBITRATION (see arbitrate_collisions). Batches are cut from main in
# parallel, so two batches can land incompatible edits in the same module with
# neither agent ever seeing the other -- exactly what happened on 2026-08-17/18
# with #163 (SparseMaternPrior) vs #154 (StationaryGridPrior). Note those are two
# DIFFERENT issues that collided in one file, not two designs for one problem:
# this stage detects collisions, it does not run a bake-off.
# Before a PR is offered for review, its branch is tested for real merge
# conflicts against every other open gaia PR. On a hit, an INDEPENDENT
# gaia-auditor is given both diffs and both issue statements and asked for an
# objective verdict, which is posted on BOTH PRs. The blocked side is labelled
# needs-human-decision and never auto-merges, but stays READY FOR REVIEW -- a
# draft PR gets no code review, and the human adjudicating a design collision
# needs a review of both sides. See docs/postmortem/2026-08-18-gaia-run.md.
#
# CONVERGENCE. Copilot's code review NEVER submits an "Approve" state -- only
# ever COMMENTED -- so Copilot alone cannot gate a merge. Its comments stopping
# is a necessary but NOT sufficient signal (an unchanged fingerprint can just
# mean the revision pass ignored the feedback). The real gate is a gaia-auditor
# that reads the final diff plus the outstanding review comments and returns a
# structured converged/blocked verdict. A merge requires BOTH: Copilot quiet and
# the auditor satisfied. The merge step still relies on main's ruleset having a
# bypass_actor entry for this token (bypass_mode pull_request, so direct-push
# protections on main still apply to it).
#
# Any failure at any stage leaves the PR/issues OPEN for a human and does NOT
# merge. Failure NEVER deletes a branch, local or remote: work is committed,
# pushed and parked under gaia/parked/* so it is always recoverable (park_branch).
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

# Arbitration + auditor gate. Both default ON: they are what stops two agents
# silently shipping incompatible designs for the same module, and what stops a
# revision pass that ignored its review from merging anyway.
GAIA_ARBITRATION="${GAIA_ARBITRATION:-1}"      # 0 disables rival-PR arbitration
GAIA_AUDIT_GATE="${GAIA_AUDIT_GATE:-1}"        # 0 disables the auditor merge gate
GAIA_MAX_BATCHES="${GAIA_MAX_BATCHES:-0}"      # 0 = drain the queue; N = stop after N batches

# ── Runaway guardrails ────────────────────────────────────────────────────────
# Everything above this block is a DOWNSTREAM gate: it refuses to merge. Downstream
# gates protect `main`; they do nothing about an invocation that spends eight hours
# and $200 rewriting two hundred files before the first gate ever runs. These are the
# UPSTREAM bounds -- what one invocation is allowed to consume and to touch.
GAIA_MAX_TURNS="${GAIA_MAX_TURNS:-80}"            # agent turns per orchestrator invocation
GAIA_AUX_MAX_TURNS="${GAIA_AUX_MAX_TURNS:-30}"    # ... per auditor / lab-notebook invocation
GAIA_ISSUE_TIMEOUT="${GAIA_ISSUE_TIMEOUT:-5400}"  # 90 min wall clock per issue, then TERM
GAIA_AUX_TIMEOUT="${GAIA_AUX_TIMEOUT:-1200}"      # 20 min for the short-lived agents
GAIA_MAX_FILES="${GAIA_MAX_FILES:-40}"            # blast radius: files touched by ONE issue
GAIA_MAX_DIFF_LINES="${GAIA_MAX_DIFF_LINES:-4000}" # blast radius: added+removed lines
GAIA_MAX_COST_USD="${GAIA_MAX_COST_USD:-0}"       # 0 = uncapped; else halt the queue past this
GAIA_RUN_COST=0                                   # accumulated across the whole run
GAIA_PENDING_META=()                              # per-issue meta awaiting the batch outcome
GAIA_PENDING_RAW=()

# The pipeline owns git and gh. Every agent is TOLD not to commit; the 2026-08-17/18
# post-mortem (§3.6) confirms the instruction was present verbatim in all 19 sessions and
# that it did not prevent the incident. Prose is not a guardrail. These deny the tool.
#
# Deliberately subcommand-scoped, not a blanket `Bash` deny: agents legitimately need
# `git diff`, `git log`, `gh issue view` and `gh pr view` to do their jobs. What they must
# never reach is anything that WRITES history, moves a ref, or mutates GitHub. `gh api` is
# denied wholesale because it is the escape hatch around every other entry here.
GAIA_VCS_DENY=(
  "Bash(git commit:*)" "Bash(git push:*)" "Bash(git merge:*)" "Bash(git rebase:*)"
  "Bash(git reset:*)" "Bash(git checkout:*)" "Bash(git switch:*)" "Bash(git branch:*)"
  "Bash(git tag:*)" "Bash(git clean:*)" "Bash(git stash:*)" "Bash(git cherry-pick:*)"
  "Bash(git revert:*)" "Bash(git am:*)" "Bash(git apply:*)" "Bash(git gc:*)"
  "Bash(git prune:*)" "Bash(git reflog:*)" "Bash(git filter-branch:*)"
  "Bash(git worktree:*)" "Bash(git remote:*)" "Bash(git config:*)" "Bash(git restore:*)"
  # fetch/pull update refs too: `pull` moves the local branch (and can merge), and `fetch`
  # rewrites remote-tracking refs and FETCH_HEAD -- which collision arbitration reads to
  # materialise a rival's diff. Denied for the same reason as the rest. (Copilot, PR #218.)
  "Bash(git fetch:*)" "Bash(git pull:*)" "Bash(git update-ref:*)" "Bash(git symbolic-ref:*)"
  "Bash(git submodule:*)" "Bash(git notes:*)" "Bash(git replace:*)"
  "Bash(gh pr merge:*)" "Bash(gh pr create:*)" "Bash(gh pr close:*)" "Bash(gh pr ready:*)"
  "Bash(gh pr edit:*)" "Bash(gh issue close:*)" "Bash(gh issue delete:*)"
  "Bash(gh repo delete:*)" "Bash(gh release:*)" "Bash(gh api:*)" "Bash(gh workflow:*)"
)
# The read-only roles (auditor, lab-notebook-as-drafter) get no editing tools at all. The
# gaia-auditor SUBAGENT already has no Bash in its own grant -- but the queue reaches it
# through a top-level `claude -p` session that has the FULL tool set and merely delegates,
# so without this the sandbox stops at the subagent boundary and never covers the wrapper.
GAIA_READONLY_DENY=( "Edit" "Write" "NotebookEdit" "${GAIA_VCS_DENY[@]}" )

: "${ANTHROPIC_API_KEY:?ANTHROPIC_API_KEY must be set}"

cd "$REPO_DIR"
mkdir -p "$LOG_DIR"
REPO_SLUG="$(gh repo view --json nameWithOwner -q .nameWithOwner)"

# One killable process group. The 2026-08-17/18 incident ran for another hour
# after the operator killed what they believed was the run: they had killed a
# `claude -p` CHILD, and this loop simply started the next issue. Record the
# loop's own PID where a human can find it, and make a TERM/INT stop the LOOP
# rather than just whatever child happens to be running.
GAIA_PIDFILE="$LOG_DIR/gaia_run_queue.pid"
if [ -f "$GAIA_PIDFILE" ] && kill -0 "$(cat "$GAIA_PIDFILE" 2>/dev/null)" 2>/dev/null; then
  echo "!!! another gaia_run_queue.sh is already running (PID $(cat "$GAIA_PIDFILE")). Stop it first:" >&2
  echo "      kill \$(cat $GAIA_PIDFILE)" >&2
  exit 1
fi
echo $$ > "$GAIA_PIDFILE"
GAIA_STOP=0
gaia_request_stop() {
  GAIA_STOP=1
  echo "" >&2
  echo "  !!! stop requested -- finishing the current issue, then halting the queue." >&2
  echo "      (a second TERM kills immediately -- work already COMMITTED is safe on the branch," >&2
  echo "       but anything uncommitted at that instant is left in the working tree, not pushed)" >&2
  trap - TERM INT
}
trap gaia_request_stop TERM INT
trap 'rm -f "$GAIA_PIDFILE"' EXIT
echo "gaia queue PID $$ (stop with: kill $$   or   kill \$(cat $GAIA_PIDFILE))"
# Print the bounds at launch. An operator authorising an unattended multi-hour run should be
# able to see, without reading the script, what a single invocation is allowed to consume.
echo "guardrails: max ${GAIA_MAX_TURNS} turns and ${GAIA_ISSUE_TIMEOUT}s per issue; \
blast radius ${GAIA_MAX_FILES} files / ${GAIA_MAX_DIFF_LINES} lines; \
cost ceiling $([ "$GAIA_MAX_COST_USD" = 0 ] && echo 'NONE (set GAIA_MAX_COST_USD)' || echo "\$${GAIA_MAX_COST_USD}"); \
git+gh denied to every agent"

# Fail at STARTUP on a broken publication path, not eleven hours in. The
# 2026-08-17/18 run pushed nine branches and lost every one of them because
# `gh pr create --json` is not a flag that exists -- the error surfaced only
# AFTER each batch had done its work, and the failure path then deleted the
# branch. Anything that must work for a batch to be publishable is checked here.
preflight() {
  local fatal=0
  if ! gh auth status >/dev/null 2>&1; then
    echo "  !!! preflight: 'gh auth status' failed -- no usable GitHub credential" >&2; fatal=1
  fi
  # `gh pr create` has NO --json flag (never has). If a future refactor
  # reintroduces one, this is the tripwire.
  if gh pr create --help 2>&1 | grep -qE '^\s+--json'; then
    echo "  !!! preflight: this gh's 'pr create' now has --json; open_draft_pr can be simplified" >&2
  fi
  # The number-resolution path open_draft_pr actually depends on.
  if ! gh pr view --help 2>&1 | grep -qE '^\s+--json'; then
    echo "  !!! preflight: 'gh pr view' has no --json -- cannot resolve PR numbers" >&2; fatal=1
  fi
  # Every binary a batch cannot complete without. `claude` and `pixi` were the
  # notable omissions: without them a batch gets as far as branching and
  # committing before dying, which is exactly the expensive-late-failure this
  # function exists to prevent.
  # `timeout` (coreutils) is what bounds every agent invocation's wall clock. Without it the
  # guardrail silently does not exist, which is worse than not having it at all.
  for tool in jq python3 git gh claude pixi timeout awk; do
    command -v "$tool" >/dev/null || { echo "  !!! preflight: '$tool' not on PATH" >&2; fatal=1; }
  done
  # The helper scripts the loop shells out to, per batch.
  for helper in scripts/gaia_group_issues.py scripts/gaia-launch/gaia_ticker.py \
                scripts/gaia-launch/gaia_trace.py; do
    [ -f "$REPO_DIR/$helper" ] || { echo "  !!! preflight: missing $helper" >&2; fatal=1; }
  done
  # The guardrails are only real if this claude build honours the flags they are expressed
  # in. --max-turns is accepted but undocumented in `claude --help`, so probe for the failure
  # mode that matters: a build that REJECTS the flag would abort every invocation, and a
  # build that silently ignores it would leave the turn cap unenforced. Warn, do not block --
  # the wall-clock timeout and the post-hoc vcs assertion still hold either way.
  if ! claude --help 2>&1 | grep -q -- '--disallowed-tools'; then
    echo "  !!! preflight: this claude ($(claude --version 2>/dev/null)) has no --disallowed-tools;" >&2
    echo "      agents will NOT be tool-fenced. assert_no_vcs_mutation is then the only guard." >&2
  fi
  if [ "$fatal" -ne 0 ]; then
    echo "  !!! preflight failed -- refusing to start. Nothing has been changed." >&2
    exit 1
  fi
  echo "  preflight OK (gh $(gh --version | head -1 | awk '{print $3}'), repo ${REPO_SLUG})"
}
preflight

# A stable fingerprint of stdin, for the convergence check below -- NOT a security primitive, so
# any of these is fine; `shasum` is macOS/Perl-native and not guaranteed on a fresh Linux box (the
# actual unattended target per docs/gaia-automation.md), where `sha256sum` (coreutils) is standard.
# `cksum` (POSIX, always present) is the last-resort fallback so this never hard-fails on a minimal image.
fingerprint() {
  if command -v shasum >/dev/null; then
    shasum -a 256 | cut -d' ' -f1
  elif command -v sha256sum >/dev/null; then
    sha256sum | cut -d' ' -f1
  else
    cksum | cut -d' ' -f1
  fi
}

# THE dirty-tree predicate. Returns 0 (true) if the working tree has ANY change the
# pipeline should care about -- tracked modifications, staged changes, OR UNTRACKED FILES.
#
# The untracked half is not a nicety. `git diff --quiet && git diff --cached --quiet` is
# blind to new files, and an agent resolving an issue very often produces exactly that: a
# new module plus a new test. Two call sites used the blind form and read such an issue as
# "no changes produced", skipping its commit -- after which the work was either swept into
# the NEXT issue's `git add -A` under the wrong `Closes #N`, or (if it was the last issue in
# the batch) left dirty in the tree indefinitely. park_branch always had this right; the
# commit paths did not. One predicate now, used everywhere, so they cannot drift again.
tree_dirty() {
  ! git diff --quiet \
    || ! git diff --cached --quiet \
    || [ -n "$(git status --porcelain --untracked-files=normal)" ]
}

# Fail closed on a tree that is dirty when it has no business being dirty. Every caller
# passes a `where` describing the moment, so the console says which invariant broke rather
# than just "dirty". Returns 1 and prints the offending paths; the caller decides whether
# that is fatal (batch start) or merely loud (post-merge).
assert_tree_clean() {
  local where="$1" logfile="${2:-/dev/null}"
  tree_dirty || return 0
  {
    echo "  !!! working tree is DIRTY ${where}; it should be clean here."
    git status --porcelain --untracked-files=normal | sed 's/^/  | /'
  } | tee -a "$logfile"
  return 1
}

# Move unexpected working-tree residue OUT OF THE WAY without destroying it and without
# attributing it to anybody's batch. Used at the two points where the tree must be clean
# but a park would be wrong: before a batch starts (we are on `main` -- parking would
# commit the residue TO main and then rename main) and after a merge (the batch is already
# shipped; there is no batch branch left to park onto). Commits the residue to its own
# throwaway branch and returns to a clean `main`.
quarantine_residue() {
  local label="$1" why="$2" logfile="$3"
  local ref="gaia/residue/${label}-$(date -u +%Y%m%dT%H%M%SZ)" commit_rc=0
  git checkout -b "$ref" >> "$logfile" 2>&1 || {
    echo "  !!! could not create ${ref}; NOT touching the tree. Residue left exactly as found." | tee -a "$logfile"
    return 1
  }
  git add -A >> "$logfile" 2>&1 || true
  # --no-verify is deliberate. Residue is BY DEFINITION unreviewed and may well fail this
  # repo's pre-commit hook (which runs the test suite). A hook rejecting it is not a reason
  # to lose it -- the whole point of this function is to preserve work nobody has vetted.
  git commit --no-verify -m "gaia residue (unreviewed): ${why}

Found in the working tree where it should have been clean. This did NOT pass the gate and
was NOT part of any reviewed PR. Quarantined here so the next batch starts clean; nothing
was deleted.

Co-Authored-By: Claude <noreply@anthropic.com>" >> "$logfile" 2>&1 || commit_rc=$?

  if [ "$commit_rc" -ne 0 ]; then
    # FAIL CLOSED, and above all do NOT `checkout -f`. The earlier version fell through to a
    # forced checkout on commit failure, which would DELETE the very residue it was called to
    # preserve -- a direct contradiction of invariant 1. Stay on the residue branch, leave the
    # tree exactly as it is, and make the caller stop. (Found by Copilot review on PR #218.)
    {
      echo "  !!! could not commit the residue (exit ${commit_rc}). It is UNTOUCHED on branch ${ref}."
      echo "      Nothing was discarded and nothing was force-checked-out."
      echo "      Resolve by hand before running the queue again:  git -C \"$REPO_DIR\" status"
    } | tee -a "$logfile"
    return 1
  fi

  # The commit succeeded, so the tree is clean and this checkout cannot destroy anything.
  git checkout main >> "$logfile" 2>&1 || {
    echo "  !!! quarantined on ${ref} but could not return to main; stopping here rather than forcing." | tee -a "$logfile"
    return 1
  }
  echo "  residue quarantined on ${ref} (nothing deleted); inspect: git log -1 --stat ${ref}" | tee -a "$logfile"
  return 0
}

# The guardrail that does not depend on the CLI honouring anything. Deny rules are the
# first line, but they are enforced by `claude`, and the whole point of a runaway guard is
# that it must hold when the thing it is guarding misbehaves. So: snapshot version control
# before every agent invocation, and PROVE afterwards that the agent did not move it.
vcs_state() {
  # HEAD and the branch name are not enough. They miss a created or deleted branch, and they
  # miss anything that moves a remote-tracking ref (a stray `git fetch`), which collision
  # arbitration later reads. Fingerprint the WHOLE local ref namespace as well, so the check
  # is about "did any ref move", not just "did this one". (Copilot review, PR #218.)
  printf '%s@%s@%s' \
    "$(git rev-parse HEAD 2>/dev/null || echo none)" \
    "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo none)" \
    "$(git show-ref 2>/dev/null | fingerprint)"
}

# Returns 1 if the agent committed, checked out, or otherwise moved a ref. The caller
# treats that as a batch failure -- not because the work is necessarily bad, but because
# the pipeline's accounting of what is on which branch is now wrong, and every downstream
# guarantee (the Closes #N trailer, the gate, the dashboard-with-its-code) rests on it.
assert_no_vcs_mutation() {
  local before="$1" who="$2" logfile="$3" after
  after="$(vcs_state)"
  [ "$before" = "$after" ] && return 0
  {
    echo "  !!! ${who} MUTATED version control despite being instructed not to."
    echo "  |   before: ${before}"
    echo "  |   after:  ${after}"
    echo "  |   The pipeline owns git. Treating this as a batch failure."
  } | tee -a "$logfile"
  return 1
}

# Accumulate spend by SUMMING every `result` record (a transcript can hold more than one
# session, and the budget cares about total spend) and halt the whole queue past the
# ceiling. Checked between issues, not mid-issue: a partially-run issue is worse than a
# slightly-overspent one, and the point is to bound the RUN, not to kill work in flight.
accumulate_cost() {
  local raw="$1" logfile="$2" this
  [ -f "$raw" ] || return 0
  this="$(jq -rs '[.[] | select(.type=="result") | .total_cost_usd // 0] | add // 0' "$raw" 2>/dev/null)" || this=0
  GAIA_RUN_COST="$(awk -v a="$GAIA_RUN_COST" -v b="${this:-0}" 'BEGIN{printf "%.4f", a+b}')"
  echo "  spend: this issue \$${this:-0}, run total \$${GAIA_RUN_COST}" | tee -a "$logfile"
}

cost_ceiling_hit() {
  [ "$GAIA_MAX_COST_USD" = "0" ] && return 1
  awk -v c="$GAIA_RUN_COST" -v m="$GAIA_MAX_COST_USD" 'BEGIN{exit !(c>=m)}'
}

# ── Measure, not just ship ───────────────────────────────────────────────────
# `gaia-run.sh` deliberately leaves the tree dirty and writes down what the agent did and
# whether the tests passed; `gaia_run_queue.sh` commits, reviews, gates and merges. The
# split left the DELIVERY path unmeasured: the queue rendered a dashboard a human could
# read and threw away every number on it. So there was no way to ask whether the pipeline
# was getting better or worse, only whether any single run felt bad.
#
# gaia_trace.py already derives cost, turns, tool histograms, error counts and the subagent
# roster from the transcript. All the queue has to add is the outcome labels it alone knows
# -- the gate result, the PR, the blast radius -- and point the same call at the same corpus
# the harness writes to. One schema, one file, both harnesses.
write_measurement() {
  local number="$1" title="$2" raw="$3" dash_rel="$4" branch="$5" pr_number="$6" \
        outcome="$7" wall_s="$8" logfile="$9"
  local dir meta files lines
  dir="$(dirname "$raw")"
  meta="${dir}/issue-${number}-${ts}.meta.json"
  files="$(git diff --cached --name-only | wc -l | tr -d ' ')"
  lines="$(git diff --cached --numstat | awk '{a+=$1+$2} END{print a+0}')"
  [[ "$files"  =~ ^[0-9]+$ ]] || files=0
  [[ "$lines"  =~ ^[0-9]+$ ]] || lines=0
  [[ "$wall_s" =~ ^[0-9]+$ ]] || wall_s=0
  jq -n \
    --arg run_id "issue-${number}-${ts}" --arg repo "$REPO_SLUG" --arg issue "$number" \
    --arg issue_title "$title" --arg git_rev "$(git rev-parse HEAD 2>/dev/null)" \
    --arg test_cmd "pixi run test && pixi run check-dois" --arg outcome "$outcome" \
    --arg dir "$dir" --arg claude_version "$(claude --version 2>/dev/null | head -1)" \
    --argjson wall_s "${wall_s:-0}" --argjson diff_lines "${lines:-0}" \
    --argjson files_touched "${files:-0}" \
    --arg harness "gaia_run_queue.sh" --arg branch "$branch" --arg pr "${pr_number:-}" \
    --arg dashboard "$dash_rel" \
    --argjson max_turns "$GAIA_MAX_TURNS" --argjson issue_timeout_s "$GAIA_ISSUE_TIMEOUT" \
    '$ARGS.named | . + {delivery: {harness: .harness, branch: .branch, pr: .pr,
        dashboard: .dashboard, max_turns: .max_turns, issue_timeout_s: .issue_timeout_s}}' \
    > "$meta" 2>>"$logfile" || return 0
  # Deliberately NOT written to the corpus yet. `outcome` is the reward signal, and at
  # commit time the batch gate has not run -- the honest value is not known. Queue the
  # meta and its transcript; flush_measurements fills in the real outcome afterwards.
  GAIA_PENDING_META+=("$meta")
  GAIA_PENDING_RAW+=("$raw")
}

# Stamp the batch's actual outcome onto every queued issue record and append them to the
# corpus. Called on EVERY exit path a batch can take -- gate pass, gate fail, park -- so a
# failed batch is measured too. A corpus that only contains successes teaches nothing.
flush_measurements() {
  local outcome="$1" logfile="$2" i meta
  for i in "${!GAIA_PENDING_META[@]}"; do
    meta="${GAIA_PENDING_META[$i]}"
    [ -f "$meta" ] || continue
    jq --arg o "$outcome" '.outcome = $o' "$meta" > "${meta}.tmp" 2>>"$logfile" \
      && mv "${meta}.tmp" "$meta" || rm -f "${meta}.tmp"
    python3 "$REPO_DIR/scripts/gaia-launch/gaia_trace.py" "${GAIA_PENDING_RAW[$i]}" \
      --records "$LOG_DIR/records.jsonl" --meta "$meta" >> "$logfile" 2>&1 \
      || echo "  could not append a corpus record from ${meta}" | tee -a "$logfile"
  done
  [ "${#GAIA_PENDING_META[@]}" -gt 0 ] && \
    echo "  measured: ${#GAIA_PENDING_META[@]} issue record(s) -> ${LOG_DIR}/records.jsonl (outcome=${outcome})" | tee -a "$logfile"
  GAIA_PENDING_META=(); GAIA_PENDING_RAW=()
  return 0
}

# ── Provenance ledger ────────────────────────────────────────────────────────
# The Provenance Keeper agent is bypassed in this pipeline (the shell owns git, because it
# must guarantee the Closes #N trailer and convert a failed commit into a controlled park
# rather than a `set -e` death). Bypassing the AGENT is fine; dropping the RECORD is not --
# and until now there was no provenance artifact in this repo at all.
#
# So the queue writes the ledger and the Keeper owns and audits the schema. Committed, not
# gitignored: provenance that lives only in .gaia-runs/ dies with the box it ran on.
#
# NOTE the entry carries `parent_rev`, not its own commit sha -- it has to be written BEFORE
# the commit in order to land inside it. parent_rev plus the commit that contains this line
# fully identifies the change; git supplies the resulting sha.
append_provenance() {
  local number="$1" title="$2" branch="$3" pr_number="$4" dash_rel="$5" raw="$6" logfile="$7"
  local ledger="$REPO_DIR/docs/provenance/ledger.jsonl" cost turns
  mkdir -p "$(dirname "$ledger")"
  # SUMMED over every `result` record in the transcript, because one .raw.jsonl can hold
  # more than one session (a retry, or a resumed run) and the operator's actual spend is
  # the sum. Note this can legitimately EXCEED the `cost_usd` that gaia_trace.py puts in
  # records.jsonl, which is session-scoped (it keeps the LAST result record it sees).
  # Different questions: the ledger answers "what did this cost", the corpus field answers
  # "what did this session cost". Hence the distinct names.
  #
  # `--argjson` is FATAL on empty or non-numeric input -- it would take the whole ledger
  # entry down over a truncated transcript, which is exactly when provenance matters most.
  # Normalise to a number here so jq only ever sees one.
  cost="$(jq -rs '[.[] | select(.type=="result") | .total_cost_usd // 0] | add // 0' "$raw" 2>/dev/null)"
  turns="$(jq -rs '[.[] | select(.type=="result") | .num_turns // 0] | add // 0' "$raw" 2>/dev/null)"
  [[ "$cost"  =~ ^[0-9]+([.][0-9]+)?([eE][-+]?[0-9]+)?$ ]] || cost=0
  [[ "$turns" =~ ^[0-9]+$ ]] || turns=0
  jq -nc \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg issue "$number" --arg issue_title "$title" \
    --arg branch "$branch" --arg pr "${pr_number:-}" \
    --arg parent_rev "$(git rev-parse HEAD 2>/dev/null)" \
    --arg repo "$REPO_SLUG" \
    --arg harness "gaia_run_queue.sh" \
    --arg claude_version "$(claude --version 2>/dev/null | head -1)" \
    --arg env_lock "$( (sha256sum "$REPO_DIR/pixi.lock" 2>/dev/null || echo none) | cut -d" " -f1)" \
    --arg dashboard "$dash_rel" \
    --arg transcript "$(basename "$raw")" \
    --argjson cost_usd_total "${cost:-0}" --argjson turns_total "${turns:-0}" \
    --arg gate "pixi run test && pixi run check-dois && quarto render docs/twin" \
    --arg ai_assistance "Written by the gaia multi-agent system (Claude). Not human-authored. Reviewed by an automated code review and an independent auditor gate before merge; see the dashboard for the full trajectory." \
    '$ARGS.named' >> "$ledger" 2>>"$logfile" \
    || { echo "  could not append to the provenance ledger for #${number}" | tee -a "$logfile"; return 0; }
  echo "  provenance: appended ledger entry for #${number} (parent $(git rev-parse --short HEAD 2>/dev/null), \$${cost:-0}, ${turns:-0} turns)" | tee -a "$logfile"
}

# Blast radius. A minimal correct change for one issue does not touch 200 files. When it
# does, the most likely explanations are a runaway refactor, a stray build artifact, or
# residue from something else -- none of which should be committed under this issue's
# `Closes #N`. Expects the change to be STAGED already, so untracked files are counted.
blast_radius_ok() {
  local number="$1" logfile="$2" files lines
  files="$(git diff --cached --name-only | wc -l | tr -d ' ')"
  lines="$(git diff --cached --numstat | awk '{a+=$1+$2} END{print a+0}')"
  echo "  blast radius for #${number}: ${files} files, ${lines} changed lines" | tee -a "$logfile"
  if [ "$files" -gt "$GAIA_MAX_FILES" ] || [ "$lines" -gt "$GAIA_MAX_DIFF_LINES" ]; then
    {
      echo "  !!! #${number} exceeds the blast-radius cap (max ${GAIA_MAX_FILES} files / ${GAIA_MAX_DIFF_LINES} lines)."
      echo "  |   Raise GAIA_MAX_FILES / GAIA_MAX_DIFF_LINES if this is genuinely a large change."
      git diff --cached --stat | tail -20 | sed 's/^/  | /'
    } | tee -a "$logfile"
    return 1
  fi
  return 0
}

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

# Park, never destroy. The predecessor of this function ran `git reset --hard`,
# `git clean -fd`, `git branch -D` AND `git push origin --delete` on ANY non-zero
# exit -- including a typo in a gh flag. On 2026-08-17/18 that destroyed 730
# uncommitted lines of issue #176 work outright (never staged, so not even
# recoverable from the object database) and deleted nine successfully-pushed
# branches from the remote. Nothing here deletes anything: in-flight work is
# COMMITTED, PUSHED, and the local branch renamed out of the way so the next
# batch's `checkout -B` cannot clobber it.
park_branch() {
  local branch="$1" logfile="$2" reason="${3:-batch failed}"
  local parked="gaia/parked/${branch#gaia/}-$(date -u +%Y%m%dT%H%M%SZ)"
  {
    echo "  parking branch ${branch} (${reason}):"
    git diff --stat 2>&1
    # Preserve any uncommitted work as a real commit rather than discarding it.
    # `git add -A` picks up untracked files too. .gaia-runs/ (logs, transcripts)
    # is gitignored in full; the published dashboards live under docs/gaia-runs/
    # and are NOT ignored, so they are picked up here as intended. Formerly
    # the rendered dashboards, so the run logs are unaffected either way.
    if tree_dirty; then
      git add -A 2>&1 || true
      git commit -m "gaia WIP (parked, unreviewed): ${reason}

Uncommitted work preserved automatically when the batch was parked.
This commit has NOT passed the gate and has NOT been reviewed.

Co-Authored-By: Claude <noreply@anthropic.com>" 2>&1 || true
    fi
    # Publish before parking so the work survives loss of this machine.
    git push -u origin "$branch" 2>&1 || echo "  (could not push ${branch}; it remains locally at $(git rev-parse --short HEAD 2>/dev/null))"
    git checkout main 2>&1 || git checkout -f main 2>&1 || true
    git branch -m "$branch" "$parked" 2>&1 || true
    echo "  parked as local branch ${parked}; remote branch ${branch} left in place."
    echo "  recover with:  git checkout ${parked}    (or: git fetch origin ${branch})"
  } >> "$logfile" 2>&1
  echo "  parked ${branch} -> ${parked} (nothing deleted; see $logfile)" | tee -a "$logfile"
}

# `gh pr create` prints the PR URL on stdout and has NO --json flag. Resolving
# the number through `gh pr view` afterwards is the whole fix for the bug that
# stranded the 2026-08-17/18 run.
pr_number_for_branch() {
  gh pr view "$1" --json number -q .number 2>/dev/null
}

open_draft_pr() {
  local branch="$1" title="$2" body="$3" logfile="$4" n=""
  gh pr create --draft --base main --head "$branch" \
    --title "$title" --body "$body" >> "$logfile" 2>&1 || true
  # Read the number back rather than parsing create's output: this also
  # transparently adopts a PR that already exists for this head.
  n="$(pr_number_for_branch "$branch")" || n=""
  [ -n "$n" ] && [ "$n" != "null" ] || return 1
  printf '%s' "$n"
}

# Files this branch changes relative to its merge-base with main.
changed_files_for_ref() {
  local ref="$1" base
  base="$(git merge-base main "$ref" 2>/dev/null)" || return 1
  git diff --name-only "$base" "$ref" 2>/dev/null
}

# Other open gaia PRs whose branches would genuinely CONFLICT with this one --
# not merely touch a shared file. Overlap is the cheap prefilter; merge-tree is
# the real test. Note --write-tree DOES write a tree object to the object
# database (it is how merge-tree reports the merged result); what it does not
# do is move any ref, touch the index, or alter the working tree. The stray
# trees are unreachable and get collected by a normal gc.
find_conflicting_prs() {
  local branch="$1" logfile="$2" mine rivals rival_branch rival_num base overlap
  mine="$(changed_files_for_ref "$branch")" || return 0
  [ -n "$mine" ] || return 0
  rivals="$(gh pr list --state open --json number,headRefName \
    --jq '.[] | select(.headRefName | startswith("gaia/")) | "\(.number)\t\(.headRefName)"' 2>>"$logfile")" || return 0
  while IFS=$'\t' read -r rival_num rival_branch; do
    [ -z "${rival_branch:-}" ] && continue
    [ "$rival_branch" = "$branch" ] && continue
    git fetch -q origin "$rival_branch" 2>>"$logfile" || continue
    overlap="$(comm -12 <(printf '%s\n' "$mine" | sort -u) \
                        <(changed_files_for_ref FETCH_HEAD 2>/dev/null | sort -u) 2>/dev/null)" || continue
    [ -n "$overlap" ] || continue
    base="$(git merge-base "$branch" FETCH_HEAD 2>/dev/null)" || continue
    if ! git merge-tree --write-tree --merge-base="$base" "$branch" FETCH_HEAD >/dev/null 2>&1; then
      printf '%s\t%s\t%s\n' "$rival_num" "$rival_branch" "$(printf '%s' "$overlap" | tr '\n' ',' | sed 's/,$//')"
    fi
  done <<< "$rivals"
}

# COLLISION arbitration. Read the name literally: this is a detector for branches that
# textually collide, NOT a bake-off between two designs commissioned for the same problem.
#
# The pair it judges is whatever two batches happened to touch the same files. They are
# almost always resolving DIFFERENT issues -- e.g. #215 (sparse GMRF/SPDE Matern, issue
# #163) and #216 (stationary-grid covariance, issue #154), which collided in
# observability.py while answering two different questions. "Which is better, A or B?" is
# not even well posed for such a pair, which is why `reconcile` is a first-class verdict
# and why the prompt below explicitly invites it.
#
# A genuine A/B would require the SAME issue set resolved twice on two branches by two
# independent orchestrator runs, and then arbitrated. That is a different mechanism and
# this is not it. Do not read a verdict here as "the project chose design A".
#
# What it IS good for: making a silent, incompatible double-merge impossible.
#
# The auditor is deliberately given both diffs and both issue statements but is NOT told
# which branch is "ours" -- the point is an objective verdict, not a rubber stamp for
# whichever batch happened to run second.
arbitrate_collision() {
  local branch="$1" pr_number="$2" rival_branch="$3" rival_num="$4" files="$5" logfile="$6"
  local out verdict dir
  # The gaia-auditor is READ-ONLY BY DESIGN -- its tool grant is
  # Read/Grep/Glob/WebSearch/WebFetch/Skill, with no Bash. Telling it to run
  # `git diff` would simply fail. So the caller (which does have git)
  # materialises everything it needs to judge, and hands it file paths to Read.
  dir="$(mktemp -d)"
  git diff "$(git merge-base main "$branch")...$branch" > "$dir/proposal-A.diff" 2>>"$logfile" || true
  git fetch -q origin "$rival_branch" 2>>"$logfile" || true
  git diff "$(git merge-base main FETCH_HEAD)...FETCH_HEAD" > "$dir/proposal-B.diff" 2>>"$logfile" || true
  gh pr view "$pr_number" --json title,body,number > "$dir/proposal-A-pr.json" 2>>"$logfile" || true
  gh pr view "$rival_num"  --json title,body,number > "$dir/proposal-B-pr.json" 2>>"$logfile" || true
  out="$(timeout --signal=TERM --kill-after=60 "$GAIA_AUX_TIMEOUT" claude -p "Use the gaia-auditor agent as an impartial ARBITRATOR between two competing
pull requests in ${REPO_DIR} (${REPO_SLUG}). They modify the same files and cannot both be merged
as written. You are not an author of either. Judge them on the merits.

Proposal A: PR #${pr_number}, branch ${branch}
Proposal B: PR #${rival_num}, branch ${rival_branch}
Files in conflict: ${files}

Everything you need has been materialised for you -- Read these files, do not guess and do not
try to run git or gh (you have no shell):
  ${dir}/proposal-A.diff      full diff of A against its merge-base with main
  ${dir}/proposal-B.diff      full diff of B against its merge-base with main
  ${dir}/proposal-A-pr.json   A's PR title and body (states the issue it closes)
  ${dir}/proposal-B-pr.json   B's PR title and body
You may also Read/Grep the current checkout for surrounding context.

Assess: correctness; scientific and numerical soundness; scalability; test coverage; API and
maintenance cost; and whether one subsumes the other. If they are solving genuinely different
problems that merely collide textually, say so -- that verdict is 'reconcile'.

Finish your reply with EXACTLY one fenced json block and nothing after it:
\`\`\`json
{\"verdict\": \"A\" | \"B\" | \"reconcile\" | \"escalate\",
 \"confidence\": \"high\" | \"medium\" | \"low\",
 \"rationale\": \"<=6 sentences, concrete, citing the code\",
 \"reconciliation\": \"if verdict is reconcile: how to combine them; else empty\"}
\`\`\`" --permission-mode acceptEdits --dangerously-skip-permissions \
    --max-turns "$GAIA_AUX_MAX_TURNS" \
    --disallowed-tools "${GAIA_READONLY_DENY[@]}" 2>>"$logfile")" || out=""
  # Take the LAST json block: the auditor's prose may quote earlier examples.
  verdict="$(printf '%s' "$out" | awk '/^```json/{f=1;buf="";next} /^```/{if(f){last=buf;f=0}next} f{buf=buf$0"\n"} END{printf "%s", last}')"
  rm -rf "$dir"
  if [ -z "$verdict" ] || ! jq -e . >/dev/null 2>&1 <<<"$verdict"; then
    printf '%s' "$out" >> "$logfile"
    printf '{"verdict":"escalate","confidence":"low","rationale":"The arbitrator produced no parseable verdict; escalating to a human.","reconciliation":""}'
    return 0
  fi
  printf '%s' "$verdict"
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

# `gh pr edit --add-label` goes through GraphQL and needs the read:org scope,
# which a plain repo+workflow token does not have -- it fails with a scope error
# that has nothing to do with labels. The REST issues/labels endpoint needs only
# `repo`, so use that and keep the automation working on a least-privilege token.
add_label() {
  local number="$1" label="$2" logfile="$3"
  gh api "repos/${REPO_SLUG}/issues/${number}/labels" -f "labels[]=${label}" >> "$logfile" 2>&1 \
    || echo "  could not label #${number} with ${label}; add it by hand" | tee -a "$logfile"
}

# Returns 0 if this PR may proceed to review/merge, 1 if arbitration ruled
# against it (or could not decide). Either way BOTH PRs get the verdict posted,
# so the losing side is never silently dropped.
arbitrate_collisions() {
  local branch="$1" pr_number="$2" logfile="$3"
  local conflicts rival_num rival_branch files verdict v conf rationale recon proceed=0
  [ "$GAIA_ARBITRATION" = "1" ] || return 0
  conflicts="$(find_conflicting_prs "$branch" "$logfile")" || conflicts=""
  [ -n "$conflicts" ] || { echo "  no competing open gaia PR conflicts with ${branch}" | tee -a "$logfile"; return 0; }

  while IFS=$'\t' read -r rival_num rival_branch files; do
    [ -z "${rival_num:-}" ] && continue
    echo "  !!! PR #${pr_number} conflicts with open PR #${rival_num} on: ${files}" | tee -a "$logfile"
    echo "  calling an independent gaia-auditor to arbitrate (logged to $logfile)..." | tee -a "$logfile"
    verdict="$(arbitrate_collision "$branch" "$pr_number" "$rival_branch" "$rival_num" "$files" "$logfile")"
    v="$(jq -r '.verdict // "escalate"' <<<"$verdict")"
    conf="$(jq -r '.confidence // "low"' <<<"$verdict")"
    rationale="$(jq -r '.rationale // ""' <<<"$verdict")"
    recon="$(jq -r '.reconciliation // ""' <<<"$verdict")"
    echo "  arbitration verdict: ${v} (confidence ${conf})" | tee -a "$logfile"

    local note="## Automated collision arbitration

PR #${pr_number} (\`${branch}\`) and PR #${rival_num} (\`${rival_branch}\`) modify the same files and **cannot both merge as written**.

> **What this is.** A *collision* detector: these two branches were cut from \`main\` independently and
> happened to touch the same files. They are most likely resolving **different** issues. This is **not**
> an A/B bake-off between two designs commissioned for the same problem, and a verdict of \"A\" does not
> mean the project has chosen design A -- it means A is the one that should land first. If the two are
> solving different problems that merely collide textually, the correct verdict is \`reconcile\`.

**Files in conflict:** \`${files}\`

An independent \`gaia-auditor\` — not an author of either change — reviewed both diffs and both issue statements.

**Verdict: ${v}** (confidence: ${conf})

${rationale}"
    [ -n "$recon" ] && note="${note}

**Suggested reconciliation:** ${recon}"
    note="${note}

This verdict is advisory and was produced by an autonomous agent. **A human decides.** Neither PR will be auto-merged while this conflict stands. See \`docs/postmortem/2026-08-18-gaia-run.md\`."

    gh pr comment "$pr_number" --body "$note" >> "$logfile" 2>&1 || true
    gh pr comment "$rival_num" --body "$note" >> "$logfile" 2>&1 || true

    # Block by LABEL, not by demoting to draft. A draft PR does not get a
    # Copilot review, so demoting the loser would silently deny it the very
    # review a human needs in order to adjudicate. Returning non-zero already
    # stops the merge; the label makes the block visible and filterable.
    gh label create needs-human-decision --color B60205 \
      --description "Automated arbitration found a competing PR; a human must choose" >/dev/null 2>&1 || true
    case "$v" in
      A) echo "  arbitrator favours THIS PR (#${pr_number}); #${rival_num} needs rework by a human" | tee -a "$logfile"
         add_label "$rival_num" needs-human-decision "$logfile" ;;
      B) echo "  arbitrator favours the rival (#${rival_num}); #${pr_number} blocked pending your decision" | tee -a "$logfile"
         add_label "$pr_number" needs-human-decision "$logfile"
         proceed=1 ;;
      *) echo "  arbitrator returned '${v}' -- both PRs left open for a human; not merging" | tee -a "$logfile"
         add_label "$pr_number" needs-human-decision "$logfile"
         add_label "$rival_num" needs-human-decision "$logfile"
         proceed=1 ;;
    esac
  done <<< "$conflicts"
  return "$proceed"
}

# The real merge gate. Copilot never approves, and an unchanged comment
# fingerprint can equally mean "the revision pass ignored the review" -- so a
# separate auditor reads the FINAL diff against the outstanding comments and
# says whether the PR is actually done. Returns 0 = converged, 1 = blocked.
audit_pr_convergence() {
  local pr_number="$1" branch="$2" numbers_csv="$3" review_comments="$4" logfile="$5"
  local out verdict conv blocking rationale dir
  [ "$GAIA_AUDIT_GATE" = "1" ] || return 0
  echo "  auditor convergence gate on PR #${pr_number}..." | tee -a "$logfile"
  # Same constraint as arbitrate_collision: the auditor has no Bash, so the diff and
  # the review comments are written out for it to Read rather than fetch.
  dir="$(mktemp -d)"
  git diff "$(git merge-base main "$branch")...$branch" > "$dir/final.diff" 2>>"$logfile" || true
  printf '%s\n' "${review_comments:-(no inline review comments were left)}" > "$dir/review-comments.txt"
  out="$(timeout --signal=TERM --kill-after=60 "$GAIA_AUX_TIMEOUT" claude -p "Use the gaia-auditor agent to decide whether PR #${pr_number} (branch ${branch},
resolving ${numbers_csv}) in ${REPO_DIR} is genuinely ready to merge. You are an independent
reviewer, not the author. Be objective and be willing to block.

Everything you need has been materialised -- Read these, do not guess and do not try to run git
or gh (you have no shell):
  ${dir}/final.diff             the complete final diff against main
  ${dir}/review-comments.txt    the code-review comments left on the PR
You may also Read/Grep the current checkout for surrounding context.

Some review comments may already be addressed, some may have been ignored, and some may be wrong.

Decide, on the evidence in the diff:
  1. Is each substantive review comment either ADDRESSED in the code or explicitly and correctly
     rebutted? A comment that was silently ignored is NOT addressed.
  2. Does the change actually resolve the issues it claims to close?
  3. Is it correct, tested, and free of obvious scientific or numerical errors?
  4. Are there NEW problems the change introduces that review did not catch?

Do not accept a change merely because review went quiet. Block if anything material is unresolved.

Finish your reply with EXACTLY one fenced json block and nothing after it:
\`\`\`json
{\"converged\": true | false,
 \"blocking\": [\"one line per unresolved problem; empty array if none\"],
 \"rationale\": \"<=6 sentences citing the code\"}
\`\`\`" --permission-mode acceptEdits --dangerously-skip-permissions \
    --max-turns "$GAIA_AUX_MAX_TURNS" \
    --disallowed-tools "${GAIA_READONLY_DENY[@]}" 2>>"$logfile")" || out=""
  verdict="$(printf '%s' "$out" | awk '/^```json/{f=1;buf="";next} /^```/{if(f){last=buf;f=0}next} f{buf=buf$0"\n"} END{printf "%s", last}')"
  rm -rf "$dir"
  if [ -z "$verdict" ] || ! jq -e . >/dev/null 2>&1 <<<"$verdict"; then
    printf '%s' "$out" >> "$logfile"
    echo "  auditor produced no parseable verdict; treating as BLOCKED (fail closed)" | tee -a "$logfile"
    gh pr comment "$pr_number" --body "## Automated auditor gate

The auditor did not return a parseable verdict, so this PR is **blocked** rather than merged (fail closed). A human should review it. See \`docs/postmortem/2026-08-18-gaia-run.md\`." >> "$logfile" 2>&1 || true
    return 1
  fi
  conv="$(jq -r '.converged // false' <<<"$verdict")"
  blocking="$(jq -r '(.blocking // []) | map("- " + .) | join("\n")' <<<"$verdict")"
  rationale="$(jq -r '.rationale // ""' <<<"$verdict")"
  if [ "$conv" = "true" ]; then
    echo "  auditor: CONVERGED" | tee -a "$logfile"
    gh pr comment "$pr_number" --body "## Automated auditor gate — converged

An independent \`gaia-auditor\` reviewed the final diff against the outstanding review comments and found nothing material unresolved.

${rationale}

Produced by an autonomous agent; this is a gate, not a substitute for human review." >> "$logfile" 2>&1 || true
    return 0
  fi
  echo "  auditor: BLOCKED -- leaving PR #${pr_number} open for a human" | tee -a "$logfile"
  gh pr comment "$pr_number" --body "## Automated auditor gate — blocked

An independent \`gaia-auditor\` reviewed the final diff against the outstanding review comments and found unresolved problems. **This PR was not merged.**

${blocking:-- (no specific items returned)}

${rationale}

Produced by an autonomous agent. A human should resolve these before merging." >> "$logfile" 2>&1 || true
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

batch_count=0
while IFS= read -r batch_json; do
  [ -z "$batch_json" ] && continue
  if [ "$GAIA_STOP" -ne 0 ]; then
    echo "=== stop requested; halting the queue before the next batch ==="
    break
  fi
  if [ "$GAIA_MAX_BATCHES" -gt 0 ] && [ "$batch_count" -ge "$GAIA_MAX_BATCHES" ]; then
    echo "=== GAIA_MAX_BATCHES=${GAIA_MAX_BATCHES} reached; stopping (remaining batches untouched) ==="
    break
  fi
  batch_count=$((batch_count + 1))

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

  # A batch must START from a clean tree. Anything dirty here is residue from a previous
  # batch (or a human's half-finished edit), and `git add -A` below would sweep it into
  # this batch's first commit, attributing someone else's work to this issue and shipping
  # it unreviewed. Fail closed: park whatever is here under its own branch, then skip.
  # NOTE: we are on `main` here, so this must NOT call park_branch -- that would commit the
  # residue onto main and then rename main out from under the queue.
  if ! assert_tree_clean "before starting ${numbers_csv}" "$logfile"; then
    # A failed quarantine means unpreserved work is sitting in the tree. HALT THE WHOLE
    # QUEUE rather than `continue`: the next batch's first act is `git checkout main`, which
    # against a dirty tree either fails (killing the script mid-flight under `set -e`) or,
    # worse, gets forced somewhere and destroys the work. Nothing automated should touch a
    # tree we could not preserve.
    if ! quarantine_residue "prebatch-$(jq -r '.issues[0].number' <<<"$batch_json")" \
        "tree was already dirty before ${numbers_csv} started" "$logfile"; then
      report_failure "could not preserve pre-existing residue; HALTING the queue with the tree untouched" "$logfile" 1
      GAIA_STOP=1
      break
    fi
  fi
  if ! assert_tree_clean "after quarantining, before starting ${numbers_csv}" "$logfile"; then
    report_failure "could not get to a clean tree before ${numbers_csv}; skipping this batch rather than committing someone else's work" "$logfile" 1
    continue
  fi

  git checkout -B "$branch" main

  # Resolve the batch ONE ISSUE AT A TIME so each fix lands as its own commit that names the issue
  # it closes, pushed onto a DRAFT PR as it lands; the PR is flipped to ready-for-review only once
  # every issue is committed and the batch gate passes. The PR is merged with `--merge` (below), so
  # these per-issue commits are preserved in main's history. Issue CLOSURE is driven by the
  # "Closes #N" lines in the PR *body* (guaranteed below), not by these commit messages.
  # `cmd && rc=0 || rc=$?` (not a bare `cmd; rc=$?`) is required under `set -e`: a plain failing
  # command exits the whole script before a following `rc=$?` line runs. `tee` (not `>>`) keeps the
  # orchestrator's work visible live; `set -o pipefail` keeps issue_rc as claude's code, not tee's.
  any_committed=0
  batch_failed=0
  pr_number=""
  while IFS= read -r number; do
    [ -z "$number" ] && continue
    if [ "$GAIA_STOP" -ne 0 ]; then
      echo "  stop requested; not starting #${number}. Work so far stays on ${branch}." | tee -a "$logfile"
      break
    fi
    # Budget check BETWEEN issues, never mid-issue: a half-resolved issue is worse than a
    # slightly-overspent run, and the point is to bound the run, not to kill work in flight.
    if cost_ceiling_hit; then
      echo "  cost ceiling reached (\$${GAIA_RUN_COST} >= \$${GAIA_MAX_COST_USD}); not starting #${number}. Work so far stays on ${branch}." | tee -a "$logfile"
      GAIA_STOP=1
      break
    fi
    title="$(jq -r --arg n "$number" '.issues[] | select((.number|tostring)==$n) | .title' <<<"$batch_json")"
    echo "  resolving #${number} (${title}) [live below, also logged to $logfile]..." | tee -a "$logfile"
    # stream-json (piped through gaia_ticker.py) instead of plain text: gives a live, per-agent
    # ticker in $logfile (same as before, just attributed by name instead of one undifferentiated
    # stream) AND a raw transcript this loop can render into a dashboard below. Claude's own stderr
    # goes straight to $logfile, same as it always did; only its stdout changes shape.
    raw="$LOG_DIR/issue-${number}-${ts}.raw.jsonl"
    issue_start_epoch="$(date +%s)"
    vcs_before="$(vcs_state)"
    # --max-turns and the timeout are the two bounds that hold when nothing else does: an
    # agent that has lost the plot burns turns, and one that has deadlocked burns only wall
    # clock. Neither was bounded before -- gaia-run.sh capped turns, the queue did not, so
    # the DELIVERY path was the unbounded one. --kill-after gives claude a TERM to flush its
    # transcript (which is the recovery material) before SIGKILL.
    timeout --signal=TERM --kill-after=60 "$GAIA_ISSUE_TIMEOUT" \
      claude -p "Use the gaia orchestrator to resolve GitHub issue #${number} (\"${title}\") in ${REPO_SLUG}.
Follow /gaia:ground-rules. Make the minimal correct change (code, tests, and/or docs) for THIS issue only.
Do not commit -- leave the working tree dirty for the pipeline to commit.
The pipeline owns git and gh; committing, pushing, branching and merging are denied to you
at the tool level, and the queue verifies afterwards that no ref moved." \
        --permission-mode acceptEdits \
        --dangerously-skip-permissions \
        --max-turns "$GAIA_MAX_TURNS" \
        --disallowed-tools "${GAIA_VCS_DENY[@]}" \
        --output-format stream-json \
        --verbose \
        2>>"$logfile" \
      | python3 "$REPO_DIR/scripts/gaia-launch/gaia_ticker.py" 2>>"$logfile" \
      | tee "$raw" >/dev/null \
      && issue_rc=0 || issue_rc=$?
    accumulate_cost "$raw" "$logfile"
    if [ "$issue_rc" -eq 124 ]; then
      report_failure "orchestrator on #${number} hit the ${GAIA_ISSUE_TIMEOUT}s wall-clock cap and was terminated; parking the batch ${numbers_csv}" "$logfile" "$issue_rc"
      batch_failed=1
      break
    fi
    if [ "$issue_rc" -ne 0 ]; then
      report_failure "orchestrator failed on #${number}; discarding the whole batch ${numbers_csv}" "$logfile" "$issue_rc"
      batch_failed=1
      break
    fi
    if ! assert_no_vcs_mutation "$vcs_before" "the orchestrator on #${number}" "$logfile"; then
      batch_failed=1
      break
    fi
    if ! tree_dirty; then
      echo "  no changes produced for #${number}; skipping its commit (see $logfile)" | tee -a "$logfile"
      continue
    fi

    # Render this issue's dashboard from the transcript just captured, so it lands in the SAME
    # commit as the code it documents. Only reached once we know a real diff exists (above), so a
    # no-op issue never leaves an orphaned dashboard for `git add -A` to misattribute to whichever
    # issue commits next. A render failure must never block the actual fix from being committed.
    dash_rel="docs/gaia-runs/issue-${number}/${ts}/dashboard.html"
    mkdir -p "$(dirname "$dash_rel")"
    python3 "$REPO_DIR/scripts/gaia-launch/gaia_trace.py" "$raw" --html "$dash_rel" \
      >> "$logfile" 2>&1 \
      || echo "  could not build dashboard.html for #${number}; committing the code change without it" | tee -a "$logfile"

    # Written BEFORE staging so the ledger entry is committed alongside the code it
    # describes -- same discipline as the dashboard. Provenance that lands in a later
    # commit than its change is provenance you have to reconstruct.
    append_provenance "$number" "$title" "$branch" "$pr_number" "$dash_rel" "$raw" "$logfile"

    git add -A
    # Blast radius, checked with everything STAGED so untracked files count. Over the cap the
    # batch is parked rather than committed: whatever produced a 200-file diff for one issue,
    # it is not something to ship under that issue's `Closes #N` without a human looking.
    if ! blast_radius_ok "$number" "$logfile"; then
      report_failure "#${number} exceeded the blast-radius cap; parking the batch ${numbers_csv} instead of committing it" "$logfile" 1
      batch_failed=1
      break
    fi
    write_measurement "$number" "$title" "$raw" "$dash_rel" "$branch" "$pr_number" \
      "committed" "$(( $(date +%s) - issue_start_epoch ))" "$logfile"

    # Guard commit AND push explicitly: under `set -euo pipefail` a bare failing git command (a
    # commit hook, missing identity, a transient push error) would kill the WHOLE script before
    # abandon_branch/report_failure ever run, leaving partial batch state behind. Convert either
    # failure into the controlled batch_failed path instead.
    git commit -m "gaia: resolve #${number} (${title})

Closes #${number}

Automated change by the gaia orchestrator; the whole batch is gated before review.

Co-Authored-By: Claude <noreply@anthropic.com>" >> "$logfile" 2>&1 && commit_rc=0 || commit_rc=$?
    if [ "$commit_rc" -ne 0 ]; then
      report_failure "git commit failed for #${number}; abandoning batch ${numbers_csv}" "$logfile" "$commit_rc"
      batch_failed=1
      break
    fi
    any_committed=1

    # Push this commit; on the FIRST commit of the batch open the PR as a DRAFT so the per-issue
    # commits stream onto it as they land. It is NOT marked ready-for-review (and Copilot is NOT
    # requested) until every issue is committed AND the batch gate passes, further below. The draft
    # body carries the ${closes_lines} up front so issue closure is guaranteed even if the
    # ready-for-review body swap below fails and the placeholder body has to stand.
    git push -u origin "$branch" >> "$logfile" 2>&1 && push_rc=0 || push_rc=$?
    if [ "$push_rc" -ne 0 ]; then
      report_failure "git push failed for #${number}; abandoning batch ${numbers_csv}" "$logfile" "$push_rc"
      batch_failed=1
      break
    fi
    if [ -z "$pr_number" ]; then
      # NOTE: `gh pr create` has no --json flag. Passing one made it exit non-zero
      # on every batch of the 2026-08-17/18 run, which tripped the (then
      # destructive) failure path and deleted nine already-pushed branches.
      # open_draft_pr creates, then reads the number back via `gh pr view`.
      pr_number="$(open_draft_pr "$branch" \
        "gaia: ${readable_key} (${numbers_csv})" \
        "Draft -- the gaia orchestrator is resolving ${numbers_csv} (${readable_key}), one commit per issue. Marked ready for review once every issue in the batch is committed and the local gate (test + check-dois + quarto render) passes.

${closes_lines}" \
        "$logfile")" && draft_rc=0 || draft_rc=$?
      if [ "$draft_rc" -ne 0 ] || [ -z "$pr_number" ]; then
        report_failure "could not open draft PR for ${numbers_csv}; parking batch" "$logfile" "$draft_rc"
        batch_failed=1
        break
      fi
      echo "  opened DRAFT PR #${pr_number} for ${numbers_csv}" | tee -a "$logfile"
    fi
  done <<< "$numbers"

  if [ "$batch_failed" -ne 0 ]; then
    flush_measurements "fail" "$logfile"
    park_branch "$branch" "$logfile" "batch failed on ${numbers_csv}"
    continue
  fi
  if [ "$any_committed" -eq 0 ]; then
    echo "  no changes produced for any issue in ${numbers_csv}; skipping (see $logfile)" | tee -a "$logfile"
    flush_measurements "unverified" "$logfile"
    # A genuinely empty batch: nothing committed AND nothing pushed. Dropping the
    # local pointer loses no work -- but only after PROVING it is identical to
    # main and the tree is clean, rather than assuming it.
    git checkout main >> "$logfile" 2>&1 || git checkout -f main >> "$logfile" 2>&1 || true
    if [ -z "$(git log --oneline "main..${branch}" 2>/dev/null)" ] && [ -z "$(git status --porcelain)" ]; then
      git branch -d "$branch" >> "$logfile" 2>&1 || true
    else
      park_branch "$branch" "$logfile" "no-op batch, but the branch was not identical to main"
    fi
    continue
  fi

  # Gate the accumulated batch ONCE (one quarto render per batch, not per issue). The per-issue
  # commits have already been pushed to the DRAFT PR above; this whole-branch gate is what must
  # pass before the PR is flipped to ready-for-review below. On failure the batch is PARKED --
  # branch and draft PR both survive -- so a not-yet-green draft never reaches review or the
  # --merge, but its work is never destroyed either.
  echo "  pre-flight gate: pixi run test && pixi run check-dois" | tee -a "$logfile"
  { pixi run test >> "$logfile" 2>&1 && pixi run check-dois >> "$logfile" 2>&1; } && test_rc=0 || test_rc=$?
  if [ "$test_rc" -ne 0 ]; then
    flush_measurements "fail" "$logfile"
    report_failure "pre-flight gate FAILED for ${numbers_csv}; PR left as draft, issues stay open" "$logfile" "$test_rc"
    [ -n "$pr_number" ] && gh pr comment "$pr_number" --body "Pre-flight gate failed (\`pixi run test\` / \`check-dois\`); left as a draft for a human. See \`${logfile}\`." >> "$logfile" 2>&1 || true
    park_branch "$branch" "$logfile" "pre-flight gate failed for ${numbers_csv}"
    continue
  fi
  pixi run quarto render docs/twin --to html >> "$logfile" 2>&1 && quarto_rc=0 || quarto_rc=$?
  if [ "$quarto_rc" -ne 0 ]; then
    flush_measurements "fail" "$logfile"
    report_failure "quarto render failed for ${numbers_csv}; PR left as draft" "$logfile" "$quarto_rc"
    [ -n "$pr_number" ] && gh pr comment "$pr_number" --body "Quarto render failed; left as a draft for a human. See \`${logfile}\`." >> "$logfile" 2>&1 || true
    park_branch "$branch" "$logfile" "quarto render failed for ${numbers_csv}"
    continue
  fi

  # The gate is green: every issue committed in this batch is now known to have passed
  # `pixi run test`, `check-dois` and the twin render. That is the reward signal, so write
  # the corpus records now rather than at merge time -- merge depends on Copilot's mood and
  # a human's availability, neither of which says anything about whether the agent was right.
  flush_measurements "pass" "$logfile"

  # A bare `var="$(cmd)"` with no exit-code guard would, under `set -e`, silently kill the WHOLE
  # script (not just this batch) if `cmd` fails -- there is no later stage to report or recover.
  # Guard it, and fall back to a minimal body/message (still carrying the Closes lines) so a
  # lab-notebook drafting failure never blocks the actual PR from opening or merging.
  echo "  drafting PR description via gaia-lab-notebook (logged to $logfile)..." | tee -a "$logfile"
  pr_body="$(timeout --signal=TERM --kill-after=60 "$GAIA_AUX_TIMEOUT" claude -p "Use the gaia-lab-notebook agent to write a clear, scientist-facing pull
request description for the change on branch ${branch} in ${REPO_DIR}, which together
resolves this batch of related issues (grouped under '${readable_key}'):

${issue_bullets}

Read the actual diff (git diff main...${branch}) -- don't guess. Explain in plain
language: what was wrong across these issues, what changed, and what it means
scientifically. No filler, no restating the diff line by line. End the body with
these literal lines, one per issue:
${closes_lines}" --permission-mode acceptEdits --dangerously-skip-permissions \
    --max-turns "$GAIA_AUX_MAX_TURNS" \
    --disallowed-tools "${GAIA_READONLY_DENY[@]}" 2>>"$logfile")" \
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

  # The draft PR already exists (opened on the first commit above). Now that the whole batch is
  # committed and gated, swap the placeholder body for the real one and mark it ready for review.
  gh pr edit "$pr_number" --title "gaia: ${readable_key} (${numbers_csv})" --body "$pr_body" >> "$logfile" 2>&1 \
    || echo "  could not update PR #${pr_number} body; the draft placeholder stands" | tee -a "$logfile"
  # Mark ready, then VERIFY it took. A PR left in draft gets no Copilot review at
  # all, so the whole review stage would silently no-op -- a failure that looks
  # identical to "Copilot had nothing to say". Retry once, then say so loudly.
  gh pr ready "$pr_number" >> "$logfile" 2>&1 || true
  if [ "$(gh pr view "$pr_number" --json isDraft -q .isDraft 2>>"$logfile")" = "true" ]; then
    echo "  PR #${pr_number} still in draft after 'gh pr ready'; retrying once" | tee -a "$logfile"
    sleep 5
    gh pr ready "$pr_number" >> "$logfile" 2>&1 || true
  fi
  if [ "$(gh pr view "$pr_number" --json isDraft -q .isDraft 2>>"$logfile")" = "true" ]; then
    echo "  !!! PR #${pr_number} is STILL a draft -- Copilot will not review it. Mark it ready by hand: gh pr ready ${pr_number}" | tee -a "$logfile"
    gh pr comment "$pr_number" --body "This PR could not be marked ready for review automatically, so **no code review was triggered**. Mark it ready by hand (\`gh pr ready ${pr_number}\`) to get one." >> "$logfile" 2>&1 || true
  else
    echo "  marked PR #${pr_number} ready for review (${numbers_csv})" | tee -a "$logfile"
  fi

  # Request review BEFORE arbitration. If this batch collides with a sibling PR,
  # a human has to choose between them -- and they should have a code review of
  # BOTH sides in front of them when they do. Requesting afterwards would skip
  # review entirely on any PR that arbitration blocks.
  gh api "repos/${REPO_SLUG}/pulls/${pr_number}/requested_reviewers" \
    -f "reviewers[]=${COPILOT_REVIEWER}" >> "$logfile" 2>&1 \
    || echo "  could not request Copilot review via API; add it once by hand and re-run" | tee -a "$logfile"

  # COLLISION ARBITRATION. Batches are cut from main in parallel, so a sibling
  # batch can have touched the same module without either agent ever seeing the
  # other. Test for a real merge conflict against every other open gaia PR and,
  # on a hit, hand both diffs to an independent auditor. A blocked PR stays
  # READY (so it still gets reviewed) and is labelled needs-human-decision; it
  # simply never auto-merges.
  #
  # This detects COLLISIONS. It is not a bake-off: the two PRs are whatever
  # happened to overlap, usually resolving different issues, so the auditor is
  # answering "which lands first / can these be reconciled", not "which design
  # is better for one shared problem". See arbitrate_collision() above.
  if ! arbitrate_collisions "$branch" "$pr_number" "$logfile"; then
    echo "  arbitration blocked PR #${pr_number}; left ready for review and labelled for a human" | tee -a "$logfile"
    git checkout main >> "$logfile" 2>&1 || true
    continue
  fi

  # Iterate-until-convergence, not one fixed round: Copilot's code review NEVER submits an
  # "Approve" state (confirmed empirically -- it only ever leaves a COMMENTED review), so waiting
  # for approval would hang forever. "Converged" here means Copilot has nothing NEW left to say --
  # tracked as a fingerprint of its inline comments AND its review body, not the review's (permanently
  # COMMENTED) state -- Copilot can leave actionable feedback in the body with zero inline comments, so
  # inline comments alone are not the whole signal.
  # Merging past a merely-COMMENTED review relies on the repo's ruleset bypass_actor for this token
  # (scoped to bypass_mode=pull_request only -- direct-push protections on main still apply).
  gate_ok=1
  prev_round_fingerprint=""
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

    # A FAILED fetch of inline comments must not masquerade as "no comments": the old placeholder made a
    # stable fingerprint that false-converged us straight into a merge. `if !` distinguishes a genuine
    # request failure (non-zero exit) from a legitimately empty comment set (exit 0, empty output) --
    # gh returns success with empty output when a PR simply has no inline comments.
    if ! review_comments="$(gh api "repos/${REPO_SLUG}/pulls/${pr_number}/comments" --jq '.[] | "- \(.path):\(.line // .original_line): \(.body)"' 2>>"$logfile")"; then
      echo "  could not fetch inline comments for PR #$pr_number; leaving it open for a human rather than risk a false-converge merge" | tee -a "$logfile"
      gate_ok=0
      break
    fi
    review_body="$(jq -r '.body // ""' <<<"$review" 2>>"$logfile")" || review_body=""

    # "Nothing to say" requires BOTH no inline comments AND no review body -- otherwise body-only
    # feedback would be silently dropped. Convergence otherwise means the WHOLE payload (inline comments
    # + review body) is byte-identical to the previous round, not just the inline comments.
    if [ -z "$review_comments" ] && [ -z "$review_body" ]; then
      echo "  converged: Copilot left no inline comments and no review body (round ${review_round})" | tee -a "$logfile"
      break
    fi
    round_fingerprint="$(printf '%s\n--- review body ---\n%s' "$review_comments" "$review_body" | fingerprint)"
    if [ -n "$prev_round_fingerprint" ] && [ "$round_fingerprint" = "$prev_round_fingerprint" ]; then
      echo "  converged: Copilot's inline comments and review body are unchanged since the previous round (round ${review_round})" | tee -a "$logfile"
      break
    fi
    if [ "$review_round" -eq "$REVIEW_MAX_ROUNDS" ]; then
      echo "  hit the ${REVIEW_MAX_ROUNDS}-round cap with unresolved Copilot comments; proceeding to the gate/merge step anyway (CI green + the bypass actor are the real gate here, not Copilot's approval, which never comes) -- see $logfile for what's still open" | tee -a "$logfile"
      break
    fi
    prev_round_fingerprint="$round_fingerprint"

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
    vcs_before="$(vcs_state)"
    timeout --signal=TERM --kill-after=60 "$GAIA_ISSUE_TIMEOUT" \
      claude -p "$revise_prompt" \
      --permission-mode acceptEdits \
      --dangerously-skip-permissions \
      --max-turns "$GAIA_MAX_TURNS" \
      --disallowed-tools "${GAIA_VCS_DENY[@]}" \
      2>&1 | tee -a "$logfile" || echo "  revision pass errored or timed out; continuing to gate check" | tee -a "$logfile"
    # A revision pass that committed has already put unreviewed work on the branch under a
    # message the pipeline did not write. Stop before pushing more on top of it.
    if ! assert_no_vcs_mutation "$vcs_before" "the revision pass on PR #${pr_number}" "$logfile"; then
      gate_ok=0
      break
    fi

    if tree_dirty; then
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

  # THE MERGE GATE. Copilot going quiet is necessary but not sufficient -- an
  # unchanged comment fingerprint reads identically whether the revision pass
  # addressed the feedback or ignored it. An independent auditor reads the final
  # diff against the outstanding comments and has to agree before anything
  # merges. It fails CLOSED: no parseable verdict means blocked, not merged.
  if ! audit_pr_convergence "$pr_number" "$branch" "$numbers_csv" "${review_comments:-}" "$logfile"; then
    echo "  auditor gate blocked PR #${pr_number}; NOT merging, issues stay open" | tee -a "$logfile"
    git checkout main >> "$logfile" 2>&1 || true
    continue
  fi

  close_message="$(timeout --signal=TERM --kill-after=60 "$GAIA_AUX_TIMEOUT" claude -p "Use the gaia-lab-notebook agent to write a short, clear message for a
research scientist explaining that this batch of related issues has just been resolved
and merged via PR #${pr_number} in ${REPO_DIR} (grouped under '${readable_key}'):

${issue_bullets}

Read the actual diff on that branch -- don't guess. Plain language: what was wrong,
what changed, what it means for the science/results. This will be posted as the
closing comment on each issue in the batch." \
    --permission-mode acceptEdits --dangerously-skip-permissions \
    --max-turns "$GAIA_AUX_MAX_TURNS" \
    --disallowed-tools "${GAIA_READONLY_DENY[@]}" 2>>"$logfile")" \
    && close_message_rc=0 || close_message_rc=$?
  if [ "$close_message_rc" -ne 0 ] || [ -z "$close_message" ]; then
    report_failure "gaia-lab-notebook failed to draft the close message for ${numbers_csv}; using a minimal message" "$logfile" "$close_message_rc"
    close_message="Resolved via PR #${pr_number}. Closing-message drafting failed; see ${logfile}."
  fi

  gh pr merge "$pr_number" --merge --delete-branch --body "$close_message" >> "$logfile" 2>&1 \
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

  # A batch that MERGED has, by definition, shipped everything it produced. `gh pr merge
  # --delete-branch` switches back to the base branch, so anything still dirty at this
  # point is either a build artifact that should be gitignored or agent work that escaped
  # the commit path -- both of which would otherwise be inherited by the next batch and
  # blamed on its first issue. This is not fatal (the merge already succeeded and nothing
  # is at risk), but it must be loud and it must not propagate.
  git checkout main >> "$logfile" 2>&1 || git checkout -f main >> "$logfile" 2>&1 || true
  if ! assert_tree_clean "after merging PR #${pr_number} (${numbers_csv})" "$logfile"; then
    # The merge already succeeded, so nothing shipped is at risk -- but the same reasoning
    # applies to what is left behind: if it could not be preserved, no later batch may run.
    if ! quarantine_residue "postmerge-pr${pr_number}" \
        "left in the tree after PR #${pr_number} merged" "$logfile"; then
      report_failure "PR #${pr_number} merged, but post-merge residue could not be preserved; HALTING the queue with the tree untouched" "$logfile" 1
      GAIA_STOP=1
    fi
  fi

  if [ -n "$milestone" ]; then
    epic_number="$(epic_for_milestone "$milestone")" || epic_number=""
    if [ -n "$epic_number" ]; then
      gh issue comment "$epic_number" --body "Sub-issues ${numbers_csv} resolved via PR #${pr_number} (squash-merged, Copilot-reviewed, checks green). Epic left open for your own review." \
        || echo "  could not comment on epic #$epic_number" | tee -a "$logfile"
    fi
  fi
done < <(python3 "$REPO_DIR/scripts/gaia_group_issues.py")
