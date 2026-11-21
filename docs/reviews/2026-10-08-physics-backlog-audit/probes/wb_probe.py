import sys, numpy as np
sys.path.insert(0,'scratchpad/main')
from src.models.water_budget import coupled_water_budget as cwb, SPECIFIC_YIELD
env=dict(theta_wp=0.12,theta_fc=0.30,theta_sat=0.45)
# 1. #89: same 455 mm in one month, monthly vs daily
P=455.; 
m=cwb(np.array([[P]]),np.array([[0.]]),**env)
d=cwb(np.full((30,1),P/30),np.zeros((30,1)),dt_days=1.0,**env)
print('#89 monthly rech %.1f mm dWT %.2f | daily rech %.1f dWT %.2f ratio %.2f'%(m.recharge_mm.sum(),5-m.wt_depth_m[-1,0],d.recharge_mm.sum(),5-d.wt_depth_m[-1,0],d.recharge_mm.sum()/m.recharge_mm.sum()))
# multi-month with PET
rng=np.random.default_rng(0)
Pm=np.tile([200,180,150,100,60,30,15,20,60,150,220,230],10).astype(float); PETm=np.tile([10,15,30,50,80,100,120,110,70,35,15,10],10).astype(float)
m=cwb(Pm[:,None],PETm[:,None],**env)
Pd=np.repeat(Pm/30.436875,30)[:,None]; PETd=np.repeat(PETm/30.436875,30)[:,None]
d=cwb(Pd,PETd,dt_days=1.0,**env)
print('#89 10yr climatology: monthly rech/yr %.0f, daily rech/yr %.0f'%(m.recharge_mm.sum()/10,d.recharge_mm.sum()/10))
# 2. capillary rise mass leak: shallow table, no rain, legacy (no hand)
n=120
r=cwb(np.zeros((n,1)),np.full((n,1),60.),wt_depth0_m=1.5,**env)
print('#172 cap rise total %.0f mm over 10 yr; WT change %.3f m (should drop %.2f m if debited)'%(r.cap_rise_mm.sum(), r.wt_depth_m[-1,0]-1.5, r.cap_rise_mm.sum()/1000/SPECIFIC_YIELD))
# 3. valley-floor cell HAND < wt0 with hand mode: runaway?
for hand in [0.0,2.0,30.0]:
  r=cwb(Pm[:,None],PETm[:,None],wt_depth0_m=3.0,hand_m=np.array([hand]),slope_tan=np.array([0.05]),**env)
  print('hand=%4.1f wt0=3: final wt_depth %.2f m min %.2f; recharge/yr %.0f baseflow/yr %.0f runoff/yr %.0f cap/yr %.0f'%(hand,r.wt_depth_m[-1,0],r.wt_depth_m.min(),r.recharge_mm.sum()/10,r.baseflow_mm.sum()/10,r.runoff_mm.sum()/10,r.cap_rise_mm.sum()/10))
# daily too
for hand in [0.0,30.0]:
  r=cwb(Pd,PETd,dt_days=1.0,wt_depth0_m=3.0,hand_m=np.array([hand]),slope_tan=np.array([0.05]),**env)
  print('DAILY hand=%4.1f: final wt %.2f min %.2f; rech/yr %.0f bf/yr %.0f runoff/yr %.0f cap/yr %.0f'%(hand,r.wt_depth_m[-1,0],r.wt_depth_m.min(),r.recharge_mm.sum()/10,r.baseflow_mm.sum()/10,r.runoff_mm.sum()/10,r.cap_rise_mm.sum()/10))
# 4. #173: VSA fires? deficit at 5 m
print('#173 VSA deficit at wt=5m: %.0f mm; at 0.5 m: %.0f mm'%(SPECIFIC_YIELD*5*1000, SPECIFIC_YIELD*0.5*1000))
# 5. mass balance closure check in hand mode daily
r=cwb(Pd,PETd,dt_days=1.0,wt_depth0_m=3.0,hand_m=np.array([30.0]),slope_tan=np.array([0.2]),**env)
dS=(r.theta[-1,0]-0.30)*1000
lhs=Pd.sum()+r.cap_rise_mm.sum()-r.runoff_mm.sum()-r.aet_mm.sum()-r.recharge_mm.sum()-r.interflow_mm.sum()
print('root store closure resid %.2f mm'%(lhs-dS))
gw=(3.0-r.wt_depth_m[-1,0])*SPECIFIC_YIELD*1000
print('gw closure: rech-bf-cap %.1f vs dStore %.1f (cap not debited -> resid %.1f)'%(r.recharge_mm.sum()-r.baseflow_mm.sum()-r.cap_rise_mm.sum(),gw, r.recharge_mm.sum()-r.baseflow_mm.sum()-gw))
# f_lat with Ka=2 at slopes
for s in [0.05,0.236,0.5]: print('tanb %.3f f_lat %.2f'%(s,2*s/(1+2*s)))
