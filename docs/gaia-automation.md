# Running the gaia agents unattended, in sync with GitHub

This describes the remote-server automation that works the open issue backlog with the
**gaia** agent family (`.claude/gaia/plugins/gaia`), independently of any interactive
Claude Code session, and keeps GitHub as the source of truth throughout. The moving parts:

| File | Role |
|---|---|
| `scripts/gaia_bootstrap.sh` | One-time setup on a fresh remote Linux box |
| `scripts/gaia_group_issues.py` | Groups open issues into PR-sized batches (the queue) |
| `scripts/gaia_run_queue.sh` | Runs the queue: orchestrator → PR → arbitration → review → auditor gate → merge |
| `scripts/gaia-launch/gaia_ticker.py` | Live per-agent ticker while a batch runs |
| `scripts/gaia-launch/gaia_trace.py` | Renders a transcript into the HTML dashboard |
| `scripts/gaia-launch/gaia_runs_site_index.py` | Builds the index over all published dashboards |

> **The safety model, in five invariants.** Everything below follows from these:
>
> 1. **Nothing is ever deleted.** Failure parks work — committed, pushed, renamed out of the
>    way. The only automatic branch removal is after a successful merge.
> 2. **Gates fail closed.** An unparseable verdict, a timeout, or an unreachable service
>    blocks a merge; it never waves one through.
> 3. **One loop, one PID, one stop command.** The queue is killable as a unit, not
>    child-by-child.
> 4. **Publication is verified before any work starts**, so a broken `gh`/auth path costs
>    seconds rather than a full batch.
> 5. **A PR is never left in draft.** Draft PRs get no code review, so the queue marks each
>    PR ready, *verifies* it took, and requests review before anything can block it. Work
>    that is held back is labelled, not hidden.

## What it does, end to end

For each batch of related issues (see grouping, below):

1. Branch off `main`, run the **gaia orchestrator** to resolve the batch **one issue at a
   time**, so each fix lands as its own commit naming the issue it closes.
2. Local pre-flight gate: `pixi run test`, `pixi run check-dois`, and a `quarto render` of
   the twin book. Any failure **parks** the branch (see *When a batch fails*) and leaves the
   issues open — nothing half-broken reaches review or merge.
3. Open **one draft PR** for the batch on the first commit, then swap in a real description
   drafted by the `gaia-lab-notebook` agent (reads the actual diff, explains it in plain
   language, ends with one `Closes #N` per issue) and mark it ready for review.
4. **Arbitration.** Batches are cut from `main` in parallel, so two batches can
   independently propose *competing* designs for the same module without either agent
   seeing the other. The branch is tested against every other open `gaia/*` PR —
   changed-file overlap as a prefilter, then `git merge-tree` as the real conflict test. On
   a genuine conflict an **independent `gaia-auditor`** receives both diffs and both issue
   statements, is not told which side is "ours", and returns a verdict
   (`A` / `B` / `reconcile` / `escalate`). The verdict is posted on **both** PRs; the losing
   side is labelled `needs-human-decision` and never auto-merges. It deliberately stays
   **ready for review**, not demoted to draft: a draft PR gets no code review, and the
   human adjudicating a design collision needs a review of *both* sides in front of them.
5. Request a **Copilot code review** on the PR and wait for it (up to 20 minutes).
6. **Revise and re-review, up to `REVIEW_MAX_ROUNDS` (default 3) rounds**: feed Copilot's
   comments back to the orchestrator, let it address what's actually called for, re-run the
   local gate, push, and wait for a fresh review. Copilot's review **never** reaches an
   "Approve" state — only ever `COMMENTED` — so this loop tracks a fingerprint of its
   comments, not the review state.
7. Wait for **GitHub Actions checks** on the PR to go green.
8. **Auditor merge gate.** Copilot going quiet is necessary but *not* sufficient: an
   unchanged comment fingerprint reads the same whether the revision pass addressed the
   feedback or ignored it. An independent `gaia-auditor` reads the final diff against the
   outstanding comments and must confirm that each substantive comment is addressed or
   correctly rebutted, that the change resolves the issues it claims to close, and that it
   introduces no new problems. It **fails closed** — unparseable output blocks the merge —
   and posts its verdict on the PR either way. A merge needs **both** signals.
