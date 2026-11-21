import sys,numpy as np
sys.path.insert(0,"scratchpad/main")
from src.models import dvv
from codameter.uq_depth import band_sensitivity_matrix
K=band_sensitivity_matrix(dvv.pnw_velocity_profile(400.0),np.array([0.2236,0.7071,1.4142,2.8284]))
G=np.asarray(K.G);z=np.asarray(K.depths_km)
for b in range(4):
  neg=G[b]<0; print(b,"min",G[b].min(),"neg frac of |G|",np.abs(G[b][neg]).sum()/np.abs(G[b]).sum(),"sum",G[b].sum(), "neg depths km", z[neg][:6])
