# Gaia — Denolle Group Research Agents

*A coordinated family of research specialists for Earth-science work, built on the
Olympus governance pattern but renamed to plain research functions and rebuilt
around the group's three research pillars and the single-project research cycle.*

**Status:** roster v0.5 — **13 agents**. Derived from the Olympus design (a private
postdoc extraction, developed outside this repository) and an Earth-science audit of
it. Round 1 leaned the 16-agent candidate set to 10;
round 2 added the Theoretician/Modeler, Research Software Engineer, and Data Engineer
(→13); round 3 merged the RSE into the Scientific Coder (→12); round 4 added the
**Research Impact** agent (→13). See the review-round notes below.

---

## What carried over from Olympus (the governance skeleton)

The valuable part of Olympus was never its roster — it was its **separation of
powers**, which transfers directly to research:

- **Hub-and-spoke orchestration.** The Orchestrator decomposes a research goal,
  assigns each task to the right specialist, gathers reports, and decides the next
  move. Specialists answer to the hub, not each other.
- **An independent auditor.** The Auditor is read-only and independent; the
  Orchestrator cannot overrule its verdict or proceed past a Critical finding by
  fiat. The maker is never the sole judge of the make.
- **The design-review bounded loop.** A study/experiment plan is audited *once*
  before any resources are spent, Critical/Major findings addressed, an optional
  capped second pass, then it proceeds. A flawed assumption caught at the design
  stage costs one revision; caught after a field season or a 10k-core run, it costs
  the whole effort.
- **Human gates.** Anything consequential, irreversible, or outward-facing —
  manuscript submission, data/code release, a field-deployment commitment, a large
  compute allocation — stops for a human.
- **Model tiering.** Opus for judgment/hard reasoning, Sonnet for building/writing,
  Haiku for fast mechanical work. Match the agent to the *weight* of the task.

---

## Design philosophy

The scientist sets the **Scientific Vision**; the agents *orchestrate, synthesize, and
generate* under it — they scale the scientist's own scrutiny, they don't replace it.
Four commitments shape the design:

- **Built on three Opens.** *Open Data* (accessible, transparent, reproducible
  datasets), *Open Software* (modular, extensible agents for scientific tasks), and
  *Open Knowledge* (scientific literature + numerical methods) feed every agent.
- **Domain-expert personas, designed by the scientist.** Each agent encodes *our*
  group's rigor standards for its slice of the work — not a generic assistant.
- **A human-rigor foundation.** Scientific Rigor & Critical Thinking = human checking
  **plus** agent-based review (the independent Auditor). Nothing consequential ships
  without a human gate.
- **Right model for the weight of the task.** Opus for judgment, Sonnet for building,
  Haiku for mechanical work.

**The three pillars:** (A) laboratory experiments · (B) theoretical development with
numerical implementation · (C) data-driven discovery, processing & assimilation.

**The 8-stage research workflow** each project moves through (and the lead agents):

| # | Stage | Lead agent(s) |
|---|---|---|
| 1 | Literature Review | Literature Scout (+ Auditor for novelty) |
| 2 | Ideation | Theoretician, Study Designer, Auditor |
| 3 | Data Pipeline | Data Engineer (+ Scientific Coder) |
| 4 | Method Development | Theoretician, Study Designer |
| 5 | Implementation | Scientific Coder (+ Debugger & Tester, Run Monitor, Courier) |
| 6 | Results | Scientific Coder, Run Monitor, Debugger & Tester |
| 7 | Interpretation | Auditor, Research Impact, Lab Notebook |
| 8 | Future Work Scoping | Research Impact, Study Designer, Auditor |

Cross-cutting throughout: **Orchestrator** (coordination), **Auditor** (review),
**Lab Notebook** (chronicle), **Provenance Keeper** (versioning + AI-use logging).

---

## Roster — the team (13 agents, v0.5)

Round 1 leaned the 16-agent candidate set to 10; round 2 added the Theoretician,
Research Software Engineer, and Data Engineer (→13); round 3 merged the RSE into the
Scientific Coder (→12); round 4 added the **Research Impact** agent (→13). These are
**flat peer agents**: the Theoretician derives the model → the Scientific Coder
implements *and* engineers it → the Debugger & Tester tests it → the Auditor judges the
rigor → the Research Impact agent scopes the "so what"; the Data Engineer feeds them
clean data throughout.

