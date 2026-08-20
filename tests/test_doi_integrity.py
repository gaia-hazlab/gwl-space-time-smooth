"""Tests for the DOI-integrity CI gate (``scripts/check_doi_integrity.py``, issue #158).

The gate's acceptance criterion is "CI goes red on an unresolvable DOI". Until this file
existed that was an *unverified claim*: nothing proved the script exits nonzero on a bad
DOI, nor that its regex catches every DOI-field syntax the real bib actually uses. These
tests convert the claim into a proven one.

OFFLINE BY CONSTRUCTION. No test here touches the network. Every test that reaches
``probe()``/``resolves()``/``check_canary()``/``check_gate()``/``main()`` goes through
:func:`_mocked_doi_org`, which swaps in a recorder that answers from a dict and raises on
any URL it was not told about -- so a leaked real request fails the test loudly instead of
silently phoning doi.org. The live check stays in the separate ``check-dois`` CI job
(``pixi run check-dois``); the ``test`` job must remain runnable on a machine with no
network at all (verified with ``unshare -rn``).

What the patch actually is, stated precisely because this file's value is rigour: the
script does ``import requests``, so ``doi_check.requests`` IS the process-wide ``requests``
module object, and assigning ``doi_check.requests.get`` mutates that singleton for every
importer in the process, not just for the module under test. It is restored in a ``finally``
and nothing else in this offline suite uses ``requests``, so it is safe as the suite is run
today (serially, one process). It is NOT safe under parallel in-process execution
(pytest-xdist ``--dist loadfile`` puts other files in other processes and is fine; a
threaded runner would not be). Do not describe this as module-local isolation -- it isn't.

The harness answers ONLY DOIs a test explicitly declared. There is no permissive catch-all
default: an undeclared DOI raises. That is the same failure mode the script's own canary
exists to catch -- a world that says "yes, resolves" to anything proves nothing -- and it
is not a hypothetical here: an earlier version of this harness defaulted every unknown DOI
to 302, which is precisely why it answered the gate's self-check probe with a redirect the
day that probe was added. Every DOI in ``CANARY_DOIS`` is likewise never served by the bulk
``default``; the canaries have their own ``canary=`` channel, defaulting to the real world's
404 (the STRICT answer), so a test running against a *broken* or *inconclusive* gate has to
say so out loud. A canary newly added to the script therefore inherits 404, never a
permissive answer -- pinned by
:func:`test_the_harness_never_answers_a_canary_from_the_permissive_default`.

Fake DOIs are all under the obviously-synthetic ``10.9999/...`` prefix so that no fixture
in this file can ever be mistaken for a real citation.

This file is the independent check on that script, so defects found in it are reported to
its owner and pinned here as current behaviour rather than patched from the test side,
which would hide them. Two such findings -- a conclusive 404 discarded by a transport blip
on a later retry, and check_gate() certifying off zero probes -- have since been FIXED by
the script's owner, so section 7 now states both positively, as the contract they became.
One finding remains pinned-not-endorsed: see
``test_known_extraction_limitations_are_pinned_not_endorsed``.

Runs standalone (``python -m tests.test_doi_integrity``); also pytest-discoverable.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import sys
import tempfile
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_doi_integrity.py"
REAL_BIB = REPO_ROOT / "docs" / "references.bib"


def _load_script():
    """Import the CI script by path -- ``scripts/`` is not an importable package.

    ``sys.modules[spec.name] = module`` before ``exec_module`` is not optional cargo cult:
    without it, anything in the script that re-enters its own module by name during
    execution breaks. ``@dataclass(frozen=True)`` is the concrete case -- it looks the
    module up in ``sys.modules`` to synthesise ``__eq__``/``__hash__`` and raises on a
    module that is not there yet, which took out all 22 tests at collection time once.
    Registering it first means the script is free to use whatever it likes and this loader
    is not silently dictating its implementation.
    """
    spec = importlib.util.spec_from_file_location("check_doi_integrity", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


doi_check = _load_script()

CANARY_DOIS = doi_check.CANARY_DOIS


def _canary_url(doi: str) -> str:
    return f"https://doi.org/{doi}"


CANARY_URLS = [_canary_url(d) for d in CANARY_DOIS]


# ---------------------------------------------------------------------------
# Offline harness
# ---------------------------------------------------------------------------

def _response(status: int) -> requests.Response:
    """A real ``requests.Response`` with a status code set.

    Deliberately a real Response, not a hand-rolled stub: ``.ok`` and ``.is_redirect``
    are then computed by requests itself, so the test asserts against the library's
    contract rather than against our belief about what a 302 means. doi.org sends a
    Location header with its 3xx handle-registry redirect and none with its 404, which
    is what is reproduced here.
    """
    r = requests.Response()
    r.status_code = status
    r.url = "https://doi.org/"
    if 300 <= status < 400:
        r.headers["Location"] = "https://example.invalid/landing-page"
    return r


class _FakeGet:
    """Stand-in for ``requests.get`` that answers from a table and never does I/O."""

    def __init__(self, outcomes: dict, default):
        # outcomes: doi -> status int | Exception instance | list of either (one per call)
        self.outcomes = dict(outcomes)
        self.default = default
        self.calls: list[tuple[str, dict]] = []

    def calls_for(self, doi: str) -> int:
        return sum(1 for url, _ in self.calls if url == f"https://doi.org/{doi}")

    @property
    def bib_calls(self) -> list:
        """Calls for DOIs from the bib, i.e. everything but the gate's self-check probes.

        Kept separate so that assertions about "what the gate did to references.bib"
        state a count of real citations and are not silently absorbing the self-check's
        request budget. Derived from ``CANARY_DOIS``, so a new canary is excluded
        automatically rather than leaking into the bib counts as a phantom citation.
        """
        return [c for c in self.calls if c[0] not in CANARY_URLS]

    @property
    def canary_calls(self) -> list:
        return [c for c in self.calls if c[0] in CANARY_URLS]

    def __call__(self, url, **kwargs):
        assert url.startswith("https://doi.org/"), f"unexpected non-doi.org request: {url}"
        self.calls.append((url, kwargs))
        doi = url[len("https://doi.org/") :]
        outcome = self.outcomes.get(doi, self.default)
        if isinstance(outcome, list):
            outcome = outcome[min(self.calls_for(doi) - 1, len(outcome) - 1)]
        if outcome is None:
            raise AssertionError(f"test did not declare an outcome for DOI {doi!r}")
        if isinstance(outcome, BaseException):
            raise outcome
        return _response(outcome)


def _canary_answers(overrides=None, others=404) -> dict:
    """A TOTAL answer table for the self-check: one entry per DOI in ``CANARY_DOIS``.

    ``overrides`` names the canaries a test wants to answer unusually; every other canary
    gets ``others``, which defaults to 404 -- the strict, real-world answer. Total by
    construction, and override keys are checked against ``CANARY_DOIS``, so a typo'd or
    stale canary name is an error rather than a silently-ignored entry that leaves the
    real canary on the default.
    """
    answers = {doi: others for doi in CANARY_DOIS}
    for doi, value in dict(overrides or {}).items():
        assert doi in CANARY_DOIS, f"{doi!r} is not in CANARY_DOIS: {CANARY_DOIS}"
        answers[doi] = value
    return answers


@contextlib.contextmanager
def _mocked_doi_org(outcomes=None, default=None, canary=404):
    """Replace ``requests.get`` with the offline recorder for the duration. Restores it.

    Note this mutates the process-wide ``requests`` module attribute (the script does
    ``import requests``, so ``doi_check.requests`` is that same module object) -- see the
    module docstring. Restored in ``finally``.

    ``outcomes`` maps DOI -> status / exception / list-per-call. ``default`` answers the
    DOIs a test does not enumerate one by one (the 71 in the real bib); it is ``None`` by
    default, which makes an undeclared DOI a loud AssertionError rather than an invented
    success. ``canary`` answers the DOIs in ``CANARY_DOIS`` and they NEVER fall through to
    ``default``: pass one value to give every canary the same answer, or a dict (built via
    :func:`_canary_answers`) to answer them individually. Default 404 = the healthy world,
    so "the gate is broken" / "the self-check was inconclusive" is always an explicit,
    visible choice in the calling test.
    """
    outcomes = dict(outcomes or {})
    for doi in CANARY_DOIS:
        assert doi not in outcomes, (
            f"declare canary {doi}'s answer with the canary= parameter, not via outcomes, "
            "so there is exactly one way to say it"
        )
    if isinstance(canary, dict):
        assert set(canary) == set(CANARY_DOIS), (
            "a dict canary= must answer every DOI in CANARY_DOIS exactly (use "
            f"_canary_answers): missing {sorted(set(CANARY_DOIS) - set(canary))}, "
            f"unknown {sorted(set(canary) - set(CANARY_DOIS))}"
        )
        outcomes.update(canary)
    else:
        for doi in CANARY_DOIS:
            outcomes[doi] = canary
    fake = _FakeGet(outcomes, default)
    original = doi_check.requests.get
    doi_check.requests.get = fake
    try:
        yield fake
    finally:
        doi_check.requests.get = original


@contextlib.contextmanager
def _captured():
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        yield out, err


@contextlib.contextmanager
def _bib_file(text: str):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "references.bib"
        p.write_text(text, encoding="utf-8")
        yield p


@contextlib.contextmanager
def _chdir(path):
    prior = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prior)


def _run_main(bib_path, outcomes=None, default=None, canary=404):
    """Run ``main()`` offline. Returns (exit_code, combined stdout+stderr, fake_get)."""
    with _mocked_doi_org(outcomes, default, canary) as fake, _captured() as (out, err):
        code = doi_check.main(["check_doi_integrity.py", str(bib_path)])
    return code, out.getvalue() + err.getvalue(), fake


def _real_dois() -> list[str]:
    """The DOIs in the real bib. Explicit encoding: the file contains non-ASCII bytes
    (accented author names), so a bare read_text() is at the mercy of the locale --
    the script itself was fixed for exactly this."""
    return doi_check.extract_dois(REAL_BIB.read_text(encoding="utf-8"))


# Three entries, three different BibTeX DOI syntaxes, all obviously synthetic DOIs.
BAD = "10.9999/definitely-not-real-two"
SYNTHETIC_BIB = """
@article{synthetic_one,
  title={Synthetic entry, test fixture only -- not a citation},
  doi={10.9999/definitely-not-real-one}
}

