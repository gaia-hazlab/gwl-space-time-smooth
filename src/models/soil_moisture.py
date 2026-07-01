"""Soil-moisture state module (gaia-soil-hydromechanics — SCAFFOLD).

One of the three coupled state variables of gaia-soil-hydromechanics (soil moisture,
groundwater level, soil mechanical properties). This module estimates the vadose-zone
soil-moisture / saturation state θ(x, t) on the canonical 90 m EPSG:5070 grid.

Static ↔ dynamic decomposition (mirrors the project scope):
  * **Static** — soil water-holding capacity from SOLUS100 / POLARIS texture and
    hydraulics (field capacity, wilting point, porosity, Ksat). These are the same
    covariates already fetched by ``src.data.fetch_gaia`` (solus/polaris).
  * **Dynamic** — the time-varying wetness signal, from a reanalysis / remote-sensing
    driver (e.g. SMAP, SPoRT-LIS, or a PRISM water-balance) plus the climate forcing
    indices already assembled for the GWL climate-response stage.

Complementarity: this couples upward to the vadose zone that GAIA Pillar 1 (Richards +
rock physics) models top-down, and downward to the water table produced by the GWL module.
The soil-moisture state also feeds the *dynamic* stiffness proxy in
``src.models.soil_mechanics`` (saturation → effective stress → Vs / dv/v).

STATUS: interface scaffold. ``estimate_soil_moisture`` raises NotImplementedError; the
CLI wires up I/O so downstream modules can import the contract now and the physics can
be filled in without touching call sites.
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
class SoilMoistureInputs:
    """Aligned 90 m EPSG:5070 inputs for the soil-moisture estimate.

    All arrays share one (y, x) shape; ``dynamic_driver`` carries a leading time axis.
    """

    field_capacity: np.ndarray          # (y, x) volumetric θ at field capacity  [SOLUS/POLARIS]
    wilting_point: np.ndarray           # (y, x) volumetric θ at wilting point    [SOLUS/POLARIS]
    porosity: np.ndarray                # (y, x) saturated θ                       [SOLUS/POLARIS]
    dynamic_driver: np.ndarray          # (time, y, x) wetness driver (reanalysis / RS anomaly)


def estimate_soil_moisture(inp: SoilMoistureInputs) -> np.ndarray:
    """Return volumetric soil moisture θ(time, y, x) on the 90 m grid.

    Contract (fill in): combine the static capacity envelope (wilting_point ≤ θ ≤ porosity)
    with the dynamic driver to produce a physically bounded, time-varying θ, plus a
    per-cell uncertainty companion (θ_std) written alongside. Output units: m³/m³.
    """
    raise NotImplementedError(
        "soil-moisture estimator not implemented — scaffold only. "
        "Wire the static SOLUS/POLARIS envelope + dynamic reanalysis driver here."
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--solus", type=Path, default=Path("data/processed/solus100_wa.zarr"),
                   help="SOLUS100 (or POLARIS) soil hydraulics — static capacity terms.")
    p.add_argument("--driver", type=Path, default=None,
                   help="Dynamic wetness driver (reanalysis / remote-sensing) on the 90 m grid.")
    p.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    args = p.parse_args()

    logger.warning("src.models.soil_moisture is a SCAFFOLD — no output produced yet. "
                   "Inputs would be: solus=%s driver=%s -> %s/soil_moisture.zarr",
                   args.solus, args.driver, args.output_dir)
    raise SystemExit("soil_moisture: not yet implemented (scaffold).")


if __name__ == "__main__":
    main()
