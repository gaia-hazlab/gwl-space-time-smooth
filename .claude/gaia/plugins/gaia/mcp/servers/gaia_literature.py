# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.2", "httpx>=0.27"]
# ///
"""gaia-literature — MCP server for prior-art & citation lookup.

Tools (all keyless, via the public OpenAlex API; optional passthrough to the
group's local `gaia-kb` Graph-RAG CLI when installed):

  - search_works(query, ...)   find papers by topic/keywords; for prior-art surveys
  - work_by_doi(doi)           one work's metadata + citation/reference counts
  - cited_by(id_or_doi, ...)   who cites a work — for real-world uptake / impact
  - rag_query(question)        ask the local gaia-literature-kb (if `gaia-kb` is on PATH)

Serves the Literature Scout (prior-art), the Auditor (novelty grounding), the
Research Impact agent (uptake), and the Study Designer. Polite-pool email comes
from GAIA_OPENALEX_MAILTO (default below) so OpenAlex can contact us if a query
misbehaves; no API key is required.

Run standalone:  uv run --script gaia_literature.py
"""

from __future__ import annotations

import os
import shutil
import subprocess

import httpx
from mcp.server.fastmcp import FastMCP

OPENALEX = "https://api.openalex.org"
MAILTO = os.environ.get("GAIA_OPENALEX_MAILTO", "gaia-hazlab@uw.edu")
TIMEOUT = float(os.environ.get("GAIA_LIT_TIMEOUT", "30"))

mcp = FastMCP("literature")


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=OPENALEX,
        params={"mailto": MAILTO},
        timeout=TIMEOUT,
        headers={"User-Agent": f"gaia-literature-mcp (mailto:{MAILTO})"},
    )


def _abstract(inv_index: dict | None, max_words: int = 80) -> str:
    """Reconstruct an abstract from OpenAlex's inverted index (truncated)."""
    if not inv_index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inv_index.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    words = [w for _, w in positions[:max_words]]
    text = " ".join(words)
    return text + ("…" if len(positions) > max_words else "")


def _slim(work: dict) -> dict:
    """Compact a verbose OpenAlex work into the fields an agent actually needs."""
    return {
        "title": work.get("title"),
        "year": work.get("publication_year"),
        "doi": (work.get("doi") or "").replace("https://doi.org/", "") or None,
        "openalex_id": (work.get("id") or "").replace("https://openalex.org/", "") or None,
        "venue": ((work.get("primary_location") or {}).get("source") or {}).get("display_name"),
        "authors": [
            (a.get("author") or {}).get("display_name")
            for a in (work.get("authorships") or [])[:8]
        ],
        "cited_by_count": work.get("cited_by_count"),
        "is_open_access": (work.get("open_access") or {}).get("is_oa"),
        "abstract": _abstract(work.get("abstract_inverted_index")),
    }


@mcp.tool()
def search_works(query: str, limit: int = 10, from_year: int | None = None) -> list[dict]:
    """Search the literature for prior art on a topic.

    Args:
        query: free-text topic/keywords (e.g. "supershear rupture velocity estimation").
        limit: max results (1-25).
        from_year: only return works published in/after this year (optional).

    Returns a list of compact records (title, year, doi, venue, authors,
    cited_by_count, abstract snippet), most-cited first. Use this to ground a
    novelty claim or to survey what is already known.
    """
    limit = max(1, min(int(limit), 25))
    params: dict[str, str | int] = {
        "search": query,
        "per-page": limit,
        "sort": "cited_by_count:desc",
    }
    if from_year:
        params["filter"] = f"from_publication_date:{int(from_year)}-01-01"
    with _client() as c:
        r = c.get("/works", params=params)
        r.raise_for_status()
        results = r.json().get("results", [])
    return [_slim(w) for w in results]


@mcp.tool()
def work_by_doi(doi: str) -> dict:
    """Look up one work by DOI; returns its metadata plus citation and reference counts.

    Args:
        doi: a DOI (with or without the https://doi.org/ prefix).
    """
    doi = doi.strip().replace("https://doi.org/", "")
    with _client() as c:
        r = c.get(f"/works/https://doi.org/{doi}")
        if r.status_code == 404:
            return {"error": f"no work found for DOI {doi}"}
        r.raise_for_status()
        w = r.json()
    out = _slim(w)
    out["n_references"] = len(w.get("referenced_works") or [])
    return out


@mcp.tool()
def cited_by(id_or_doi: str, limit: int = 10) -> list[dict]:
    """Find works that cite a given paper — a proxy for real-world uptake / impact.

    Args:
        id_or_doi: an OpenAlex work id (e.g. W2741809807) or a DOI.
        limit: max citing works to return (1-25), most-cited first.
    """
    limit = max(1, min(int(limit), 25))
    ref = id_or_doi.strip()
    with _client() as c:
        if ref.upper().startswith("W"):
            oa_id = ref
        else:
            doi = ref.replace("https://doi.org/", "")
            rr = c.get(f"/works/https://doi.org/{doi}")
            if rr.status_code == 404:
                return [{"error": f"no work found for {ref}"}]
            rr.raise_for_status()
            oa_id = (rr.json().get("id") or "").replace("https://openalex.org/", "")
        r = c.get(
            "/works",
            params={"filter": f"cites:{oa_id}", "per-page": limit, "sort": "cited_by_count:desc"},
        )
        r.raise_for_status()
        results = r.json().get("results", [])
    return [_slim(w) for w in results]


@mcp.tool()
def rag_query(question: str) -> dict:
    """Query the group's local gaia-literature-kb Graph-RAG (if `gaia-kb` is installed).

    Falls back with a clear message when the CLI isn't on PATH, so the agent can
    use search_works() instead. Grounds answers in the group's curated corpus.
    """
    exe = shutil.which("gaia-kb")
    if not exe:
        return {
            "available": False,
            "note": "gaia-kb CLI not found on PATH; use search_works() for OpenAlex instead.",
        }
    try:
        proc = subprocess.run(
            [exe, "query", question],
            capture_output=True, text=True, timeout=120,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return {"available": True, "error": str(exc)}
    return {
        "available": True,
        "answer": proc.stdout.strip(),
        "stderr": proc.stderr.strip() or None,
        "returncode": proc.returncode,
    }


if __name__ == "__main__":
    mcp.run()
