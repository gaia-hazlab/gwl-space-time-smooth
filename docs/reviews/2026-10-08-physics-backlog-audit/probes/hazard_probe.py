import sys, numpy as np
sys.path.insert(0, 'scratchpad/main')
from src.models.water_budget import coupled_water_budget, accumulate_runoff, K_ANISO
rng=np.random.default_rng(0)
# 1. lateral fraction on landslide slopes
for deg in [13.3,18.5,27.9,35,40]:
    t=np.tan(np.radians(deg)); f=K_ANISO*t/(1+K_ANISO*t); print(f"slope {deg:5.1f} f_lat={f:.2f} -> exported recharge = {1-f:.2f} of root-zone drainage")
# synthetic PNW wet season, daily: Oct-Mar ~ 1400 mm, gamma storms
nt=240
p=np.where(rng.random(nt)<0.55, rng.gamma(0.8,14,nt),0.0); p[:30]*=0.3; p[180:]*=0.3
p[100]=120; p[101]=80  # AR
pet=np.full(nt,1.0)
print('total P',p.sum().round())
cells={'valley_fill HAND=1,d0=2':(0.0,1.0,2.0),'terrace HAND=4,d0=3':(0.02,4.0,3.0),'hillslope 30deg HAND=60 d0=15':(np.tan(np.radians(30)),60.0,15.0),'hollow 35deg HAND=20 d0=3':(np.tan(np.radians(35)),20.0,3.0)}
for k,(tb,hand,d0) in cells.items():
    wb=coupled_water_budget(p[:,None],pet[:,None],0.10,0.30,0.45,root_depth_m=1.0,dt_days=1.0,slope_tan=np.array([tb]),hand_m=np.array([hand]),wt_depth0_m=np.array([d0]))
    wt=wb.wt_depth_m[:,0]; th=wb.theta[:,0]
    print(f"{k}: wt min {wt.min():.2f} max {wt.max():.2f} end {wt[-1]:.2f}; d(wt) day99->102 {wt[99]:.2f}->{wt[102]:.2f}; P10 DTW {np.quantile(wt,0.1):.2f}; sum rech {wb.recharge_mm.sum():.0f} inter {wb.interflow_mm.sum():.0f} run {wb.runoff_mm.sum():.0f} bf {wb.baseflow_mm.sum():.0f} aet {wb.aet_mm.sum():.0f}; theta max {th.max():.3f}")
    # lag of wt response peak to AR
    print('   wt days 98..106', np.round(wt[98:107],2))
# 3. accumulate_runoff mass
r=np.ones((50,50)); fa=rng.lognormal(0,2,(50,50)); out=accumulate_runoff(r,fa); print('accumulate_runoff mass ratio',out.sum()/r.sum())
fa2=np.zeros((50,50)); fa2[25,25]=1; print('single-max cell ratio', accumulate_runoff(r,fa2).sum()/r.sum())
# 4. FS sensitivity infinite slope
gw=9.81; gs=19.0
def FS(c,z,beta,phi,m):
    b=np.radians(beta); f=np.radians(phi)
    return (c + (gs-m*gw)*z*np.cos(b)**2*np.tan(f))/(gs*z*np.sin(b)*np.cos(b))
for z,c in [(1.5,4.0),(14.6,10.0)]:
    for beta in [30,35]:
        fs=[FS(c,z,beta,33,m) for m in (0,0.5,1.0)]
        dm=0.1/abs(FS(c,z,beta,33,0)-FS(c,z,beta,33,1))  # fraction of z for dFS=0.1
        print(f"z={z} c={c}kPa beta={beta}: FS dry/half/sat {np.round(fs,2)}; dFS=0.1 <-> dh_w={dm*z:.2f} m")
# 5. Zhu2017/RB2020 GLM wtd sensitivity
for pgv,vs in [(30,200)]:
    X=lambda wtd:8.801+0.334*np.log(pgv)-1.918*np.log(vs)+0.0005408*1500-0.2054*1.0-0.0333*wtd
    for w in (0.5,1.5,3,5,18.5):
        x=X(w); print(f"GLM wtd={w}: X={x:.2f} P={1/(1+np.exp(-x)):.3f}")
    print('Vs30 200->180 dX', -1.918*np.log(180/200))
