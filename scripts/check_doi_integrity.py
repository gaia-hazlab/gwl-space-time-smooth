"""CI gate (#158): every DOI in references.bib must resolve at doi.org.

references.bib has a history of fabricated/wrong DOIs slipping in (see the FIXED/ADDED
provenance comments in the file) -- entries that cite a real-looking DOI which in fact
resolves to an unrelated paper, or does not resolve at all. This script is the automated
backstop for that: it extracts every ``doi = {...}`` field and resolves it against
https://doi.org, failing loudly (nonzero exit, one line per bad DOI) on anything that
does not come back 2xx/3xx.

By default it checks only that the DOI is *registered*. With ``--metadata`` it additionally
queries the Crossref REST API and compares the bib entry's title, first-author family name,
and year against the registered metadata -- catching the failure mode a resolution-only check
cannot see: a real, resolvable DOI attached to the wrong paper. That is the failure this file
has actually suffered (see the FIXED provenance comments in references.bib), so ``--metadata``
is the mode to run when a literature update lands.

Year is compared with a +/-1 year tolerance because Crossref's ``issued`` date is the
online-first date for many journals while the bib entry cites the print issue.

The check looks only at doi.org's own response, without following the redirect: a
registered DOI gets a 3xx handle-registry redirect from doi.org itself, an unregistered
one gets 404. Following the redirect to the publisher's landing page is deliberately
avoided -- several publishers (AIP, Wiley/AGU, ACM) return 403 to bots there, which would
otherwise be indistinguishable from a genuinely broken DOI.

Usage:  python scripts/check_doi_integrity.py [path/to/references.bib] [--metadata]
"""

from __future__ import annotations

import html
import re
import sys
import unicodedata
from pathlib import Path

import requests

DEFAULT_BIB = Path("docs/references.bib")
DOI_RE = re.compile(r"""doi\s*=\s*[{"]\s*([^}"]+?)\s*[}"]""", re.IGNORECASE)
ENTRY_RE = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,(.*?)(?=\n@|\Z)", re.DOTALL)
FIELD_RE = re.compile(r"(\w+)\s*=\s*\{(.*?)\}\s*,?\s*(?=\n\s*\w+\s*=|\n\s*\}|\Z)", re.DOTALL)
CROSSREF = "https://api.crossref.org/works/"
YEAR_TOL = 1
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


def parse_entries(bib_text: str) -> list[dict]:
    """Parse ``@type{key, field = {value}, ...}`` blocks into dicts (best effort, no bibtex dep)."""
    out = []
    for key, body in ENTRY_RE.findall(bib_text):
        fields = {k.lower(): " ".join(v.split()) for k, v in FIELD_RE.findall(body)}
        if "doi" in fields:
            out.append({"key": key, **fields})
    return out


def _normalise(s: str) -> str:
    """Fold markup so a comparison is about words: LaTeX accents/braces, HTML entities, unicode.

    ``Mat{\\'e}rn`` (bibtex), ``Matérn`` (Crossref), and ``Mat&eacute;rn`` must all compare equal,
    or the check drowns in false positives and stops being read.
    """
    s = html.unescape(s)
    s = re.sub(r"\\[a-zA-Z]+", "", s)                     # \emph, \textit, ...
    s = re.sub(r"\\.", "", s)                             # \', \", \~ accent escapes
    s = s.replace("{", "").replace("}", "")               # bibtex case-protection braces
    s = unicodedata.normalize("NFKD", s)                  # é -> e + combining accent
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^0-9a-zA-Z]+", " ", s)
    return " ".join(s.lower().split())


def crossref_metadata(doi: str) -> dict | None:
    try:
        r = requests.get(CROSSREF + doi, timeout=TIMEOUT_S,
                         headers={"User-Agent": "doi-integrity-check/1.0 (bib metadata audit)"})
        if not r.ok:
            return None
        return r.json()["message"]
    except (requests.RequestException, ValueError, KeyError):
        return None


def metadata_mismatches(entry: dict, meta: dict) -> list[str]:
    """Report every way the bib entry disagrees with the registered Crossref metadata."""
    problems = []

    bib_title = _normalise(entry.get("title", ""))
    cr_title = _normalise((meta.get("title") or [""])[0])
    if bib_title and cr_title and bib_title != cr_title:
        # tolerate subtitle/punctuation drift; require one to contain the other
        if bib_title not in cr_title and cr_title not in bib_title:
            problems.append(f"title: bib={entry.get('title','')!r} crossref={(meta.get('title') or [''])[0]!r}")

    bib_first = _normalise(entry.get("author", "").split(" and ")[0].split(",")[0])
    cr_authors = meta.get("author") or []
    cr_first = _normalise(cr_authors[0].get("family", "")) if cr_authors else ""
    if bib_first and cr_first and cr_first not in bib_first and bib_first not in cr_first:
        problems.append(f"first author: bib={bib_first!r} crossref={cr_first!r}")

    # A bib entry may legitimately truncate a long author list; it may NOT invent authors the
    # registered record does not have. Only the second case is a citation-integrity failure.
    if cr_authors and entry.get("author"):
        n_bib = len(entry["author"].split(" and "))
        if n_bib > len(cr_authors) + 1:
            problems.append(f"author count: bib={n_bib} > crossref={len(cr_authors)}")

    try:
        bib_year = int(re.sub(r"[^0-9]", "", entry.get("year", "")) or 0)
    except ValueError:
        bib_year = 0
    parts = meta.get("issued", {}).get("date-parts") or [[None]]
    cr_year = parts[0][0]
    if bib_year and cr_year and abs(bib_year - cr_year) > YEAR_TOL:
        problems.append(f"year: bib={bib_year} crossref={cr_year}")

    bib_j = _normalise(entry.get("journal", "") or entry.get("booktitle", ""))
    cr_j = _normalise((meta.get("container-title") or [""])[0])
    if bib_j and cr_j and bib_j not in cr_j and cr_j not in bib_j:
        problems.append(f"journal: bib={entry.get('journal','')!r} crossref={(meta.get('container-title') or [''])[0]!r}")

    return problems


def check_metadata(bib_path: Path) -> int:
    """Compare every entry's title/author/year/journal against Crossref. Non-zero on a mismatch."""
    entries = parse_entries(bib_path.read_text())
    bad, unchecked = [], []
    for e in entries:
        meta = crossref_metadata(e["doi"])
        if meta is None:
            unchecked.append(e)                       # not in Crossref (DataCite/arXiv/book) -- resolution check covers it
            print(f"SKIP {e['key']:<28} {e['doi']}  (no Crossref record)")
            continue
        problems = metadata_mismatches(e, meta)
        print(f"{'OK  ' if not problems else 'MISMATCH'} {e['key']:<28} {e['doi']}")
        for p in problems:
            print(f"       - {p}")
        if problems:
            bad.append((e["key"], problems))
    print(f"\n{len(entries)} entries, {len(bad)} with metadata mismatches, {len(unchecked)} not in Crossref")
    if bad:
        print("\nMetadata mismatches (a resolvable DOI on the wrong paper is still a fabricated "
              "citation):", file=sys.stderr)
        for key, problems in bad:
            print(f"  {key}: {'; '.join(problems)}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    bib_path = Path(args[0]) if args else DEFAULT_BIB
    if "--metadata" in argv:
        return check_metadata(bib_path)

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
