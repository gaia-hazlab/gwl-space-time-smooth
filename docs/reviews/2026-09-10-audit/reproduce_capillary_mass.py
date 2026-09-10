"""Read-only one-column conservation counterexample for main435445f."""
import json
import sys
import numpy as np
sys.path.insert(0, sys.argv[1])
from src.models.water_budget import coupled_water_budget

results = {}
for cap_max in (0.0, 30.0):
    result = coupled_water_budget(
        np.zeros(1), np.zeros(1), theta_wp=0.1, theta_fc=0.3,
        theta_sat=0.5, root_depth_m=1.0, specific_yield=0.3,
        wt_depth0_m=0.5, init='wp', dt_days=1.0,
        cap_max_mm=cap_max,
    )
    root_change = (float(result.theta[0]) - 0.1) * 1000.0
    gw_change = 0.3 * (0.5 - float(result.wt_depth_m[0])) * 1000.0
    outflow = sum(float(getattr(result, name)[0]) for name in (
        'runoff_mm', 'interflow_mm', 'baseflow_mm', 'aet_mm'))
    results[str(cap_max)] = dict(
        capillary_rise_mm=float(result.cap_rise_mm[0]),
        root_storage_change_mm=root_change,
        groundwater_storage_change_mm=gw_change,
        external_input_mm=0.0, external_output_mm=outflow,
        total_water_balance_residual_mm=root_change + gw_change + outflow,
    )
print(json.dumps(results, indent=2))
assert abs(results['0.0']['total_water_balance_residual_mm']) < 1e-5
assert results['30.0']['total_water_balance_residual_mm'] > 0.7
