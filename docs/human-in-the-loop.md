# The human in the loop, when the decision matters

*A technical account of where a person enters this pipeline, why exactly there, what the
machine owes them when it calls, and what it is forbidden from calling them about.*

Companion to [`gaia-automation.md`](gaia-automation.md), which describes the pipeline
itself. This document is about one property of it: the placement of the human.

---

## 1. The problem, stated precisely

Ground rule 2 of the Gaia charter says:

> **Human gates.** Stop for a human on anything consequential, irreversible, or
> outward-facing. Orchestrate up to that line and stop.

That is the right rule and it is unimplementable as written, because *consequential* is
exactly the judgment we are trying to automate. Every autonomous research pipeline
degenerates toward one of two failures, and both of them are failures of this rule's
mechanisation, not of its intent:

**Failure A — the pager.** The gate fires on every deep review. A human is interrupted
per contested plan, arrives with no context, re-derives a distinction the reviewers had
already made implicitly, and learns within a week that the escalations are mostly noise.
The rational response to a noisy pager is to stop reading it, at which point the gate has
negative value: it costs interruptions *and* it no longer stops anything, because it is
being rubber-stamped.

**Failure B — the rubber stamp.** The gate fires on nothing, or on something a determined
agent can talk its way past. Work proceeds; a sign error in a unit convention propagates
into six downstream issues; the cost surfaces a month later as rework of everything built
on top.

The two failures are not symmetric, and their asymmetry is the whole design. A false page
costs one context switch — minutes to hours, plus the corrosion of trust. A missed
`breaking` finding costs the rework of every artifact built on the wrong interface, and
it is discovered late, by someone who did not make the error. So the gate must be
**cheap to be wrong toward stopping** and **expensive to be wrong toward proceeding**,
while still keeping the total page rate low enough that a human reads every page.

That trilemma is what the rest of this document resolves. The resolution has one central
move, and it is worth stating before the machinery:

> **Severity is a property of the finding. Scope is a property of the consequence.
> Only consequence justifies an interruption.**

---

## 2. What actually happened: issue #186

The design below is not hypothetical. It is the direct product of the science gate's first
completed run, and every mechanism can be traced to something that run got wrong.

On 2026-08-20 the gate ran end to end on issue #186 (*"P0: Back-transform Stage-3 kriging
predictive variance before combining uncertainty"*). A read-only `gaia-study-designer`
session pre-registered a plan; three read-only personas reviewed it before a line of code
was written. The artifacts are on disk in `.gaia-runs/plan-186-20260820T213824Z/` — gitignored, so
they live on the machine that ran it, not in the repository.

| | |
|---|---|
| Personas | `gaia-auditor`, `twin-hydrogeologist`, `twin-geostatistician` |
| Verdicts | `revise`, `revise`, `revise` — **nobody voted `block`** |
| Concerns | **41** total: 12 `critical`, 19 `major`, 10 `minor` |
| Per persona | auditor 4/8/2 · hydrogeologist 2/3/2 · geostatistician 6/8/6 |
| Aggregate decision | **`block`** — the batch stopped |
| Planning session | $2.44, 630 s, 2 turns (`.gaia-runs/records.jsonl`) |

The aggregation rule at the time was *"any `block` vote, or any `critical` concern"*. No
one voted block. Twelve criticals were enough. The batch stopped, and a human was called
mid-run.

**The panel was right and the decision was useless.** Reading the concerns afterwards,
they are not interchangeable:

- `twin-hydrogeologist`: `interpolate_residuals.py` adds a water-table **elevation**
  anomaly to a **depth** baseline, violating the project's own invariant
  `ΔD = −Δh_wt` — the product's seasonal signal is sign-inverted. That is not a
  refinement. Everything downstream that reads seasonal high water table is wrong.
- `twin-geostatistician`: `QuantileTransformer` clips normal scores at ±5.199, so at
  `MIN_SITES_PER_MONTH=30` two of thirty points carry `z² = 27` and `Var(z) ≈ 2.7`
  instead of 1 — every variogram pair involving them inflated ~50×. Also not a
  refinement.
