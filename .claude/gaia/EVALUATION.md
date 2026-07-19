# Gaia vs. Olympus, and how to evaluate the agents

*Private working note (inside the gitignored `research/gaia/`). Part 1 compares the
Gaia research framework with the Olympus (Opus-as-Fable) system it derives from. Part
2 gives directions for building a golden evaluation dataset. Date: 2026-06-29.*

---

# Part 1 — Gaia vs. Olympus / Fable

Gaia is a **domain re-specialization** of Olympus, not a fresh design. The valuable
inheritance is the **governance pattern** (separation of powers); almost everything
else was rebuilt for research.

## What Gaia kept (shared DNA)

- **Hub-and-spoke orchestration** — one coordinator (Zeus → Orchestrator), peers don't
  call peers.
- **An independent, read-only auditor** — Atlas → Auditor; the maker is never the sole
  judge; the orchestrator can't ship past a Critical finding by fiat. *(The crown jewel
  in both.)*
- **Design-review bounded loop** — audit the plan once before building/spending, fix
  Critical/Major, capped second pass. (Athena↔Atlas → Study Designer↔Auditor.)
- **Model tiering** — Opus / Sonnet / Haiku by the weight of the task.
- **Human gates** on anything consequential, irreversible, or outward-facing.
- **Honest-by-construction reporting** — capture failures, name uncertainty, no
  manufactured confidence.

## What Gaia changed

| Dimension | Olympus (Opus-as-Fable) | Gaia |
|---|---|---|
| **Purpose** | General agentic delivery: coding, websites, security, note-taking, supervising | One **research project** lifecycle in Earth science |
| **Optimizes for** | Autonomous build-and-ship | **Scientific rigor + openness**; scale (not replace) the scientist's scrutiny |
| **Roster basis** | Software-delivery roles | Research-cycle roles (3 pillars × 8 stages) |
| **Naming** | Greek pantheon (Zeus, Atlas, Hephaestus…) | Plain research functions under the **Gaia** brand |
| **AI attribution** | **Hide it** — Mnemosyne pushes as one person, "never mention Claude" | **Disclose it** — Provenance Keeper *always* logs AI use, configurable identity *(values inversion — the single biggest divergence)* |
| **Auditor scope** | General logic/method review | Expanded to own **UQ/statistics, numerical V&V, falsifiability/novelty** |
| **Storage** | Assumes an Obsidian vault | Plain **markdown files**, tool-agnostic |
| **Domain grounding** | Generic SWE | Geophysics formats, HPC, numerical methods, hazard/resource impact |
| **Added** | — | Theoretician/Modeler, Data Engineer, Research Impact; UQ/V&V/Novelty (into Auditor); Experimentalist (into Study Designer) |
| **Dropped** | — | Frontend (Daedalus), security (Argus faculty), git-as-single-identity |
| **Explicit workflow** | None stated | The **8-stage** research workflow (Lit → … → Future Work) |

## Verdict

Same **skeleton**, different **body and ethics**. Olympus is built to *deliver
autonomously and quietly*; Gaia is built to *reason rigorously and transparently*. The
disclosure flip and the rigor-owning Auditor are the philosophical heart of the
difference — Gaia treats the agents as instruments of the scientific method under human
judgment, where Olympus treats them as an autonomous workforce.

---

# Part 2 — Evaluating the agents: a golden-dataset design

## The core challenge

Research outputs are open-ended and "correct" is rarely binary, so you cannot evaluate
these agents by eyeballing transcripts. You need **ground truth**. Four ways to
manufacture it, in rough order of cost and value:

1. **Planted-defect items** *(cheapest, highest leverage).* Take a realistic artifact
   and inject *known* flaws — a units error, an unconverged solver, a missing control,
   a hallucination-bait novelty claim, a data gap. Ground truth = the planted set.
2. **Reference-solution items.** Tasks with a known analytical / benchmark / published
   answer (manufactured solutions, standard PDE benchmarks, a past result). Ground
   truth = the reference; metric = error against it.
3. **Expert-labeled real cases** *(most valuable, group-specific).* Your **own past
   papers, code, data, and reviewer reports** — where you already know what was wrong,
   what reviewers caught, and what turned out (ir)reproducible. The PI/postdoc labels
   the "correct" findings.
4. **Clean controls** *(essential, often skipped).* Artifacts with **no** defect, to
   measure the **false-positive rate**. An agent that flags everything is worthless;
   the Auditor must say "sound" when it's sound.

> **Your unfair advantage:** the group's archive is a ready-made labeled corpus. A past
> manuscript + its referee comments = an artifact with labeled flaws. Past code + its
> known reproducibility outcome = a labeled V&V case. Mine it before synthesizing data.

## Golden-item schema

```yaml
id: AUD-014
agent: auditor                 # which agent(s) this tests
stage: 6                        # workflow stage 1–8
pillar: B                       # A / B / C
artifact: path/to/artifact      # the input (text, code, data, plan, result)
task: "Review this Results section for soundness."
ground_truth:
  planted_flaws:                # for critique agents
    - {id: f1, type: units, location: "eq. 4", severity: critical,
       decisive_test: "dimensional check of eq. 4"}
  reference: null               # for build/derivation agents (path or value)
  expert_findings: [...]        # for real labeled cases
clean: false                    # true = control item with no defect
difficulty: hard                # easy / medium / hard / adversarial
provenance: "denolle2023, planted"
rubric_ref: auditor_v1
```

## Per-agent evaluation targets

