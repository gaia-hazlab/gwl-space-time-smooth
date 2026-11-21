import sys,numpy as np
exec(open(sys.argv[2]+'/p1.py').read().split('for free,wt')[0])
for wt in [0.0,0.3,1.0,3.0]:
  for q in [0,5e-6,2e-5]:
    c,h0=column(free=False,wt=wt)
    try:
        H,tot=RI.run(c,h0,np.full(24,q),3600.,[0.1,900],1e-4,100,24); r='ok'
    except RuntimeError as e: r=str(e)
    print(wt,q,r)