@article{synthetic_two,
  title={Synthetic entry, test fixture only -- not a citation},
  doi = {10.9999/definitely-not-real-two},
}

@article{synthetic_three,
  title={Synthetic entry, test fixture only -- not a citation},
  DOI = "10.9999/definitely-not-real-three"
}
"""
SYNTHETIC_DOIS = [
    "10.9999/definitely-not-real-one",
    BAD,
    "10.9999/definitely-not-real-three",
]

# Requests that main()'s gate self-check costs before it touches the first real DOI.
# Every canary is probed (check_gate does not short-circuit), and a healthy canary answers
# with an HTTP error status, which probe() treats as a non-resolution and therefore retries
# -- so each probe spends its whole budget: one attempt plus RETRIES retries.
#
# Written as that RELATIONSHIP rather than as the literal number it currently equals, so
# that adding a canary or raising RETRIES does not break the totals below, while a change
# to *whether every canary is probed, or whether a 404 is retried* does -- which is the
# change that would matter. Vacuity of the counts is guarded in
# test_the_canaries_are_probed_before_any_real_doi_and_cost_a_known_number_of_requests.
SELF_CHECK_REQUESTS = len(CANARY_DOIS) * (doi_check.RETRIES + 1)
PER_CANARY_REQUESTS = doi_check.RETRIES + 1


# ---------------------------------------------------------------------------
# 1. THE acceptance criterion: red on an unresolvable DOI, and it says which one
# ---------------------------------------------------------------------------

def test_main_exits_nonzero_and_names_the_doi_that_does_not_resolve():
    """#158's acceptance criterion. One DOI 404s, the rest 302 -> nonzero + named."""
    with _bib_file(SYNTHETIC_BIB) as bib:
        code, output, fake = _run_main(bib, outcomes={BAD: 404}, default=302)

        assert code != 0, "gate stayed green with an unresolvable DOI in the bib"
        assert code == 1
        assert BAD in output, "the failing DOI is not named anywhere in the output"
        assert f"FAIL {BAD}" in output
        assert "HTTP 404" in output, "the reason for the failure is not reported"
        assert "3 DOIs checked, 1 failed" in output
        # the DOIs that DO resolve must not be smeared as failures
        for good in (SYNTHETIC_DOIS[0], SYNTHETIC_DOIS[2]):
            assert f"OK   {good}" in output or f"OK  {good}" in output
        assert all(u.startswith("https://doi.org/") for u, _ in fake.calls)

        # Non-vacuity control: the SAME bib with the SAME harness, only the 404 removed,
        # must go green. That proves the red above came from the bad DOI and not from
        # some incidental property of the fixture or the mock.
        control_code, control_out, _ = _run_main(bib, outcomes={}, default=302)
        assert control_code == 0, control_out


def test_real_references_bib_goes_red_when_one_of_its_dois_stops_resolving():
    """Same criterion, exercised against the REAL docs/references.bib, not a fixture."""
    dois = _real_dois()
    assert dois, "no DOIs extracted from the real bib -- fixture/path problem"
    victim = dois[0]

    code, output, fake = _run_main(REAL_BIB, outcomes={victim: 404}, default=302)
    assert code == 1
    assert f"FAIL {victim}" in output
    assert f"{len(dois)} DOIs checked, 1 failed" in output
    assert "Unresolvable DOIs" in output

    ok_code, ok_out, _ = _run_main(REAL_BIB, outcomes={}, default=302)
    assert ok_code == 0, ok_out


# ---------------------------------------------------------------------------
# 2. Green when everything resolves (2xx AND 3xx both count as pass)
# ---------------------------------------------------------------------------

def test_main_returns_zero_when_every_doi_resolves_2xx_or_3xx():
    with _bib_file(SYNTHETIC_BIB) as bib:
        code, output, fake = _run_main(
            bib,
            outcomes={
                SYNTHETIC_DOIS[0]: 200,  # 2xx
                SYNTHETIC_DOIS[1]: 301,  # permanent redirect
                SYNTHETIC_DOIS[2]: 303,  # see-other
            },
        )
    assert code == 0, output
    assert "3 DOIs checked, 0 failed" in output
    assert "FAIL" not in output
    # A resolving DOI costs exactly one request -- stated twice, on purpose. The first
    # form is the claim itself, isolated from the gate self-check. The second pins the
    # total, so that a request made by some *new* part of main() cannot hide inside a
    # loose count.
    assert len(fake.bib_calls) == 3, "a resolving DOI should cost exactly one request"
    assert len(fake.calls) == SELF_CHECK_REQUESTS + 3, "unaccounted-for requests"


def test_requests_are_made_the_way_the_script_documents():
    """allow_redirects=False is load-bearing: following the redirect hits publisher
    landing pages that 403 bots, which would be indistinguishable from a dead DOI."""
    with _bib_file(SYNTHETIC_BIB) as bib:
        code, _, fake = _run_main(bib, default=302)
    assert code == 0
    # every request, the gate's own self-check probes included
    assert len(fake.calls) == SELF_CHECK_REQUESTS + 3
    for url, kwargs in fake.calls:
        assert kwargs["allow_redirects"] is False
        assert kwargs["timeout"] == doi_check.TIMEOUT_S
        assert "User-Agent" in kwargs["headers"]


