"""Probe the verbatim science_gate function with real validators and fake model/GitHub.

Usage: python science-gate-harness.py [--repo PATH] [--output-dir EMPTY_OR_NEW_DIR]
The default output is a fresh temporary directory. No queue is started, and the
real gh/claude binaries are never invoked. Keep gate-fixture.py beside this file.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo', type=Path, default=Path.cwd())
parser.add_argument('--output-dir', type=Path)
args = parser.parse_args()
repo = args.repo.resolve()
fixture = Path(__file__).resolve().with_name('gate-fixture.py')
if not fixture.is_file():
    parser.error(f'Missing adjacent fixture: {fixture}')
source = (repo / 'scripts/gaia_run_queue.sh').read_text()
if args.output_dir is None:
    out = Path(tempfile.mkdtemp(prefix='soil-twin-science-gate-')).resolve()
else:
    out = args.output_dir.resolve()
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        parser.error('--output-dir must be absent or an empty directory; existing evidence is never overwritten')
    out.mkdir(parents=True, exist_ok=True)
start = source.index('science_gate() {\n')
end = source.index('\n}\n', start) + 3
function_file = out / 'science-gate-function.sh'
function_file.write_text(source[start:end])
results = {
    'method': 'Verbatim science_gate() extracted from working-tree runner; real gaia_plan.py/gaia_panel.py; stub brief, gh, claude, timeout, record and label functions. Not a full-queue integration test.',
    'runner_sha256': hashlib.sha256(source.encode()).hexdigest(),
    'cases': [],
}
for scenario in ['approve', 'revise_approve', 'revise_exhaust', 'block_approve', 'major_approve', 'malformed_concerns', 'failed_dispatch', 'wrong_identity']:
    case = out / scenario
    case.mkdir()
    helper = case / 'scripts/gaia-launch'
    helper.mkdir(parents=True)
    for filename in ['gaia_plan.py', 'gaia_panel.py']:
        shutil.copyfile(repo / 'scripts/gaia-launch' / filename, helper / filename)
    (helper / 'gaia_brief.py').write_text('print("Offline prior-work fixture.")\n')
    shell = r'''set -euo pipefail
REPO_DIR="$FIXTURE_DIR"; REPO_SLUG="fixture/offline"; LOG_DIR="$FIXTURE_DIR/logs"; mkdir -p "$LOG_DIR"
GAIA_SCIENCE_GATE=1; GAIA_PLAN_REVISIONS=1; GAIA_PLAN_TIMEOUT=1; GAIA_PLAN_MAX_TURNS=1
GAIA_AUX_TIMEOUT=1; GAIA_AUX_MAX_TURNS=1; GAIA_READONLY_DENY=(Fixture)
ts=fixture; PLAN_FILE="$LOG_DIR/plan.json"; BRIEF_FILE="$LOG_DIR/brief.md"; PANEL_FEEDBACK=""
timeout() { shift 3; "$@"; }
claude() { "$FIXTURE_PYTHON" "$FIXTURE_SCRIPT" "$@"; }
gh() { printf '%s\n' "$*" >> "$FIXTURE_DIR/gh-calls.txt"; }
add_label() { printf '%s\n' "$1:$2" >> "$FIXTURE_DIR/labels.txt"; }
record_gate_block() { printf '%s\n' "$4" >> "$FIXTURE_DIR/outcomes.txt"; }
source "$EXTRACTED_FUNCTION"
if science_gate 900 "Offline fixture" "" "" "$LOG_DIR/run.log"; then echo 0 > "$FIXTURE_DIR/gate-rc"; else echo 1 > "$FIXTURE_DIR/gate-rc"; fi
'''
    (case / 'harness.sh').write_text(shell)
    env = dict(os.environ, FIXTURE_DIR=str(case), FIXTURE_SCENARIO=scenario,
               FIXTURE_SCRIPT=str(fixture), FIXTURE_PYTHON=sys.executable,
               EXTRACTED_FUNCTION=str(function_file), PYTHONDONTWRITEBYTECODE='1')
    proc = subprocess.run(['/bin/bash', str(case / 'harness.sh')], env=env,
                          text=True, capture_output=True, timeout=30)
    (case / 'stdout.txt').write_text(proc.stdout)
    (case / 'stderr.txt').write_text(proc.stderr)
    def read(name):
        path = case / name
        return path.read_text().strip() if path.exists() else None
    prompts = [json.loads(line)['prompt'] for line in (read('prompts.jsonl') or '').splitlines()]
    plans = [prompt for prompt in prompts if 'gaia-study-designer' in prompt]
    results['cases'].append({
        'scenario': scenario, 'harness_exit_code': proc.returncode,
        'gate_return_code': read('gate-rc'), 'plan_attempts': read('plan-count'),
        'labels': read('labels.txt'), 'outcomes': read('outcomes.txt'),
        'second_plan_contains_concern': len(plans) > 1 and 'Check controlled groundwater debit.' in plans[1],
    })
(out / 'science-gate-results.json').write_text(json.dumps(results, indent=2) + '\n')
print(f'Output directory: {out}', file=sys.stderr)
print(json.dumps(results, indent=2))
if any(case['harness_exit_code'] != 0 for case in results['cases']):
    raise SystemExit('A fixture failed to execute; inspect its stderr.txt before interpreting the result.')
