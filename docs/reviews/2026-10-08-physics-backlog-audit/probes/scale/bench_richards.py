"""Benchmark rainier3d's serial 1D Richards solver (imported read-only) on a representative column.
Scratch probe; no repo edits."""
import sys, time, json
import numpy as np
sys.path.insert(0, sys.argv[1] + "/src")
from rainier3d.cz import richards as RI

def grid(base, top=0.05, g=1.12):
    tops=[0.0]; h=top
    while tops[-1]+h < base:
        tops.append(tops[-1]+h); h*=g
    e=np.append(tops, base); return 0.5*(e[:-1]+e[1:]), np.diff(e)

def column(base=30.0, wt=10.0, free=False):
    z, dz = grid(base)
    soil = z < 1.4; cover = (z >= 1.4) & (z < 15); wea = z >= 15
    sel = lambda a,b,c: np.select([soil,cover,wea],[a,b,c])
    c = RI.Column(dz=dz, z=z,
        theta_r=sel(0.06,0.05,0.03), theta_s=sel(0.55,0.35,0.25),
        alpha=sel(3.0,3.0,1.0), n=sel(1.4,1.6,1.4),
        ksat=sel(1.6e-5,1.0e-5,1.0e-6),
        bottom_head=None if free else z[-1]-wt)
    h0 = z - wt
    return c, h0

def rain_series(days, seed=0, wet_frac=0.55, mean_wet_mm=9.0):
    rng=np.random.default_rng(seed); hrs=[]
    for d in range(days):
        if rng.random()<wet_frac:
            tot=rng.gamma(0.8, mean_wet_mm/0.8); w=rng.dirichlet(np.full(24,0.3))
            hrs.extend(tot*w)
        else: hrs.extend([0.0]*24)
    return np.array(hrs)/1000/3600

out={}
for name,(base,free) in {"30m_fixedWT10m":(30,False),"30m_free":(30,True),"150m_fixedWT10m":(150,False)}.items():
    c,h0=column(base, free=free)
    days=int(sys.argv[2]) if len(sys.argv)>2 else 30
    r=rain_series(days)
    t=time.perf_counter()
    try:
        H,tot=RI.run(c,h0,r,3600.0,[0.1,900],1e-4,100,24)
        ok=True; reason=None
    except RuntimeError as e:
        ok=False; reason=str(e); tot={}
    dt=time.perf_counter()-t
    mm=lambda k: 1000*float(tot[k]) if k in tot else None  # null, not NaN, when unavailable
    out[name]=dict(nlayers=len(c.z), days=days, rain_mm=float(r.sum()*3600*1000), wall_s=dt,
                   s_per_column_day=dt/days, ok=ok, failure_reason=reason,
                   mb_err_mm=mm("mass_balance_error"), runoff_mm=mm("runoff"), bottom_mm=mm("bottom"))
print(json.dumps(out, indent=1, allow_nan=False))
