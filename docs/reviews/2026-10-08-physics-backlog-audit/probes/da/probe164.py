import numpy as np
s=1.0; sig2=0.25; N=5
g=np.ones((N,1)); B=np.array([[s]])
for name,R in [("full",sig2*np.ones((N,N))),("diag",sig2*np.eye(N)),("rho0.999",sig2*(0.999*np.ones((N,N))+0.001*np.eye(N)))]:
    M=g@B@g.T+R
    print(name,"cond(M)=%.2e"%np.linalg.cond(M), "eigmin=%.2e"%np.linalg.eigvalsh(M).min())
    try:
        np.linalg.cholesky(M); 
    except Exception as e: print("  cholesky fails:",e)
    vp=s-(B@g.T@np.linalg.pinv(M)@g@B)[0,0]
    print("  post var (pinv)=%.4f"%vp)
print("single datum post var", s*sig2/(s+sig2), " diag-N analytic", s*sig2/(N*s+sig2), " ratio", (s*sig2/(N*s+sig2))/(s*sig2/(s+sig2)))