| Gaia function (file) | Was (Olympus) | Role | Pillars | Stage(s) | Model |
|---|---|---|---|---|---|
| **Orchestrator** (`orchestrator.md`) | Zeus | Decompose the goal, assign specialists, hold the thread, gate to human | all | all | opus |
| **Auditor** (`auditor.md`) | Atlas (+ UQ, V&V, Hypothesis/Novelty) | **Scientific-rigor red-team** — logic, uncertainty/statistics, numerical soundness (V&V), falsifiability & novelty; read-only, names the decisive test | all | all (review) | opus |
| **Literature Scout** (`literature-scout.md`) | Prometheus | Prior-art survey & synthesis; **paired with the Auditor** to ground novelty claims | all | 1,2 | **opus** |
| **Study Designer** (`study-designer.md`) | Athena (+ Experimentalist) | Computational **and** lab/field design: hypotheses, controls, sampling, instruments/calibration, deployment, metadata, permit/safety gate | all | 2,4 | opus |
| **Theoretician / Modeler** (`theoretician.md`) | — | Derive equations & assumptions, nondimensionalize, scaling/dimensional analysis, choose the numerical method, produce analytical/limiting-case solutions (= V&V benchmarks) | B (A,C theory) | 2,4 | opus |
| **Data Engineer** (`data-engineer.md`) | — | Geophysical data ingestion & QC (miniSEED/StationXML/SEG-Y), reproducible data pipelines, assimilation inputs/diagnostics | C | 3,5 | sonnet |
| **Scientific Coder & Software Engineer** (`scientific-coder.md`) | Hephaestus (+ RSE) | Implement the science **and** engineer it well — architecture, packaging, performance/HPC, CI, reproducible environments (behavior-preserving); run the V&V/UQ analyses the Auditor demands | B,C | 4,5,6 | opus |
| **Debugger & Tester** (`debugger.md`) | Theseus (+ Cassandra) | Independent second pair of eyes: testing/QA **and** root-cause debugging — deliberately not the Coder | B,C | 5,6 | opus |
| **Run Monitor** (`run-monitor.md`) | Argus (runtime only) | Watch long HPC/simulation runs: OOM, stall, disk, walltime, prereqs | B,C | 5,6 | opus |
| **Research Impact** (`research-impact.md`) | — | Assess impact honestly across **society, fundamental Earth science** (geodynamics/earth dynamics), **hazard mitigation, resource management**; demonstrated vs. aspirational | all | 7,8 | opus |
| **Lab Notebook** (`lab-notebook.md`) | Calliope | Method/results chronicle + docs; **records in markdown files** | A,B,C | 5–7 (+ throughout) | sonnet |
| **Provenance Keeper** (`provenance-keeper.md`) | Mnemosyne | Version & provenance; **always logs AI use**; configurable identity | B,C | throughout | sonnet |
| **Courier** (`courier.md`) | Hermes | Fast mechanical file ops (cheap tier keeps this off the bigger agents) | all | support | haiku |

**Merged into the Auditor (round 1, kept):** Uncertainty Analyst, Verification &
Validation, and Hypothesis & Novelty Framer → **Auditor** (it owns the rigor critique;
the Coder runs the analyses). Experimentalist → **Study Designer**. Test Engineer →
**Debugger & Tester**.

**Re-added (round 2):** **Data Engineer** (un-merged from the Coder — a real distinct
craft Maleen wanted back), plus two new agents — **Theoretician / Modeler** and
**Research Software Engineer** *(the latter merged back into the Coder in round 3)*.

**Cut / deferred (pre-review):** Daedalus (frontend/design) — revisit only if a
concrete scientific-viz/dashboard need appears. Argus's *security* faculty — out of
scope for typical research compute.

