import numpy as np, sys
sys.path.insert(0,'.')
from src.models.water_budget import coupled_water_budget
wp,fc,sat=np.array([0.12]),np.array([0.30]),np.array([0.46])
rng=np.random.default_rng(0)
n=300
P=np.where(rng.random((n,3))<0.4, rng.gamma(2,10,(n,3)),0.0)
E=np.full((n,3),2.0)
# cells: ridge (hand 60, d0 20), valley (hand 1, d0 3), mid (hand 10,d0 2)
hand=np.array([60.,1.,10.]); d0=np.array([20.,3.,2.]); tb=np.array([0.4,0.0,0.1])
for cfg in [dict(), dict(hand_m=hand, slope_tan=tb)]:
    wb=coupled_water_budget(P,E,wp,fc,sat,root_depth_m=1.0,wt_depth0_m=d0,dt_days=1.0,**cfg)
    z=1000.
    S=wb.theta.astype(float)*z; Sy=0.30
    S0=fc*z
    dS=S[-1]-S0
    h=(d0-wb.wt_depth_m[-1])*Sy*1000
    out=wb.runoff_mm.sum(0)+wb.interflow_mm.sum(0)+wb.baseflow_mm.sum(0)+wb.aet_mm.sum(0)
    resid=P.sum(0)-out-dS-h
    print(cfg.keys(), 'P',P.sum(0).round(0),'resid(P-out-dS-dGW) mm',resid.round(1),'cap',wb.cap_rise_mm.sum(0).round(1),'wt_end',wb.wt_depth_m[-1].round(2), 'wt_min', wb.wt_depth_m.min(0).round(2))
