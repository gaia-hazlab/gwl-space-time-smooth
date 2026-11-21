import sys,numpy as np
sys.path.insert(0,sys.argv[1])
from src.models.water_budget import coupled_water_budget as cwb
rng=np.random.default_rng(0); nt=300
P=rng.gamma(0.5,8,(nt,3)); pet=np.full((nt,3),2.0)
for hand in [None, np.array([60.,10.,0.5])]:
    wt0=np.array([20.,3.,1.0]); z=1.0
    b=cwb(P,pet,0.1,0.3,0.45,root_depth_m=1.0,wt_depth0_m=wt0,dt_days=1,slope_tan=np.array([0.3,0.1,0.0]),hand_m=hand)
    # storages: S0 = fc*z*1000
    S0=0.3*1000; Send=b.theta[-1].astype(float)*1000
    h_end=wt0-b.wt_depth_m[-1].astype(float)
    out=(b.runoff_mm+b.aet_mm+b.interflow_mm+b.baseflow_mm).sum(0)
    res=P.sum(0)-out-(Send-S0)-0.30*h_end*1000
    print('hand',hand,'res',res.round(2),'cap',b.cap_rise_mm.sum(0).round(2),'min wt',b.wt_depth_m.min(0))