- `twin-geostatistician`: two producers **outside** the declared 13-file scope
  (`interpolate_baseline.py`, `interpolate_anomalies.py`) already write the same artifact
  names, so after the fix one filename can hold either NST-space or metre-space sigma.
  An interface question — it reaches other issues.
- `twin-geostatistician`: Clopper–Pearson assumes independent Bernoulli trials, but
  withheld wells are spatially correlated at the variogram range, so the coverage
  interval is too narrow and the n=316 power threshold is optimistic. **Real science,
  entirely inside this milestone's own deliverable.**
- `gaia-auditor`: `σ_response = sqrt(1−R²)·5.0` has no hydrogeologic provenance and is
  inverted with respect to domain. Real, and again inside the milestone.

The first three are decisions someone has to make before the work proceeds. The last two
are work items. The gate could not tell them apart, so it escalated all of them, and
called a human to perform a triage the reviewers had already performed implicitly — they
simply had nowhere to write it down.

**The lever is not to ask the panel to find less.** Review depth is the asset. The
geostatistician's observation that kriging weights are invariant to a variogram scale
factor (so `ẑ` must *not* be rescaled, only `σ_z²`) is a bug that would otherwise have
shipped, and it was raised as `minor`. What was miscalibrated is not the finding rate.
It is what a finding *triggers*.

> **Caveat, stated because it matters for how much weight this evidence carries:** the
> `scope` field did not exist when #186 ran. The verdicts on disk carry
> `severity`, `claim` and `decisive_test` only. The re-classification above is a reading
> of those concerns, not a measurement of the new field in action. The design claim —
> that reviewers can and will declare scope reliably — is at this writing **unmeasured on
> a real run**. See §11.

---

## 3. The taxonomy of handoffs

Every point at which this pipeline can hand control to a person, classified by *why*.
The last column is the one most such tables omit and the one that matters most: **what
happens if the human never arrives.**

### Class A — reserved by policy (never automated, regardless of evidence)

These do not depend on a model's judgment at all. They are consequential, irreversible or
outward-facing by their nature, which is ground rule 2 applied directly.

| Decision | Mechanism | Default with no human |
|---|---|---|
| Closing an epic / tracking issue | Pipeline comments, never closes | Stays open indefinitely — correct |
| Which of two colliding designs the project adopts | Arbitration verdict posted as **advisory** on both PRs; blocked side held | Both PRs stay open, labelled `needs-human-decision` |
| Fate of a parked branch (resume / rewrite / drop) | `gaia/parked/*`, nothing prunes | Branch persists; nothing is lost |
| Manuscript submission, data/code release, field commitment, large allocation | Out of pipeline scope entirely | Never happens autonomously |

The collision case deserves emphasis, because it looks more authoritative than it is. A
verdict of `A` means *"land A first"*. It does **not** mean *"the project has chosen
design A"*. The pair is whatever two branches happened to touch the same files, usually
resolving *different* issues; it is not an A/B bake-off. The mechanism exists to make a
collision visible and stop a silent double-merge — not to settle architecture.

### Class B — escalations on evidence (the machine decided this needs a person)

| Trigger | Where | What the human decides | Default with no human |
|---|---|---|---|
| `critical` concern scoped `breaking` or `wrong-physics` | `gaia_panel.py::aggregate` | Whether the objection stands, and what the plan becomes | Issue parked, labelled, batch continues |
| **Stalemate** — a round that resolved and withdrew *nothing* while still blocking | `gaia_panel.py::aggregate` | Whether the panel or the plan is wrong | Parked; no further planning spend |
| Second block after the revisit pass | `gaia_run_queue.sh` | A real disagreement, with siblings' landed work as context | Parked |
| Three strikes on an identical failure signature | `gaia_failsig.py` | Whether the approach is viable at all | Run stops iterating |
| Auditor blocks a PR, or returns an unparseable verdict | `gaia_run_queue.sh` | Merge or not | PR left **open**, never force-merged |
| Gate-integrity violation (test skipped, tolerance raised, gate definition altered) | `gaia_gate_integrity.py` | Whether the weakening is legitimate | Blocked |
| Persona dispatch missing from the transcript | `gaia_panel.py --expect-for` | — (fails closed to `block`) | Blocked |
| Plan invalid, or planning timed out | `gaia_plan.py --from-stream` | Whether to re-plan | Gate exit recorded by cause |
| Checks red, DOI check fails, quarto render fails, Copilot review times out | `gaia_run_queue.sh` | — | PR left open with a log |

