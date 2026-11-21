"""Independent probe of src/models/water_budget.py (origin/main checkout). Read-only on the repo."""
import sys, json
import numpy as np
MAIN = "scratchpad/main"
sys.path.insert(0, MAIN)
import types
for _m in ("rioxarray","xarray","pandas"):
    try: __import__(_m)
    except ImportError: sys.modules[_m]=types.ModuleType(_m)
from src.models.water_budget import coupled_water_budget, accumulate_runoff, SPECIFIC_YIELD
from src.models.forecast import liquid_input, ForecastForcing
from src.models.soil_moisture import total_water_bucket

WP, FC, SAT = 0.10, 0.28, 0.45
out = {}

def ledger(wb, liquid, sy, z_mm, theta0_mm, wt0):
    """Total column water (root zone + aquifer head anomaly) vs boundary fluxes."""
    S = wb.theta.astype("f8") * z_mm
    gw = (wt0 - wb.wt_depth_m.astype("f8")) * sy * 1000.0       # aquifer storage anomaly (mm)
    total_end = S[-1] + gw[-1]
    total_start = theta0_mm + 0.0
    inflow = liquid.sum(0)
    outflow = (wb.runoff_mm.astype("f8") + wb.aet_mm + wb.interflow_mm + wb.baseflow_mm).sum(0)
    resid = (total_end - total_start) - (inflow - outflow)   # >0 = water created
    return resid, wb.cap_rise_mm.astype("f8").sum(0)

# --- A. capillary leak, one dry month, no forcing ---------------------------------------------
P = np.zeros((1, 1)); E = np.zeros((1, 1))
wb = coupled_water_budget(P, E, WP, FC, SAT, root_depth_m=1.0, wt_depth0_m=0.5, init="wp")
r, cap = ledger(wb, P, SPECIFIC_YIELD, 1000.0, WP * 1000.0, 0.5)
out["A_one_dry_month_created_mm"] = float(r[0]); out["A_cap_rise_mm"] = float(cap[0])

# --- B. 300 daily dry steps, a range of table depths, legacy branch ---------------------------
d0 = np.array([0.3, 0.5, 1.0, 1.5, 1.99, 3.0])
P = np.zeros((300, d0.size)); E = np.full((300, d0.size), 1.5)
wb = coupled_water_budget(P, E, WP, FC, SAT, root_depth_m=1.0, wt_depth0_m=d0, init="fc", dt_days=1.0)
r, cap = ledger(wb, P, SPECIFIC_YIELD, 1000.0, FC * 1000.0, d0)
out["B_daily300_dry_legacy"] = {"d0_m": d0.tolist(), "created_mm": r.round(3).tolist(), "sum_cap_mm": cap.round(3).tolist()}

# --- C. wet year, HAND branch, slope; full ledger incl. interflow+baseflow ---------------------
rng = np.random.default_rng(0)
nt = 365
p = rng.gamma(0.4, 12.0, size=nt)                 # ~1750 mm/yr, intermittent
p[150:270] *= 0.15                                 # dry summer
pet = 1.0 + 2.0 * np.sin(np.pi * np.arange(nt) / nt) ** 2
cells = {  # name: (d0, HAND, tanb)
    "ridge":     (15.0, 60.0, 0.40),
    "midslope":  (4.0, 12.0, 0.25),
    "toe":       (1.5, 3.0, 0.08),
    "valley_hand_eq_d0": (0.8, 0.8, 0.01),
    "valley_hand0": (0.5, 0.0, 0.0),
    "terrace_hand_lt_d0": (6.0, 4.0, 0.02),
}
names = list(cells); d0 = np.array([cells[k][0] for k in names]); hd = np.array([cells[k][1] for k in names]); tb = np.array([cells[k][2] for k in names])
P = np.repeat(p[:, None], len(names), 1); E = np.repeat(pet[:, None], len(names), 1)
wb = coupled_water_budget(P, E, WP, FC, SAT, root_depth_m=1.0, wt_depth0_m=d0, dt_days=1.0,
                          slope_tan=tb, hand_m=hd)
r, cap = ledger(wb, P, SPECIFIC_YIELD, 1000.0, FC * 1000.0, d0)
C = {}
for i, k in enumerate(names):
    C[k] = dict(P=float(P[:, i].sum()), runoff=float(wb.runoff_mm[:, i].sum()), interflow=float(wb.interflow_mm[:, i].sum()),
                baseflow=float(wb.baseflow_mm[:, i].sum()), aet=float(wb.aet_mm[:, i].sum()), recharge=float(wb.recharge_mm[:, i].sum()),
                cap=float(cap[i]), created_mm=float(r[i]), wt_end_m=float(wb.wt_depth_m[-1, i]), wt_min_m=float(wb.wt_depth_m[:, i].min()),
                BFI=float(wb.baseflow_mm[:, i].sum() / max(1e-9, (wb.runoff_mm[:, i] + wb.interflow_mm[:, i] + wb.baseflow_mm[:, i]).sum())))
out["C_wet_year_HAND_branch"] = C

# --- D. valley cell, ZERO forcing, 10 years monthly, HAND branch: perpetual motion? -------------
nt = 120
P = np.zeros((nt, 2)); E = np.zeros((nt, 2))
wb = coupled_water_budget(P, E, WP, FC, SAT, root_depth_m=1.0, wt_depth0_m=np.array([0.5, 0.5]),
                          hand_m=np.array([0.0, 5.0]), slope_tan=np.array([0.0, 0.0]))