def test_resolves_reports_status_detail_for_the_report_line():
    """``resolves()`` is now a thin wrapper over ``probe()``; its (bool, str) contract and
    the exact detail strings are what main()'s report lines are built from, so they are
    pinned here byte-for-byte."""
    with _mocked_doi_org({"10.9999/a": 302, "10.9999/b": 200, "10.9999/c": 404}):
        assert doi_check.resolves("10.9999/a") == (True, "302")
        assert doi_check.resolves("10.9999/b") == (True, "200")
        assert doi_check.resolves("10.9999/c") == (False, "HTTP 404")


def test_probe_returns_a_structured_result_so_callers_need_not_sniff_strings():
    """The classification path is structural now. Pin the structure, not the prose:
    a caller deciding on ``detail.startswith("HTTP ")`` was the fragility that got
    replaced, and ``status`` is what distinguishes "doi.org said 404" from "the request
    never completed" -- a distinction the detail string alone cannot carry."""
    boom = requests.RequestException("simulated connection reset")
    with _mocked_doi_org({"10.9999/a": 302, "10.9999/c": 404, "10.9999/x": boom}):
        redirected = doi_check.probe("10.9999/a")
        absent = doi_check.probe("10.9999/c")
        unreachable = doi_check.probe("10.9999/x")

    assert redirected.doi == "10.9999/a"
    assert (redirected.resolved, redirected.status) == (True, 302)
    assert redirected.error == ""
    assert (absent.resolved, absent.status, absent.error) == (False, 404, "")
    # status is None <=> every attempt raised; that is the "measured nothing" signal.
    assert (unreachable.resolved, unreachable.status) == (False, None)
    assert "simulated connection reset" in unreachable.error
    assert unreachable.detail == unreachable.error, "transport error text must survive"


# ---------------------------------------------------------------------------
# 3. Network exceptions are failures, not silent passes -- and retries happen
# ---------------------------------------------------------------------------

def test_network_exception_on_every_retry_is_a_failure_not_a_silent_pass():
    boom = requests.RequestException("simulated connection reset")
    with _bib_file(SYNTHETIC_BIB) as bib:
        code, output, fake = _run_main(bib, outcomes={BAD: boom}, default=302)

    assert code == 1, "an exception on every attempt was swallowed into a green run"
    assert f"FAIL {BAD}" in output
    assert "simulated connection reset" in output, "the exception text was discarded"
    # retries actually happen: RETRIES additional attempts after the first
    assert fake.calls_for(BAD) == doi_check.RETRIES + 1
    assert doi_check.RETRIES >= 1, "RETRIES=0 would make the count assertion vacuous"


def test_a_transient_exception_is_survived_by_the_retry():
    """Complement to the test above: proves the retry loop is real, not just counted."""
    boom = requests.RequestException("transient DNS blip")
    with _bib_file(SYNTHETIC_BIB) as bib:
        code, output, fake = _run_main(bib, outcomes={BAD: [boom, 302]}, default=302)
    assert code == 0, output
    assert fake.calls_for(BAD) == 2, "did not retry after a transient failure"


def test_error_status_is_also_retried_before_being_reported():
    with _mocked_doi_org({"10.9999/gone": 500}) as fake:
        ok, detail = doi_check.resolves("10.9999/gone")
    assert ok is False and detail == "HTTP 500"
    assert fake.calls_for("10.9999/gone") == doi_check.RETRIES + 1


# ---------------------------------------------------------------------------
# 4. Extraction coverage against the REAL bib, derived non-circularly
# ---------------------------------------------------------------------------

def _independent_doi_fields(bib_text: str) -> list[tuple[str, str, str]]:
    """Line-oriented, regex-free scan for DOI field assignments.

    Deliberately derived a DIFFERENT way from the script's ``DOI_RE`` (split on '=',
    compare the key, peel the delimiter with string ops) so that comparing the two is
    not circular: a bug in DOI_RE cannot hide inside this function.

    Returns (key_as_written, delimiter, value) per field. Comment lines are NOT counted,
    because ``% doi={...}`` is not a live citation -- see the known-limitations test.
    """
    fields = []
    for raw in bib_text.splitlines():
        line = raw.strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip().lower() != "doi":
            continue
        value = value.strip().rstrip(",").strip()
        if not value or value[0] not in "{\"":
            continue
        closer = "}" if value[0] == "{" else '"'
        end = value.find(closer, 1)
        if end == -1:
            continue
        fields.append((key.strip(), value[0], value[1:end].strip()))
    return fields


# Coverage floor for the non-circular comparison below. The real bib has 71 DOI fields
# today (verified at the time of writing; 20 distinct registrant prefixes).
#
# WHY THIS NUMBER EXISTS AND WHY IT IS HIGH: the assertion underneath it compares two
# independently-derived DOI lists. That comparison is only as strong as the number of DOIs
# it compares -- if references.bib were reduced to two entries, DOI_RE could start missing
# most syntaxes and the comparison would still pass on the two that remain. The floor is
# what stops the *test* from quietly becoming vacuous as the bib changes. It was 20 against
# an actual 71, which meant 51 DOI fields -- 72% of the gate's coverage -- could disappear
# with the suite still green; the Auditor flagged that, correctly.
#
# 65 is chosen as 71 minus a small editorial margin: this bib's own provenance comments
# record entries being REMOVED when their DOI turned out to be fabricated, so the count can
# legitimately drop a little, and the check-dois job should not be blocked by the test suite
# while that happens. Six is roughly two such removals plus slack. Any larger drop is not
# editorial churn, it is a regression in what CI covers, and it should stop the suite.
#
# DO NOT LOWER THIS TO MAKE A FAILURE GO AWAY. If it fails, either the bib really lost that
# many citations (find out why) or extraction/paths broke (find out where). Raise it when
# the bib grows.
MIN_REAL_DOI_FIELDS = 65


def test_extract_dois_finds_every_doi_field_in_the_real_references_bib():
    """Empirical, non-circular coverage check on the real file.

    If this fails after someone edits references.bib, the bib has grown a DOI-field
    syntax that one of the two extractors handles and the other does not -- i.e. either
    the CI gate is skipping a citation (false green) or it is checking something that is
    not a live citation. Either way, look before "fixing" the test.
    """
    text = REAL_BIB.read_text(encoding="utf-8")
    independent = [value for _, _, value in _independent_doi_fields(text)]
    extracted = doi_check.extract_dois(text)

    assert len(independent) >= MIN_REAL_DOI_FIELDS, (
        f"independent scan found only {len(independent)} DOI fields in {REAL_BIB}, below "
        f"the floor of {MIN_REAL_DOI_FIELDS}; the comparison below would no longer be "
        "covering the gate's real surface (vacuity guard -- read the comment above it "
        "before touching the number)"
    )
    missed = set(independent) - set(extracted)
    spurious = set(extracted) - set(independent)
    assert not missed, f"DOI_RE MISSES these real DOI fields (false green): {sorted(missed)}"
    assert not spurious, f"DOI_RE extracts non-fields: {sorted(spurious)}"
    assert extracted == independent, "same DOIs but different order/multiplicity"


def test_every_doi_in_the_real_bib_is_well_formed_after_extraction():
    for doi in _real_dois():
        assert doi.startswith("10."), f"not a DOI: {doi!r}"
        assert doi == doi.strip(), f"delimiters/whitespace leaked into {doi!r}"
        assert not any(c in doi for c in '{}"\n\t'), f"stray delimiter in {doi!r}"


def test_real_bib_uses_no_doi_field_syntax_that_is_left_untested():
    """Canary: if references.bib ever grows a key spelling or delimiter that the
    variant unit test below does not cover, this fails and someone must extend it."""
    fields = _independent_doi_fields(REAL_BIB.read_text(encoding="utf-8"))
    assert fields
    for key, delim, _ in fields:
        assert key.lower() == "doi", f"unexpected DOI key spelling {key!r}"
        assert delim in "{\"", f"unexpected value delimiter {delim!r}"


