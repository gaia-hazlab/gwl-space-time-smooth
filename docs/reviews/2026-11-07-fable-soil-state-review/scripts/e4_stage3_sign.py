#!/usr/bin/env python3
"""Replicates the Stage-3 assembly of src/models/interpolate_residuals.py lines 204-210 on a 2x2
synthetic to record the sign inversion reported in #230. Writes results/e4_stage3_sign.json."""
import hashlib, json, re, subprocess
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "src/models/interpolate_residuals.py"
OUT = Path(__file__).resolve().parents[1] / "results" / "e4_stage3_sign.json"
text = SRC.read_text()
block = text[text.index("dtw_final = ("):text.index("wte_final =") + 60]
baseline_dtw = np.full((2, 2), 5.0, np.float32)            # m below surface
dem_arr = np.full((2, 2), 100.0, np.float32)
cr_cube = np.full((1, 2, 2), +1.0, np.float32)             # wte_anomaly_m: water-table ELEVATION anomaly, +1 m = table rose 1 m
residual_cube = np.zeros((1, 2, 2), np.float32)
dtw_final = (baseline_dtw[np.newaxis, :, :] + cr_cube + residual_cube)      # the code as written
wte_final = dem_arr[np.newaxis, :, :] - dtw_final
expected_dtw = baseline_dtw - 1.0                                           # a 1 m rise makes the table 1 m SHALLOWER
rec = {"issue": "#230", "source": str(SRC.relative_to(ROOT)), "source_sha256": hashlib.sha256(SRC.read_bytes()).hexdigest(),
       "commit": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
       "code_block": block.strip(), "anomaly_convention_source": "src/models/interpolate_anomalies.py:115 anomaly_wte_m = wte_m - median_wte_m (elevation, positive up)",
       "input_wte_anomaly_m": 1.0, "baseline_dtw_m": 5.0, "dtw_final_as_coded_m": float(dtw_final[0, 0, 0]), "dtw_final_expected_m": float(expected_dtw[0, 0]),
       "wte_final_as_coded_m": float(wte_final[0, 0, 0]), "wte_final_expected_m": 100.0 - 4.0,
       "verdict": "sign inverted: a +1 m water-table rise is written as a 1 m deeper table; wte_final inherits the error"}
OUT.parent.mkdir(parents=True, exist_ok=True); OUT.write_text(json.dumps(rec, indent=1) + "\n")
print(json.dumps({k: rec[k] for k in ("dtw_final_as_coded_m", "dtw_final_expected_m", "wte_final_as_coded_m", "wte_final_expected_m", "verdict")}, indent=1))