r, cap = ledger(wb, P, SPECIFIC_YIELD, 1000.0, FC * 1000.0, np.array([0.5, 0.5]))
out["D_zero_forcing_10yr_monthly"] = {
    "valley_HAND0": dict(wt_depth_start=float(wb.wt_depth_m[0, 0]), wt_depth_end=float(wb.wt_depth_m[-1, 0]),
                         created_mm=float(r[0]), sum_cap=float(cap[0]), sum_recharge=float(wb.recharge_mm[:, 0].sum()),
                         sum_baseflow=float(wb.baseflow_mm[:, 0].sum())),
    "hillcell_HAND5": dict(wt_depth_end=float(wb.wt_depth_m[-1, 1]), created_mm=float(r[1]), sum_cap=float(cap[1]),
                           sum_baseflow=float(wb.baseflow_mm[:, 1].sum())),
}
# same with legacy branch (hand_m None)
wbL = coupled_water_budget(P[:, :1], E[:, :1], WP, FC, SAT, root_depth_m=1.0, wt_depth0_m=0.5)
rL, capL = ledger(wbL, P[:, :1], SPECIFIC_YIELD, 1000.0, FC * 1000.0, 0.5)
out["D_zero_forcing_10yr_monthly"]["legacy"] = dict(wt_depth_end=float(wbL.wt_depth_m[-1, 0]), created_mm=float(rL[0]), sum_cap=float(capL[0]))

# --- E. valley cell under 3 wet years daily: does the table go above ground and stay? ---------
nt = 3 * 365
p3 = np.tile(p, 3)[:nt]; e3 = np.tile(pet, 3)[:nt]
wb = coupled_water_budget(p3[:, None], e3[:, None], WP, FC, SAT, root_depth_m=1.0, wt_depth0_m=np.array([2.0]),
                          dt_days=1.0, hand_m=np.array([1.0]), slope_tan=np.array([0.0]))
r, cap = ledger(wb, p3[:, None], SPECIFIC_YIELD, 1000.0, FC * 1000.0, np.array([2.0]))
out["E_valley_HAND1_d0_2_three_wet_years"] = dict(wt_start=2.0, wt_end=float(wb.wt_depth_m[-1, 0]), wt_min=float(wb.wt_depth_m[:, 0].min()),
    baseflow=float(wb.baseflow_mm.sum()), recharge=float(wb.recharge_mm.sum()), runoff=float(wb.runoff_mm.sum()), created_mm=float(r[0]),
    frac_days_table_above_surface=float((wb.wt_depth_m[:, 0] < 0).mean()))

# --- F. accumulate_runoff conserves? ----------------------------------------------------------
ro = np.full((10,), 10.0); fa = np.arange(1, 11, dtype=float)
routed = accumulate_runoff(ro, fa)
out["F_accumulate_runoff_in_out_mm"] = [float(ro.sum()), float(routed.sum())]

# --- G. total_water_bucket silently deletes water above saturation ---------------------------
Pm = np.array([[600.0]]); Em = np.array([[0.0]])
th = total_water_bucket(Pm, Em, np.array([WP]), np.array([FC]), np.array([SAT]), init="fc")
S1 = float(th[0, 0]) * 1000; S0 = FC * 1000
# accounted output: only drainage term (excess*drain_frac); everything else unlabelled
out["G_total_water_bucket"] = dict(S0=S0, P=600.0, S1=S1, note="no runoff/drainage flux returned; P-(S1-S0) mm leaves unlabelled",
                                   unlabelled_loss_mm=600.0 - (S1 - S0))

# --- H. snow: forecast starts with zero SWE and returns no SWE state -------------------------
ff = ForecastForcing(times=np.arange(10), precip_mm=np.zeros((10, 1)), pet_mm=np.zeros((10, 1)), dt_days=1.0,
                     tmean_c=np.full((10, 1), 8.0))
li = liquid_input(ff)
out["H_snow_initial_state"] = dict(melt_over_10_warm_days_mm=float(li.sum()),
    note="a 10-day forecast launched on 1 April over a 1.5 m SWE pack at 8 C melts 0 mm: SWE is initialised to zero and never passed in or out")

# --- I. VSA deficit double count and Sy*d magnitude ------------------------------------------
for d in (0.5, 1.0, 2.0, 5.0):
    out.setdefault("I_VSA_deficit_mm", {})[str(d)] = SPECIFIC_YIELD * d * 1000.0

# --- J. recession timescale implied by the HAND sink -----------------------------------------
sy, rref = SPECIFIC_YIELD, 3.0
out["J_tau_days_vs_head0"] = {str(h0): sy * h0 * 1000.0 / rref for h0 in (0.5, 2, 5, 20, 60)}
# steady state if actual mean recharge Rbar != Rref: head above river -> head0*Rbar/Rref
out["J_note"] = "linear sink: equilibrium head above drainage = head0 * Rbar/Rref; timescale = Sy*head0/Rref"
# f_lat at the domain median slope
for ka in (2.0, 20.0):
    kt = ka * np.tan(np.radians(13.3)); out.setdefault("K_flat_median_slope", {})[str(ka)] = float(kt / (1 + kt))
print(json.dumps(out, indent=1))