Every Class-B path shares one property: **it leaves the work recoverable and the record
complete.** Nothing is force-merged, retried silently, or discarded. A parked branch is
pushed before it is renamed, so the work survives loss of the machine.

### How a Class-B escalation actually reaches a person

Classifying an escalation is not delivering one. Until 2026-08-22 every path above ended at
a label and a line in a console log on whichever box the queue ran on — which means the
escalation path was *"someone remembers to look"*, and that is not an escalation path.

The delivery is now mechanical, and it has exactly two tempos:

| | Immediate — once per park | Periodic — the sitting |
|---|---|---|
| **What** | A decision packet posted on the issue, and the issue **assigned** | The queue page, one rolling digest issue, an email if the queue is not empty |
| **How you hear** | GitHub's own assignment notification. It already knows how to reach a person | You choose when. Editing the digest body does not notify; the weekly email is the only outbound |
| **How often** | Once per park, counted rather than guessed: the workflow compares park stamps against packets, so a **re-park** pages again and a **re-label** does not | Weekly, Monday morning |
| **Why not more** | Re-notifying about a decision you have already seen is exactly how a gate becomes a pager | Parked issues are decisions to make; the digest is what makes them a sitting rather than a stream |

What makes this work in CI, which never sees the box's `.gaia-runs/`, is the **park stamp**:
`gaia_run_queue.sh` writes `<!-- gaia-park:{…} -->` into its park comment, naming the commit
the plan was judged against, the files the plan said it would touch, and the blocking concerns
with their decisive tests. GitHub hands it back verbatim, the workflow has the repository
checked out, and `git` answers the rest — so the staleness on the page is the same measurement
the run made locally, computed from the same stamp.

`.github/workflows/gaia-human-gate.yml` · `scripts/gaia-launch/gaia_human_queue.py` ·
25 tests in `scripts/gaia-launch/tests/test_human_queue.py`.

**What no mechanism here can do is make a person read.** Delivery is guaranteed; the decision
is not. What the digest adds is that the not-reading is visible — a decision waiting more than
a week is marked overdue, and a parked plan whose files have been rewritten underneath it is
marked stale, which is the point at which the honest advice is to re-plan rather than resume.

### Class C — explicitly *not* a page

This class is the design's actual contribution, and it is defined by exclusion: findings
that are real, correct, worth acting on, and nevertheless must not interrupt anyone.

| What | Where it goes instead |
|---|---|
| `critical` or `major` scoped `in-milestone` | Posted on the issue · recorded in `panel.json` · **carried into the implementation prompt as a must-address item** · appended to the standing ledger |
| Any `minor` concern | Ledger and issue record |
| Net loss of tests or assertions in a diff | Reported as a **warning**, never a block — a genuine refactor produces it too |
| A wrong grouping in the standing-concern digest | Costs a glance, not a decision — nothing gates on it |

**Deferred is not discarded, and the panel prompt says so.** This is not politeness; it
is incentive design. A reviewer who believes a finding will be dropped learns to inflate
its scope until it is heard, and scope inflation is the one failure mode that would
collapse this whole scheme back into Failure A.

---

## 4. The decision flow

