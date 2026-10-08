import numpy as np
# Temporal basis identifiability for dv/v = a*seasonal + b*log-healing + c*slow-exp + noise
# Event at t0 (known), healing tmin=1 d; slow exponential T=3 yr (fire/disturbance recovery)
def basis(n_days, t0, tmin=1.0, T=3*365.0, known=True):
    t = np.arange(n_days, dtype=float)
    s = np.sin(2*np.pi*t/365.25); c = np.cos(2*np.pi*t/365.25)
    step = (t >= t0).astype(float)
    dt = np.maximum(t - t0, 0)
    heal = step*np.log1p(dt/tmin)          # log-t healing after event (Snieder 2017 form approx)
    slow = step*np.exp(-dt/T)               # multi-year exponential recovery
    X = np.column_stack([np.ones_like(t), s, c, step, heal, slow])
    return X
def vif(X):
    Xs = (X - X.mean(0))/X.std(0); Xs = Xs[:,1:]
    C = np.corrcoef(Xs, rowvar=False)
    return np.diag(np.linalg.inv(C))
for yrs in (1, 2, 5, 10):
    n = int(yrs*365)
    for t0frac in (0.1, 0.5):
        X = basis(n, t0frac*n)
        Xn = X/np.linalg.norm(X,axis=0)
        k = np.linalg.cond(Xn)
        v = vif(X)
        print(f"record {yrs:2d} yr, event at {t0frac:.0%}: cond={k:9.1f}  VIF[sin,cos,step,logheal,slowexp]={np.round(v,1)}")
# unknown event: is the step/log/exp separable from seasonal if t0 misplaced by 30 days? -> bias
