# Gaia MCP servers

Domain tools the agents can't get from the built-ins (Read/Bash/WebSearch). Declared
in [`../.mcp.json`](../.mcp.json) and auto-started when the plugin is enabled.

## Servers

| Server (`.mcp.json` key) | Script | Tools | Keyless? |
|---|---|---|---|
| **`literature`** | `servers/gaia_literature.py` | `search_works`, `work_by_doi`, `cited_by`, `rag_query` | yes (OpenAlex; `rag_query` uses local `gaia-kb` if installed) |
| **`seismo`** | `servers/gaia_seismo.py` | `query_events`, `station_metadata`, `waveform_availability` | yes (USGS + FDSN web services) |

Both are single-file Python servers with PEP-723 inline dependencies, launched with
`uv run --script` — no separate install, `uv` resolves `mcp`+`httpx` on first run.

## Which agent gets which tools (least privilege)

The servers are visible to the whole session, but each subagent's `tools:` allowlist
decides what it can call (granted as a per-server wildcard `mcp__plugin_gaia_<server>__*`):

| Agent | Granted | Why |
|---|---|---|
| **Literature Scout** | `literature` | prior-art surveys with real citation counts |
| **Auditor** | `literature` | ground novelty claims; check "first" claims against prior art |
| **Research Impact** | `literature` | real-world uptake via `cited_by` |
| **Study Designer** | `literature` + `seismo` | prior art + station/instrument planning |
| **Data Engineer** | `seismo` | discover events, station metadata, data availability before a download/QC pass |

The other 8 agents need no external MCP tools (Theoretician, Coder, Debugger, Run
Monitor, Lab Notebook, Provenance Keeper, Courier, Orchestrator) and are left at their
built-in toolsets. Add a grant only when a real need appears.

## Prerequisites

- **`uv`** on PATH (ships with `uvx`; https://docs.astral.sh/uv/). That's all — `uv`
  fetches `mcp` and `httpx` per the scripts' inline metadata.
- Optional: the group's **`gaia-kb`** CLI (from `gaia-literature-kb`) on PATH enables
  `literature.rag_query` against the curated Graph-RAG corpus; absent, it degrades to a
  clear message and the agent uses `search_works` (OpenAlex) instead.

Config via env (optional): `GAIA_OPENALEX_MAILTO` (polite-pool email),
`GAIA_FDSN_BASE` (default `https://service.iris.edu`).

## Verifying

After install, run `/mcp` in the session to see `literature` and `seismo` connected and
list their tools (confirm the exact `mcp__plugin_gaia_*` names match the agent grants).
Test a server directly:

```bash
uv run --script servers/gaia_literature.py   # starts the stdio server; Ctrl-D to exit
```

## Optional external servers

If you want generic web/preprint tools too, add to `.mcp.json` (and grant the relevant
agents `mcp__plugin_gaia_fetch__*` / `mcp__plugin_gaia_arxiv__*`):

```json
"fetch": { "command": "uvx", "args": ["mcp-server-fetch"] },
"arxiv": { "command": "uvx", "args": ["arxiv-mcp-server"] }
```

Left out by default — `literature` (OpenAlex) already covers preprints, and the agents
have built-in `WebFetch`/`WebSearch`.

## A note on the human gate

These tools **read** public services. They don't download bulk waveforms, deposit data,
or mint DOIs — those are consequential actions that stay with the Data Engineer's
pipeline and the Provenance Keeper under the human gate (see `/gaia:ground-rules`).