def test_extract_dois_handles_every_bibtex_syntax_variant():
    cases = {
        "  doi={10.9999/brace-no-space}\n": ["10.9999/brace-no-space"],
        "  doi = {10.9999/brace-spaced},\n": ["10.9999/brace-spaced"],
        '  doi = "10.9999/double-quoted"\n': ["10.9999/double-quoted"],
        "  DOI = {10.9999/upper-key}\n": ["10.9999/upper-key"],
        "  Doi={10.9999/mixed-key}\n": ["10.9999/mixed-key"],
        "  doi\t=\t{  10.9999/tabs-and-padding  },\n": ["10.9999/tabs-and-padding"],
        '  DOI="10.9999/upper-and-quoted",\n': ["10.9999/upper-and-quoted"],
    }
    for text, expected in cases.items():
        assert doi_check.extract_dois(text) == expected, f"failed on {text!r}"

    multi = "@a{k,\n doi={10.9999/first}\n}\n@b{k2,\n DOI = \"10.9999/second\"\n}\n"
    assert doi_check.extract_dois(multi) == ["10.9999/first", "10.9999/second"]


def test_known_extraction_limitations_are_pinned_not_endorsed():
    """Documents current behaviour on syntaxes NOT present in references.bib today.

    These are reported to the owner of the script, not fixed here. They matter only if
    the bib later grows one of these forms.
    """
    # (a) An empty DOI field is silently skipped rather than flagged.
    assert doi_check.extract_dois("  doi = {}\n") == []
    # (b) A commented-out DOI is still extracted and would still be resolved, so
    #     commenting out a known-bad citation would keep CI red.
    assert doi_check.extract_dois("% doi = {10.9999/commented-out}\n") == [
        "10.9999/commented-out"
    ]
    # (c) DOIs carried only in a url field are out of scope and never checked.
    assert doi_check.extract_dois("  url = {https://doi.org/10.9999/url-only}\n") == []
    # (d) A value containing a closing brace truncates at the brace.
    assert doi_check.extract_dois("  doi = {10.9999/a}b}\n") == ["10.9999/a"]


# ---------------------------------------------------------------------------
# 5. The gate must not pass vacuously
# ---------------------------------------------------------------------------

def test_no_doi_fields_found_is_a_hard_failure():
    """Guards against a green run when the bib path is wrong or the file was renamed."""
    for label, text in {
        "empty file": "",
        "entries without DOIs": "@book{x,\n  title={No DOI here},\n  year={1957}\n}\n",
        "DOIs only mentioned in prose": (
            "% Every DOI in this file was verified; see api.crossref.org/works/{doi}.\n"
            "@misc{y,\n  note={the doi was unregistered and the entry was removed}\n}\n"
        ),
    }.items():
        with _bib_file(text) as bib:
            code, output, fake = _run_main(bib)
        assert code != 0, f"gate passed vacuously on: {label}"
        assert "no DOI fields found" in output, label
        assert str(bib) in output, "the offending path is not named"
        assert fake.calls == [], (
            "made a request despite finding no DOIs -- the cheap offline checks must "
            "short-circuit before even the gate self-check probes"
        )


def test_a_missing_bib_file_fails_loudly_rather_than_passing():
    missing = REPO_ROOT / "docs" / "references-does-not-exist.bib"
    assert not missing.exists()
    try:
        with _mocked_doi_org(), _captured():
            doi_check.main(["check_doi_integrity.py", str(missing)])
    except FileNotFoundError:
        return
    raise AssertionError("a missing bib file did not fail the gate")


def test_default_bib_path_is_the_real_one_when_run_the_way_ci_runs_it():
    """`pixi run check-dois` passes no argv, so DEFAULT_BIB must resolve from repo root."""
    assert doi_check.DEFAULT_BIB == Path("docs/references.bib")
    expected = len(_real_dois())
    with _chdir(REPO_ROOT):
        with _mocked_doi_org(default=302) as fake, _captured() as (out, err):
            code = doi_check.main(["scripts/check_doi_integrity.py"])
    assert code == 0, out.getvalue() + err.getvalue()
    assert len(fake.bib_calls) == expected, "did not check every DOI in the default bib"
    assert len(fake.calls) == SELF_CHECK_REQUESTS + expected, "unaccounted-for requests"
    assert f"{expected} DOIs checked, 0 failed" in out.getvalue()


# ---------------------------------------------------------------------------
# 6. The gate's own self-check (the canaries)
#
# The script's central assumption is that doi.org answers an UNREGISTERED DOI with a status
# >= 400. Everything else rests on it: resolves() passes anything < 400, so if that
# assumption ever stopped holding, resolves() would return True for every input and this
# gate would report "OK" for fabricated DOIs, forever, silently. check_gate() turns that
# assumption into a live measurement against every DOI in CANARY_DOIS, and grades it three
# ways: VERIFIED (a conclusive 404/410 -- the gate demonstrably still discriminates),
# BROKEN (doi.org accepted a DOI that cannot exist), INCONCLUSIVE (the probe measured
# nothing). Only VERIFIED may certify a clean bib.
#
# These tests prove the measurement is load-bearing -- offline, by mocking doi.org's answer
# to it. They assert on GateStatus members, not on message wording.
# ---------------------------------------------------------------------------

def _ok_line(doi: str) -> str:
    """The per-DOI success line main() prints, i.e. the gate certifying that DOI."""
    return f"OK   {doi}"


def _classify(status_or_exc, doi):
    """Run the REAL ``check_canary`` against a mocked doi.org answer for ``doi``."""
    answers = _canary_answers({doi: status_or_exc})
    with _mocked_doi_org(outcomes={}, default=None, canary=answers):
        return doi_check.check_canary(doi)


def test_there_is_more_than_one_canary_and_each_covers_a_distinct_lookup_path():
    """WHY there are two probes -- pinned structurally, because a single-probe gate is a
    gate with a blind spot and nothing else in the suite would notice the collapse.

    doi.org's handle proxy resolves in two stages: find the naming authority (prefix),
    then find the handle (suffix) under it. Those can regress independently, and the
    dangerous one is the second: every fabricated DOI in this bib's provenance history was
    a REAL prefix with a bogus suffix. A gate whose only probe used an unassigned prefix
    would keep reporting healthy if doi.org started serving HTTP 200 "not registered with
    $PUBLISHER" for unknown suffixes under known prefixes -- and would then pass every
    fabricated DOI. So the canary set must cover both stages.
    """
    assert len(CANARY_DOIS) >= 2, (
        "the canary set collapsed to a single probe; see this test's docstring -- one "
        "probe cannot cover both of doi.org's lookup stages"
    )
    assert len(set(CANARY_DOIS)) == len(CANARY_DOIS), "duplicate canaries probe nothing new"

    real_prefixes = {doi.split("/")[0] for doi in _real_dois()}
    assert real_prefixes, "no DOIs in the real bib -- cannot judge canary prefix coverage"
    canary_prefixes = {doi.split("/")[0] for doi in CANARY_DOIS}

    unknown_authority = canary_prefixes - real_prefixes
    known_authority = canary_prefixes & real_prefixes
    assert unknown_authority, (
        "no canary uses a prefix that is absent from references.bib, so the "
        "unknown-naming-authority lookup path is unprobed"
    )
    assert known_authority, (
        "no canary uses a prefix that real citations in references.bib actually use, so "
        "the unknown-suffix-under-a-known-authority path -- the shape every fabricated "
        "DOI in this file's history had -- is unprobed"
    )
    # The unassignable prefix must stay unassignable, or the self-check could one day go
    # green against a handle that really got registered.
    assert "10.0000" in unknown_authority, (
        "the canary set no longer includes a probe under the unassignable 10.0000 prefix"
    )


