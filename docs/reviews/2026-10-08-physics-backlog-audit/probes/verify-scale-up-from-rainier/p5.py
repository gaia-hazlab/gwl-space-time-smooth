import sys,numpy as np
exec(open(sys.argv[2]+'/p1.py').read().split('for free,wt')[0])
def rain_series(days, seed=0, wet_frac=0.55, mean_wet_mm=9.0):
    rng=np.random.default_rng(seed); hrs=[]
    for d in range(days):
        if rng.random()<wet_frac:
            tot=rng.gamma(0.8, mean_wet_mm/0.8); w=rng.dirichlet(np.full(24,0.3)); hrs.extend(tot*w)
        else: hrs.extend([0.0]*24)
    return np.array(hrs)/1000/3600
c,h=column(free=False,wt=10.)
for yr in range(4):
    r=rain_series(365,seed=yr)
    H,tot=RI.run(c,h,r,3600.,[0.1,900],1e-4,100,24*365)
    h=H[-1]
    print(yr,{k:round(v*1000,1) for k,v in tot.items()}, 'WT depth', float(c.z[np.argmax(h>=0)]))
