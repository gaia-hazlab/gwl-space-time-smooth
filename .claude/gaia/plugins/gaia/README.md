# Gaia — Claude Code plugin

The Denolle-group **Gaia** research agents, packaged as a Claude Code plugin so they
can be installed and launched from the Claude CLI. Ships:

- **13 subagents** (`agents/`) — the v0.5 roster: Orchestrator, Auditor, Literature
  Scout, Study Designer, Theoretician, Data Engineer, Scientific Coder, Debugger &
  Tester, Run Monitor, Research Impact, Lab Notebook, Provenance Keeper, Courier.
- **`/gaia:ground-rules`** (`commands/ground-rules.md`) — loads and enforces the Gaia
  operating rules (separation of powers, human gates, model tiering, always-log-AI-use,
  design-review-first). Run it at the start of a research session; pass a task to start
  orchestrating it under the rules.
- **MCP servers** (`mcp/`, `.mcp.json`) — two keyless domain servers that auto-start
  with the plugin: **`literature`** (OpenAlex prior-art / citations + local Graph-RAG)
  and **`seismo`** (USGS events + FDSN station metadata & data availability). Granted
  per-agent under least privilege — see [`mcp/README.md`](mcp/README.md).
  **Prerequisite:** `uv` on PATH (ships with `uvx`).

## Install (local marketplace)

In this repository the plugin lives at `.claude/gaia/`, which doubles as a single-plugin
**marketplace** (`.claude-plugin/marketplace.json` at its root) — this is the path
`scripts/gaia_bootstrap.sh` registers. From a Claude Code session, with the current
working directory at the repo root:

```
/plugin marketplace add ./.claude/gaia
/plugin install gaia@gaia
```

Then `/gaia:ground-rules` is available and the 13 agents are dispatchable. To update
after editing, `/plugin marketplace update gaia` (or re-add the path).

**Quick dev test (no marketplace):** launch a session with the plugin loaded directly —

```
claude --plugin-dir ./.claude/gaia/plugins/gaia
```

and validate the manifest with `claude plugin validate .` from inside `plugins/gaia/`.

## Source of truth

The canonical agent designs live one level up at `.claude/gaia/*.md`; the copies in
`agents/` here are the packaged distributable. Edit the parent files, then re-copy into
`agents/` (or re-run the packaging step) before publishing a new plugin version. The
roster rationale, evaluation design, and review board are in the parent folder
(`README.md`, `EVALUATION.md`, `gaia-review.html`).

Roster v0.5, Denolle-group internal material.
