#!/usr/bin/env python3
"""Detect an agent weakening the thing that judges it.

The pipeline's only mechanical definition of "done" is ``pixi run test`` plus the DOI and
render gates. An agent asked to make that pass has two routes: fix the code, or soften the
gate. Nothing in the pipeline distinguished them, and the second route is invisible in a
green CI run -- which is exactly what makes it dangerous in a numerics repository, where
loosening one ``rtol`` can turn a failing convergence claim into a passing one without a
single line of physics changing.

This is the mechanical form of the prose rule "do not force the calculation to run by
changing the physical problem". It reads the STAGED diff and reports gate-weakening
signals. It has no model in it and no opinions: every finding names a file, a line, and
the before/after text, so a human can overrule it in one glance.

Findings are one of two severities:

  block  -- an unambiguous softening of the judge: a disabled test, a loosened numeric
            tolerance, an edited gate definition. These stop the commit.
  warn   -- suspicious but legitimately common: net loss of tests or assertions, which a
            genuine refactor also produces. Reported, never blocking.

Usage:
    python gaia_gate_integrity.py [--staged | --diff FILE] [--json OUT]
Exit status:
    0  no blocking finding
    1  at least one blocking finding
    2  could not read a diff (fail closed -- the caller must treat this as blocking)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict

# Paths whose modification changes what "passing" MEANS rather than whether the code passes.
GATE_PATHS = (
    "pixi.toml", "pyproject.toml", "setup.cfg", "tox.ini", "pytest.ini",
    ".github/workflows/", "conftest.py", "docs/references.bib.checkignore",
)
# Only these gate keys matter; an unrelated pixi task or workflow is not a gate.
GATE_KEYS = re.compile(r"\b(test|check-dois|check-dois-metadata|quarto|pytest|addopts|"
                       r"filterwarnings|testpaths|markers)\b")

TEST_FILE = re.compile(r"(^|/)(tests?/|test_[^/]*\.py$|[^/]*_test\.py$)")
TEST_DEF = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)")
SKIP_MARK = re.compile(r"@pytest\.mark\.(skip|skipif|xfail)|pytest\.skip\(|pytest\.xfail\(|"
                       r"unittest\.skip|@unittest\.skip")
ASSERT = re.compile(r"^\s*(assert\b|self\.assert\w+\()")

# Tolerance-ish keywords whose numeric value going UP means the check got weaker.
TOL_KW = re.compile(
    r"\b(rtol|atol|tol|tolerance|eps|epsilon|delta|abs|rel|max_error|err_tol|"
    r"threshold|places|decimal)\s*=\s*([0-9][0-9_]*\.?[0-9]*(?:[eE][-+]?[0-9]+)?)")
# A bare numeric bound in an assertion: `assert err < 1e-6`
BARE_BOUND = re.compile(r"assert\s+[^<>\n]+?([<>]=?)\s*([0-9][0-9_]*\.?[0-9]*(?:[eE][-+]?[0-9]+)?)")


def _num(s: str) -> float | None:
    try:
        return float(s.replace("_", ""))
    except ValueError:
        return None


def read_diff(args) -> str:
    if args.diff:
        with open(args.diff, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    # -U0 keeps hunks tight so a +/- pair is genuinely a changed line, not context.
    r = subprocess.run(["git", "diff", "--cached", "-U0", "--no-color"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "git diff --cached failed")
    return r.stdout


def parse_hunks(diff: str):
    """Yield (path, removed_lines, added_lines) per file. Line numbers are not tracked:
    the caller wants WHAT changed, and -U0 already guarantees these are changed lines."""
    path, removed, added = None, [], []
    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            if path is not None:
                yield path, removed, added
            # b/<path> is the post-image name, which is the one that exists after the change.
            m = re.search(r" b/(.+)$", line)
            path, removed, added = (m.group(1) if m else "?"), [], []
        elif line.startswith("--- ") or line.startswith("+++ ") or line.startswith("@@"):
            continue
        elif line.startswith("-"):
            removed.append(line[1:])
        elif line.startswith("+"):
            added.append(line[1:])
    if path is not None:
        yield path, removed, added


def analyse(diff: str) -> list[dict]:
    findings: list[dict] = []
    for path, removed, added in parse_hunks(diff):
        is_test = bool(TEST_FILE.search(path))
        is_gate = any(path == g or path.startswith(g) for g in GATE_PATHS) or path.endswith("conftest.py")

        # 1. The gate definition itself. Trigger on REMOVED lines only: in a diff, altering
        #    or deleting an existing gate shows up as a removal, whereas ADDING a new task is
        #    how you make the gate stricter (this repo's own `check-dois-metadata` is exactly
        #    that, and flagging it was a false positive on real history). Comments are
        #    stripped first -- prose mentioning `check-dois` is not a gate change.
        if is_gate:
            for ln in removed:
                code = re.sub(r"#.*$", "", ln).strip()
                if code and GATE_KEYS.search(code):
                    findings.append(dict(
                        severity="block", kind="gate-definition-changed", file=path,
                        detail=code[:200],
                        why="An existing gate definition was altered or removed. This changes what "
                            "the gate runs, not whether the code passes it."))
                    break

        if not is_test:
            continue

        # 2. Tests disabled. Unambiguous: an added skip/xfail makes a red test green
        #    without touching the code under test.
        for ln in added:
            if SKIP_MARK.search(ln):
                findings.append(dict(
                    severity="block", kind="test-disabled", file=path,
                    detail=ln.strip()[:200],
                    why="A skip/xfail turns a failing test green without changing the code under test."))

        # 3. Tolerances loosened. Compare like-named keywords across the removed and added
        #    sides of the same file; a LARGER value is a weaker check. This is the classic
        #    silent cheat in a numerics repo.
        old_tol, new_tol = defaultdict(list), defaultdict(list)
        for ln in removed:
            for kw, val in TOL_KW.findall(ln):
                old_tol[kw].append((_num(val), ln.strip()))
        for ln in added:
            for kw, val in TOL_KW.findall(ln):
                new_tol[kw].append((_num(val), ln.strip()))
        for kw in set(old_tol) & set(new_tol):
            o = max((v for v, _ in old_tol[kw] if v is not None), default=None)
            n_pairs = [(v, t) for v, t in new_tol[kw] if v is not None]
            if o is None or not n_pairs:
                continue
            n, text = max(n_pairs)
            # `places`/`decimal` invert: FEWER places is a weaker assertion.
            weaker = (n < o) if kw in ("places", "decimal") else (n > o)
            if weaker:
                findings.append(dict(
                    severity="block", kind="tolerance-loosened", file=path,
                    detail=f"{kw}: {o:g} -> {n:g}   ({text[:120]})",
                    why="A weaker numeric tolerance can turn a failing convergence claim into a passing one."))

        # 4. Bare assertion bounds: `assert err < 1e-6` -> `assert err < 1e-3`.
        ob = [(_num(v), l) for l in removed for _, v in BARE_BOUND.findall(l)]
        nb = [(_num(v), l) for l in added for _, v in BARE_BOUND.findall(l)]
        if ob and nb:
            o = max((v for v, _ in ob if v is not None), default=None)
            cand = [(v, l) for v, l in nb if v is not None]
            if o is not None and cand:
                n, text = max(cand)
                if n > o:
                    findings.append(dict(
                        severity="block", kind="assert-bound-loosened", file=path,
                        detail=f"{o:g} -> {n:g}   ({text.strip()[:120]})",
                        why="The numeric bound in an assertion was raised, weakening it."))

        # 5. Net loss of tests or assertions. A genuine refactor does this too, so it is a
        #    WARNING -- reported so a reviewer looks, never blocking on its own.
        gone = {m.group(1) for l in removed if (m := TEST_DEF.match(l))}
        came = {m.group(1) for l in added if (m := TEST_DEF.match(l))}
        net_lost = gone - came
        if net_lost:
            findings.append(dict(
                severity="warn", kind="tests-removed", file=path,
                detail=", ".join(sorted(net_lost))[:200],
                why="Test functions disappeared. Legitimate in a rename/refactor; verify they moved."))
        a_out = sum(1 for l in removed if ASSERT.match(l))
        a_in = sum(1 for l in added if ASSERT.match(l))
        if a_out > a_in and not net_lost:
            findings.append(dict(
                severity="warn", kind="assertions-reduced", file=path,
                detail=f"-{a_out} / +{a_in} assertion lines",
                why="Net fewer assertions in a test file whose tests were kept."))
    return findings


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--staged", action="store_true", help="analyse `git diff --cached` (default)")
    p.add_argument("--diff", metavar="FILE", help="analyse a diff file instead")
    p.add_argument("--json", metavar="OUT", help="write findings as JSON")
    args = p.parse_args()

    try:
        diff = read_diff(args)
    except Exception as e:                                    # fail closed
        print(f"gate-integrity: could not read a diff: {e}", file=sys.stderr)
        return 2

    findings = analyse(diff)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(findings, fh, indent=2)

    blocking = [f for f in findings if f["severity"] == "block"]
    for f in findings:
        tag = "!!! BLOCK" if f["severity"] == "block" else "    warn "
        print(f"{tag}  {f['kind']}  {f['file']}\n           {f['detail']}\n           {f['why']}",
              file=sys.stderr)
    if not findings:
        print("gate-integrity: clean (no gate weakening detected)", file=sys.stderr)
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
