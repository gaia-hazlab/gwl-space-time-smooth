# Sensitivity of Zhu et al. (2017) global geospatial liquefaction GLM (as implemented by
# Rashidian & Baise 2020 / USGS ground-failure) to its inputs. Coefficients from memory; verify.
import numpy as np, sys
sys.path.insert(0,'../../main')
def X(pgv,vs30,precip,dw_km,wtd_m):
    return 8.801+0.334*np.log(pgv)-1.918*np.log(vs30)+5.408e-4*precip-0.2054*dw_km-0.0333*wtd_m
P=lambda x:1/(1+np.exp(-x))
base=dict(pgv=30,vs30=200,precip=1000,dw_km=0.5,wtd_m=3)
x0=X(**base); print('base X',round(x0,3),'P',round(P(x0),3))
for k,lo,hi in [('wtd_m',1,5),('wtd_m',0.5,2.0),('vs30',200*np.exp(-0.35),200*np.exp(0.35)),('pgv',30/1.8,30*1.8)]:
    a=dict(base);a[k]=lo;b=dict(base);b[k]=hi
    print(k,round(lo,2),round(hi,2),'dP',round(P(X(**a))-P(X(**b)),3))
from src.data.fetch_vs30 import wald_allen_vs30, nehrp_class_probabilities
for sdeg in [0.001,0.05,0.12,0.5,1,5,10]:
    v=wald_allen_vs30(sdeg); print('slope',sdeg,'deg ->',v, 'P(E..A) sigma_ln=0.4', np.round(nehrp_class_probabilities(float(v),0.4,lognormal=True),2))
print('grad of 0.126 deg =',np.tan(np.deg2rad(0.126)))
