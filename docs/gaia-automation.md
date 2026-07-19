# Running the gaia agents unattended, in sync with GitHub

This describes the remote-server automation that works the open issue backlog with the
**gaia** agent family (`.claude/gaia/plugins/gaia`), independently of any interactive
Claude Code session, and keeps GitHub as the source of truth throughout. Three files:

| File | Role |
|---|---|
| `scripts/gaia_bootstrap.sh` | One-time setup on a fresh remote Linux box |
| `scripts/gaia_group_issues.py` | Groups open issues into PR-sized batches (the queue) |
| `scripts/gaia_run_queue.sh` | Runs the queue: orchestrator → PR → Copilot review → merge |

## What it does, end to end

For each batch of related issues (see grouping, below):

1. Branch off `main`, run the **gaia orchestrator** to resolve the whole batch as one
   coherent change.
2. Local pre-flight gate: `pixi run test`, `pixi run check-dois`, and a `quarto render` of
   the twin book. Any failure discards the branch and leaves the issues open — nothing
   half-broken ever gets pushed.
3. Open **one PR** for the batch, with a description drafted by the `gaia-lab-notebook`
   agent (reads the actual diff, explains it in plain language, ends with one
   `Closes #N` per issue in the batch).
4. Request a **Copilot code review** on the PR and wait for it (up to 20 minutes).
5. Run **one revision round**: feed Copilot's review back to the orchestrator, let it
   address what's actually called for, re-run the local gate, push.
6. Wait for **GitHub Actions checks** on the PR to go green.
7. **Squash-merge.** Every issue in the batch closes via the `Closes #N` lines. Each
   issue (and the PR) gets the same scientist-facing closing message, again drafted by
   `gaia-lab-notebook`. If the batch belongs to a milestone, that milestone's `epic`
   tracker issue gets a one-line progress comment — **the epic itself is never closed
   by this script.**

Any failure at any stage (orchestrator errors, gate fails, no Copilot review in time,
revision breaks the gate, checks stay red) stops that batch, leaves the PR/issues open,
and moves on to the next batch. Nothing merges on a guess.

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

Two credentials it does **not** set up for you, on purpose:

- **Git over SSH** — `git clone`/`git push` use the SSH remote, so the box needs a
  private key that can push to this repo (copy an existing key over, or generate a
  fresh deploy key on the box and add its public half under repo → Settings → Deploy
  keys, with write access). This is independent of the `gh` CLI login below.
- **`gh` CLI auth** — every `gh issue list` / `gh pr create` / `gh pr merge` / the
  Copilot-reviewer request in `gaia_run_queue.sh` goes through this, not SSH:
  ```bash
  echo "$GH_TOKEN" | gh auth login --with-token   # needs repo + workflow scopes
  ```
- **`ANTHROPIC_API_KEY`** — put it in the shell profile or a systemd
  `EnvironmentFile`, never in the repo.

Before the first real run, sanity-check both:

```bash
ssh -T git@github.com
git -C "$REPO_DIR" push --dry-run origin main
gh auth status
```

Also verify the Copilot reviewer login once by hand (open any PR in the GitHub UI,
check who "Copilot" resolves to as a requested reviewer) — `gaia_run_queue.sh` hardcodes
`copilot-pull-request-reviewer[bot]` at the top; update it there if your org differs.
And confirm branch protection on `main` actually permits this token to merge — if it
doesn't, the merge step fails loudly, which is the safe outcome, but you won't get the
close-the-loop behavior until it's allowed.

## Running it

One pass over the current queue:

```bash
cd "$REPO_DIR"
export ANTHROPIC_API_KEY=...
scripts/gaia_run_queue.sh
```

Unattended, recurring, single-instance-at-a-time via `flock`:

```cron
*/30 * * * * flock -n /tmp/gaia_run_queue.lock /path/to/scripts/gaia_run_queue.sh >> $HOME/gwl-space-time-smooth/.gaia-runs/cron.log 2>&1
```

Every run logs per-batch to `.gaia-runs/batch-<first-issue-number>-<timestamp>.log` —
that's the first place to look when a batch didn't do what you expected.

## What stays a human decision

- **Epics are never closed** by this pipeline, only commented on — matches the group's
  standing rule that tracking issues wait for your own review, not an automated "done."
- **Anything that doesn't clear the gate** (tests, DOI check, quarto render, Copilot
  review timeout, checks red) is left open with a log, not force-merged or retried
  silently.
- **Copilot review substitutes for your own adversarial pass in this pipeline only** —
  it does not change how interactive PR work with you is handled; that still waits for
  your explicit go-ahead to merge or close.
