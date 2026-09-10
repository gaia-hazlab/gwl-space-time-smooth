"""Offline model fixture for exact science_gate function; no model or network calls."""
import json, os, re, sys
from pathlib import Path
root=Path(os.environ['FIXTURE_DIR'])
prompt=sys.argv[sys.argv.index('-p')+1]
with (root/'prompts.jsonl').open('a') as f: f.write(json.dumps({'prompt':prompt})+'\n')
scenario=os.environ['FIXTURE_SCENARIO']
if 'gaia-study-designer' in prompt:
    counter=root/'plan-count'; n=int(counter.read_text())+1 if counter.exists() else 1; counter.write_text(str(n))
    name='gaia:gaia-study-designer'
    obj={'obstruction':'Fixture missing coverage.', 'questions':['Does fixture conserve water?'], 'approach':'Perform a deterministic check.', 'artifacts':['test.txt'],'expected_files':1,'expected_lines':1,'expected_runtime_min':1,'stopping_conditions':['Stop on failure.'],'negative_result_criteria':'Show evidence of failure and localize it.', 'out_of_scope':['No external changes.']}
else:
    persona=re.search(r'Use the (\S+) agent',prompt).group(1)
    name=persona if persona.startswith('twin-') else 'gaia:'+persona
    n=int((root/'plan-count').read_text())
    verdict='approve'
    if scenario in ('revise_approve','revise_exhaust') and (n==1 or scenario=='revise_exhaust'): verdict='revise'
    if scenario=='block_approve' and n==1: verdict='block'
    concerns=[] if verdict=='approve' else [{'severity':'major','claim':'Check controlled groundwater debit.','decisive_test':'Dry column transfer must conserve water.'}]
    if scenario=='major_approve': concerns=[{'severity':'major','claim':'Groundwater debit remains absent.','decisive_test':'Conservation oracle.'}]
    if scenario=='malformed_concerns': concerns='critical issue'
    obj={'verdict':verdict,'concerns':concerns}
    if scenario=='wrong_identity': name='not-'+name+'-imposter'
text='```json\n'+json.dumps(obj)+'\n```'
print(json.dumps({'type':'assistant','message':{'content':[{'type':'tool_use','id':'fixture-call','name':'Agent','input':{'subagent_type':name}}]}}))
print(json.dumps({'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':'fixture-call','is_error':scenario=='failed_dispatch','content':'Agent unavailable' if scenario=='failed_dispatch' else text}]}}))
print(json.dumps({'type':'result','result':text}))