**Design note (the Auditor's read-only line).** The Auditor absorbed roles that
*compute* things (UQ, V&V), but it stays **read-only**: it demands the evidence and
names the decisive test, while the **Scientific Coder** executes. This preserves the
separation of powers — the maker never grades their own homework, the judge never
becomes the maker.

---

## The AI-disclosure policy (flipped from Olympus)

Olympus's record-keeper (Mnemosyne) was hardwired to push under one person's
identity and to **never mention AI**. Gaia inverts this to match the group's
standing policy and the pre-submission reviewer's governance:

> **Always log AI use.** Every record the Provenance Keeper writes — commits,
> method notes, release metadata — discloses that AI assistance was used, honestly
> and traceably. Author identity is **configurable per group member**, never
> hardcoded. We disclose; we do not hide.

This keeps Gaia consistent with `pre-submission-agent` (AI-use disclosure stamp,
Governance rule 4).

---

## Round-1 review — resolved (Maleen, 2026-06-29)

- **Study Designer vs. Experimentalist** → **merged** into Study Designer.
- **Debugger + Test Engineer** → **merged** into one "Debugger & Tester" (the value
  is a second pair of eyes separate from the Coder).
- **Uncertainty Analyst, V&V, Hypothesis & Novelty Framer** → **merged into the
  Auditor** (rigor critique); execution moved to the Scientific Coder.
- **Data Engineer** → merged into the Scientific Coder *(reversed in round 2 — see below)*.
- **Literature Scout** → promoted to **Opus**, **paired with the Auditor** for novelty.
- **Courier** → **kept** (cheaper tier than the Orchestrator doing it directly).
- **Lab Notebook storage** → **markdown files** (decoupled from Obsidian).
- **Cross-suite ownership** → keep Gaia's **Auditor separate** from the
  pre-submission adversarial review; they are distinct owners by decision.

## Round-2 additions (Maleen, 2026-06-29)

Added three **flat peer** build-cluster agents (not nested under a "software lead," not
bundled into the Coder — see the architecture note below):

- **Data Engineer** — un-merged from the Scientific Coder; a distinct data craft.
- **Theoretician / Modeler** — new; owns the derivation/model/method side of Pillar B
  that no agent covered (the original audit flagged this gap).
- **Research Software Engineer** — new; hardens working code into good software
  *(merged back into the Scientific Coder in round 3 — see below)*.

> **Architecture decision — flat peers, not a nested sub-team.** Every Gaia specialist
> is already a subagent of the Orchestrator (hub-and-spoke). The build cluster
> (Theoretician → Coder → Debugger&Tester → Run Monitor, fed by the Data Engineer) is
> kept as flat peers so each stays independently model-tiered and auditable, and the
> Olympus "one hub, peers don't call peers" discipline holds. Revisit a mid-level
> "build lead" sub-orchestrator only if the Orchestrator struggles to juggle the cluster.

## Round-3 change (Maleen, 2026-06-29)

- **Research Software Engineer → merged into the Scientific Coder.** The
  "make it correct" vs. "make it good software" line blurred in practice (it was the
  flagged risk), so one **Scientific Coder & Software Engineer** now owns both —
  implementing the science and hardening it (architecture, performance/HPC, packaging,
  CI, reproducible environments), with behavior-preservation as an internal discipline
  when it optimizes.

## Round-4 addition (2026-06-29)

- **Research Impact** — new agent that scopes the "so what" honestly across four axes:
  **society**, **fundamental Earth science** (geodynamics, earth dynamics), **hazard
  mitigation**, and **resource management** — separating demonstrated impact from
  aspiration. It fills stages 7–8 (Interpretation, Future Work Scoping), which were
  thin, and supplies broader-impacts framing for proposals.

## Merged vs. many smaller agents — where we land

The recurring design tension (we've gone 16→10→13→12→13). Neither extreme wins; the
test is **"would two different people own this in a well-run lab, and do they need to
check each other?"**

**Split into smaller agents when:**
- **Independence is required** — the maker must not be the judge (Coder ↔ Auditor ↔
  Debugger & Tester). This is the rigor foundation; never collapse it.
- **The cognitive frame differs** — deriving (Theoretician) vs. implementing (Coder)
  vs. wrangling data (Data Engineer) are different crafts; one prompt does them blandly.
- **Model tiers differ** — mechanical work belongs on Haiku (Courier), not Opus.
- *Cost:* focused context, cheap tiering, discrete auditable reports, swap one without
  touching others. *Cons:* orchestration overhead, context-loss across handoffs,
  boundary disputes, over-fragmentation (a role too small doesn't earn its keep).

**Merge into a broader agent when:**
- **It's genuinely one person's job** — a scientist who both writes and engineers code
  (Coder + RSE); testing and debugging by one second-pair-of-eyes (Debugger & Tester);
  the rigor critiques under one independent judge (Auditor).
- *Cost:* no handoff friction, one context, simpler mental model, cheaper orchestration.
  *Cons:* diluted focus, lost independence, can't tier per sub-task, one opaque step,
  a regression in one faculty risks the others.

**Gaia's rule:** keep the **separation of powers** splits (design/build/judge) no
matter what; merge only *within* a side when the work is one craft and splitting adds
only handoffs.
