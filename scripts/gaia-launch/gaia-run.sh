#!/usr/bin/env bash
# gaia-run.sh — run the gaia orchestrator on one GitHub issue, watch it live,
# and archive the whole trajectory for later evaluation.
#
#   ./gaia-run.sh 42 "NaNs at basin edges"
#   ./gaia-run.sh 42 "NaNs at basin edges" mdenolle/gwl-space-time-smooth
#
# Configuration (environment):
#   GAIA_RUNS       archive root                 default ~/gaia-runs
#   GAIA_TEST_CMD   verification command         default: pytest -q  ("skip" to omit)
#   GAIA_MAX_TURNS  cap on agent turns           default 60
#   GAIA_THINKING   1 to ask for reasoning before edits
#
# Requires: claude, jq, python3, git, and gaia_trace.py/gaia_ticker.py alongside
# this script.

set -uo pipefail

ISSUE_NUM="${1:?usage: gaia-run.sh ISSUE_NUM ISSUE_TITLE [REPO_SLUG]}"
ISSUE_TITLE="${2:?missing ISSUE_TITLE}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRACE="$HERE/gaia_trace.py"
TICKER="$HERE/gaia_ticker.py"
[[ -f "$TRACE" ]] || { echo "gaia_trace.py not found next to this script" >&2; exit 1; }
[[ -f "$TICKER" ]] || { echo "gaia_ticker.py not found next to this script" >&2; exit 1; }
for tool in claude jq python3; do
  command -v "$tool" >/dev/null || { echo "$tool not on PATH" >&2; exit 1; }
done

if [[ -n "${3:-}" ]]; then
  REPO_SLUG="$3"
else
  REPO_SLUG="$(git config --get remote.origin.url 2>/dev/null \
    | sed -E 's#(git@|https://)[^:/]+[:/]##; s#\.git$##')"
  [[ -n "$REPO_SLUG" ]] || { echo "no REPO_SLUG given and no git remote found" >&2; exit 1; }
fi

RUNS="${GAIA_RUNS:-$HOME/gaia-runs}"
TEST_CMD="${GAIA_TEST_CMD:-pytest -q}"
MAX_TURNS="${GAIA_MAX_TURNS:-60}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
SLUG_SAFE="${REPO_SLUG//\//_}"
DIR="$RUNS/${SLUG_SAFE}/issue-${ISSUE_NUM}/${STAMP}"
mkdir -p "$DIR"

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
GIT_REV="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
GIT_DIRTY_BEFORE="$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"

# A clean tree going in keeps change.diff attributable to the agent alone.
if [[ "${GIT_DIRTY_BEFORE:-0}" != "0" ]]; then
  echo "warning: $GIT_DIRTY_BEFORE file(s) already modified; change.diff will include them."
  echo "         Ctrl-C to stop, or wait 5s to continue."
  sleep 5
fi

THINK_CLAUSE=""
[[ "${GAIA_THINKING:-0}" == "1" ]] && \
  THINK_CLAUSE=" Think through the diagnosis before editing."

PROMPT="Use the gaia orchestrator to resolve GitHub issue #${ISSUE_NUM} \
(\"${ISSUE_TITLE}\") in ${REPO_SLUG}. \
Follow /gaia:ground-rules. Minimal correct change for THIS issue only. \
Do not commit — leave the working tree dirty.${THINK_CLAUSE}"

printf '%s\n' "$PROMPT" > "$DIR/prompt.txt"

echo "run    $DIR"
echo "repo   $REPO_SLUG @ ${GIT_REV:0:8}"
echo "verify $TEST_CMD"
echo "────────────────────────────────────────────────────────────"

START_EPOCH="$(date +%s)"

claude -p "$PROMPT" \
  --permission-mode acceptEdits \
  --dangerously-skip-permissions \
  --max-turns "$MAX_TURNS" \
  --verbose \
  --output-format stream-json \
  2> "$DIR/claude.stderr" \
| python3 "$TICKER" \
| tee "$DIR/raw.jsonl" >/dev/null

CLAUDE_RC="${PIPESTATUS[0]}"
WALL="$(( $(date +%s) - START_EPOCH ))"

# ---- capture what changed -------------------------------------------------
( cd "$REPO_ROOT" && git diff > "$DIR/change.diff" ) 2>/dev/null || : > "$DIR/change.diff"
( cd "$REPO_ROOT" && git status --porcelain > "$DIR/status.txt" ) 2>/dev/null || :
DIFF_LINES="$(wc -l < "$DIR/change.diff" 2>/dev/null | tr -d ' ')"
FILES_TOUCHED="$(grep -c '^+++ ' "$DIR/change.diff" 2>/dev/null || true)"
DIFF_LINES="${DIFF_LINES:-0}"; FILES_TOUCHED="${FILES_TOUCHED:-0}"

# ---- verification: the reward signal --------------------------------------
if [[ "$TEST_CMD" == "skip" ]]; then
  OUTCOME="unverified"; TEST_RC=-1
else
  echo "verification: $TEST_CMD"
  ( cd "$REPO_ROOT" && eval "$TEST_CMD" ) > "$DIR/tests.log" 2>&1
  TEST_RC=$?
  if [[ "$TEST_RC" -eq 0 ]]; then OUTCOME="pass"; else OUTCOME="fail"; fi
fi

# ---- run metadata ---------------------------------------------------------
jq -n \
  --arg run_id "$STAMP" --arg repo "$REPO_SLUG" --arg issue "$ISSUE_NUM" \
  --arg issue_title "$ISSUE_TITLE" --arg git_rev "$GIT_REV" \
  --arg repo_root "$REPO_ROOT" --arg test_cmd "$TEST_CMD" \
  --arg outcome "$OUTCOME" --arg dir "$DIR" \
  --arg claude_version "$(claude --version 2>/dev/null | head -1)" \
  --argjson claude_rc "$CLAUDE_RC" --argjson test_rc "$TEST_RC" \
  --argjson wall_s "$WALL" --argjson diff_lines "$DIFF_LINES" \
  --argjson files_touched "$FILES_TOUCHED" \
  --argjson dirty_before "${GIT_DIRTY_BEFORE:-0}" \
  '$ARGS.named' > "$DIR/meta.json"

# ---- derived views + corpus record ----------------------------------------
python3 "$TRACE" "$DIR/raw.jsonl" \
  --html    "$DIR/dashboard.html" \
  --md      "$DIR/transcript.md" \
  --mermaid "$DIR/graph.mmd" \
  --records "$RUNS/records.jsonl" \
  --meta    "$DIR/meta.json"

echo "outcome:   $OUTCOME   diff: ${DIFF_LINES} lines / ${FILES_TOUCHED} file(s)"
echo "dashboard: $DIR/dashboard.html"
echo "corpus:    $RUNS/records.jsonl"
