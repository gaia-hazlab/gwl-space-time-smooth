"""CI gate (#158): every DOI in references.bib must resolve at doi.org.

references.bib has a history of fabricated/wrong DOIs slipping in (see the FIXED/ADDED
provenance comments in the file) -- entries that cite a real-looking DOI which in fact
resolves to an unrelated paper, or does not resolve at all. This script is the automated
backstop for that: it extracts every ``doi = {...}`` field and resolves it against
https://doi.org, failing loudly (nonzero exit, one line per bad DOI) on anything that
does not come back 2xx/3xx.

It does not check that the DOI resolves to the *correct* paper (title/author matching
against Crossref) -- that verification is manual, recorded in the file's comments.

The check looks only at doi.org's own response, without following the redirect: a
registered DOI gets a 3xx handle-registry redirect from doi.org itself, an unregistered
one gets 404. Following the redirect to the publisher's landing page is deliberately
avoided -- several publishers (AIP, Wiley/AGU, ACM) return 403 to bots there, which would
otherwise be indistinguishable from a genuinely broken DOI.

That whole design rests on one assumption -- that doi.org answers an unregistered DOI
with a status >= 400 -- so the script self-checks the assumption on every run before
trusting its own verdict (see ``CANARY_DOIS`` / :func:`check_gate`). The self-check is
three-state: only a conclusive 404/410 counts as verified, and a run whose self-check was
inconclusive refuses to report an all-clear.

Exit status:
  0  every DOI resolved AND the gate self-check was VERIFIED
  1  at least one DOI failed to resolve, or the gate itself is BROKEN, or the
     self-check was INCONCLUSIVE (so a zero-failure result cannot be certified)

Usage:  python scripts/check_doi_integrity.py [path/to/references.bib]
"""

from __future__ import annotations

import re
import sys
from enum import Enum
from pathlib import Path
from typing import NamedTuple

import requests

DEFAULT_BIB = Path("docs/references.bib")
DOI_RE = re.compile(r"""doi\s*=\s*[{"]\s*([^}"]+?)\s*[}"]""", re.IGNORECASE)
TIMEOUT_S = 15
RETRIES = 2
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; doi-integrity-check/1.0)"}

# Self-check probes for the gate itself. These are NOT citations and must never appear in
# references.bib -- they are deliberately-invalid DOIs whose only job is to come back 404.
# If doi.org ever answers one of them with a status < 400 (a 200 "not found" error page, or
# a redirect to a "DOI not registered" landing page), then resolves() would return True for
# *every* input and the gate would silently pass fabricated DOIs -- so that case is fatal.
#
# There are two of them because doi.org's handle proxy has two distinct lookup paths and a
# regression could hit either one independently:
#   * 10.0000/...  -- unknown *naming authority*: the prefix itself is unassigned, so no
#     handle under it can ever be registered.
#   * 10.1029/...  -- unknown *handle under a known authority*: 10.1029 (AGU/Wiley) is a
#     real registered prefix used by 15 entries in references.bib, but this suffix is not
#     and cannot be a real handle. This is the shape every fabricated DOI in this file's
#     provenance comments actually had, and the more plausible future break: doi.org
#     serving a helpful HTTP 200 "this DOI is not registered with $PUBLISHER" page for an
#     unknown suffix under a known prefix, while an unknown prefix keeps returning 404.
# Both must be conclusively unresolvable for the gate to be considered self-verified.
CANARY_DOIS = (
    "10.0000/gaia-doi-gate-canary-must-not-resolve",
    "10.1029/gaia-doi-gate-canary-must-not-resolve",
)

# Statuses that conclusively mean "doi.org looked and there is no such DOI". Anything else
# (403, 429, 5xx, a transport exception) measures nothing about doi.org's 404 semantics.
CONCLUSIVE_ABSENT = frozenset({404, 410})


class GateStatus(Enum):
    """Outcome of the gate's self-check.

    VERIFIED      -- doi.org conclusively reported the canary absent (404/410); a
                     non-resolving DOI really is distinguishable from a resolving one.
    INCONCLUSIVE  -- the probe measured nothing (any other status, or a transport error on
                     every attempt). The gate may or may not work; it has not been shown to.
    BROKEN        -- doi.org accepted a DOI that cannot exist; resolves() is meaningless.
    """

    VERIFIED = "VERIFIED"
    INCONCLUSIVE = "INCONCLUSIVE"
    BROKEN = "BROKEN"


class ProbeResult(NamedTuple):
    """Structured outcome of one doi.org lookup, so callers never sniff message strings."""

    doi: str
    resolved: bool
    status: int | None  # HTTP status of the last attempt that completed; None iff none did
    error: str  # transport error text when ``status`` is None, else ""

    @property
    def detail(self) -> str:
        """Human-readable detail, as printed in the per-DOI result lines."""
        if self.status is None:
            return self.error
        return str(self.status) if self.resolved else f"HTTP {self.status}"


def extract_dois(bib_text: str) -> list[str]:
    return DOI_RE.findall(bib_text)


