#!/usr/bin/env python3
"""P1 (#301): bounded one-member cost of the land-surface bucket with a memory preflight.

Three separately labelled numbers: measured bucket cost per member-year; MODFLOW cost (not
measured here, see #283); projected ensemble throughput (a projection, never a cycling benchmark).
Writes results/p1_bounded_performance.json; writes no array to disk.
"""
from __future__ import annotations

import json
import platform
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from src.models import water_budget as wb  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "results" / "p1_bounded_performance.json"
CAP_BYTES = 8 * 1024 ** 3
FIELDS, BYTES_PER_CELLSTEP = 8, 12          # eight float64 outputs plus float32 copies
DOMAIN_CELLS, N_OBS, STEPS = 1567 * 1890, 863, 365


def preflight(cells, steps):
    est = cells * steps * FIELDS * BYTES_PER_CELLSTEP + 2 * cells * steps * 8    # forcing arrays too
    return est, est <= CAP_BYTES


def peak_rss_gb():
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / 1024 ** 3 if platform.system() == "Darwin" else r / 1024 ** 2


def host_info():
    """CPU, RAM and free disk on macOS (sysctl) or Linux (/proc); a field that cannot be read is None."""
    def sysctl(key):
        try:
            return subprocess.run(["sysctl", "-n", key], capture_output=True, text=True, check=True).stdout.strip() or None
        except (OSError, subprocess.CalledProcessError):
            return None
    cpu = ram_gb = None
    if platform.system() == "Darwin":
        cpu = sysctl("machdep.cpu.brand_string")
        mem = sysctl("hw.memsize")
        ram_gb = int(mem) / 1e9 if mem and mem.isdigit() else None
    else:
        try:
            cpu = next((l.split(":", 1)[1].strip() for l in Path("/proc/cpuinfo").read_text().splitlines() if l.startswith("model name")), None)
            kb = next((int(l.split()[1]) for l in Path("/proc/meminfo").read_text().splitlines() if l.startswith("MemTotal:")), None)
            ram_gb = kb * 1024 / 1e9 if kb else None
        except OSError:
            pass
    return {"system": platform.system(), "machine": platform.machine(), "cpu": cpu or platform.processor() or None,
            "ram_gb": ram_gb, "free_disk_gb": shutil.disk_usage("/").free / 1e9}


def run_tile(n):
    rng = np.random.default_rng(3)
    liquid = rng.gamma(0.6, 6.0, size=(STEPS, n, n)) * (rng.random((STEPS, n, n)) < 0.45)
    pet = np.clip(2.0 + 2.0 * np.sin(2 * np.pi * np.arange(STEPS) / 365.25)[:, None, None] + 0.1 * rng.standard_normal((STEPS, n, n)), 0, None)
    slope = np.abs(0.2 * rng.standard_normal((n, n))); hand = np.abs(20 * rng.standard_normal((n, n)))
    t0 = time.perf_counter()
    wb.coupled_water_budget(liquid, pet, 0.10, 0.28, 0.45, wt_depth0_m=5.0, init="fc", dt_days=1.0, slope_tan=slope, hand_m=hand)
    return time.perf_counter() - t0


def main():
    rows = []
    for n in (200, 400, 800):
        est, ok = preflight(n * n, STEPS)
        if not ok:
            rows.append({"tile": n, "cells": n * n, "preflight_gb": est / 1024 ** 3, "run": False}); continue
        wall = run_tile(n)
        rows.append({"tile": n, "cells": n * n, "preflight_gb": est / 1024 ** 3, "run": True, "wall_s": wall,
                     "peak_rss_gb_so_far": peak_rss_gb(), "cell_steps_per_s": n * n * STEPS / wall})
    ran = [r for r in rows if r["run"]]
    if len(ran) < 2:
        sys.exit(f"p1: only {len(ran)} tile(s) fit under the {CAP_BYTES / 1024**3:.0f} GB preflight cap; "
                 "the scaling fit needs at least two. Lower the tile sizes or raise CAP_BYTES.")
    cells = np.array([r["cells"] for r in ran], float); walls = np.array([r["wall_s"] for r in ran])
    slope, intercept = np.polyfit(np.log(cells), np.log(walls), 1)
    fit_resid = float(np.max(np.abs(np.log(walls) - (slope * np.log(cells) + intercept))))
    proj_domain = float(np.exp(intercept) * DOMAIN_CELLS ** slope)
    est_domain, _ = preflight(DOMAIN_CELLS, STEPS)
    record = {"issue": "gaia-hazlab/gwl-space-time-smooth#301",
              "host": host_info(),
              "preflight_rule": f"cells x steps x {FIELDS} fields x {BYTES_PER_CELLSTEP} B (+ forcing) must stay below {CAP_BYTES / 1024**3:.0f} GB",
              "tiles": rows, "scaling_fit": {"wall_s = a * cells^b": {"a": float(np.exp(intercept)), "b": float(slope)}, "max_log_residual": fit_resid},
              "measured_bucket_cost": {"label": "MEASURED: land-surface bucket, one member, 365 daily steps", "per_cell_step_ns": float(1e9 * np.mean(walls / (cells * STEPS)))},
              "modflow_cost": {"label": "NOT MEASURED HERE", "where": "#283 measures MF6 runtime per member-year at each k"},
              "projection": {"label": "PROJECTION from the tile fit, not a cycling benchmark",
                             "domain_cells": DOMAIN_CELLS, "one_member_year_wall_s": proj_domain,
                             "full_domain_history_gb_if_allocated": est_domain / 1024 ** 3, "note": "a full-domain 365-step history would exceed the 8 GB cap by this factor and must be chunked in time",
                             "fifty_member_year_core_hours_if_linear": 50 * proj_domain / 3600.0},
              "dense_intermediate_not_allocated": {"shape": [DOMAIN_CELLS, N_OBS], "float64_gb": DOMAIN_CELLS * N_OBS * 8 / 1024 ** 3, "source": "observability.py:140-144"},
              "peak_rss_gb": peak_rss_gb()}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(record, indent=1, allow_nan=False) + "\n")
    print(json.dumps({k: record[k] for k in ("tiles", "scaling_fit", "measured_bucket_cost", "projection", "dense_intermediate_not_allocated", "peak_rss_gb")}, indent=1))


if __name__ == "__main__":
    main()