```mermaid
flowchart TD
    P[Pre-registered plan<br/>read-only session, schema-validated] --> V{Valid?}
    V -- no --> X1[Gate exit: plan-invalid / plan-timeout<br/>recorded by cause]
    V -- yes --> R1[Round 1: routed panel<br/>auditor + up to 2 project personas<br/>all read-only by tool grant]
    R1 --> D1{Any critical concern<br/>scoped breaking<br/>or wrong-physics?<br/>Any block vote?}
    D1 -- no --> IMPL[Implement<br/>deferred concerns carried in<br/>as must-address items]
    D1 -- yes --> REV[Re-plan<br/>fed ONLY the blocking concerns]
    REV --> R2[Round 2: ADJUDICATION<br/>each persona handed its OWN prior verdict<br/>+ the diff of what changed]
    R2 --> MOVE{Did a ruling land on a concern<br/>that BLOCKED last round?}
    MOVE -- "no — hollow, or nothing" --> STALE[STALEMATE<br/>→ human]
    MOVE -- "yes, still blocking" --> PARK[Park this issue<br/>→ human, at end of run]
    MOVE -- "no longer blocking" --> IMPL
    PARK --> REVISIT[Revisit pass after siblings land<br/>same standing objections, new context]
    REVISIT --> D2{Blocks again?}
    D2 -- yes --> HUMAN[Real disagreement → human]
    D2 -- no --> IMPL
    IMPL --> LEDGER[(Standing ledger<br/>science-concerns.jsonl)]
    STALE --> STAMP[Park stamp on the issue<br/>commit + the plan's files]
    PARK --> STAMP
    HUMAN --> STAMP
    STAMP --> LABEL([needs-human-decision])
    LABEL --> GATE[Human gate workflow<br/>decision packet + assignment]
    GATE --> SIT[One review sitting<br/>queue page · rolling digest · weekly email]
    LEDGER --> SIT
```

The stamp is written **before** the label, and that ordering is the mechanism: the label is
what triggers the workflow, so a workflow that fired first would find nothing to escalate.

---

## 5. Scope: the field that makes the gate a gate

Every concern declares a **scope** alongside its severity.

| Scope | Meaning | Blocks? |
|---|---|---|
| `breaking` | Fixes an interface, artifact name, unit convention or assumption that **other** issues will build on. Wrong here forces rework elsewhere later | yes, at `critical` |
| `wrong-physics` | The result would be physically or mathematically **incorrect as stated** — not merely under-validated or short of the ideal method | yes, at `critical` |
| `in-milestone` | Real, but its correction lives inside this issue's deliverable or a follow-up that can be filed and scheduled | no |

Configured by `GAIA_PANEL_BLOCK_ON` (default `breaking,wrong-physics`). Three properties
of that configuration are deliberate:

1. **An unrecognised value falls back to the default**, rather than opening the gate.
2. **There is no way to block on nothing.** Running without a science gate is
   `GAIA_SCIENCE_GATE=0`, which is printed in the run banner. Disabling review is
   allowed; disabling review *while appearing to review* is not.
3. **An undeclared or unrecognised scope blocks.** A persona whose prompt has not been
   updated behaves exactly like the old gate rather than slipping past it.

Symmetry matters on the way back, too: only the **blocking** concerns are fed to the
re-plan. Handing a planner all forty-one is not a redirection — it is scope creep with a
review as its excuse.

`scripts/gaia-launch/tests/test_panel_scope.py` pins the rule in both directions,
including every fail-closed path.

---

## 6. Convergence as a number, not an impression

The question *"should a human be called yet?"* is usually answered by a round counter —
try twice, then escalate. A counter is a poor instrument: two productive rounds and two
rounds of noise look identical to it.

The revision loop could not converge at all, for a structural reason. Every panel call is
a fresh `claude -p` session with no memory of the last one, **and every round overwrote
the previous round's verdicts on disk**, so there was nothing to remember it with. A
persona reviewing a revised plan re-derived from whatever was in front of it: free to
resolve nothing, drop what it said last time, and object to something else instead.
Rounds differed without getting closer, and the revision budget bought noise.

So each round writes into its own `r<N>/` directory, and from round 2 each persona is
handed **its own previous verdict** — not the panel's; another persona's concerns are not
its to resolve or inherit — together with the **unified diff of what the planner
changed**. It must rule on each prior concern before raising anything new:

| Status | Meaning |
|---|---|
| `resolved` | The revision answers it |
| `unresolved` | It still stands — and the claim says what is *still* wrong, not what was |
| `withdrawn` | The reviewer no longer believes it |

`withdrawn` is load-bearing and was added on purpose. **A panel that can never back down
converges by attrition, which is not convergence.** Without it, the only way a
disagreement ends is the planner capitulating, and the escalation signal degrades into a
measure of planner stamina.

