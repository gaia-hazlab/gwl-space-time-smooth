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

This plugin lives inside the private `research/gaia/` folder, which doubles as a
single-plugin **marketplace** (`.claude-plugin/marketplace.json` at its root). From a
Claude Code session:

```
/plugin marketplace add /Users/marinedenolle/GitHub/academic-practice-agents/research/gaia
/plugin install gaia@gaia
```

Then `/gaia:ground-rules` is available and the 13 agents are dispatchable. To update
after editing, `/plugin marketplace update gaia` (or re-add the path).

**Quick dev test (no marketplace):** launch a session with the plugin loaded directly —

```
claude --plugin-dir /Users/marinedenolle/GitHub/academic-practice-agents/research/gaia/plugins/gaia
```

and validate the manifest with `claude plugin validate .` from inside `plugins/gaia/`.

## Source of truth

The canonical agent designs live one level up at `research/gaia/*.md`; the copies in
`agents/` here are the packaged distributable. Edit the parent files, then re-copy into
`agents/` (or re-run the packaging step) before publishing a new plugin version. The
roster rationale, evaluation design, and review board are in the parent folder
(`README.md`, `EVALUATION.md`, `gaia-review.html`).

**Private** — internal Denolle-group material, roster v0.5 under review. Not for public
distribution yet.
