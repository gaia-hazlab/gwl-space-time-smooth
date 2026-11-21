import sys,numpy as np
sys.path.insert(0,sys.argv[1]+"/src")
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
    c = RI.Column(dz=dz, z=z, theta_r=sel(0.06,0.05,0.03), theta_s=sel(0.55,0.35,0.25),
        alpha=sel(3.0,3.0,1.0), n=sel(1.4,1.6,1.4), ksat=sel(1.6e-5,1.0e-5,1.0e-6),
        bottom_head=None if free else z[-1]-wt)
    return c, z-wt
for free,wt in [(True,10.),(True,40.),(False,10.)]:
  c,h0=column(free=free,wt=wt)
  for dt in [0.1,10,900]:
    for itmax in [100,2000,20000]:
      h,ok,inf,qb,it=RI._step(c,h0,dt,0.0,1e-4,itmax)
      print(f"free={free} wt={wt} dt={dt} itmax={itmax} ok={ok} it={it}")
      if ok: break