def probe(doi: str) -> ProbeResult:
    """Resolve ``doi`` at doi.org, retrying transport/HTTP failures, structured result.

    An answer from doi.org outranks a transport error regardless of attempt order: once any
    attempt has completed with an HTTP status, a later exception cannot erase it. Otherwise
    the sequence 404, 404, timeout would report ``status=None`` -- "we never reached
    doi.org" -- on a run where doi.org twice said, conclusively, that the DOI is absent,
    turning a verified gate into an INCONCLUSIVE (and now fatal) one and libelling an
    answered DOI as unreachable in the report line. ``status is None`` therefore means no
    attempt ever completed, not merely that the last one raised.
    """
    url = f"https://doi.org/{doi}"
    last = ProbeResult(doi, False, None, "")
    for _ in range(RETRIES + 1):
        try:
            r = requests.get(url, allow_redirects=False, timeout=TIMEOUT_S, headers=HEADERS)
            last = ProbeResult(doi, r.is_redirect or r.ok, r.status_code, "")
            if last.resolved:
                return last
        except requests.RequestException as exc:
            if last.status is None:
                last = ProbeResult(doi, False, None, str(exc))
    return last


def resolves(doi: str) -> tuple[bool, str]:
    """``(resolved?, detail)`` for one DOI -- the per-entry check used by :func:`main`."""
    result = probe(doi)
    return result.resolved, result.detail


def check_canary(doi: str) -> tuple[GateStatus, str]:
    """Probe one deliberately-invalid DOI and classify what it proved about the gate."""
    result = probe(doi)
    if result.resolved:
        return GateStatus.BROKEN, (
            f"DOI GATE NOT FUNCTIONING: doi.org accepted a known-unregistered DOI "
            f"{doi} (HTTP {result.detail}); the check cannot distinguish good from bad "
            f"DOIs. Not reporting on the DOIs in references.bib -- they are unverified."
        )
    if result.status in CONCLUSIVE_ABSENT:
        return GateStatus.VERIFIED, (
            f"canary {doi} correctly unresolvable ({result.detail}); this probe path is verified"
        )
    if result.status is not None:
        return GateStatus.INCONCLUSIVE, (
            f"canary {doi} INCONCLUSIVE: doi.org answered {result.detail}, which is neither "
            f"a resolution nor a conclusive 404/410, so it says nothing about whether the "
            f"gate can still detect an unregistered DOI"
        )
    return GateStatus.INCONCLUSIVE, (
        f"canary {doi} INCONCLUSIVE: could not be probed in {RETRIES + 1} attempts "
        f"({result.error}); the gate self-check measured nothing"
    )


def check_gate() -> tuple[GateStatus, list[str]]:
    """Run every canary probe; return the worst outcome plus one report line per canary.

    BROKEN if any canary resolved (doi.org accepts DOIs that cannot exist), else
    INCONCLUSIVE if any canary failed to produce a conclusive 404/410, else VERIFIED.

    An empty ``CANARY_DOIS`` is INCONCLUSIVE, never VERIFIED: certifying the gate off zero
    probes is the same silent green this script exists to prevent, and "all canaries were
    conclusive" is vacuously true when there are none.
    """
    if not CANARY_DOIS:
        return GateStatus.INCONCLUSIVE, [
            "gate self-check INCONCLUSIVE: no canary DOIs are configured, so nothing was "
            "probed and the gate has not been shown to detect an unregistered DOI"
        ]
    lines: list[str] = []
    statuses: list[GateStatus] = []
    for doi in CANARY_DOIS:
        status, line = check_canary(doi)
        statuses.append(status)
        lines.append(line)
    if GateStatus.BROKEN in statuses:
        return GateStatus.BROKEN, lines
    if GateStatus.INCONCLUSIVE in statuses:
        return GateStatus.INCONCLUSIVE, lines
    return GateStatus.VERIFIED, lines


def main(argv: list[str]) -> int:
    bib_path = Path(argv[1]) if len(argv) > 1 else DEFAULT_BIB
    dois = extract_dois(bib_path.read_text(encoding="utf-8"))
    if not dois:
        print(f"no DOI fields found in {bib_path}", file=sys.stderr)
        return 1

    # Verify the gate can still tell a bad DOI from a good one before trusting its verdict.
    gate_status, gate_lines = check_gate()
    for line in gate_lines:
        print(line, file=sys.stderr)
    print(f"gate self-check: {gate_status.value}", file=sys.stderr)
    if gate_status is GateStatus.BROKEN:
        return 1

    failures = []
    for doi in dois:
        ok, detail = resolves(doi)
        print(f"{'OK  ' if ok else 'FAIL'} {doi}  ({detail})")
        if not ok:
            failures.append((doi, detail))

    print(f"\n{len(dois)} DOIs checked, {len(failures)} failed")
    if failures:
        print("\nUnresolvable DOIs (fix or remove from references.bib):", file=sys.stderr)
        for doi, detail in failures:
            print(f"  {doi}: {detail}", file=sys.stderr)
        return 1
    if gate_status is GateStatus.INCONCLUSIVE:
        # Zero failures, but the gate was never shown to be able to detect a failure. An
        # all-clear from an unverified gate is exactly the silent-green this script exists
        # to prevent, so refuse to certify it rather than reporting success.
        print(
            "\nGATE SELF-CHECK INCONCLUSIVE: every DOI above came back OK, but doi.org never "
            "conclusively confirmed that an unregistered DOI still 404s, so this all-clear "
            "cannot be trusted. Re-run when doi.org is reachable and answering normally.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