def test_every_canary_is_a_probe_and_never_a_citation():
    """Cheap guard that no deliberately-invalid probe leaks into the bibliography (where
    it would be an unresolvable DOI -- exactly what this gate exists to catch)."""
    text = REAL_BIB.read_text(encoding="utf-8")
    extracted = doi_check.extract_dois(text)
    assert CANARY_DOIS, "there are no canaries at all"
    for doi in CANARY_DOIS:
        assert doi not in text, f"canary probe {doi} appears in references.bib"
        assert doi not in extracted, f"canary probe {doi} is extracted as a citation"
    assert "10.0000" not in text, "a DOI under the unassignable 10.0000 prefix is cited"
    # The 10.1029 canary deliberately SHARES a prefix with real citations, so a substring
    # check on the prefix alone would be wrong here -- the full-DOI checks above are the
    # right granularity. Assert that overlap is real, so this comment cannot rot.
    assert any(d.startswith("10.1029/") for d in extracted), (
        "no 10.1029 citations left in the bib; the known-authority canary's prefix should "
        "track a prefix the bib actually uses"
    )


def test_check_canary_classifies_every_doi_org_answer_by_what_it_proves():
    """The three-state classification table, driven through the real ``check_canary``.

    Structural: asserts GateStatus members, never message text. Run for EVERY canary, so
    a new probe cannot arrive with different semantics from the existing ones.

      resolved (anything < 400, redirect or not) -> BROKEN       (gate cannot discriminate)
      conclusive absence (404/410)               -> VERIFIED     (gate demonstrably works)
      any other status (403/429/5xx)             -> INCONCLUSIVE (measured nothing)
      every attempt raised                       -> INCONCLUSIVE (measured nothing)
    """
    S = doi_check.GateStatus
    # 204: ok=True without being a redirect; 301/302: is_redirect=True; 399: the top
    # boundary of "< 400". Both branches of ``r.is_redirect or r.ok`` are covered.
    resolving = (200, 204, 301, 302, 399)
    inconclusive = (403, 429, 500, 503)
    assert 404 in doi_check.CONCLUSIVE_ABSENT, (
        "404 -- the answer doi.org actually gives for an unregistered DOI, measured live "
        "-- is no longer treated as conclusive; the self-check can never be VERIFIED"
    )
    assert 410 in doi_check.CONCLUSIVE_ABSENT
    for status in resolving + inconclusive:
        assert status not in doi_check.CONCLUSIVE_ABSENT, (
            f"HTTP {status} is in CONCLUSIVE_ABSENT, which contradicts this table"
        )

    for doi in CANARY_DOIS:
        for status in resolving:
            got, _ = _classify(status, doi)
            assert got is S.BROKEN, f"{doi} @ HTTP {status}: expected BROKEN, got {got}"
        # Driven from the constant, so widening CONCLUSIVE_ABSENT is exercised, not missed.
        for status in sorted(doi_check.CONCLUSIVE_ABSENT):
            got, _ = _classify(status, doi)
            assert got is S.VERIFIED, f"{doi} @ HTTP {status}: expected VERIFIED, got {got}"
        for status in inconclusive:
            got, _ = _classify(status, doi)
            assert got is S.INCONCLUSIVE, (
                f"{doi} @ HTTP {status}: expected INCONCLUSIVE (the probe measured nothing "
                f"about doi.org's 404 semantics), got {got}"
            )
        got, message = _classify(requests.RequestException("probe never completed"), doi)
        assert got is S.INCONCLUSIVE, f"{doi} @ transport failure: got {got}"
        assert "probe never completed" in message, "the transport error text was discarded"


def test_check_gate_probes_every_canary_and_returns_the_worst_status():
    """No short-circuit, and worst-wins.

    Short-circuiting on the first canary would silently un-probe the others -- the exact
    blind spot the second canary was added to close. And a gate that averaged, or took the
    last, or took the first answer would let one healthy probe mask a broken one.
    Precedence: BROKEN > INCONCLUSIVE > VERIFIED.
    """
    S = doi_check.GateStatus
    first, last = CANARY_DOIS[0], CANARY_DOIS[-1]

    def run(answers):
        with _mocked_doi_org(outcomes={}, default=None, canary=answers) as fake:
            status, lines = doi_check.check_gate()
        return status, lines, fake

    # (a) all conclusive -> VERIFIED, one report line per canary, every canary probed
    status, lines, fake = run(_canary_answers())
    assert status is S.VERIFIED
    assert len(lines) == len(CANARY_DOIS), "one report line per canary"
    for doi in CANARY_DOIS:
        assert fake.calls_for(doi) == PER_CANARY_REQUESTS, f"{doi} was not fully probed"

    # (b) FIRST canary already BROKEN -> every later canary is STILL probed. This is the
    #     anti-short-circuit assertion: it fails if check_gate returns on first BROKEN.
    status, lines, fake = run(_canary_answers({first: 200}))
    assert status is S.BROKEN
    for doi in CANARY_DOIS:
        assert fake.calls_for(doi) >= 1, (
            f"check_gate short-circuited: {doi} was never probed after an earlier canary "
            "came back BROKEN"
        )
    assert len(lines) == len(CANARY_DOIS)

    # (c) a LATER canary broken while the first is healthy -> still BROKEN (one healthy
    #     probe must not mask a broken one)
    status, _, fake = run(_canary_answers({last: 302}))
    assert status is S.BROKEN
    assert fake.calls_for(last) >= 1

    # (d) worst-wins between the two non-VERIFIED states
    assert run(_canary_answers({first: 200, last: 403}))[0] is S.BROKEN
    assert run(_canary_answers({first: 403, last: 200}))[0] is S.BROKEN
    # (e) one VERIFIED + one INCONCLUSIVE -> INCONCLUSIVE. Partial verification is not
    #     verification: the unprobed lookup path is exactly where a regression could hide.
    assert run(_canary_answers({last: 403}))[0] is S.INCONCLUSIVE
    assert run(_canary_answers({first: 403}))[0] is S.INCONCLUSIVE
    boom = requests.RequestException("self-check probe timed out")
    assert run(_canary_answers({last: boom}))[0] is S.INCONCLUSIVE


def test_canaries_are_probed_in_declared_order():
    """The declared order is the documented probe order (unknown authority first, then
    unknown suffix under a known authority). Pinned because the report lines and the
    request sequence are how a human reading a red CI log works out which lookup path
    broke."""
    with _bib_file(SYNTHETIC_BIB) as bib:
        code, _, fake = _run_main(bib, outcomes={}, default=302)
    assert code == 0
    probed_order = []
    for url, _ in fake.canary_calls:
        if url not in probed_order:
            probed_order.append(url)
    assert probed_order == CANARY_URLS, (
        f"canaries were probed in a different order than declared: {probed_order}"
    )


def test_gate_refuses_to_certify_any_doi_when_doi_org_accepts_a_canary():
    """THE test for the original finding. A canary that resolves means resolves() can no
    longer tell a good DOI from a fabricated one, so every "OK" line would be a false
    certification. The gate must then report NOTHING about references.bib and exit red.

    Run against the REAL docs/references.bib, because those are the citations that would be
    falsely certified. All four accepting statuses are exercised: resolves() passes on
    ``r.is_redirect or r.ok``, which is two distinct branches (3xx vs any other < 400), and
    a gate that caught only one of them would still be broken in the other.
    """
    real_dois = _real_dois()
    assert real_dois, "no DOIs in the real bib -- there would be nothing to falsely certify"

    for accepting_status in (200, 204, 301, 302):
        code, output, fake = _run_main(
            REAL_BIB, outcomes={}, default=302, canary=accepting_status
        )
        ctx = f"every canary answered HTTP {accepting_status}"

        assert code != 0, f"{ctx}: gate went green while unable to detect a bad DOI"
        assert code == 1, ctx
        assert "DOI GATE NOT FUNCTIONING" in output, f"{ctx}: the failure was not loud"
        for doi in CANARY_DOIS:
            assert doi in output, f"{ctx}: the message does not name canary {doi}"

        # The point of the finding: it must refuse to certify what it cannot verify.
        assert "OK  " not in output, f"{ctx}: certified a DOI it could not actually verify"
        assert "DOIs checked" not in output, f"{ctx}: printed a summary tally anyway"
        for doi in real_dois:
            assert doi not in output, f"{ctx}: reported on {doi} without being able to check it"
        assert fake.bib_calls == [], f"{ctx}: probed real DOIs after the gate was known broken"

    # Non-vacuity control: same bib, same harness, ONLY the canaries' answer changed back
    # to the real world's 404 -- now it does certify, and does so for every DOI. This is
    # what proves the red above came from the canaries and not from the fixture or the mock.
    ok_code, ok_out, ok_fake = _run_main(REAL_BIB, outcomes={}, default=302, canary=404)
    assert ok_code == 0, ok_out
    assert _ok_line(real_dois[0]) in ok_out
    assert f"{len(real_dois)} DOIs checked, 0 failed" in ok_out
    assert len(ok_fake.bib_calls) == len(real_dois)


