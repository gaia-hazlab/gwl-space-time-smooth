import numpy as np
for T in [1,2,3,5,10]:
  for t0frac in [0.0, 0.5]:
    t=np.arange(0,T*365,1.0)
    t0=t0frac*T*365
    dt=np.clip(t-t0,0,None)
    heal=np.where(t>=t0, np.log1p(dt/1.0),0.0)    # log-t healing, tc=1 d
    slow=np.where(t>=t0, 1-np.exp(-dt/(2*365)),0.0) # multi-year exponential
    s=np.sin(2*np.pi*t/365.25); c=np.cos(2*np.pi*t/365.25)
    A=np.column_stack([np.ones_like(t),heal,slow,s,c])
    An=(A-A.mean(0)); An[:,0]=1; An=An/np.linalg.norm(An,axis=0)
    r=np.corrcoef(heal[t>=t0],slow[t>=t0])[0,1]
    # posterior correlation of heal/slow amplitudes with white noise, flat prior
    P=np.linalg.inv(An.T@An); pc=P[1,2]/np.sqrt(P[1,1]*P[2,2])
    vif=np.diag(P)  # since columns unit norm
    print(f"T={T:>2}yr event@{t0frac:.1f}T  corr(heal,slow)={r:.3f}  post-corr={pc:+.3f}  cond={np.linalg.cond(An):.1e}  VIF heal={vif[1]:.0f} slow={vif[2]:.0f}")
