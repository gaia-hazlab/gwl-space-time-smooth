import sys, numpy as np, time
sys.path.insert(0, "scratchpad/main")
from src.models import dvv, dvv_coupling as dc
# 1. material vadose sensitivity d(dv/v)/dtheta
for sand,clay in [(70,10),(40,20),(20,40)]:
    env = dc.coupling_envelope(np.array([[sand]]),np.array([[clay]]),np.array([[0.08]]),np.array([[0.45]]))
    for th in [0.15,0.25,0.35]:
        v0=dc._vs_vadose(np.array([[th]]),env); v1=dc._vs_vadose(np.array([[th+0.01]]),env)
        print(f"sand{sand} clay{clay} th{th}: Vs={v0[0,0]:.0f} m/s  ddvv/dth={( (v1-v0)/v0/0.01)[0,0]:.2f}")
# 2. kernels & resolution
from codameter.uq_depth import band_sensitivity_matrix, invert_depth_profile
prof = dvv.pnw_velocity_profile(400.0)
fc = np.sqrt(np.array(dvv.DEFAULT_BANDS)[:,0]*np.array(dvv.DEFAULT_BANDS)[:,1])
t=time.time(); K = band_sensitivity_matrix(prof, fc); print("kernel build s", time.time()-t)
z=np.asarray(K.depths_km); G=np.asarray(K.G)
print("fc",fc, "peak depths km", K.peak_depths_km)
for b in range(len(fc)):
    print(f"band {fc[b]:.2f}Hz frac weight top1m={G[b,z<=0.001].sum()/G[b].sum():.4f} top10m={G[b,z<=0.01].sum()/G[b].sum():.3f} top30m={G[b,z<=0.03].sum()/G[b].sum():.3f}")
print("dz first nodes", z[:5])
# resolution: invert unit perturbations
cov=np.diag(np.full(len(fc),3e-4**2))
def inv(d):
    p=invert_depth_profile(d,cov,K,prior_std=5e-3,corr_length_km=0.1); return np.asarray(p.mean), p.std
# truth A: 5% softening in top 1 m only
for name,mask in [("top1m",z<=0.001),("top5m",z<=0.005),("top30m",z<=0.03),("below30m",z>0.03)]:
    m=np.where(mask,-0.05,0.0); d=G@m
    mh,sd=inv(d)
    r=dvv.invert_states_from_bands(d,cov,K,water_table_km=0.03)
    print(f"truth -5% in {name}: band dvv={np.round(d*100,3)}%, recovered mean top1m={mh[z<=0.001].mean()*100 if (z<=0.001).any() else np.nan:.3f}% top30m={mh[z<=0.03].mean()*100:.3f}% deep={mh[z>0.03].mean()*100:.3f}%  SMdvv={r['soil_moisture_dvv']*100:.3f}% WTDdvv={r['wtd_relative_dvv']*100:.3f}% sd_sm={r['soil_moisture_dvv_std']*100:.3f}%")
# 3. Hertz-Mindlin K_sat estimate kernel averaged: WT at 5 m drops 1 m
zm=z*1000; wt=5.0
sig=np.where(zm<=wt,18*zm,18*wt+9.2*(zm-wt))  # kPa
dsig=np.where(zm>wt+1,9.81,np.where(zm>wt,9.81*(zm-wt),0))
m=(1/6)*dsig/np.clip(sig,1,None)
print("HM dv/v per m WT drop (kernel avg per band):", np.round(G@m,5), "K_SAT=",dc.K_SAT)
