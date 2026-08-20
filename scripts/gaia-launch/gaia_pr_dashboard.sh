#!/usr/bin/env bash
# gaia_pr_dashboard.sh — render and stage the run dashboard for a pull request.
#
#   scripts/gaia-launch/gaia_pr_dashboard.sh <pr-number> [transcript.jsonl]
#
# WHY THIS EXISTS. gaia_run_queue.sh renders a dashboard per ISSUE and commits it alongside
# the code it documents, which covers every PR the queue opens itself. A PR raised from an
# INTERACTIVE session produced no dashboard at all — so the published index silently omitted
# exactly the work a human had been involved in, which is the work whose provenance matters
# most. This closes that gap: same renderer, same redaction, same layout, one directory up.
#
# With no transcript argument it picks the most recently modified session file for THIS repo
# out of ~/.claude/projects/<slugified-cwd>/. That is a convenience, not a guarantee — pass
# the path explicitly if more than one session contributed to the PR.
#
# Output (committed, published by the quarto-pages workflow on merge):
#   docs/gaia-runs/pr-<n>/<timestamp>/dashboard.html
set -euo pipefail

PR_NUMBER="${1:?usage: gaia_pr_dashboard.sh <pr-number> [transcript.jsonl]}"
REPO_DIR="$(git rev-parse --show-toplevel)"
TRACE="$REPO_DIR/scripts/gaia-launch/gaia_trace.py"
[ -f "$TRACE" ] || { echo "!!! missing $TRACE" >&2; exit 1; }

TRANSCRIPT="${2:-}"
if [ -z "$TRANSCRIPT" ]; then
  # Claude Code slugifies the project path by replacing every '/' with '-'.
  SESSION_DIR="$HOME/.claude/projects/${REPO_DIR//\//-}"
  [ -d "$SESSION_DIR" ] || { echo "!!! no session dir at $SESSION_DIR; pass a transcript explicitly" >&2; exit 1; }
  # -maxdepth 1 so a nested archive directory cannot win the newest-file race.
  TRANSCRIPT="$(find "$SESSION_DIR" -maxdepth 1 -name '*.jsonl' -printf '%T@ %p\n' 2>/dev/null \
                | sort -rn | head -1 | cut -d' ' -f2-)"
  [ -n "$TRANSCRIPT" ] || { echo "!!! no .jsonl transcripts in $SESSION_DIR" >&2; exit 1; }
  echo "  using the newest session transcript: $TRANSCRIPT"
  echo "  (pass one explicitly if another session also contributed to PR #${PR_NUMBER})"
fi
[ -f "$TRANSCRIPT" ] || { echo "!!! no such transcript: $TRANSCRIPT" >&2; exit 1; }

TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_REL="docs/gaia-runs/pr-${PR_NUMBER}/${TS}/dashboard.html"
mkdir -p "$REPO_DIR/$(dirname "$OUT_REL")"

TITLE="PR #${PR_NUMBER}"
# A title beats the session UUID, which tells a reader nothing. Best-effort: a missing or
# unauthenticated gh must not stop the dashboard from being rendered.
if command -v gh >/dev/null 2>&1; then
  PR_TITLE="$(gh pr view "$PR_NUMBER" --json title -q .title 2>/dev/null || true)"
  [ -n "${PR_TITLE:-}" ] && TITLE="PR #${PR_NUMBER} — ${PR_TITLE}"
fi

# Secret redaction happens inside gaia_trace.py, so this path inherits it unchanged.
python3 "$TRACE" "$TRANSCRIPT" --html "$REPO_DIR/$OUT_REL" --title "$TITLE"

git -C "$REPO_DIR" add "$OUT_REL"
echo "  staged $OUT_REL"
echo "  commit it with the PR it documents, then it publishes on merge."
