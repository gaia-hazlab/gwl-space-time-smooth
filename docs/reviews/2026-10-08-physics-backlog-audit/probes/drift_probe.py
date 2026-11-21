import sys, numpy as np
sys.path.insert(0,'scratchpad/main')
from src.models.water_budget import coupled_water_budget
rng=np.random.default_rng(1)
ny=20; nt=365*ny
doy=np.arange(nt)%365
wet=(doy<120)|(doy>=275)   # Oct-Apr wet
p=np.where(wet&(rng.random(nt)<0.6), rng.gamma(0.8,15,nt), np.where(rng.random(nt)<0.15, rng.gamma(0.8,6,nt),0))
pet=2.0+2.0*np.sin(2*np.pi*(doy-100)/365)  # ~730 mm/yr
print('P/yr',p.sum()/ny, 'PET/yr', pet.sum()/ny)
for name,(deg,hand,d0) in {'hillslope30':(30,60,15),'hollow35':(35,20,3),'gentle10':(10,15,5),'valley':(0.5,1.0,2.0)}.items():
    wb=coupled_water_budget(p[:,None],pet[:,None],0.10,0.30,0.45,root_depth_m=1.0,dt_days=1.0,
        slope_tan=np.array([np.tan(np.radians(deg))]),hand_m=np.array([hand]),wt_depth0_m=np.array([d0]))
    wt=wb.wt_depth_m[:,0]
    yr=[wt[i*365:(i+1)*365] for i in range(ny)]
    print(f"{name}: mean rech {wb.recharge_mm.sum()/nt:.2f} mm/d (R_ref 3.0); DTW yr1 mean {yr[0].mean():.2f} yr5 {yr[4].mean():.2f} yr20 {yr[-1].mean():.2f}; yr20 P10 {np.quantile(yr[-1],0.1):.2f} amplitude yr20 {yr[-1].max()-yr[-1].min():.2f}")
