"""Digital-twin GIF: the soil state evolving through the 2025-26 wet season, on the Cascades domain."""
from __future__ import annotations
import shutil, sys, warnings
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
import numpy as np, pandas as pd, rioxarray as rxr, xarray as xr
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from src.viz.fonts import register_inter; register_inter()
except Exception: pass
from src.config.domain import DOMAIN
from src.io.zarr_store import open_zarr
from src.models.forecast import ForecastForcing, forecast_soil_state

STEP = 8
P = Path("data/processed")
g = lambda f: rxr.open_rasterio(P/f, masked=True).squeeze("band", drop=True)
soil = xr.open_zarr(P/"soil_domain_90m.zarr"); wt = xr.open_zarr(P/"baseline_wt_domain_90m.zarr")
f = open_zarr(P/"prism_daily_2025-09_2026-06.zarr").rio.write_crs("EPSG:4326")
sub = DOMAIN.template().isel(y=slice(None,None,STEP), x=slice(None,None,STEP))
PR = f.precip_mm.rio.reproject_match(sub).values
TM = f.tmean_c.rio.reproject_match(sub).values
PE = f.pet_mm.rio.reproject_match(sub).values
times = pd.to_datetime(f.time.values)
sl = (slice(None,None,STEP), slice(None,None,STEP))
wp,fc,sat = (soil[k].values[sl] for k in ("theta_wp","theta_fc","theta_sat"))
d0 = wt.dtw_m.values[sl]; hd = g("terrain_hand_domain_90m.tif").values[sl]
tb = np.tan(np.radians(g("terrain_slope_domain_90m.tif").values[sl]))
v0 = g("vs30_domain_90m.tif").values[sl]; rd = soil.root_depth_m.values[sl]

fo = ForecastForcing(times=times.values, precip_mm=PR, pet_mm=PE, dt_days=1.0, tmean_c=TM, source="PRISM")
fx = forecast_soil_state(fo, theta_wp=wp, theta_fc=fc, theta_sat=sat, vs30_base=v0,
                         wt_depth0_m=d0, root_depth_m=rd, slope_tan=tb, hand_m=hd)
land = np.isfinite(d0)&np.isfinite(wp)&np.isfinite(hd)
msk = lambda a: np.where(land, a, np.nan)

idx = np.arange(0, len(times), 7)                 # weekly cadence -> ~43 frames
TH  = np.stack([msk(fx.theta[i]) for i in idx])
WT  = np.stack([msk(d0 - fx.wt_depth_m[i]) for i in idx])     # +ve = table risen
DV  = np.stack([msk(100*fx.dvv_high[i]) for i in idx])
pr_s = np.array([np.nanmean(PR[i][land]) for i in range(len(times))])

fig, ax = plt.subplots(1, 4, figsize=(13.5, 3.9), constrained_layout=True,
                       gridspec_kw={"width_ratios":[1,1,1,1.15]})
S = [(TH,"Soil moisture θ","YlGnBu","m³ m⁻³"),
     (WT,"Water table rise","Blues","m above baseline"),
     (DV,"dv/v  (shallow band)","RdBu","%")]
ims=[]
for a,(D,t,cm,u) in zip(ax[:3], S):
    v=D[np.isfinite(D)]; lo,hi=np.percentile(v,[2,98])
    if t.startswith("dv"): hi=max(abs(lo),abs(hi)); lo=-hi
    c=plt.get_cmap(cm).copy(); c.set_bad("#eef0f3")
    im=a.imshow(D[0],cmap=c,vmin=lo,vmax=hi); ims.append(im)
    a.set_title(f"{t}\n[{u}]",fontsize=11,fontweight="bold"); a.set_xticks([]); a.set_yticks([])
    fig.colorbar(im,ax=a,shrink=.75)
ax[3].bar(times, pr_s, color="#2E86AB", width=1.0)
vline=ax[3].axvline(times[0], color="#E84855", lw=2)
ax[3].set_title("Rainfall forcing (PRISM daily)",fontsize=11,fontweight="bold")
ax[3].set_ylabel("mm / day"); ax[3].tick_params(axis="x", rotation=35, labelsize=8)
ttl=fig.suptitle("",fontsize=13,fontweight="bold")

def upd(k):
    for im,(D,_,_,_) in zip(ims,S): im.set_data(D[k])
    vline.set_xdata([times[idx[k]]]*2)
    ttl.set_text("GAIA Digital Twin of Soil — wet season 2025–26, western Cascades (90 m)\n%s"
                 % pd.Timestamp(times[idx[k]]).strftime("%d %b %Y"))
    return ims+[vline,ttl]

out=Path("figures/demo/twin_wetseason.gif"); out.parent.mkdir(parents=True,exist_ok=True)
FuncAnimation(fig,upd,frames=len(idx),blit=False).save(out,writer=PillowWriter(fps=5),dpi=72)
shutil.copy(out, Path("docs/twin/assets")/out.name)
print("wrote %s (%d frames)"%(out,len(idx)))