New concerns are admissible only if the *changes* introduced them, or if they are a
critical breaking / wrong-physics problem genuinely missed. Hunting for fresh objections
in parts of the plan that did not change costs another full planning cycle and settles
nothing.

That turns the escalation trigger into arithmetic:

```python
moved     = adjudicated["resolved"] + adjudicated["withdrawn"]
stalemate = bool(priors) and moved == 0 and decision == "block"
```

A round that moves nothing while still blocking is a **stalemate**: the plan and the
panel are talking past each other, and the next round is the same conversation at the
same price. The queue stops there and hands over — the same reasoning as three-strikes on
identical failure signatures. **An unrecognised status counts as `unresolved`**, so
malformed output cannot claim a concern was answered.

### 6a. Movement has to move what was blocking

The arithmetic above has a hole, and it is one line wide. `moved` counts *any* ruling as
progress, so a persona that will not drop its blocking concern can withdraw a minor one it
never cared about: `moved` becomes 1, the stalemate rule goes quiet, and the queue buys
another planning round that settles nothing. Nothing noticed, because nothing checked
*which* concern moved.

So each ruling is now matched back to **the previous round's blocking concerns** — by
referent, the same rule the panel's own convergence and the standing ledger use — and only
a ruling on one of *those* counts as movement:

```python
stalemate = decision == "block" and moved_blocking == 0     # when the previous round is on disk
```

Rulings that match nothing that blocked are reported as `hollow`. That is deliberately not
an accusation: withdrawing a deferred concern is legitimate, and a reviewer may do it for
good reasons. It is the difference between *"we are converging"* and *"we are moving the
deck chairs"*, said out loud in the panel summary and in the chair's brief, where a person
can weigh it.

Two properties hold this in place. A persona that blocked nothing last round **cannot
unblock anything this round** — its rulings are real work and are counted, they are just
not what stands between this issue and implementation. And the grading needs the previous
round's `panel.json`: without it (round 1, or a missing file) the old count-everything rule
stands, so **an absent file can never be what opens the gate**, and never what closes one
either.

This makes the pipeline *more* likely to call a human, not less, and that is the intent.
The escalations it adds are the ones that were previously papered over by a withdrawal
nobody read.

The revisit pass inherits this. An issue parked in pass 1 and re-planned after its
siblings landed points at the last completed round of that first pass, so it answers the
same standing objections rather than meeting a new panel. **A fresh panel has nothing to
converge on** — which is also why "just ask again with a different reviewer" is not a
convergence strategy.

---

## 7. What the machine owes the human at the handoff

An escalation is a request for a **decision**, not a request for an investigation. If the
person has to reconstruct the situation before they can rule on it, the interruption cost
is the reconstruction, and it is many times the reading cost. So every page arrives with
a complete packet:

1. **The pre-registered plan** — obstruction, ordered testable questions, approach,
   artifacts, declared budget in files/lines/runtime, stopping conditions, what would
   count as a reproducible negative result, what is explicitly out of scope. Written
   *before* the code existed, so it is a statement of intent, not a rationalisation of a
   diff.
2. **Every verdict, verbatim, on the issue** — posted at the moment it could still have
   changed the approach.
3. **A decisive test per concern.** This is a hard requirement of the panel contract:
   *a concern with no test that would settle it is an opinion, and opinions do not block
   work.* The practical consequence for the human is large — the page does not say "the
   NST looks wrong", it says *fit `QuantileTransformer` on n ∈ {30,100,500,800} iid
   N(0,1) draws and print `z.var()`; compare recovered sill/range/nugget against
   van-der-Waerden scores.* The person is handed the experiment that ends the argument.
4. **The chair's summary** (§8).
5. **The diff**, for round 2+.
6. **The parked branch**, pushed before renaming, plus `needs-human-decision` on the
   issue.
7. **The transcript** (`.gaia-runs/issue-<n>-<ts>.raw.jsonl`), which is the only record
   that survives a working tree being reset.

---

## 8. The chair: a reporter, not a judge

Individual verdicts are what the gate acts on. They are not what a scientist reads. Three
reviewers filing forty-one separately-scoped concerns is a database, and the questions a
person actually arrives with — *do they agree? where do they conflict? what has to happen
next?* — are answerable only by reading all of it and holding it in your head.

