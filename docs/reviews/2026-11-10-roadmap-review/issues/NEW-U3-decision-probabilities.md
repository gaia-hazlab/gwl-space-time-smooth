# NEW-U3: Decision-threshold and compound-hazard probabilities from shared members

Milestone: v0.7 Probabilistic nowcast and ensemble forecast. Labels: uncertainty, P2, needs-human-decision.

## Purpose
The target is climate-compounded hazards. #193 has P(FS < 1), #258 P(Q > Q_T), #191 unnamed
"threshold probabilities". No issue names thresholds with a support, and none asks for a joint
probability across hazards, which only exists if members are shared end to end. The roadmap also
carries two definitions of seasonal high (#261 annual P10, #138 annual-minimum return level).

## Decision requested
Which thresholds and which joint events are products (for example P(depth to water < 1, 2, 3 m)
in liquefiable units; P(FS < 1 and Q > Q_T) per basin and event), and one definition of seasonal high.

## Acceptance (once decided)
- Each probability is computed from members, with support stated, and scored with the Brier skill
  score against climatology on held-out data (NEW-U1).
- The joint probability differs from the product of marginals on a fixture with known dependence,
  and equals it when members are deliberately shuffled across hazards.

## Hard blockers
Blocked by: #193, NEW-I1.
