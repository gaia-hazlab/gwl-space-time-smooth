"""Tally coverage.json verdicts per axis. Classes: covered (verdict is exactly 'covered'), no owner
(verdict starts with 'no ' or says 'no acceptance'), owned-with-defect (everything else: blocked,
mis-sequenced, under-specified, untestable)."""
import collections, json, pathlib
rows = json.loads((pathlib.Path(__file__).resolve().parents[1] / "coverage.json").read_text())
def cls(v):
    v = v.lower()
    if v.startswith("no ") or "no acceptance" in v:
        return "no owner"
    return "covered" if v.strip() == "covered" else "owned, blocked or defective"
c = collections.Counter((r["axis"], cls(r["verdict"])) for r in rows)
K = ("covered", "owned, blocked or defective", "no owner")
print("| Axis | Requirements | " + " | ".join(K) + " |\n|---|---|---|---|---|")
for a in dict.fromkeys(r["axis"] for r in rows):
    print(f"| {a} | {sum(c[(a, k)] for k in K)} | " + " | ".join(str(c[(a, k)]) for k in K) + " |")
print(f"| all | {len(rows)} | " + " | ".join(str(sum(c[(a, k)] for a in {r['axis'] for r in rows})) for k in K) + " |")
