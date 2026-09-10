"""Replay the repository's unchanged DOI checker against this audit's primary metadata.

From the repository root, run with its Python environment:
  python path/to/replay_metadata_gate.py
No network requests or repository writes. Evidence JSON defaults to the script directory.
"""
from pathlib import Path
import argparse
import contextlib
import importlib.util
import io
import json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo', type=Path, default=Path.cwd())
parser.add_argument('--evidence', type=Path, default=Path(__file__).with_name('bibliography-entry-dispositions.json'))
args = parser.parse_args()
spec = importlib.util.spec_from_file_location('doi_checker', args.repo / 'scripts/check_doi_integrity.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
data = json.loads(args.evidence.read_text(encoding='utf-8'))
cache = {e['bib']['doi'].lower(): e['registry_metadata'] for e in data['entries'] if e.get('primary_registry') == 'crossref'}
checker.crossref_metadata = lambda doi: cache.get(doi.lower())
print('CACHED REPLAY: source retrieval date 2026-09-10; this is not a new network check.')
status = checker.check_metadata(args.repo / 'docs/references.bib')
print('EXIT_STATUS=', status)
probes = {}
for key in ('shi2026agroseismology', 'ramcharan2018soil', 'degraaf2015global', 'zhu2015geospatial', 'cook2009floodmapping'):
    e = next(e for e in data['entries'] if e['key'] == key)
    probes[key] = checker.metadata_mismatches(e['bib'], cache[e['bib']['doi'].lower()])
checker.crossref_metadata = lambda doi: None
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    probes['all_98_metadata_unavailable_exit_status'] = checker.check_metadata(args.repo / 'docs/references.bib')
print('CONTROLLED GAP PROBES:', json.dumps(probes, indent=2))