| Agent | "Good" looks like | Golden-data recipe | Primary metrics |
|---|---|---|---|
| **Auditor** | Finds planted flaws, names a decisive test, ranks load-bearing first, **says sound when sound** | Artifacts w/ planted flaws **+ clean controls** | Recall/precision/F1, **false-positive rate**, test-quality, severity-rank correlation |
| **Theoretician** | Correct derivation, dimensional consistency, right limiting cases & method | Problems w/ known analytical answers & limits | Derivation correctness, limit-recovery rate |
| **Scientific Coder** | Correct vs. reference, passes V&V, **behavior-preserving** on refactor | Tasks w/ analytical/benchmark solutions | Numerical error vs. reference, convergence-order recovered, regression diff = 0 |
| **Debugger & Tester** | Localizes root cause, fix is correct, tests can fail | Code w/ planted bugs + mutation set | Bug-localization accuracy, fix correctness, **mutation catch rate** |
| **Data Engineer** | Catches planted data defects, preserves provenance, fails loudly | Datasets w/ injected gaps/units/response/clock errors | QC recall, FP rate, provenance completeness |
| **Literature Scout** | Relevant prior art, **zero hallucinated citations**, calibrated confidence | Questions w/ known key refs + non-existent-ref traps | Citation precision/recall, **hallucination rate**, confidence calibration |
| **Study Designer** | Complete design (controls, power, done-conditions), catches design flaws | Briefs w/ known-missing elements | Completeness checklist %, design-flaw recall |
| **Research Impact** | Real impact axes, **no overreach**, flags for human | Results w/ expert-labeled true impact + overclaim bait | Impact recall, **overreach rate**, demonstrated-vs-aspirational accuracy |
| **Run Monitor** | Detects injected failure signal **before the cliff** | Simulated runs w/ injected OOM/stall/disk/walltime | Detection rate, **lead time before failure** |
| **Orchestrator** | Decomposes well, routes to the right specialist | Tasks w/ known correct routing/decomposition | Routing accuracy, plan completeness |
| **Lab Notebook** | Faithful capture incl. failures; method+result together | Sessions w/ known events incl. failures | Capture fidelity, **failure-omission rate** |
| **Provenance Keeper** | **Always** logs AI use, correct identity, no secrets committed | Commit scenarios w/ secret/identity traps | **Compliance pass rate (must be 100%)** |
| **Courier** | Correct mechanical result, escalates when judgment needed | Mechanical tasks + judgment-bait traps | Task correctness, correct-escalation rate |

## Metrics, beyond hit/miss

- **Calibration.** Does stated confidence match correctness? Score with a Brier score /
  reliability curve. A calibrated "I'm unsure" is worth more than a confident wrong.
- **Overreach / false-positive.** First-class metric for every critique agent (Auditor,
  Data Engineer, Research Impact). The clean controls drive this.
- **Decisive-test quality.** For the Auditor, rubric-score whether each finding carries
  a *runnable* test (its core contract), not just whether the finding is real.
- **Human agreement.** On real cases, Cohen's/Fleiss' κ between the agent's verdicts and
  expert labels — and between experts, to know if the gold itself is trustworthy.
- **LLM-as-judge, validated.** For open-ended outputs, a separate strong model + rubric
  can scale grading — but **validate the judge against human labels** on a subset before
  trusting it, and never let an agent judge its own family's output.

## Process

1. **Start with the Auditor.** Highest leverage (it's the rigor foundation) and the
   easiest to make gold for (planted flaws + controls). 30–50 items from 3–5 past group
   papers is a real first milestone.
2. **Mine the group corpus first**, synthesize second. Past papers + referee reports,
   past code + reproducibility outcomes, past data + known issues.
3. **No contamination.** Golden items must never appear in an agent's prompt context or
   any fine-tuning. Keep the set **private** (already gitignored — good) and hold out.
4. **Inter-annotator agreement.** Have ≥2 group members label a subset; report κ. If the
   humans don't agree, the gold isn't gold yet.
5. **Stratify & report by `pillar × stage × difficulty`** so you see *where* an agent is
   weak (e.g. strong on Pillar B numerics, blind on Pillar A lab design).
6. **Version the gold set and regression-track** every roster change. Each agent edit
   should be a measurable move, not a vibe.

## Compliance / guardrail evals (pass-fail, not scored)

Some behaviors are non-negotiable and tested like unit tests — any failure is a bug:

- **Provenance Keeper** always discloses AI use; never commits a planted secret; never
  uses the wrong identity.
- **Auditor** never relaxes an integrity finding for a persona/voice reason; never ships
  past Critical by fiat.
- **Human gate** respected — no agent performs an outward-facing/irreversible action
  (push, release, submit) without the gate.
- **No-overreach** — agents don't assert significance/novelty/impact the evidence
  doesn't support.

## Two high-value uses of the gold set

- **End-to-end / system eval.** Run a *past project* through the whole pipeline and
  compare what the system catches to what real review caught. Tests orchestration and
  hand-offs, not just single agents.
- **Settle the merge-vs-split debates with data.** A/B roster variants on the same gold
  set — e.g. merged *Scientific Coder* vs. split *Coder + RSE*; one *Research Impact* vs.
  split scientific/societal. The open design questions become measurements, not opinions.

## Suggested first milestone (2–3 weeks of effort)

1. Pick 3–5 finished group papers with referee reports.
2. Build ~40 Auditor items: planted flaws (from real reviewer comments + injected
   numerical/stats/units defects) **and** ~30% clean controls.
3. Label with 2 people; compute κ.
4. Run the Auditor; report recall, **false-positive rate**, and decisive-test quality,
   stratified by pillar × stage.
5. Iterate the Auditor prompt against the numbers; freeze v1; expand to the next agent.
