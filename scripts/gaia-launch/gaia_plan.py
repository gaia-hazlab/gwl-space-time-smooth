#!/usr/bin/env python3
"""The pre-registration: what the agent says it will do, before it is allowed to do it.

Our own ground rule 3 says "design-review first -- audit a plan once before resources are
spent". The queue has never done it. It goes straight from an issue title to an editing
agent, which means scope creep is only visible afterwards, in the diff, when it has already
been paid for.

This is the plan artifact and its contract. The agent emits it BEFORE touching the tree,
from a read-only session; the queue validates it, posts it to the issue, hands it to the
science panel to review, and -- once the work is done -- compares what was declared against
what actually happened. Drift between the two is the number that makes scope creep
measurable instead of anecdotal.

Validation is strict and fails CLOSED, for the same reason the auditor gate does: a plan
that cannot be parsed is not a plan, and proceeding without one silently reverts the
pipeline to its old behaviour.

Usage:
    python gaia_plan.py --validate plan.json
    python gaia_plan.py --render plan.json                     # markdown for an issue comment
    python gaia_plan.py --compare plan.json --actual actual.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Deliberately small. Every field is something a reviewer or a later comparison actually
# uses; a field nobody reads is a field the agent learns to pad.
SCHEMA = {
    "obstruction":       (str,  "What is actually blocking this issue, in one or two sentences."),
    "questions":         (list, "The ordered questions to answer. Each a testable statement."),
    "approach":          (str,  "How each question gets answered. Method, not narrative."),
    "artifacts":         (list, "Files/notebooks/figures this will produce or change."),
    "expected_files":    (int,  "How many files the diff will touch."),
    "expected_lines":    (int,  "Handwritten changed lines expected (excluding generated output)."),
    "expected_runtime_min": (int, "Wall-clock minutes of computation expected."),
    "stopping_conditions": (list, "Conditions under which to stop and report instead of improvising."),
    "negative_result_criteria": (str,
        "What a reproducible NEGATIVE result would look like here, and what would then be "
        "the narrower follow-up. Closure does not require a positive result."),
    "out_of_scope":      (list, "Explicitly NOT doing, to make scope creep detectable."),
}
REQUIRED = tuple(SCHEMA)


def validate(plan: dict) -> list[str]:
    errs = []
    if not isinstance(plan, dict):
        return ["plan is not a JSON object"]
    for key, (typ, _) in SCHEMA.items():
        if key not in plan:
            errs.append(f"missing required field: {key}")
            continue
        val = plan[key]
        if typ is int:
            if isinstance(val, bool) or not isinstance(val, int):
                errs.append(f"{key} must be an integer, got {type(val).__name__}")
            elif val < 0:
                errs.append(f"{key} must be >= 0")
        elif typ is list:
            if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                errs.append(f"{key} must be a list of strings")
            elif not val:
                errs.append(f"{key} must not be empty")
        elif typ is str:
            if not isinstance(val, str) or not val.strip():
                errs.append(f"{key} must be a non-empty string")
    # A plan that promises everything is not a plan. These bounds exist so an agent cannot
    # pre-authorise an unbounded diff by declaring one.
    if isinstance(plan.get("expected_files"), int) and plan["expected_files"] > 40:
        errs.append("expected_files > 40: split the issue rather than pre-authorising a sprawling diff")
    if isinstance(plan.get("expected_lines"), int) and plan["expected_lines"] > 4000:
        errs.append("expected_lines > 4000: split the issue")
    return errs


def render(plan: dict, issue: int | None = None) -> str:
    def bullets(xs):
        return "\n".join(f"- {x}" for x in xs) or "- (none)"
    head = f"## Pre-registered plan for #{issue}" if issue else "## Pre-registered plan"
    return f"""{head}

*Declared by the orchestrator from a read-only session, before any edit. Reviewed by the
science panel below. Compared against what actually happened when the work lands.*

**Obstruction.** {plan.get('obstruction','?')}

**Questions**
{bullets(plan.get('questions', []))}

**Approach.** {plan.get('approach','?')}

**Artifacts**
{bullets(plan.get('artifacts', []))}

**Declared budget** — {plan.get('expected_files','?')} files · \
{plan.get('expected_lines','?')} handwritten lines · \
{plan.get('expected_runtime_min','?')} min compute

**Stopping conditions**
{bullets(plan.get('stopping_conditions', []))}

**What a negative result looks like.** {plan.get('negative_result_criteria','?')}

**Explicitly out of scope**
{bullets(plan.get('out_of_scope', []))}
"""


def compare(plan: dict, actual: dict) -> tuple[str, list[str]]:
    """Declared vs actual. Returns (markdown, drift warnings). Never blocks -- a plan is a
    forecast, and punishing an honest miss would just teach the agent to inflate it."""
    rows, warn = [], []
    for key, label, tol in (("expected_files", "files touched", 2.0),
                            ("expected_lines", "handwritten lines", 2.0),
                            ("expected_runtime_min", "runtime (min)", 3.0)):
        d = plan.get(key)
        a = actual.get(key)
        if not isinstance(d, int) or not isinstance(a, (int, float)):
            continue
        ratio = (a / d) if d else (float("inf") if a else 1.0)
        flag = ""
        if d and ratio > tol:
            flag = f" ⚠️ {ratio:.1f}× over"
            warn.append(f"{label}: declared {d}, actual {a} ({ratio:.1f}× over)")
        rows.append(f"| {label} | {d} | {a}{flag} |")
    md = ("| quantity | declared | actual |\n|---|---|---|\n" + "\n".join(rows)) if rows else ""
    return md, warn


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--validate", metavar="PLAN")
    p.add_argument("--render", metavar="PLAN")
    p.add_argument("--compare", metavar="PLAN")
    p.add_argument("--actual", metavar="ACTUAL")
    p.add_argument("--issue", type=int)
    a = p.parse_args()

    def load(path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    if a.validate:
        try:
            plan = load(a.validate)
        except Exception as e:
            print(f"plan is not valid JSON: {e}", file=sys.stderr)
            return 1
        errs = validate(plan)
        for e in errs:
            print(f"  !!! plan: {e}", file=sys.stderr)
        if not errs:
            print("plan: valid", file=sys.stderr)
        return 1 if errs else 0

    if a.render:
        print(render(load(a.render), a.issue))
        return 0

    if a.compare and a.actual:
        md, warn = compare(load(a.compare), load(a.actual))
        print(md)
        for w in warn:
            print(f"  drift: {w}", file=sys.stderr)
        return 0

    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
