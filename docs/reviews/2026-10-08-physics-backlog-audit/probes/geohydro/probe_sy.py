import sys, types
sys.path.insert(0, "scratchpad/main")
for _m in ("rioxarray","xarray","pandas"):
    try: __import__(_m)
    except ImportError: sys.modules[_m]=types.ModuleType(_m)
import numpy as np
from src.models.soil_moisture import saxton_rawls_envelope
for name,(s,c) in {"sand":(92,3),"loamy sand":(82,6),"sandy loam":(65,10),"loam":(40,20),"silt loam":(20,15),"clay loam":(33,34),"clay":(20,50)}.items():
    e=saxton_rawls_envelope(np.array(s,float),np.array(c,float))
    print(f"{name:11s} wp={float(e['theta_wp']):.3f} fc={float(e['theta_fc']):.3f} sat={float(e['theta_sat']):.3f} drainable(sat-fc)={float(e['theta_sat']-e['theta_fc']):.3f} ksat={float(e['ksat']):.1f} mm/h")
