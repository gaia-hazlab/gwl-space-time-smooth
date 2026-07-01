"""Soil-mechanics state module (gaia-soil-hydromechanics — SCAFFOLD).

The third coupled state variable of gaia-soil-hydromechanics (with soil moisture and
groundwater level). Produces the soil mechanical-property state used by the downstream
hazard digital twins — liquefaction (Sanger & Maurer), landslide (LandLab), future flood.

Static ↔ dynamic decomposition (mirrors the project scope):
  * **Static** — baseline stiffness / strength from SOLUS soil properties and the
    **Vs30 / Vs(z)** parametric model (Sanger & Maurer 2025), the *same* Vs field the
    liquefaction GLM consumes → cross-model consistency by construction.
  * **Dynamic** — the differentiator no hydrology product has: **dv/v** (ambient-noise
    seismic velocity change) as a time-varying proxy for effective stress / pore pressure /
    saturation. dv/v(x, t) is combined with the soil-moisture and water-table states to
    modulate the static stiffness into a dynamic mechanical state.

Coupling: effective stress σ' = σ − u, where pore pressure u is set by the GWL module's
water table and the ``soil_moisture`` saturation state; dv/v provides an *observational*
constraint on the resulting stiffness change. This module is where the three states join.

STATUS: interface scaffold. ``estimate_mechanics`` raises NotImplementedError; the CLI
wires up I/O so the hazard twins can import the contract now.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TARGET_RES_M = 90.0


@dataclass
class MechanicsInputs:
    """Aligned 90 m EPSG:5070 inputs for the soil-mechanics estimate.

    Static fields are (y, x); dynamic fields carry a leading time axis. dvv is optional —
    when absent the estimate degrades gracefully to the static Vs30-only stiffness.
    """

    vs30: np.ndarray                     # (y, x) time-averaged shear-wave velocity  [Sanger & Maurer]
    soil_static: np.ndarray              # (y, x) SOLUS strength/plasticity proxy (e.g. clay%, PI)
    water_table_depth: np.ndarray | None # DTW from the GWL module: static (y, x) baseline OR
                                         #   time-varying (time, y, x) — implementation must
                                         #   accept either shape                       [pore pressure]
    saturation: np.ndarray | None        # (time, y, x) θ/θ_sat from soil_moisture      [effective stress]
    dvv: np.ndarray | None               # (time, y, x) ambient-noise dv/v (dimensionless, fraction)


def estimate_mechanics(inp: MechanicsInputs) -> np.ndarray:
    """Return the dynamic mechanical-state field(s) on the 90 m grid.

    Contract (fill in): start from static Vs30/SOLUS stiffness, adjust for effective
    stress from the water-table + saturation states, and constrain the *change* with
    dv/v when available. Emit at least a stiffness/Vs-proxy field and, for the
    liquefaction twin, a susceptibility term — each with a per-cell uncertainty companion.
    """
    raise NotImplementedError(
        "soil-mechanics estimator not implemented — scaffold only. "
        "Wire static Vs30/SOLUS stiffness + effective-stress coupling + dv/v constraint here."
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--vs30", type=Path, default=Path("data/processed/vs30_90m.tif"),
                   help="Vs30 (Sanger & Maurer) — static stiffness anchor.")
    p.add_argument("--solus", type=Path, default=Path("data/processed/solus100_wa.zarr"),
                   help="SOLUS soil properties — static strength/plasticity proxy.")
    p.add_argument("--dtw", type=Path, default=Path("data/processed/baseline_dtw_m.tif"),
                   help="Water-table depth for pore-pressure coupling. Default is the STATIC "
                        "baseline_dtw_m.tif placeholder; pass a time-varying GWL DTW stack for "
                        "the dynamic estimate (the estimator accepts either).")
    p.add_argument("--saturation", type=Path, default=None,
                   help="Saturation state from src.models.soil_moisture (effective-stress coupling).")
    p.add_argument("--dvv", type=Path, default=None,
                   help="Ambient-noise dv/v field (time, y, x) — dynamic stiffness constraint.")
    p.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    args = p.parse_args()

    logger.warning("src.models.soil_mechanics is a SCAFFOLD — no output produced yet. "
                   "Inputs would be: vs30=%s solus=%s dtw=%s dvv=%s -> %s/soil_mechanics.zarr",
                   args.vs30, args.solus, args.dtw, args.dvv, args.output_dir)
    raise SystemExit("soil_mechanics: not yet implemented (scaffold).")


if __name__ == "__main__":
    main()