9. **Squash-merge.** Every issue in the batch closes via the `Closes #N` lines. Each
   issue (and the PR) gets the same scientist-facing closing message, again drafted by
   `gaia-lab-notebook`. If the batch belongs to a milestone, that milestone's `epic`
   tracker issue gets a one-line progress comment — **the epic itself is never closed
   by this script.**

Any failure at any stage (orchestrator errors, gate fails, arbitration ruling against the
branch, no Copilot review in time, revision breaks the gate, checks red, auditor blocks)
stops that batch, leaves the PR/issues open, and moves on to the next. Nothing merges on a
guess, and **nothing is ever deleted.**

## Grouping the queue

`scripts/gaia_group_issues.py` decides what becomes one PR. Grouping key, in order:

1. **Milestone**, if the issue has one — this repo's milestones are already curated
   epics (e.g. *"Water budget: vadose-zone physics & calibration"*, *"Applied math: DA
   estimator correctness"*), each with its own `epic`-labeled tracker issue. Trusted
   over any label heuristic.
2. Otherwise, the first matching **topic label** (`dv-v`, `water-budget`, `geotech`,
   `landlab`, `stage-3`, `stage-2`, `stage-1`, `hydrogeology`, `soil-reanalysis`,
   `atmospheric`, `uncertainty`, `validation`, `peer-review`, `documentation`, `bug`,
   `enhancement` — in that priority order).
3. Otherwise, the issue is its own solo batch.

Within a group, any `P0`-labeled issues split off into their own, earlier batch — a
blocking-correctness fix never waits behind exploratory `P2` work just because they
share an epic. Groups are capped at **4 issues per PR** (`MAX_BATCH` in the script) so a
single review stays tractable; oversized groups split into ordered chunks. Batches run
in order of their worst (highest-priority) member: all `P0` batches first, then `P1`,
then `P2`.

`epic`-labeled issues are trackers, never work items, and are always excluded from
batches.

To preview what the queue would do without running anything:

```bash
python3 scripts/gaia_group_issues.py | jq -c '{key, branch, issues: [.issues[].number]}'
```

## One-time setup

On the remote Linux box, as the user that will own the automation (not root):

```bash
export REPO_URL="git@github.com:gaia-hazlab/gwl-space-time-smooth.git"   # SSH remote
export REPO_DIR="$HOME/gwl-space-time-smooth"
bash scripts/gaia_bootstrap.sh
```

This installs `pixi` (the pinned env, matching CI), the `gh` CLI, the Claude Code CLI,
Quarto, clones the repo, and registers the gaia plugin
(`claude plugin marketplace add ./.claude/gaia && claude plugin install gaia@gaia`).

Three credentials it does **not** set up for you, on purpose:

- **Git over SSH** — `git clone`/`git push` use the SSH remote, so the box needs a
  private key that can push to this repo (copy an existing key over, or generate a
  fresh deploy key on the box and add its public half under repo → Settings → Deploy
  keys, with write access). This is independent of the `gh` CLI login below.
- **`gh` CLI auth** — every `gh issue list` / `gh pr create` / `gh pr merge` / the
  Copilot-reviewer request in `gaia_run_queue.sh` goes through this, not SSH:
  ```bash
  echo "$GH_TOKEN" | gh auth login --with-token   # needs repo + workflow scopes
  ```
- **`ANTHROPIC_API_KEY`** — put it in a mode-600 file, a systemd `EnvironmentFile`, or a
  secret manager. **Never in the repo, and never typed inline on the command line**: an
  inline `export` is written verbatim to `~/.bash_history`, where it persists in plaintext
  long after the run and is trivial to leak in a screen share or a pasted terminal log.

  ```bash
  install -m 600 /dev/null "$HOME/.config/gaia/env"
  printf 'ANTHROPIC_API_KEY=%s\n' 'sk-ant-...' >> "$HOME/.config/gaia/env"
  # then, per shell:  set -a; . "$HOME/.config/gaia/env"; set +a
  ```

Before the first real run, sanity-check both:

```bash
ssh -T git@github.com
git -C "$REPO_DIR" push --dry-run origin main
gh auth status
```

The script's own `preflight` re-checks the parts it depends on at every launch and refuses
to start if they are broken, but these confirm the SSH push path it cannot test without
writing.

Also verify the Copilot reviewer login once by hand (open any PR in the GitHub UI,
check who "Copilot" resolves to as a requested reviewer) — `gaia_run_queue.sh` hardcodes
`copilot-pull-request-reviewer[bot]` at the top; update it there if your org differs.

One more org-dependent flag: arbitration returns a losing PR to draft with
`gh pr ready --undo`, which GitHub documents as available *"if supported by your plan."*
Confirm it works on one throwaway PR; if it does not, arbitration still posts its verdict
and still refuses to merge — the PR just stays marked ready.

If `main` has a ruleset/branch-protection rule requiring an approving review, note that
**Copilot's code review never submits "Approve"** — only ever `COMMENTED` — so a plain
`required_approving_review_count` will block this pipeline's merge step forever, no matter
how many revision rounds run. The fix used on this repo: add the automation's GitHub
identity (the same account/token `gh auth login` uses) as a **bypass actor** on the
ruleset, with `bypass_mode: "pull_request"` (bypasses the review/status-check requirement
on merge only — direct-push protections like `deletion`/`non_fast_forward` still apply to
that identity). Via the API:

```bash
gh api user --jq '.id'   # numeric actor_id for the account gaia_run_queue.sh authenticates as
# then PUT the ruleset (see its current rules via `gh api repos/{owner}/{repo}/rulesets/{id}`)
# with bypass_actors: [{"actor_id": <id>, "actor_type": "User", "bypass_mode": "pull_request"}]
```

Confirm the merge step actually works end-to-end once — if the bypass isn't configured, or a
CODEOWNERS file later makes `require_code_owner_review` bite, the merge fails loudly, which
is the safe outcome, but you won't get the close-the-loop behavior until it's resolved.

## Running it safely

### Always look at the queue first

The script drains the **entire** open backlog by default, and the backlog is usually deeper
than it looks — on this repo it currently builds around 40 batches, i.e. around 40 PRs.
Budget roughly **20–90 minutes per issue**, and note that each issue is a separate `claude
-p` invocation with its own API spend. A full drain is a multi-day commitment, not an
overnight one. Look before you launch:

```bash
# how many PRs am I authorizing?
python3 scripts/gaia_group_issues.py | wc -l

# what are they, in execution order?
python3 scripts/gaia_group_issues.py | jq -c '{key, branch, issues: [.issues[].number]}'
```

Batch JSON goes to **stdout**; the grouper also writes `holding back #N: blocked by open
#M` lines to **stderr** for issues whose declared dependencies are still open. Those are
worth reading — they are the issues the queue is deliberately *not* attempting yet:

```bash
python3 scripts/gaia_group_issues.py 2>&1 >/dev/null   # dependency diagnostics only
```

### Start with one batch

```bash
cd "$REPO_DIR"
set -a; . "$HOME/.config/gaia/env"; set +a     # ANTHROPIC_API_KEY, mode-600 file — never inline
GAIA_MAX_BATCHES=1 scripts/gaia_run_queue.sh
```

Do **not** type `export ANTHROPIC_API_KEY=sk-ant-...` on the command line: it lands in
`~/.bash_history` in plaintext. Keep it in a mode-600 file and source it.

The script prints its own stop command at startup and runs a **preflight** before touching
anything — `gh auth status`, the `gh` sub-flags it depends on, and `jq`/`python3`/`git` on
`PATH`. If the publication path is broken it exits immediately, having changed nothing. A
credential or CLI problem therefore costs you seconds at launch rather than surfacing after
a batch has already done its work.

### Knobs

| Variable | Default | Effect |
|---|---|---|
| `GAIA_MAX_BATCHES` | `0` | `0` drains the queue; `N` stops after N batches, leaving the rest untouched |
| `GAIA_ARBITRATION` | `1` | `0` disables rival-PR conflict arbitration (not recommended) |
| `GAIA_AUDIT_GATE` | `1` | `0` disables the auditor merge gate (not recommended) |
| `REVIEW_MAX_ROUNDS` | `3` | Cap on Copilot revise-and-re-review rounds |

### Stopping it

**The loop and the agent are different processes.** The queue script is the parent; each
issue runs as a `claude -p` child. Killing the child you can see in `htop` does *not* stop
the queue — the parent simply starts the next issue, and the run appears to continue after
you believe you have ended it. Stop the **loop**:

```bash
kill "$(cat .gaia-runs/gaia_run_queue.pid)"
```

That requests a graceful stop: the current issue finishes, its work is committed and
pushed, and the queue halts before the next batch. A second `TERM` kills immediately —
in-flight work is still committed and pushed, never discarded.

Confirm it is actually gone (the loop, not just a child):

```bash
pgrep -af gaia_run_queue.sh          # should print nothing
pgrep -af 'claude -p Use the gaia'   # should print nothing
```

The PID file also prevents a second concurrent run: launching while one is live exits with
the running PID. The `flock` in the cron example below is belt-and-braces on top of that.

### Unattended, recurring

```cron
*/30 * * * * flock -n /tmp/gaia_run_queue.lock /path/to/scripts/gaia_run_queue.sh >> $HOME/gwl-space-time-smooth/.gaia-runs/cron.log 2>&1
```

For a cron schedule, consider `GAIA_MAX_BATCHES=1` so each wake-up does one batch and
exits, rather than one wake-up occupying the box for hours.

### When a batch fails

Failure **parks**, it never deletes. `park_branch` commits any uncommitted work as an
explicitly-labelled `gaia WIP (parked, unreviewed)` commit, pushes the branch, and renames
the local ref so the next batch cannot clobber it:

```
gaia/parked/<original-branch-name>-<timestamp>
```

The remote branch and any draft PR are left in place. To see what is parked and recover it:

```bash
git branch --list 'gaia/parked/*'
git log --oneline main..gaia/parked/<name>          # what it contains
git checkout gaia/parked/<name>                     # pick it up locally
git fetch origin <original-branch-name>             # or fetch the pushed copy
```

Parked branches accumulate deliberately — they are the recovery material. Prune them
yourself once you have decided each one's fate. The **only** automatic branch removal left
is `gh pr merge --delete-branch`, i.e. after the work is safely in `main`, plus a `git
branch -d` for a no-op batch that is provably identical to `main` with a clean tree.

## Monitoring a run

Three views, from most live to most durable.

### 1. Live, over your shoulder

Each batch streams a per-agent ticker to the console *and* to its log, so you can watch
which agent is doing what in real time:

```bash
tail -f .gaia-runs/batch-*-$(date -u +%Y%m%d)T*.log
```

```
  [main #1] Skill  {"skill": "gaia:ground-rules"}
  [main #2] Bash   {"command": "gh issue view 154 ...
  [gaia:gaia-scientific-coder #12] Bash  {"command": "pixi run pytest ...
```

`[agent #n]` is the agent name and its call index — `main` is the top-level session,
anything else is a subagent. This comes from `gaia_ticker.py`, which sits between `claude`
and `tee` and passes the transcript through untouched.

At the end of each issue the ticker prints a summary table — the fastest way to see whether
an agent was thrashing:

```
agent                        calls  errors  tools
main                            27       0  Bash x18, Agent x5, ToolSearch x2, Skill x1
gaia:gaia-orchestrator          38       1  Read x18, Grep x13, Glob x4, Agent x2
gaia:gaia-scientific-coder      44       1  Bash x43, Read x1
```

### 2. The logs on disk

| Path | Contents | Committed? |
|---|---|---|
| `.gaia-runs/batch-<first-issue>-<ts>.log` | Everything the batch did, including git and `gh` output | no (gitignored) |
| `.gaia-runs/issue-<n>-<ts>.raw.jsonl` | Raw `stream-json` transcript for that issue | no (gitignored) |
| `.gaia-runs/gaia_run_queue.pid` | The loop's PID | no |
| `.gaia-runs/cron.log` | Cron wrapper output | no |

**The batch log is the first place to look when a batch didn't do what you expected.** Its
`!!!` lines are the failure reports, each followed by the last 40 lines of context:

```bash
grep -n '!!!' .gaia-runs/batch-*.log          # every failure across every run
grep -n 'parked\|arbitration verdict\|auditor:' .gaia-runs/batch-*.log
```

### 3. The dashboards

For every issue that produced a commit, the queue renders a **self-contained HTML
dashboard** — the agent call graph, the full transcript, tool counts, cost and duration —
and commits it *in the same commit as the code it documents*:

```
docs/gaia-runs/issue-<n>/<timestamp>/dashboard.html
```

Because they are committed, they are published by the `quarto-pages` workflow on merge,
with a generated index over all of them:

- **Index:** <https://gaia-hazlab.github.io/gwl-space-time-smooth/gaia-runs/>
- **One run:** `https://gaia-hazlab.github.io/gwl-space-time-smooth/gaia-runs/issue-<n>/<timestamp>/dashboard.html`

Note the dashboards only appear on the site **after the PR merges**. To read one before
that, open the file from the branch, or render it yourself from any transcript — including
a run that never got committed:

```bash
# from a queue transcript
python3 scripts/gaia-launch/gaia_trace.py .gaia-runs/issue-154-20260818T101610Z.raw.jsonl \
  --html /tmp/issue-154.html

# or from an interactive session file
python3 scripts/gaia-launch/gaia_trace.py \
  ~/.claude/projects/-home-mdenolle-gwl-space-time-smooth/<session-id>.jsonl --html /tmp/s.html
```

Other useful outputs from the same tool — `--inspect` for a terminal summary, `--counts`
for tool tallies, `--md` for a readable transcript, `--mermaid` for the call graph:

```bash
python3 scripts/gaia-launch/gaia_trace.py <transcript>.jsonl --inspect
python3 scripts/gaia-launch/gaia_trace.py <transcript>.jsonl --md /tmp/run.md --mermaid /tmp/run.mmd
```

Transcripts are the most durable record you have, and the only one that survives a working
tree being reset: they capture the agent's file writes as tool calls, so work that was never
committed can still be reconstructed from `.gaia-runs/issue-<n>-<ts>.raw.jsonl`. **Do not
clear `.gaia-runs/` while any batch is unresolved** — it is gitignored, so nothing else is
keeping a copy.

Secrets in transcripts are redacted before a dashboard is committed. That redaction is
verified, but it is a mitigation, not a licence — keep credentials out of commands the
agents run in the first place.

## What stays a human decision

- **Epics are never closed** by this pipeline, only commented on — matches the group's
  standing rule that tracking issues wait for your own review, not an automated "done."
- **Anything that doesn't clear the gate** (tests, DOI check, quarto render, Copilot
  review timeout, checks red, auditor block) is left open with a log, not force-merged or
  retried silently.
