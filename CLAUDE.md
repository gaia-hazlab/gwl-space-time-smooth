# Working in this repository

## Prose goes through plain-voice

Every human-facing prose deliverable this repository produces — the review-loop report,
`docs/*.md` and `docs/*.html`, README prose, issue and PR bodies, panel summaries, abstracts,
talk text — is written under the **plain-voice** skill (`.claude/skills/plain-voice/`), or
handed to the **plain-voice** agent (`.claude/agents/plain-voice.md`) before it ships.

Load it before drafting, not after: `Skill(skill="plain-voice")`. It removes the LLM-tell
vocabulary, phrase patterns and cadence tics, and it names the features of a scientist's voice
that must survive the edit: concrete nouns, active verbs, real numbers, one claim per sentence,
variable sentence length, opinions stated as opinions, and uncertainty stated as uncertainty.

Apply it silently. The output is the cleaned prose, not a description of how it was cleaned.

Two limits on it, both of which matter more than the voice rules:

- **It edits how prose reads, never what it claims.** Numbers and their precision, hedges the
  evidence requires, negative results, limitations, decisive tests, attributions and method
  names are content. They survive the edit unchanged, or the sentence stays as it is. Never
  upgrade "is consistent with" to "shows". Where a cadence fix and a claim collide, the claim
  wins and the ugly sentence ships.
- **A clean draft needs no edit.** If a pass finds almost nothing, say so and change nothing.

## Ground rules for the agents

The research agents run under the gaia ground rules (`.claude/gaia/`), and ground rule 5
applies to everything written here: **AI assistance is disclosed, in every record.** That is
not in tension with plain-voice — the disclosure is a fact, and facts are content.
