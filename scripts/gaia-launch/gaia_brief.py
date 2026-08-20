#!/usr/bin/env python3
"""What has already been tried on this issue, assembled from GitHub and our own ledger.

The queue used to hand the orchestrator three lines: resolve #N, follow the ground rules,
make the minimal change. It knew nothing about what previous batches had concluded, what
PRs had already touched the same ground, or that it had itself failed this issue twice
before. Every invocation re-derived context from scratch -- the single largest avoidable
token cost in the pipeline, and a standing risk of redoing settled work.

Codex prompts solve this by hand ("do not repeat calculations accepted in PRs #152-162").
Hand-maintained lists rot. This generates the equivalent from two sources that are already
maintained: the GitHub graph, and the provenance ledger / measurement corpus the queue
writes for every issue it attempts.

Deliberately SHORT. It is prepended to an agent prompt, so it is capped and ordered by
usefulness: what blocks this, what was already decided, what we ourselves already tried.
A brief that has to be summarised before use is not a brief.

Usage:
    python gaia_brief.py 163 --repo owner/name [--max-chars 4000] [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER = REPO_ROOT / "docs" / "provenance" / "ledger.jsonl"
RECORDS = REPO_ROOT / ".gaia-runs" / "records.jsonl"


def gh(args: list[str], default=None):
    """`gh api` with every failure swallowed: a brief is an optimisation, never a gate.
    A rate-limited or offline run must degrade to less context, not to a dead batch."""
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else default
    except Exception:
        return default


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def build(issue: int, repo: str, max_chars: int) -> tuple[str, dict]:
    data: dict = {"issue": issue}
    parts: list[str] = []

    meta = gh(["api", f"repos/{repo}/issues/{issue}",
               "--jq", '{title,state,body,labels:[.labels[].name],milestone:.milestone.title}'], {})
    data["meta"] = meta
    if meta:
        lab = ", ".join(meta.get("labels") or []) or "none"
        parts.append(f"### Issue #{issue} — {meta.get('title','?')}\n"
                     f"labels: {lab} · milestone: {meta.get('milestone') or 'none'}")

    # 1. Cross-references in the body: issues this one depends on or supersedes. Their STATE
    #    is the part that matters -- an open blocker is a reason to stop, not to proceed.
    body = (meta or {}).get("body") or ""
    refs = sorted({int(n) for n in re.findall(r"#(\d{1,5})\b", body)} - {issue})[:8]
    linked = []
    for n in refs:
        m = gh(["api", f"repos/{repo}/issues/{n}", "--jq", '{number,title,state}'])
        if m:
            linked.append(m)
    data["linked"] = linked
    if linked:
        parts.append("### Issues this one references\n" + "\n".join(
            f"- #{m['number']} [{m['state']}] {m['title'][:90]}" for m in linked))

    # 2. PRs that already touched this issue. Merged ones are settled work: the single most
    #    valuable thing to know, because redoing them is pure waste.
    # Quote "#N" rather than searching the bare number: `163` full-text-matches any PR whose
    # body happens to contain that digit string (a line count, a DOI fragment, another
    # issue's number), which drowns the real references in noise.
    prs = gh(["api", "-X", "GET", "search/issues", "-f",
              f'q=repo:{repo} is:pr "#{issue}" in:body', "--jq",
              '[.items[] | {number,title,state,merged:(.pull_request.merged_at != null)}][:8]'], [])
    # Merged first: settled work is the most valuable thing to know and the most expensive
    # thing to redo. Open/closed PRs are context; merged ones are constraints.
    prs = sorted(prs or [], key=lambda p: (not p["merged"], -p["number"]))
    data["prs"] = prs
    if prs:
        parts.append("### Pull requests that already reference this issue\n"
                     "(merged first — these are settled; do not redo them)\n" + "\n".join(
            f"- PR #{p['number']} [{'MERGED' if p['merged'] else p['state']}] {p['title'][:90]}"
            for p in prs))

    # 3. Our own prior attempts. This is the part no hand-written prompt can keep current,
    #    and the part that stops the queue repeating a failure it already paid for.
    mine = [r for r in read_jsonl(RECORDS) if str(r.get("issue")) == str(issue)]
    led = [r for r in read_jsonl(LEDGER) if str(r.get("issue")) == str(issue)]
    data["attempts"] = [{k: r.get(k) for k in
                         ("run_id", "outcome", "cost_usd", "files_touched", "diff_lines")}
                        for r in mine]
    if mine or led:
        lines = []
        for r in mine[-4:]:
            lines.append(f"- {r.get('run_id','?')}: outcome={r.get('outcome','?')} "
                         f"cost=${r.get('cost_usd') or 0:.2f} "
                         f"files={r.get('files_touched','?')} lines={r.get('diff_lines','?')}")
        for r in led[-4:]:
            lines.append(f"- ledger {r.get('ts','?')}: branch={r.get('branch','?')} "
                         f"pr={r.get('pr') or '-'} turns={r.get('turns_total','?')}")
        parts.append("### This queue's own prior attempts on this issue\n" + "\n".join(lines)
                     + "\n\nDo not repeat an attempt that already failed the same way. "
                       "If a previous attempt was accepted, build on it rather than redoing it.")

    text = "\n\n".join(parts).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit("\n", 1)[0] + "\n\n_[brief truncated]_"
    if not text:
        text = f"### Issue #{issue}\nNo prior work found for this issue (GitHub unreachable or a first attempt)."
    return text, data


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("issue", type=int)
    p.add_argument("--repo", default=os.environ.get("REPO_SLUG"), required=False)
    p.add_argument("--max-chars", type=int, default=4000)
    p.add_argument("--json", metavar="OUT")
    a = p.parse_args()
    if not a.repo:
        print("need --repo owner/name (or REPO_SLUG in the environment)", file=sys.stderr)
        return 2
    text, data = build(a.issue, a.repo, a.max_chars)
    if a.json:
        Path(a.json).write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
