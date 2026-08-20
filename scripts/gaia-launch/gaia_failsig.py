#!/usr/bin/env python3
"""Stable signatures for test failures, so the queue can stop repeating itself.

The pipeline already refuses to loop on Copilot: it fingerprints the review payload and
calls convergence when the fingerprint stops changing. The agent's OWN failures had no such
check -- a revision pass that produces the identical traceback three times costs three full
orchestrator invocations and learns nothing. This is the same idea pointed at pytest.

A signature must be stable across runs that fail the SAME way and different across runs that
fail differently. So the volatile parts are normalised out -- absolute paths, hex addresses,
durations, line numbers, pytest's own seed/duration chatter -- while the parts that identify
the failure are kept: the test node id, the exception type, and the shape of the message.

Numeric VALUES inside an assertion message are deliberately normalised to <num>. Two runs
that both fail `assert 0.031 == approx(0.030)` and `assert 0.029 == approx(0.030)` are the
same unresolved problem, not two discoveries, and treating them as distinct is exactly the
loop this exists to break.

Usage:
    pytest ... 2>&1 | python gaia_failsig.py --summary
    python gaia_failsig.py --log gate.log --json sigs.json
Exit status is always 0: this is a reporter, not a gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys

# One line per failure in pytest's short summary, e.g.
#   FAILED tests/test_x.py::test_y - AssertionError: assert 1 == 2
SHORT_SUMMARY = re.compile(r"^(?:FAILED|ERROR)\s+(\S+?)(?:\s+-\s+(.*))?$", re.MULTILINE)
# Fallback: the "_____ test_name _____" section headers.
SECTION = re.compile(r"^_{5,}\s+(\S+)\s+_{5,}$", re.MULTILINE)
EXC_LINE = re.compile(r"^E\s+(\w+(?:Error|Exception|Warning|Failure)):?\s*(.*)$", re.MULTILINE)

_NORMALISERS = (
    (re.compile(r"0x[0-9a-fA-F]+"), "<addr>"),                 # object addresses
    (re.compile(r"/[\w./+-]+/"), "<path>/"),                    # absolute paths
    (re.compile(r"\b\d+\.\d+(?:[eE][-+]?\d+)?\b"), "<num>"),    # floats (incl. exponent)
    (re.compile(r"\b\d+[eE][-+]?\d+\b"), "<num>"),              # 1e-6
    (re.compile(r"\b\d{3,}\b"), "<num>"),                       # long ints (ids, sizes)
    (re.compile(r"\s+"), " "),                                  # whitespace
)


def normalise(text: str) -> str:
    out = text.strip()
    for pat, rep in _NORMALISERS:
        out = pat.sub(rep, out)
    return out.strip()


def signatures(log: str) -> list[dict]:
    """[{test, exc, message, signature}] -- one entry per distinct failure in the log."""
    found: dict[str, dict] = {}

    for node, msg in SHORT_SUMMARY.findall(log):
        exc, rest = "", (msg or "")
        m = re.match(r"(\w+(?:Error|Exception|Warning|Failure)):?\s*(.*)", rest)
        if m:
            exc, rest = m.group(1), m.group(2)
        norm = normalise(rest)
        sig = hashlib.sha256(f"{node}|{exc}|{norm}".encode()).hexdigest()[:16]
        found[sig] = dict(test=node, exc=exc or "unknown", message=norm[:300], signature=sig)

    # Some failures (collection errors, fixture errors) never reach the short summary.
    if not found:
        tests = SECTION.findall(log)
        excs = EXC_LINE.findall(log)
        for i, node in enumerate(tests or ["<unknown>"]):
            exc, rest = (excs[i] if i < len(excs) else ("unknown", ""))
            norm = normalise(rest)
            sig = hashlib.sha256(f"{node}|{exc}|{norm}".encode()).hexdigest()[:16]
            found[sig] = dict(test=node, exc=exc, message=norm[:300], signature=sig)
    return sorted(found.values(), key=lambda d: (d["test"], d["signature"]))


def batch_signature(sigs: list[dict]) -> str:
    """One hash for the whole failure SET, so 'the run failed the same way' is one compare."""
    joined = "|".join(s["signature"] for s in sigs)
    return hashlib.sha256(joined.encode()).hexdigest()[:16] if joined else "none"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--log", metavar="FILE", help="pytest output (default: stdin)")
    p.add_argument("--json", metavar="OUT", help="write signatures as JSON")
    p.add_argument("--summary", action="store_true", help="print a human summary")
    p.add_argument("--batch-only", action="store_true",
                   help="print ONLY the whole-run signature (what the queue compares)")
    a = p.parse_args()

    log = open(a.log, encoding="utf-8", errors="replace").read() if a.log else sys.stdin.read()
    sigs = signatures(log)
    batch = batch_signature(sigs)

    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump({"batch_signature": batch, "failures": sigs}, fh, indent=2)
    if a.batch_only:
        print(batch)
        return 0
    print(batch)
    if a.summary:
        for s in sigs:
            print(f"  {s['signature']}  {s['test']}\n      {s['exc']}: {s['message'][:120]}",
                  file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