def test_one_broken_canary_condemns_the_gate_even_when_the_other_is_healthy():
    """THE test for why there are two canaries -- a prefix-specific regression.

    The concrete scenario, and its mirror:
      * 10.0000/... (unassigned prefix)      -> 404, looks perfectly healthy
        10.1029/... (real prefix, bogus suffix) -> 200 "not registered with $PUBLISHER"
      * and the reverse.

    In the first case doi.org would accept every fabricated DOI in this bib's provenance
    history (real prefix, invented suffix) while a single-probe gate on 10.0000 reported
    all-clear. That is not hypothetical: it is the failure mode the second canary was added
    for. So each canary alone must be able to condemn the gate, and the run must produce NO
    per-DOI output and touch NO real DOI.

    Run against the REAL bib -- the falsely-certified citations would be these.
    """
    # Precondition, not decoration: if the canary set stopped covering both of doi.org's
    # lookup stages (e.g. collapsed back to one probe), the loop below would no longer be
    # exercising a prefix-specific regression and this test would be theatre.
    real_dois = _real_dois()
    real_prefixes = {doi.split("/")[0] for doi in real_dois}
    canary_prefixes = {doi.split("/")[0] for doi in CANARY_DOIS}
    assert len(CANARY_DOIS) >= 2, (
        "single-probe gate: a prefix-specific regression is invisible"
    )
    assert canary_prefixes - real_prefixes, "no canary probes an unknown naming authority"
    assert canary_prefixes & real_prefixes, (
        "no canary probes an unknown suffix under a naming authority the bib really uses; "
        "that is the shape every fabricated DOI in this bib's history had"
    )

    for broken in CANARY_DOIS:
        healthy = [d for d in CANARY_DOIS if d != broken]
        code, output, fake = _run_main(
            REAL_BIB,
            outcomes={},
            default=302,
            canary=_canary_answers({broken: 200}),  # others stay at the healthy 404
        )
        ctx = f"canary {broken} answered HTTP 200 while {healthy} answered 404"

        assert code != 0, f"{ctx}: gate went green with a demonstrably broken lookup path"
        assert code == 1, ctx
        assert "DOI GATE NOT FUNCTIONING" in output, f"{ctx}: the failure was not loud"
        assert broken in output, f"{ctx}: the broken canary is not named"
        assert "OK  " not in output, f"{ctx}: certified DOIs it could not verify"
        assert "DOIs checked" not in output, f"{ctx}: printed a summary tally anyway"
        for doi in real_dois:
            assert doi not in output, f"{ctx}: reported on {doi} it could not check"
        assert fake.bib_calls == [], f"{ctx}: spent requests on real DOIs after BROKEN"

        # Structural confirmation at the check_gate level, independent of any wording.
        with _mocked_doi_org(canary=_canary_answers({broken: 200})):
            status, _ = doi_check.check_gate()
        assert status is doi_check.GateStatus.BROKEN, ctx

    # Non-vacuity control: with NO canary broken the same bib certifies cleanly, so the
    # reds above came from the single flipped canary and nothing else.
    ok_code, ok_out, _ = _run_main(REAL_BIB, outcomes={}, default=302, canary=404)
    assert ok_code == 0, ok_out


def test_correctly_unresolvable_canaries_let_the_run_proceed_and_report():
    """The healthy case: EVERY canary 404s, so the gate is verified and says so."""
    with _bib_file(SYNTHETIC_BIB) as bib:
        code, output, fake = _run_main(
            bib, outcomes={}, default=302, canary=_canary_answers()
        )

    assert code == 0, output
    assert f"gate self-check: {doi_check.GateStatus.VERIFIED.value}" in output
    assert "HTTP 404" in output, "the canaries' actual status is not reported"
    for doi in CANARY_DOIS:
        assert doi in output, f"canary {doi} is not named in the self-check report"
        assert fake.calls_for(doi) == PER_CANARY_REQUESTS, f"{doi} was not fully probed"
    assert "3 DOIs checked, 0 failed" in output
    assert len(fake.bib_calls) == 3
    assert len(fake.canary_calls) == SELF_CHECK_REQUESTS

    # 410 is the other conclusive absence; the gate must be verifiable by it too, or
    # CONCLUSIVE_ABSENT is decorative.
    with _bib_file(SYNTHETIC_BIB) as bib:
        code_410, out_410, _ = _run_main(bib, outcomes={}, default=302, canary=410)
    assert code_410 == 0, out_410
    assert f"gate self-check: {doi_check.GateStatus.VERIFIED.value}" in out_410


def test_the_canaries_are_probed_before_any_real_doi_and_cost_a_known_number_of_requests():
    """Ordering matters: a gate that certified DOIs first and self-checked afterwards
    would still print the false OK lines. Pin the order and the cost.

    The cost is asserted as ``len(CANARY_DOIS) * (RETRIES + 1)`` -- the RELATIONSHIP, not
    the number it happens to equal today (6). What is pinned is "every canary is probed,
    and a conclusive-absence answer still burns the full retry budget because probe() only
    returns early on a resolution". Adding a canary or changing RETRIES moves the number
    without breaking the claim; skipping a canary or not retrying breaks the claim.
    """
    assert doi_check.RETRIES >= 1 and len(CANARY_DOIS) >= 2, (
        "RETRIES=0 or a single canary would make the request counts in this file vacuous"
    )
    assert SELF_CHECK_REQUESTS == len(CANARY_DOIS) * (doi_check.RETRIES + 1)

    with _bib_file(SYNTHETIC_BIB) as bib:
        code, _, fake = _run_main(bib, outcomes={}, default=302, canary=404)

    assert code == 0
    urls = [u for u, _ in fake.calls]
    # The self-check occupies the whole prefix of the request stream, canary by canary in
    # declared order, before a single real DOI is touched.
    expected_prefix = [u for u in CANARY_URLS for _ in range(PER_CANARY_REQUESTS)]
    assert urls[:SELF_CHECK_REQUESTS] == expected_prefix, (
        f"the gate self-check is not the first thing on the wire, or is interleaved: "
        f"{urls[:SELF_CHECK_REQUESTS + 1]}"
    )
    assert not (set(urls[SELF_CHECK_REQUESTS:]) & set(CANARY_URLS)), "a canary was re-probed"
    assert len(urls) == SELF_CHECK_REQUESTS + 3