So the panel also summarises, and the division of labour inside that summary is the
integrity property:

**Mechanical — computed, and cannot be fabricated.**
`convergence()` reports where *different* reviewers landed on the same thing. Two
personas from different disciplines independently naming the same file, symbol or method
is the strongest signal a panel produces: corroboration no single reviewer can
manufacture. It is keyed on **referents**, not wording, and rarity-weighted — sharing
`interpolate_residuals.py` when six concerns mention it is not agreement, it is working
in the same area. Reported naively that produced nineteen "agreements" on a panel that
had perhaps four. The critical-issue list is taken straight from the aggregate the gate
itself used, so the summary cannot describe a decision other than the one made.

**Judged — written by a chair.**
What the disagreements actually *are*, and what the panel proposes doing about them. No
mechanical rule reads scientific conflict out of prose.

The chair is dispatched as the **lab-notebook** persona — the documenter — precisely
because it has no scientific stake to add. It is called **after** `decision`,
`blocking_concerns` and `stalemate` are already fixed, and it cannot change them.

Which gives the fail-closed rule its one principled exception:

> **Fail closed on anything that gates. Fail soft on anything that only describes.**

A missing persona dispatch, an undeclared scope, an unparseable auditor verdict, an
unrecognised prior status — all block. A synthesis that fails to parse costs the prose
sections and nothing else. It *must* fail soft: it is a report about a decision that has
already been made, and failing it closed would let a formatting error stop science.

---

## 9. Verifying that the reviewer was real

A human's willingness to act on an escalation depends on the reviewer's identity being a
fact rather than a claim. "Use the gaia-auditor agent" is prose. Whether the session
actually *delegated* — and therefore whether that persona's system prompt, tool grant and
model tier were ever loaded — is a fact recorded in the transcript as a `Task` dispatch
carrying a `subagent_type`.

