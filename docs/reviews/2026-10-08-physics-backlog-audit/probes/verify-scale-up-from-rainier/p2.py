import sys,time,numpy as np
exec(open(sys.argv[2]+'/p5.py').read().split('c,h=column')[0])
cnt=dict(steps=0,its=0); orig=RI._step
def wrap(*a):
    r=orig(*a); cnt['steps']+=1; cnt['its']+=r[4]; return r
RI._step=wrap
c,h=column(free=False,wt=10.)
r=rain_series(365,seed=0)
t=time.perf_counter(); RI.run(c,h,r,3600.,[0.1,900],1e-4,100,24*365); el=time.perf_counter()-t
print(el/365, cnt['steps']/365, cnt['its']/365, el/cnt['its']*1e6,'us/it')
print(2.96e6*365*el/365/3600)
