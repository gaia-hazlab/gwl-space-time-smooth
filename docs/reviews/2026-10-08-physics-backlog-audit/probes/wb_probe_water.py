import sys, numpy as np
sys.path.insert(0, sys.argv[1])
from src.models.water_budget import coupled_water_budget as cwb
wp,fc,sat=np.array([[0.12]]),np.array([[0.30]]),np.array([[0.45]])
# 1) valley-floor ratchet: HAND=2 m < wt0=5 m
n=365; P=np.zeros((n,1,1)); P[30:33]=60.0; P[200:203]=60.0; E=np.full((n,1,1),1.0)
for hand in (2.0, 6.0, 30.0):
    r=cwb(P,E,wp,fc,sat,wt_depth0_m=5.0,dt_days=1.0,hand_m=np.array([[hand]]),slope_tan=np.array([[0.0]]))
    print("HAND",hand,"wt start/after storm1/end", r.wt_depth_m[0,0,0], r.wt_depth_m[40,0,0], r.wt_depth_m[-1,0,0], "baseflow tot",r.baseflow_mm.sum(), "rech tot", r.recharge_mm.sum())
# recession timescale
for head0 in (1,5,20,50):
    k=(3.0/1000/0.3)/head0; print("head0",head0,"tau days",1/k)
# 2) VSA deficit
for d in (0.5,1,2,5,20): print("wt",d,"VSA deficit mm",0.3*d*1000)
# 3) daily vs monthly, 455 mm in a month
Pm=np.array([[[455.]]]); Em=np.array([[[0.]]])
rm=cwb(Pm,Em,wp,fc,sat,wt_depth0_m=5.0)
Pd=np.full((30,1,1),455/30); Ed=np.zeros((30,1,1))
rd=cwb(Pd,Ed,wp,fc,sat,wt_depth0_m=5.0,dt_days=1.0)
print("monthly rech",rm.recharge_mm.sum(),"daily rech",rd.recharge_mm.sum())
# 4) whole-system mass: root S + Sy*h + outfluxes
r=cwb(P,E,wp,fc,sat,wt_depth0_m=0.8,dt_days=1.0,hand_m=np.array([[10.0]]))
S=r.theta[:,0,0].astype(float)*1000; G=(0.8-r.wt_depth_m[:,0,0].astype(float))*0.3*1000
tot=S+G; out=np.cumsum((r.runoff_mm+r.interflow_mm+r.baseflow_mm+r.aet_mm)[:,0,0].astype(float)); inp=np.cumsum(P[:,0,0])
res=(tot-tot[0])-(inp-inp[0])+(out-out[0]); print("shallow table system residual mm (end)",res[-1],"cap total",r.cap_rise_mm.sum())
