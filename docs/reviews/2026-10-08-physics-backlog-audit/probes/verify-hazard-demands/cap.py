import sys,numpy as np
sys.path.insert(0,'scratchpad/main')
from src.models.water_budget import coupled_water_budget
for P in [50,200,500]:
  p=np.zeros(20);p[5]=P;p[6]=P
  wb=coupled_water_budget(p[:,None],np.zeros(20)[:,None],0.1,0.3,0.45,dt_days=1.0,slope_tan=np.array([0.0]),hand_m=np.array([60.]),wt_depth0_m=np.array([15.]))
  print(P,wb.theta.max(), 0.3+0.15*np.exp(-0.5), wb.wt_depth_m[:,0].min())
# valley: wt above surface?
p=np.full(400,10.0); wb=coupled_water_budget(p[:,None],np.full(400,1.0)[:,None],0.1,0.3,0.45,dt_days=1.0,slope_tan=np.array([0.0]),hand_m=np.array([1.]),wt_depth0_m=np.array([2.]))
print('valley min wt',wb.wt_depth_m.min(), 'baseflow', wb.baseflow_mm.sum())
