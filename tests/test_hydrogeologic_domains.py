"""Tests for the hydrogeologic-domain classifier (issue #2).

Runs standalone (`python tests/test_hydrogeologic_domains.py`) — no pytest required —
and is also pytest-discoverable.
"""

from __future__ import annotations

import numpy as np

from src.features.hydrogeologic_domains import (
    DOMAIN_NODATA,
    DOMAINS,
    LITHO_BEDROCK,
    LITHO_CRBG,
    LITHO_UNCONSOLIDATED,
    LITHO_VOLCANIC_YOUNG,
    classify_domains,
    lithology_from_geology,
)

FAR = 1.0e6  # far from coast (m)


def test_each_domain_assigned():
    # One representative cell per intended domain, laid out in a row.
    hand = np.array([2.0, 30.0, 120.0, 200.0, 60.0, 1.0], dtype=np.float32)
    litho = np.array([LITHO_UNCONSOLIDATED, LITHO_UNCONSOLIDATED, LITHO_BEDROCK,
                      LITHO_VOLCANIC_YOUNG, LITHO_CRBG, LITHO_UNCONSOLIDATED], dtype=np.float32)
    dist = np.array([FAR, FAR, FAR, FAR, FAR, 500.0], dtype=np.float32)  # last cell is coastal
    d = classify_domains(hand, litho, dist)
    names = [DOMAINS[int(v)] for v in d]
    assert names == [
        "unconsolidated_valley_fill",   # uncon + low HAND
        "unconsolidated_basin",         # uncon + high HAND
        "fractured_upland",             # bedrock
        "volcanic_deep",                # young volcanic
        "confined_basalt",              # CRBG
        "coastal",                      # near shore + low HAND
    ], names


def test_coastal_priority_over_valley_fill():
    # A near-shore low unconsolidated cell must classify coastal, not valley fill.
    d = classify_domains(np.array([2.0]), np.array([LITHO_UNCONSOLIDATED]), np.array([300.0]))
    assert DOMAINS[int(d[0])] == "coastal"


def test_coastal_requires_low_hand():
    # Near the coast but high above drainage (sea cliff / upland) → not coastal.
    d = classify_domains(np.array([50.0]), np.array([LITHO_BEDROCK]), np.array([300.0]))
    assert DOMAINS[int(d[0])] == "fractured_upland"


def test_nodata_lithology_is_nodata_domain():
    d = classify_domains(np.array([2.0]), np.array([np.nan]), np.array([FAR]))
    assert int(d[0]) == DOMAIN_NODATA


def test_exactly_one_label_and_dtype():
    rng = np.random.default_rng(0)
    hand = rng.uniform(0, 250, (40, 40)).astype(np.float32)
    litho = rng.integers(0, 4, (40, 40)).astype(np.float32)
    dist = rng.uniform(0, 5000, (40, 40)).astype(np.float32)
    d = classify_domains(hand, litho, dist)
    assert d.dtype == np.uint8
    # every valid cell maps to a known domain code
    assert set(np.unique(d)).issubset(set(DOMAINS) | {DOMAIN_NODATA})


def test_crosswalk_maps_and_flags_unmapped():
    geo = np.array([100.0, 200.0, 300.0, 999.0], dtype=np.float32)
    crosswalk = {"100": LITHO_UNCONSOLIDATED, "200": LITHO_BEDROCK, "300": LITHO_CRBG}
    litho = lithology_from_geology(geo, crosswalk)
    assert litho[0] == LITHO_UNCONSOLIDATED
    assert litho[1] == LITHO_BEDROCK
    assert litho[2] == LITHO_CRBG
    assert np.isnan(litho[3])  # unmapped code → NaN → DOMAIN_NODATA downstream


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\nAll {len(fns)} tests passed.")