- **Arbitration verdicts are advisory.** When two PRs propose competing designs, the
  auditor's verdict is posted on both and the loser is held back — but *which design the
  project adopts is yours to decide.* The mechanism exists to make the collision visible
  and stop a silent merge, not to settle architecture on your behalf.
- **Parked branches wait for you.** Nothing prunes them. Deciding whether parked work is
  resumed, rewritten, or dropped is a human call.
- **Copilot review plus the auditor gate substitute for your own adversarial pass in this
  pipeline only** — they do not change how interactive PR work with you is handled; that
  still waits for your explicit go-ahead to merge or close.

## Recovering lost work

If a run ends in a state you don't understand — commits you can't find, a branch that
vanished, a working tree that was reset — work through this before changing anything.

**First, stop the clock.** Do **not** run `git gc`, `git prune`, or `git reflog expire`.
Unreachable objects are the recovery material, and those commands are what destroy them.

**1. Find out what actually happened.** The reflog is the authoritative record of every
checkout, commit and reset, with timestamps:

```bash
git reflog --date=iso | head -50
```

**2. Find commits nothing points at any more.** A deleted branch leaves its commits
reachable only from the reflog, or not at all:

```bash
git fsck --no-reflogs --unreachable | grep commit
git log -1 --stat <sha>                       # identify each one
```

**3. Make them permanently reachable *before* anything expires them.** Reflog entries
expire; tags do not. Do this first, and only then start analysing:

```bash
git tag -a recovered/<label> <sha> -m "why this exists, and what it was"
git bundle create ~/recovery.bundle --all     # outside the repo; verify it
git bundle verify ~/recovery.bundle
```

**4. Check whether the work is genuinely gone.** A `git reset --hard` on never-staged
changes leaves nothing in the object database — but the transcript still holds the agent's
file writes, so it is reconstructable:

```bash
grep -c 'cat >\|file_path' .gaia-runs/issue-<n>-<ts>.raw.jsonl
python3 scripts/gaia-launch/gaia_trace.py .gaia-runs/issue-<n>-<ts>.raw.jsonl --md /tmp/run.md
```

**5. Check the remote before assuming a push failed.** A branch can be pushed and then
deleted; `git ls-remote` shows only the present, so read the batch log for the push output
rather than inferring it.

For a worked example of this procedure applied end to end — including how each of the above
steps resolved — see [`docs/postmortem/2026-08-18-gaia-run.md`](postmortem/2026-08-18-gaia-run.md).