def test_an_inconclusive_self_check_refuses_to_certify_a_clean_bib():
    """The refusal-to-certify contract, via an unreachable canary.

    This test used to pin the OPPOSITE behaviour ("a network failure on the canary probe is
    deliberately not fatal": canary unreachable + all DOIs resolving -> exit 0, "0 failed").
    That pin was an accurate description of the old script and it is what the Auditor
    flagged: a run whose self-check measured nothing was still allowed to publish an
    all-clear, which is the silent-green this gate exists to prevent. An unreachable
    doi.org says nothing about its 404 semantics -- so it also gives no grounds to believe
    the OK lines. The contract is now: no verified self-check, no certification.
    """
    boom = requests.RequestException("simulated canary probe timeout")

    # (i) canaries unreachable, every real DOI "fine" -> NOT green. The per-DOI lines may
    #     still be printed (they are evidence), but the run must not certify them.
    with _bib_file(SYNTHETIC_BIB) as bib:
        code, output, fake = _run_main(bib, outcomes={}, default=302, canary=boom)
    assert code != 0, (
        "a run whose gate self-check measured nothing certified a clean bib anyway -- an "
        "all-clear from an unverified gate is exactly the silent green this gate exists to "
        "prevent"
    )
    assert code == 1
    assert "GATE SELF-CHECK INCONCLUSIVE" in output, "the refusal was not stated distinctly"
    assert "simulated canary probe timeout" in output, "the reason for the doubt is hidden"
    for doi in CANARY_DOIS:
        assert doi in output
        assert fake.calls_for(doi) == PER_CANARY_REQUESTS, f"{doi} probe not retried"
    # It is a refusal to certify, NOT a claim that the DOIs are bad: no DOI is blamed.
    assert "0 failed" in output, "the per-DOI checks did not run at all"
    assert "FAIL" not in output, "an inconclusive self-check must not blame the citations"
    assert len(fake.bib_calls) == 3

    # (ii) same inconclusive self-check, one genuinely bad DOI -> still red, and the DOI
    #      failure is what dominates the report. Fails closed either way.
    with _bib_file(SYNTHETIC_BIB) as bib:
        code, output, _ = _run_main(bib, outcomes={BAD: 404}, default=302, canary=boom)
    assert code == 1, "an inconclusive gate self-check turned an unresolvable DOI green"
    assert f"FAIL {BAD}" in output
    assert "Unresolvable DOIs" in output, "the actionable DOI failure was not reported"

    # Non-vacuity control: the ONLY thing changed back is the canaries' reachability, and
    # the same bib now certifies. So (i)'s red came from the inconclusive self-check.
    with _bib_file(SYNTHETIC_BIB) as bib:
        ok_code, ok_out, _ = _run_main(bib, outcomes={}, default=302, canary=404)
    assert ok_code == 0, ok_out
    assert "GATE SELF-CHECK INCONCLUSIVE" not in ok_out


def test_an_inconclusive_status_also_refuses_to_certify_and_never_masks_a_bad_doi():
    """Same contract as above, reached by STATUS rather than by transport failure, and
    with only ONE of the canaries inconclusive.

    403/429/5xx used to be reported as "gate is functioning" -- a claim the probe had not
    earned (a 500 measures nothing about 404 semantics). That was pinned as
    not-endorsed-but-current; it is now the endorsed behaviour, so it is asserted as the
    contract. The partial case matters most: one canary conclusively 404s, the other is
    throttled. Half a self-check is not a self-check, and the unprobed lookup path is
    precisely where a regression hides.
    """
    S = doi_check.GateStatus
    for status in (403, 429, 500, 503):
        for stalled in CANARY_DOIS:
            answers = _canary_answers({stalled: status})
            ctx = f"canary {stalled} answered HTTP {status}, the rest 404"

            # zero DOI failures + INCONCLUSIVE -> nonzero, with the distinct refusal
            with _bib_file(SYNTHETIC_BIB) as bib:
                code, output, _ = _run_main(bib, outcomes={}, default=302, canary=answers)
            assert code == 1, f"{ctx}: certified a clean bib on an unverified gate"
            assert "GATE SELF-CHECK INCONCLUSIVE" in output, f"{ctx}: refusal not stated"
            assert "0 failed" in output, f"{ctx}: the per-DOI checks did not run"
            assert "FAIL" not in output, f"{ctx}: blamed the citations for a gate problem"

            # a real DOI failure + INCONCLUSIVE -> nonzero, DOI named; that message wins
            with _bib_file(SYNTHETIC_BIB) as bib:
                code, output, _ = _run_main(
                    bib, outcomes={BAD: 404}, default=302, canary=answers
                )
            assert code == 1, ctx
            assert f"FAIL {BAD}" in output, f"{ctx}: the unresolvable DOI was not named"
            assert "Unresolvable DOIs" in output, ctx

            with _mocked_doi_org(canary=answers):
                assert doi_check.check_gate()[0] is S.INCONCLUSIVE, ctx


def test_exit_zero_requires_a_verified_self_check_over_the_whole_status_space():
    """Exhaustive on GateStatus: main() may return 0 only when the self-check is VERIFIED.

    This is the invariant the whole three-state design exists to enforce, so it is asserted
    over every member of the enum rather than over the two or three cases a reader happens
    to think of. Driven by patching ``check_gate`` -- the only place in this file that does
    -- so the mapping status -> exit code is isolated from how the status was reached.
    """
    S = doi_check.GateStatus
    assert set(S) == {S.VERIFIED, S.INCONCLUSIVE, S.BROKEN}, (
        "GateStatus grew a member; decide explicitly whether it may certify a clean bib "
        "and extend the table below -- do not let a new state default into exit 0"
    )
    may_certify = {S.VERIFIED}
    original = doi_check.check_gate
    try:
        for status in S:
            doi_check.check_gate = lambda s=status: (s, [f"forced {s.value}"])
            with _bib_file(SYNTHETIC_BIB) as bib:
                code, output, _ = _run_main(bib, outcomes={}, default=302)
            if status in may_certify:
                assert code == 0, f"{status.value} should certify a clean bib: {output}"
            else:
                assert code != 0, (
                    f"main() exited 0 on a clean bib with a {status.value} self-check -- an "
                    "all-clear from a gate that was never shown to work"
                )
    finally:
        doi_check.check_gate = original


def test_the_harness_never_answers_a_canary_from_the_permissive_default():
    """A property of THIS FILE, asserted because it is what keeps the rest honest.

    An earlier harness answered every unknown DOI with 302, which meant the day the
    self-check probe was added the harness itself told the gate "your canary resolves".
    The rule now is that canary answers arrive only through the dedicated ``canary=``
    channel and never fall through to ``default``, and that the channel's default is the
    STRICT 404. A canary newly added to the script must therefore inherit the strict
    answer, not a permissive one -- otherwise adding a probe would quietly weaken every
    test in this file that passes ``default=302``.
    """
    # (a) with a wide-open default, the canaries still get 404 -> the gate is VERIFIED
    with _mocked_doi_org(outcomes={}, default=302) as fake:
        for doi in CANARY_DOIS:
            assert fake.outcomes[doi] == 404, f"{doi} would have inherited default=302"
        assert doi_check.check_gate()[0] is doi_check.GateStatus.VERIFIED

    # (b) a canary declared through `outcomes` is refused: exactly one way to say it
    for doi in CANARY_DOIS:
        try:
            with _mocked_doi_org(outcomes={doi: 200}, default=302):
                pass
        except AssertionError as exc:
            assert "canary= parameter" in str(exc)
        else:
            raise AssertionError(f"harness allowed canary {doi} to be set via outcomes")

    # (c) a dict `canary=` must be TOTAL over CANARY_DOIS -- a new canary cannot slip
    #     through un-answered (and so cannot land on `default`)
    partial = {CANARY_DOIS[0]: 404}
    if len(CANARY_DOIS) > 1:
        try:
            with _mocked_doi_org(outcomes={}, default=302, canary=partial):
                pass
        except AssertionError as exc:
            assert "every DOI in CANARY_DOIS" in str(exc)
        else:
            raise AssertionError("harness accepted a canary= dict that missed a canary")

    # (d) _canary_answers rejects a stale/typo'd canary name instead of ignoring it
    try:
        _canary_answers({"10.9999/not-a-canary": 200})
    except AssertionError:
        pass
    else:
        raise AssertionError("_canary_answers accepted a DOI outside CANARY_DOIS")

    # (e) and an undeclared ordinary DOI is still a loud error, not an invented success
    with _mocked_doi_org(outcomes={}, default=None):
        try:
            doi_check.resolves("10.9999/never-declared")
        except AssertionError as exc:
            assert "did not declare an outcome" in str(exc)
        else:
            raise AssertionError("harness invented an answer for an undeclared DOI")


