"""Test Fable's proposed one-line debit in memory; never modifies repository code."""
import json, sys, types, hashlib
from pathlib import Path
import numpy as np
source_path = Path(sys.argv[1]) / 'src/models/water_budget.py'
source = source_path.read_text()
old = 'h = h + rech / 1000.0 / max(specific_yield, 1e-6)'
new = 'h = h + (rech - cap_eff) / 1000.0 / max(specific_yield, 1e-6)'
assert source.count(old) == 1
module = types.ModuleType('audit_hypothetical_budget')
sys.modules[module.__name__] = module
exec(compile(source.replace(old, new), '<hypothetical-capillary-debit>', 'exec'), module.__dict__)
records=[]
for label, extra in [('legacy_default', {}), ('legacy_negligible_recession', {'recession_months':1e12}), ('hand_zero', {'hand_m':0.0})]:
 r=module.coupled_water_budget(np.zeros(1),np.zeros(1),theta_wp=.1,theta_fc=.3,theta_sat=.5,root_depth_m=1.,specific_yield=.3,wt_depth0_m=.5,init='wp',dt_days=1.,cap_max_mm=30.,**extra)
 root=(float(r.theta[0])-.1)*1000
 gw=.3*(.5-float(r.wt_depth_m[0]))*1000
 out=sum(float(getattr(r,key)[0]) for key in ['runoff_mm','interflow_mm','baseflow_mm','aet_mm'])
 records.append({'case':label,'root_storage_change_mm':root,'groundwater_storage_change_mm':gw,'external_outflow_mm':out,'balance_residual_mm':root+gw+out})
print(json.dumps({'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'hypothetical_edit':{'before':old,'after':new},'cases':records,'note':'In-memory candidate only. Legacy recession can add water back for negative h while reporting no negative boundary flux.'},indent=2))
