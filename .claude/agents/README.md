# Project personas for the Puget Sound groundwater twin

These are **specific to this repository**, not the general `gaia` research family
(`.claude/gaia/plugins/gaia/agents/`). They exist because a generic reviewer does not know
this project's own history: that an 18.5 m baseline RMSE cannot serve a sub-metre
liquefaction requirement, that ΔD = −Δh_wt makes two prior entries for one field an error,
or that a *local* GMRF/SPDE precision only exists in 2-D at integer ν.

Each one was derived from this repository's review record, and carries that record's ranked
concerns as **priors to verify, not conclusions to repeat**:

| Persona | Derived from | Owns |
|---|---|---|
| `twin-hydrogeologist` | `docs/reviews/peer_review.md` §1 | glacial-aquifer physics, state definitions, fitness for purpose |
| `twin-geotech-engineer` | `docs/reviews/peer_review.md` §2 | Vs30, DTW and pore pressure as *decision* variables |
| `twin-atmospheric-scientist` | `docs/reviews/peer_review.md` §3 | forcing fitness, temporal support, event validation |
| `twin-geostatistician` | `sensor-uncertainty-covariance-review.md`, 2026-08 prior audit | priors, covariance, resolution claims |
| `twin-da-methodologist` | "Applied math: DA estimator correctness" milestone, 2026-08 audit | state contract, operators, time, B/Q/R |

## How they are used

`scripts/gaia_run_queue.sh` routes each issue to a panel of these from its labels and
milestone (`scripts/gaia-launch/gaia_panel.py`), and they review the **pre-registered plan
before any code is written**. The `gaia-auditor` sits on every panel for independence. A
`block`, or any `critical` concern, stops implementation.

Two properties are deliberate:

- **Read-only by tool grant.** No `Edit`, `Write` or `Bash`. A reviewer that could change the
  thing it judges is not a reviewer.
- **Dispatch is verified, not assumed.** "Use the twin-hydrogeologist agent" is prose; whether
  the session actually delegated is a fact in the transcript. A verdict from a session that
  never dispatched is the base model in costume, and it fails closed to a block.

## Adding or changing one

Keep the standing concerns tied to something in `docs/reviews/` or a merged PR. A persona
whose priors are invented rather than earned will generate confident, ungrounded objections —
which is worse than no reviewer, because it costs a revision cycle to discover.
