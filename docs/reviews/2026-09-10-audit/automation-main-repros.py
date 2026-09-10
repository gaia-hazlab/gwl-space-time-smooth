"""Safe main-snapshot reproductions: no runner, model calls, or GitHub writes."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
BASE = Path(sys.argv[1]).resolve()
ISSUES = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else Path(__file__).with_name('issue-source-snapshot.json')
sys.path.insert(0, str(BASE / 'scripts/gaia-launch'))
import gaia_panel as panel
import gaia_gate_integrity as integrity
spec = importlib.util.spec_from_file_location('main_queue', BASE / 'scripts/gaia_group_issues.py')
queue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(queue)

def issue(n, milestone='Shared milestone', labels=()):
    return {'number': n, 'title': f'Issue {n}', 'milestone': {'title': milestone},
            'labels': [{'name': label} for label in labels]}

def batches(issues):
    queue.fetch_issues = lambda: issues
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        queue.main()
    return [{'branch': b['branch'], 'issues': [i['number'] for i in b['issues']]}
            for b in map(json.loads, out.getvalue().splitlines())]

results = {}
results['panel_revise_is_nonblock'] = panel.aggregate([
    panel.normalise_verdict({'verdict': 'approve', 'concerns': []}, 'gaia-auditor'),
    panel.normalise_verdict({'verdict': 'revise', 'concerns': [
        {'severity': 'major', 'claim': 'Acceptance test uses contaminated holdout.',
         'decisive_test': 'Rebuild folds without the withheld well.'}]}, 'twin-geostatistician')])
results['empty_panel_approves'] = panel.aggregate([])
results['malformed_concerns_approve'] = panel.aggregate([
    panel.normalise_verdict({'verdict': 'approve', 'concerns': 'critical issue'}, 'gaia-auditor')])
results['novelty_reviewers_silently_omitted_at_cap'] = panel.route(
    ['uncertainty'], 'Applied math: DA estimator correctness', 'A novel unprecedented breakthrough')

with tempfile.TemporaryDirectory(prefix='gaia-main-repro-', dir='/tmp') as td:
    wd = Path(td)
    raw = wd/'failed-dispatch.jsonl'
    verdict = wd/'verdict.json'
    events = [
      {'type':'assistant', 'message':{'content':[{'type':'tool_use','id':'requested-review',
          'name':'Agent','input':{'subagent_type':'gaia:gaia-auditor'}}]}},
      {'type':'user', 'message':{'content':[{'type':'tool_result','tool_use_id':'requested-review',
          'is_error':True,'content':'Agent unavailable; it did not run.'}]}},
      {'type':'result','result':'\x60\x60\x60json\n{"verdict":"approve","concerns":[]}\n\x60\x60\x60'},
    ]
    raw.write_text(''.join(json.dumps(e)+'\n' for e in events))
    proc = subprocess.run([sys.executable, str(BASE/'scripts/gaia-launch/gaia_panel.py'),
         '--from-stream', str(raw), '--expect', 'gaia:gaia-auditor', '--out', str(verdict)],
         capture_output=True,text=True)
    results['failed_dispatch_followed_by_wrapper_approval'] = {
        'exit_code':proc.returncode,'stderr':proc.stderr.strip(),
        'verdict':json.loads(verdict.read_text())}

results['branch_identity_changes_with_backlog'] = {
 'initial':batches([issue(n) for n in [105,104,103,102,101]]),
 'after_first_four_close':batches([issue(101)]),
 'new_issue_arrives':batches([issue(n) for n in [106,105,104,103,102,101]])}
results['colliding_normalized_milestone_titles'] = batches([
    issue(901,'A shared very long milestone title prefix suffix one'),
    issue(902,'A shared very long milestone title prefix suffix two')])
snapshot = json.loads(ISSUES.read_text())
ready = batches([i for i in snapshot if i['state']=='open'])
results['real_human_blocked_issues_redispatched'] = [b for b in ready
    if set(b['issues']) & {163,186}]

results['gate_integrity_can_be_disabled_without_detector_finding'] = integrity.analyse('''diff --git a/scripts/gaia-launch/gaia_gate_integrity.py b/scripts/gaia-launch/gaia_gate_integrity.py
--- a/scripts/gaia-launch/gaia_gate_integrity.py
+++ b/scripts/gaia-launch/gaia_gate_integrity.py
@@ -220 +220 @@
-    return 1 if blocking else 0
+    return 0
''')
results['lowering_minimum_accuracy_not_detected'] = integrity.analyse('''diff --git a/tests/test_model.py b/tests/test_model.py
--- a/tests/test_model.py
+++ b/tests/test_model.py
@@ -10 +10 @@
-    assert coverage > 0.90
+    assert coverage > 0.10
''')

# Reproduce ONLY the stop-state conditional in an isolated shell snippet.
# This does not source, execute, or contact anything from the queue runner.
snippet = '''any_committed=0; batch_failed=0; GAIA_STOP=0; worked=""
for number in 900 901; do
  if [ "$GAIA_STOP" -ne 0 ]; then break; fi
  worked="$worked $number"; any_committed=1; GAIA_STOP=1
done
if [ "$batch_failed" -ne 0 ]; then echo PARK; elif [ "$any_committed" -eq 0 ]; then echo NOOP;
else echo "gate-and-merge reachable; worked:$worked; Closes list: 900 901"; fi
'''
results['stop_after_first_issue_reaches_merge_path'] = subprocess.run(
    ['bash','-c',snippet],capture_output=True,text=True,check=True).stdout.strip()

print(json.dumps(results,indent=2))
