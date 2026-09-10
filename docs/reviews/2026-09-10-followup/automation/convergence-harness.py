"""Probe the verbatim final-auditor function with all git/GitHub/model calls stubbed.

Usage: python convergence-harness.py [--repo PATH] [--output-dir EMPTY_OR_NEW_DIR]
The default output is a fresh temporary directory. The queue itself is never run.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo', type=Path, default=Path.cwd())
parser.add_argument('--output-dir', type=Path)
args = parser.parse_args()
repo = args.repo.resolve()
source = (repo / 'scripts/gaia_run_queue.sh').read_text()
if args.output_dir is None:
    out = Path(tempfile.mkdtemp(prefix='soil-twin-convergence-')).resolve()
else:
    out = args.output_dir.resolve()
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        parser.error('--output-dir must be absent or an empty directory; existing evidence is never overwritten')
    out.mkdir(parents=True, exist_ok=True)
start = source.index('audit_pr_convergence() {\n')
end = source.index('\n}\n', start) + 3
function_file = out / 'convergence-function.sh'
function_file.write_text(source[start:end])
results = []
for name, verdict in [
    ('valid', {'converged': True, 'blocking': [], 'rationale': 'Fixture accepted.'}),
    ('contradiction', {'converged': True, 'blocking': ['Mass residual is unresolved.'], 'rationale': 'Contradictory fixture.'}),
    ('string_true', {'converged': 'true', 'blocking': [], 'rationale': 'Wrong type.'}),
    ('missing_blocking', {'converged': True, 'rationale': 'Missing list.'}),
    ('proper_block', {'converged': False, 'blocking': ['Mass residual.'], 'rationale': 'Not done.'}),
]:
    case = out / ('convergence-' + name)
    case.mkdir()
    shell = r'''set -euo pipefail
GAIA_AUDIT_GATE=1; GAIA_AUX_TIMEOUT=1; GAIA_AUX_MAX_TURNS=1; GAIA_READONLY_DENY=(Fixture)
REPO_DIR="$FIXTURE_DIR"
timeout() { shift 3; "$@"; }
claude() { printf '%s\n' "$*" > "$FIXTURE_DIR/prompt.txt"; printf '```json\n%s\n```\n' "$FIXTURE_VERDICT"; }
git() { if [ "$1" = merge-base ]; then echo abcdef; else echo 'fixture diff'; fi; }
gh() { printf '%s\n' "$*" >> "$FIXTURE_DIR/gh-calls.txt"; }
source "$EXTRACTED_FUNCTION"
if audit_pr_convergence 900 fixture '#900' '' "$FIXTURE_DIR/run.log"; then echo 0 > "$FIXTURE_DIR/gate-rc"; else echo 1 > "$FIXTURE_DIR/gate-rc"; fi
'''
    (case / 'harness.sh').write_text(shell)
    env = dict(os.environ, FIXTURE_DIR=str(case), FIXTURE_VERDICT=json.dumps(verdict),
               EXTRACTED_FUNCTION=str(function_file))
    proc = subprocess.run(['/bin/bash', str(case / 'harness.sh')], env=env,
                          capture_output=True, text=True, timeout=30)
    (case / 'stdout.txt').write_text(proc.stdout)
    (case / 'stderr.txt').write_text(proc.stderr)
    result_file = case / 'gate-rc'
    results.append({'scenario': name, 'input': verdict, 'harness_exit_code': proc.returncode,
                    'gate_return_code': result_file.read_text().strip() if result_file.exists() else None})
(out / 'convergence-results.json').write_text(json.dumps(results, indent=2) + '\n')
print(f'Output directory: {out}', file=sys.stderr)
print(json.dumps(results, indent=2))
if any(case['harness_exit_code'] != 0 for case in results):
    raise SystemExit('A fixture failed to execute; inspect its stderr.txt before interpreting the result.')