# ---------------------------------------------------------------------------
# 7. Regression guards for two findings that WERE reported and are now FIXED
#
# Both of these started life in this file as pinned-not-endorsed descriptions of defects
# (a conclusive 404 discarded by a later transport blip; check_gate() certifying off zero
# probes). The script's owner fixed both, so they are now stated positively, as the
# contract. They keep their place because each one guards a live failure mode -- a false
# RED that makes the check-dois job flaky, and a false GREEN from a measurement never
# taken -- and a silent regression in either would look exactly like the old behaviour.
# ---------------------------------------------------------------------------

def test_a_conclusive_404_outranks_a_later_transport_blip_in_probe_and_in_the_report():
    """An answer from doi.org survives a transport error on a LATER retry.

    The retry loop must not overwrite its own evidence: on the sequence 404, 404, timeout,
    doi.org twice said conclusively "there is no such DOI", and a blip on the last attempt
    cannot unsay it. Before the fix that sequence produced ``status=None`` -- "we never
    reached doi.org" -- which made the self-check INCONCLUSIVE (now fatal) and made the
    per-DOI report line call a DOI *unreachable* that doi.org had actually answered 404.
    So the contract is: ``status is None`` iff NO attempt ever completed, and ``detail``
    reports what doi.org said whenever it said anything.

    The direction of the old error was safe (false red, never false green), but it was a
    false red in exactly the transient conditions retries exist to absorb.
    """
    doi = CANARY_DOIS[0]
    blip_text = "blip on the final attempt"
    blip = requests.RequestException(blip_text)
    sequence = [404] * doi_check.RETRIES + [blip]
    assert len(sequence) == doi_check.RETRIES + 1, "sequence must cover the whole budget"
    assert doi_check.RETRIES >= 1 and sequence.count(404) == doi_check.RETRIES, (
        "RETRIES=0 would leave no completed attempt before the blip and make this vacuous"
    )

    # (i) the self-check is VERIFIED: the 404s doi.org gave are what the gate is graded on
    status, message = _classify(list(sequence), doi)
    assert status is doi_check.GateStatus.VERIFIED, (
        "a conclusive 404 was discarded by a transport blip on the final retry, so a run "
        "in which doi.org twice proved the canary absent reports having measured nothing"
    )
    assert "measured nothing" not in message
    assert "404" in message, "the message does not say what doi.org actually answered"

    # (ii) the structured result: the completed answer is kept, the blip text is dropped,
    #      and the error field stays empty exactly because a status was obtained
    # (one probe per harness context: a list outcome is consumed by call count, and a
    # second probe in the same context would run off the end of the sequence)
    with _mocked_doi_org({"10.9999/blipped": list(sequence)}) as fake:
        result = doi_check.probe("10.9999/blipped")
    assert (result.resolved, result.status, result.error) == (False, 404, "")
    assert result.detail == "HTTP 404"
    with _mocked_doi_org({"10.9999/blipped": list(sequence)}):
        ok, detail = doi_check.resolves("10.9999/blipped")
    assert ok is False, "a 404 must still fail the DOI -- this is not a relaxation"
    assert detail == "HTTP 404"
    assert blip_text not in detail, "the transport error masked the answer doi.org gave"
    assert fake.calls_for("10.9999/blipped") == doi_check.RETRIES + 1, "budget not spent"

    # (iii) and the per-DOI report line main() prints names the 404, not the blip: no DOI
    #       that doi.org answered may be described to CI as unreachable
    with _bib_file(SYNTHETIC_BIB) as bib:
        code, output, _ = _run_main(bib, outcomes={BAD: list(sequence)}, default=302)
    assert code == 1, "a DOI doi.org answered 404 must still turn the gate red"
    assert f"FAIL {BAD}  (HTTP 404)" in output, "the report line does not state the 404"
    assert blip_text not in output, (
        "the report still blames a transport error for a DOI doi.org conclusively answered"
    )
    assert "3 DOIs checked, 1 failed" in output

    # --- regressions the fix must NOT have caused ---------------------------------
    # (a) when NO attempt completes, status is still None and the transport text survives:
    #     that is the genuine "measured nothing" signal and it must stay INCONCLUSIVE
    never = requests.RequestException("probe never completed")
    all_raise = [never] * (doi_check.RETRIES + 1)
    got, msg = _classify(list(all_raise), doi)
    assert got is doi_check.GateStatus.INCONCLUSIVE, (
        "a probe that never reached doi.org now claims to have measured something"
    )
    assert "measured nothing" in msg and "probe never completed" in msg
    with _mocked_doi_org({"10.9999/dead": list(all_raise)}):
        dead = doi_check.probe("10.9999/dead")
    assert (dead.resolved, dead.status) == (False, None)
    assert dead.detail == dead.error == "probe never completed"

    # (b) order-independence: exception(s) FIRST and the answer last is unchanged -- the
    #     late 404 is the completed attempt and wins over the earlier failures
    late = [never] * doi_check.RETRIES + [404]
    assert len(late) == doi_check.RETRIES + 1
    got, _ = _classify(list(late), doi)
    assert got is doi_check.GateStatus.VERIFIED
    with _mocked_doi_org({"10.9999/late": list(late)}):
        recovered = doi_check.probe("10.9999/late")
    assert (recovered.resolved, recovered.status, recovered.error) == (False, 404, "")
    assert recovered.detail == "HTTP 404"


def test_an_empty_canary_set_is_never_verified_and_cannot_certify_a_run():
    """check_gate() has its own non-vacuity guard: zero probes is INCONCLUSIVE, not VERIFIED.

    "Every canary came back conclusively absent" is vacuously true when there are no
    canaries, so an unguarded check_gate() would answer VERIFIED after making zero
    requests and main() would exit 0 with no self-check at all -- the same silent green
    this script exists to prevent, reached from the inside.

    Not reachable through the constant today (CANARY_DOIS has two entries, and
    test_there_is_more_than_one_canary_and_each_covers_a_distinct_lookup_path fails if it
    drops below two). This asserts the function's OWN guard, so the protection does not
    depend on that outside test continuing to exist.
    """
    original = doi_check.CANARY_DOIS
    try:
        doi_check.CANARY_DOIS = ()
        with _mocked_doi_org(outcomes={}, default=None) as fake:
            status, lines = doi_check.check_gate()
        assert status is doi_check.GateStatus.INCONCLUSIVE, (
            "an empty probe set certified the gate as demonstrably working, off a "
            "measurement that was never taken"
        )
        assert fake.calls == [], "no probe was made, so no verdict may be based on one"
        assert len(lines) == 1, (
            f"expected exactly one line explaining the empty probe set, got {lines!r}"
        )
        assert "canary" in lines[0].lower() and lines[0].strip(), (
            f"the reported line does not explain why nothing was probed: {lines[0]!r}"
        )

        # The actual consequence: a bib in which every DOI resolves still cannot certify.
        with _bib_file(SYNTHETIC_BIB) as bib:
            code, output, empty_fake = _run_main(bib, outcomes={}, default=302)
        assert code == 1, (
            "main() exited 0 with no canaries configured -- an all-clear from a gate that "
            "was never self-checked at all"
        )
        assert "GATE SELF-CHECK INCONCLUSIVE" in output, "the refusal was not stated"
        assert "0 failed" in output, "the citations were not checked"
        assert "FAIL" not in output, "an unprobed gate must not blame the citations"
        assert empty_fake.canary_calls == [], "a canary was probed with none configured"
    finally:
        doi_check.CANARY_DOIS = original
    # Guard restored, and the real constant is what the rest of the suite sees.
    assert doi_check.CANARY_DOIS == original == CANARY_DOIS

    # Non-vacuity control: the ONLY thing changed back is the canary set, and the same bib
    # through the same harness now certifies -- so the red above came from the empty set.
    with _bib_file(SYNTHETIC_BIB) as bib:
        ok_code, ok_out, _ = _run_main(bib, outcomes={}, default=302)
    assert ok_code == 0, ok_out
    assert "GATE SELF-CHECK INCONCLUSIVE" not in ok_out


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\nAll {len(fns)} tests passed.")
