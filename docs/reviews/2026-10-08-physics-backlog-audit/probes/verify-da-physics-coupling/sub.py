# BROKEN (2026-10-09, Codex review of PR #229, C5): reads ../wf/da/ident.py, the groundwater
# Jacobian probe, which was overwritten in the scratch tree and never archived. Raises
# FileNotFoundError. The condition numbers it reproduced are therefore unreproduced.
import sys, numpy as np, itertools
sys.path.insert(0,'.')
exec(open('../wf/da/ident.py').read().split("for cname")[0])
for cname,c in cells.items():
    J=[]
    for k in keys:
        p=dict(base);p[k]*=np.exp(eps); m=dict(base); m[k]*=np.exp(-eps)
        J.append((run(c,**p)[0]-run(c,**m)[0])/(2*eps))
    A=np.array(J).T; A=A-A.mean(0); A=A/np.linalg.norm(A,axis=0)
    for sub in [(0,1),(0,2),(1,2),(0,1,2),(0,1,3)]:
        sv=np.linalg.svd(A[:,sub],compute_uv=False); print(cname,[keys[i] for i in sub],'cond %.1f'%(sv[0]/sv[-1]))
