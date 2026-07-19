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

Usage:  python scripts/check_doi_integrity.py [path/to/references.bib]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import requests

DEFAULT_BIB = Path("docs/references.bib")
DOI_RE = re.compile(r"""doi\s*=\s*[{"]\s*([^}"]+?)\s*[}"]""", re.IGNORECASE)
TIMEOUT_S = 15
RETRIES = 2
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; doi-integrity-check/1.0)"}


def extract_dois(bib_text: str) -> list[str]:
    return DOI_RE.findall(bib_text)


def resolves(doi: str) -> tuple[bool, str]:
    url = f"https://doi.org/{doi}"
    last_err = ""
    for _ in range(RETRIES + 1):
        try:
            r = requests.get(url, allow_redirects=False, timeout=TIMEOUT_S, headers=HEADERS)
            if r.is_redirect or r.ok:
                return True, f"{r.status_code}"
            last_err = f"HTTP {r.status_code}"
        except requests.RequestException as exc:
            last_err = str(exc)
    return False, last_err


def main(argv: list[str]) -> int:
    bib_path = Path(argv[1]) if len(argv) > 1 else DEFAULT_BIB
    dois = extract_dois(bib_path.read_text())
    if not dois:
        print(f"no DOI fields found in {bib_path}", file=sys.stderr)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