Real queue runs do dispatch (issue #154's run dispatched seven), but the count varies,
and **a verdict from a session that never dispatched is the base model in costume**: the
persona's name, none of its charter. So each panel call runs with
`--output-format stream-json` and the transcript is checked for the expected
`subagent_type`. A missing dispatch fails closed to a block. Project personas resolve as
a bare name and plugin personas as `gaia:<name>`; `gaia_panel.py --expect-for` owns that
mapping so it lives in one place.

Preflight refuses to start if the gaia plugin is not installed, or if any project persona
file is missing. Both failures degrade the judges silently while still returning
confident verdicts — which is worse than a batch that refuses to begin.

The reviewers themselves are **specific to this twin** (`.claude/agents/twin-*.md`),
derived from this repository's own review record and carrying its ranked concerns as
priors. A generic reviewer does not know that an 18.5 m baseline RMSE cannot serve a
sub-metre liquefaction requirement, or that `ΔD = −Δh_wt` makes two prior entries an
error. Routing is by the issue's own labels and milestone, capped at three to bound cost,
and **the auditor sits on every panel** — ground rule 1, the maker is never the sole
judge.

---

## 10. The concerns that don't stop work, and are then forgotten

This is the expensive failure, and it is the mirror image of the pager problem.

A deferred concern used to be posted on its issue, handed to the implementer, and then
gone at the end of the run. The panel's real science evaporated every time, and the next
issue over the same ground rediscovered it from scratch — at full price, with a fresh
panel, arriving at the same conclusion.

So deferred concerns accumulate in `.gaia-runs/science-concerns.jsonl`, and are read
**holistically**. `gaia_concerns.py --render` groups them by the code, symbols and named
methods they point at rather than by wording, because reviewers from different
disciplines describe one problem in completely different words. On the real #186 panel
that turns **31 objections into seven groups** — the largest being six concerns from two
personas that are all one problem: the out-of-fold coverage validation is broken
(overlapping CV folds, a Clopper–Pearson interval that assumes independence, and a
quadrature that assumes independent error terms).

Two implementation notes carry the epistemics:

- **Prose similarity was tried first and rejected on measurement.** The best true pair
  (two personas independently on Clopper–Pearson) scored *below* a false one, and
  boilerplate like "stopping condition" manufactured matches between unrelated concerns.
  Two concerns are related when they are about the same thing, not when they use the same
  words.
- **The weight is `1/(df−1)` per shared referent, not textbook IDF**, so a pair's score
  does not drift as unrelated issues are added later. A record whose grouping changes
  because the ledger grew is not one anyone can trust.

It is a reading aid: nothing gates on it, and each group states what its members have in
common, so a wrong grouping costs a glance rather than a decision.

One thing does read it automatically, and only one: **the chair**. Before it writes the
panel summary it is handed the standing concerns from *earlier* issues that share a
referent with what this panel just filed — so it can say "this panel is rediscovering an
open project-level problem" instead of "the panel raised X". The reviewers are
deliberately *not* shown it: handing a persona the project's standing objections before it
reviews tells it what to say, and an independently rediscovered concern is evidence in a
way a prompted one is not. The chair reports; the panel judges.

The digest prints **once, at the end of a run**, next to the parked list and explicitly
separate from it. That separation is the thesis of this document in one line:

> **Parked issues are decisions to make now. Standing concerns are a document to read in
> one sitting.**

---

## 11. Batching: one sitting, not one interruption per plan

A science-gate block used to set `batch_failed` and `break`, so one contested plan
discarded its siblings' work and stopped the run. Issues share a batch because they share
a **milestone**, not because they depend on each other — so that multiplied one
disagreement into an idle run and a human called mid-batch.

Now a block parks one issue and the batch carries on. Two consequences follow, both about
what the human can trust when they finally look:

- **Closure is driven by what landed, not by the batch.** `Closes #N` lines are rebuilt
  from the issues that actually committed, on every landing, and any closing keyword the
  lab-notebook writes for a parked issue is stripped from the PR body before merge. An
  issue we cannot prove was resolved stays open.
- **Parked issues get one revisit pass** at the end of the batch, with everything their
  siblings just landed as context (`GAIA_REVISIT_PARKED=1`). This is not a retry of the
  same prompt: the code and the record have changed since the panel blocked, and on the
  first pass that context did not exist *at any price*. A second block is a real
  disagreement and belongs with a human.

Every park is collected into `.gaia-runs/parked-<run>.md` and printed once, at the end of
the run — together with a **staleness report over every issue still parked, including
those parked by earlier runs**. Parking is cheap on the day and gets expensive quietly:
the plan stays exactly as readable as it was while the tree it describes moves on, and at
some point resuming costs more than re-planning. So each park stamps the commit it was
judged against and the files its plan named, and later runs measure the distance from
there — commits since, commits rewriting *those* files, days waiting. A hundred commits
elsewhere do not make a parked plan wrong; three commits rewriting the two files it names
probably do.

And a quieter fix that exists purely to make this loop measurable: a batch that died at
the gate used to record **nothing**, because `write_measurement` is only reached at commit
time. The corpus meant to answer *"does reviewing plans change outcomes?"* could not see
the runs where the gate acted. Gate exits now write a record keyed by cause —
`plan-timeout`, `plan-invalid`, `panel-block`, `panel-stalemate`.

---

## 12. What this does not solve

Stated plainly, because a document about honest escalation that oversells its own
mechanism would be self-refuting.

1. **Round 2 has never run on real data.** The adjudication protocol, the `moved` count
   and the stalemate rule are pinned by 155 tests in
   `scripts/gaia-launch/tests/`, and are untested against a live panel. #186 blocked in
   round 1 under the old rule. The convergence numbers in §6 are a design, not a result.
   Everything §6a adds is pinned the same way and is waiting on the same run.
2. **Scope is self-declared. It is now measured, which is not the same as validated.**
   Deferred concerns are published, recorded and carried into the implementation prompt
   precisely so that scope is not the only route to being heard. Whether that holds is an
   empirical question, so every panel appends its split to `.gaia-runs/panel-scope.jsonl`
   and `gaia_panel.py --scope-report` reads them as a series. The report refuses to call a
   direction from fewer than six panels, and at this writing there are not six panels. A
   baseline exists; a trend does not.
3. **A hollow `withdrawn` is now detected, by a heuristic.** Rulings are matched back to
   the previous round's blocking concerns by shared referent (§6a), so a throwaway
   withdrawal no longer manufactures movement. The match is the same `1/(df−1)` rule used
   everywhere else and it can miss: a reviewer who resolves a blocking concern while
   naming nothing the original claim named will be read as having moved nothing, and the
   issue goes to a human. That is the safe direction of failure, and it is still a cost.
4. **Nothing enforces the sitting — delivery is not reading.** An escalation is now
   assigned, packeted, listed on a page and emailed weekly (§3), and none of that makes a
   person rule on it. What changed is that the not-reading is visible: overdue in the
   digest, stale on the page. The chair also reads the standing ledger now (§10), which
   narrows the failure to the pile nobody opens. No mechanism here removes it.
5. **Parked work ages, and the bound is a heuristic.** Every park now stamps the commit
   its plan was written against and the files the plan named, and
   `gaia_parked.py --status` reports commits-since, commits-touching-those-files, and days
   waiting, as fresh / aging / stale. The thresholds (21 days, 3 commits in the plan's own
   files) are judgement calls stated out loud rather than derived from anything, and
   nothing acts on the verdict — it recommends re-planning, and a person decides.
6. **The counterfactual is unmeasured.** The corpus of gate-exit records now exists, and
   at this writing contains **one row**. Whether reviewing plans changes outcomes is an
   open empirical question in this project, not a settled one.
7. **A model's `critical` is not calibrated against a human's.** Twelve criticals on one
   issue's plan is prima facie evidence of that. Scope routes around the miscalibration
   rather than fixing it.

---

## 13. The principles, distilled

Portable to any pipeline with autonomous reviewers and a scarce human.

1. **Separate how-wrong from how-far.** Severity belongs to the finding; scope belongs to
   the consequence. Escalate on scope. Record severity.
2. **Only consequence justifies an interruption.** A correct, important finding whose
   correction fits inside the current deliverable is work, not a decision.
3. **Deferred must not mean discarded — and the reviewer must be told so.** Otherwise the
   reviewer inflates scope, and the gate reverts to a pager.
4. **Demand a decisive test.** A concern with no test that would settle it is an opinion.
   Opinions do not block work, and the test is what turns a page into a decision.
5. **Make convergence a number.** Escalate when the loop demonstrably stops moving, not
   after N rounds by fiat. Give reviewers a way to back down, or convergence becomes
   attrition.
6. **Fail closed on anything that gates; fail soft on anything that only describes.**
7. **Verify the reviewer's identity, don't assume it.** A judge that was never loaded is
   the base model in costume.
8. **Never let one contested decision discard unrelated work**, and never close what you
   cannot prove was resolved.
9. **Batch by decision-urgency.** One review sitting beats one interruption per finding,
   and things needing a decision *now* must be printed separately from things needing to
   be read.
10. **Instrument every exit path**, including the ones where the gate acted — otherwise
    the pipeline cannot tell you whether any of this works.
11. **Classifying an escalation is not delivering one.** A taxonomy that ends at a label
    and a console line has an escalation path of "someone remembers to look". Deliver on
    the channel the person already watches, once per event — and make the periodic
    reminder a document they choose to open, not a notification.
12. **Count what moved, not how much moved.** Any convergence metric that treats all
    progress as equal can be satisfied by the cheapest possible concession, and will be.
13. **Where a field creates an incentive, log the field.** Scope decides what stops work,
    so scope is a thing reviewers can learn to inflate. That is not detectable in any one
    review — only as a series — and a measurement that feeds a gate stops measuring.

---

*Cross-references:*
[`gaia-automation.md` §The science gate](gaia-automation.md) ·
[`gaia_panel.py`](../scripts/gaia-launch/gaia_panel.py) ·
[`gaia_concerns.py`](../scripts/gaia-launch/gaia_concerns.py) ·
[`gaia_run_queue.sh`](../scripts/gaia_run_queue.sh) ·
[`postmortem/2026-08-18-gaia-run.md`](postmortem/2026-08-18-gaia-run.md)
