"""Batched (vectorised across columns) modified-Picard Richards iteration in NumPy: cost per column-iteration.
Same discretisation as rainier3d.cz.richards._step (cell-centred, arithmetic interface K, vG-Mualem)."""
import time, numpy as np
def run(B, L=38, reps=20):
    rng=np.random.default_rng(0)
    dz=np.tile(np.diff(np.append(0,np.cumsum(0.05*1.12**np.arange(L)))),(B,1))
    d=0.5*(dz[:,:-1]+dz[:,1:])
    tr=np.full((B,L),0.05); ts=np.full((B,L),0.4); al=np.full((B,L),3.0); n=np.full((B,L),1.5)+0.1*rng.random((B,L)); ks=np.full((B,L),1e-5)
    m=1-1/n; h=-np.abs(rng.normal(2,1,(B,L))); h0=h.copy(); dt=900.0; q=np.full(B,2e-6)
    def theta(h):
        a=(al*np.abs(h))**n; se=np.where(h<0,(1+a)**-m,1.0); return tr+(ts-tr)*se,se,a
    th0,_,_=theta(h0)
    t=time.perf_counter()
    for _ in range(reps):
        th,se,a=theta(h)
        K=ks*np.sqrt(se)*(1-(1-se**(1/m))**m)**2
        Kf=0.5*(K[:,:-1]+K[:,1:]); A=Kf/d
        Cm=np.where(h<0,(ts-tr)*al*n*m*a/np.maximum(al*np.abs(h),1e-12)*(1+a)**-(m+1),0)+1e-5
        diag=dz*Cm/dt; rhs=dz*(Cm*h-th+th0)/dt
        diag[:,:-1]+=A; diag[:,1:]+=A; rhs[:,:-1]-=Kf; rhs[:,1:]+=Kf; rhs[:,0]+=q; rhs[:,-1]-=K[:,-1]
        lo=-A; up=-A
        # Thomas, vectorised over columns
        cp=np.empty((B,L)); dp=np.empty((B,L))
        cp[:,0]=up[:,0]/diag[:,0]; dp[:,0]=rhs[:,0]/diag[:,0]
        for i in range(1,L):
            den=diag[:,i]-lo[:,i-1]*cp[:,i-1]
            if i<L-1: cp[:,i]=up[:,i]/den
            dp[:,i]=(rhs[:,i]-lo[:,i-1]*dp[:,i-1])/den
        x=np.empty((B,L)); x[:,-1]=dp[:,-1]
        for i in range(L-2,-1,-1): x[:,i]=dp[:,i]-cp[:,i]*x[:,i+1]
        h=np.clip(x,-1e3,1e3)
    el=time.perf_counter()-t
    return el/(reps*B)
for B in (1000,10000,50000):
    print(B, "us per column-iteration: %.2f" % (1e6*run(B)))
