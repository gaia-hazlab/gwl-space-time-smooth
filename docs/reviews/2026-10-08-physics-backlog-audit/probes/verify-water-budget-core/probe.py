import sys, numpy as np
sys.path.insert(0, sys.argv[1])
from src.models.water_budget import coupled_water_budget as cwb
wp,fc,sat=np.array([[0.12]]),np.array([[0.30]]),np.array([[0.45]])
rng=np.random.default_rng(0)
n=365*3
# realistic-ish PNW daily: 1500 mm/yr, wet winters
doy=np.arange(n)%365
pm=1500/365*(1+0.8*np.cos(2*np.pi*(doy-15)/365))
P=(rng.exponential(1,n)*pm*(rng.random(n)<0.5)*2)[:,None,None]
E=(1.6*(1-0.9*np.cos(2*np.pi*(doy-15)/365)))[:,None,None]
print("P/yr",P.sum()/3,"PET/yr",E.sum()/3)
for hand,tanb in ((2.0,0.0),(5.0,0.0),(6.0,0.0),(30.0,0.0),(30.0,0.24)):
    r=cwb(P,E,wp,fc,sat,wt_depth0_m=5.0,dt_days=1.0,hand_m=np.array([[hand]]),slope_tan=np.array([[tanb]]))
    wt=r.wt_depth_m[:,0,0]
    yr=lambda a:a[:,0,0].sum()/3
    print(f"HAND={hand} tanb={tanb}: wt start {wt[0]:.2f} y1end {wt[364]:.2f} y3end {wt[-1]:.2f} min {wt.min():.2f}; rech/yr {yr(r.recharge_mm):.0f} bf/yr {yr(r.baseflow_mm):.0f} run/yr {yr(r.runoff_mm):.0f} int/yr {yr(r.interflow_mm):.0f} aet/yr {yr(r.aet_mm):.0f}")
# full-system residual on shallow table with capillary rise
r=cwb(P,E,wp,fc,sat,wt_depth0_m=1.2,dt_days=1.0,hand_m=np.array([[10.0]]),slope_tan=np.array([[0.1]]))
S=r.theta[:,0,0].astype(float)*1000; G=(1.2-r.wt_depth_m[:,0,0].astype(float))*0.3*1000
out=np.cumsum((r.runoff_mm+r.interflow_mm+r.baseflow_mm+r.aet_mm)[:,0,0].astype(float)); inp=np.cumsum(P[:,0,0])
res=(S+G)-(S[0]+G[0])-(inp-inp[0])+(out-out[0]); print("system residual mm end",res[-1],"cap total",r.cap_rise_mm.sum())
# timestep: dt=1 vs dt=0.25 same forcing rate
P4=np.repeat(P/4,4,axis=0); E4=np.repeat(E/4,4,axis=0)
a=cwb(P,E,wp,fc,sat,wt_depth0_m=5.0,dt_days=1.0,hand_m=np.array([[30.]]),slope_tan=np.array([[0.24]]))
b=cwb(P4,E4,wp,fc,sat,wt_depth0_m=5.0,dt_days=0.25,hand_m=np.array([[30.]]),slope_tan=np.array([[0.24]]))
print("rech dt1",a.recharge_mm.sum(),"dt0.25",b.recharge_mm.sum())
# 455 mm month test
Pm=np.array([[[455.]]]); Em=np.array([[[0.]]])
rm=cwb(Pm,Em,wp,fc,sat,wt_depth0_m=5.0)
rd=cwb(np.full((30,1,1),455/30),np.zeros((30,1,1)),wp,fc,sat,wt_depth0_m=5.0,dt_days=1.0)
print("455mm monthly rech",rm.recharge_mm.sum(),"daily",rd.recharge_mm.sum())
print("Ka effective: tan 0.236 f_lat Ka2",2*0.236/(1+2*0.236))
print("R_ref 3mm/d =",3*365,"mm/yr; BFI*Q/P*P =",0.47*0.65*1500)
