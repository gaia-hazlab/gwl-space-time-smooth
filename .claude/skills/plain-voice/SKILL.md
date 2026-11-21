---
name: plain-voice
description: Strip LLM-tell vocabulary, phrase patterns, and structural tics out of any prose written for or by a scientist — papers, grants, proposals, reviews, abstracts, cover letters, reports, README and docs prose, issue and PR bodies, talk scripts, slide text, emails, op-eds, any free-text deliverable. Use whenever Claude is about to generate such prose, and whenever someone asks Claude to edit, review, audit, humanize, or "check for AI sound" in a draft. Trigger on phrases like "write a draft", "edit this", "does this sound AI", "humanize this", "review my draft", "rewrite", or any prose-generation task — even when LLM detection isn't explicitly mentioned. Encodes Kobak et al. (2025, Science Advances) excess vocabulary, Juzek & Ward (2025, COLING) focal words, the Wikipedia "Signs of AI writing" registry, and hyphen-discipline rules. Apply silently — do not narrate the filtering. Never let a wording edit change what a sentence claims. Default to this skill whenever in doubt about whether a draft sounds machine-written.
---

# plain-voice

A filter for the words, phrases, rhythms, and punctuation tics that make prose read as AI-written. Apply it silently: the author gets the cleaned output, not a commentary about LLM tells.

Written for scientific prose — papers, grants, reviews, reports, documentation — where the register problem is compounded by a second one. A paper is judged on its claims, so an edit that improves the rhythm and quietly strengthens a hedge has done more damage than any amount of `delve`. See **What the edit may never touch**.

## Why this exists

A scientist's voice is the thing that makes a reader trust the argument before they have checked it: specific, claim-direct, willing to say what was actually done. Every word on the list below dilutes that. Kobak et al. analyzed 15M PubMed abstracts and found that 66% of 2024 excess style words were verbs and 14% adjectives, almost all stylistic rather than content-bearing. These words are not wrong English; they are a register that signals "this was processed by a language model." Even in human-edited text they flatten the writer toward a global average. A paper should sound like the person who did the work, not like the average of every PubMed abstract since 2023.

In a field where reviewers now scan for AI-written text, the register also costs credibility that the science has not earned back. That is a practical reason on top of the aesthetic one.

## The core move

When generating any prose deliverable, scan the output mentally before producing it. For each candidate word from the Tier-1 list below, ask: **is this word doing structural work in the sentence, or is it ornament?** If ornament, cut it or replace with the plain English equivalent. If structural, leave it — `crucial` is sometimes the right word for a critical-path dependency, `pivotal` is sometimes the right word for a hinge moment. The skill is not a global find-and-replace; it is a register correction.

When auditing an existing draft, produce the corrected draft directly. Mark changes inline only if a diff-style review was asked for. Default: produce the rewrite, and at the end give a short count of what was caught.

## Tier 1 — Strong tells (always flag)

These are the words that appeared with >300% increase in PubMed 2020→2024 (Juzek & Ward 2025), the highest-confidence markers from Kobak et al. (2025), the post-2024 era list from the Wikipedia "Signs of AI writing" registry, and a small number of entries the published corpora do not flag but that read as machine-written in scientific prose. If one of these appears in a draft, default to replacing it.

**Verbs (and their inflections):** delve, delves, delving, delved, showcase, showcases, showcasing, showcased, underscore, underscores, underscoring, underscored, emphasize, emphasizes, emphasizing, leverage, leverages, leveraging, harness, harnesses, harnessing, garner, garnered, garnering, bolster, bolsters, bolstered, bolstering, foster, fosters, fostering, elucidate, elucidates, elucidating, surpass, surpasses, surpassing, surpassed, navigate (figurative), navigates, navigating, embark, embarks, embarking, unveil, unveils, unveiling, unveiled, shed (light on), unpack, dive (into), comprehend, comprehends, comprehending, encompass, encompasses, encompassing, exemplify, exemplifies, illuminate, illuminates, accentuate, accentuates, demonstrate, demonstrates (when it could just be "show")

**Adjectives:** intricate, meticulous, pivotal, crucial, vital, essential, paramount, profound, compelling, groundbreaking, transformative, revolutionary, unparalleled, unprecedented (when not literally true), comprehensive, exceptional, nuanced, multifaceted, robust, vibrant, dynamic, holistic, seamless, formidable, remarkable, noteworthy, notable, invaluable, key (as filler), commendable, dependable, distinctive, foundational, impactful, innovative, quintessential, breathtaking

**Nouns:** realm, landscape, tapestry, testament, paradigm, paradigm shift, paradigm-shift, mosaic, symphony, journey, lens, era, plethora, myriad, kaleidoscope, treasure trove, epitome, intricacies, advancements, insights, complexities, nuances, interplay, exploration, endeavor, endeavors, framework (as filler), avenue, avenues, cadence (when used as ornament for "rhythm" or "pace")

**Adverbs:** meticulously, intricately, seamlessly, swiftly, notably, particularly, profoundly, exceptionally, remarkably, fundamentally

For the full 434-word style list from Kobak et al. (2025), see `references/kobak-full-list.md`. For the Tier-2 weak-tell list (words humans use that LLMs overuse), see `references/strong-tells.md`. For a programmatic grep list, see `assets/tell-words.txt`.

## Tier 2 — Phrase patterns (always cut or rewrite)

Single-word filters are necessary but not sufficient. The phrase-level constructions below are stronger AI tells than any single word, because they reproduce a rhetorical *shape* rather than just vocabulary.

**Negative parallelism (the strongest current marker):**
- "It's not X, it's Y" / "It's not just X, but Y" / "More than just X, it's Y" → just state Y directly.

**Hedge preambles:**
- "It's important to note that..." → cut.
- "It's worth noting that..." → cut.
- "It's crucial to consider..." → cut.
- "It is widely believed that..." → cut or attribute.
- "Generally speaking..." → cut.
- "While this may vary..." → cut.

**Generic openers (especially as first sentence):**
- "In today's [adjective] landscape..."
- "In an increasingly [adjective] world..."
- "In the digital age..."
- "In the realm of..."
- "In an era where..."
- "As we navigate the complexities of..."

**Wrap-up sentences (the "testament" closer):**
- "X stands as a testament to..."
- "X represents a paradigm shift in..."
- "Ultimately, X underscores the importance of..."
- "X is more than just Y; it is Z."
- "Moving forward, ..." / "In conclusion, ..."
- The "complimentary summary" — any sentence that ends a paragraph by praising or summarizing what was just said is suspect.

**Metaphor clichés:**
- "the rich tapestry of..."
- "a treasure trove of..."
- "through the lens of..." (often) — sometimes the right metaphor, but flag for review.
- "at the heart of..."
- "the cornerstone of..."
- "navigate the complexities/uncertainty/landscape of..."
- "shed light on..."
- "speaks volumes" / "speaks to" (figurative)
- "the intersection of..." (when not literally about intersection)

**Tricolon (rule of three):**
- "X, Y, and Z" lists that are perfectly balanced in length and grammatical form. Humans use tricolons too — the tell is when they appear with mathematically even cadence as the climax of every other paragraph. When you find a tricolon, ask: does it earn its rhythm, or is it filler? If filler, prune to one or two items, or replace with an asymmetric structure.

## Tier 3 — Structural and cadence tics

This is the register problem people mean when they say a draft has an "AI cadence". Reinhart et al. (2025, *PNAS*) showed LLM prose has more nominalizations, fewer human subjects, and fewer epistemic stance markers than human writing. Beyond word choice, the *rhythm* gives it away.

**One-sentence dramatic paragraphs.** "Six months ago, this was impossible. Now it isn't." This rhythm — clipped, declarative, theatrical — comes from training on speech transcripts (podcasts, TED talks, marketing copy). It belongs in spoken word, not on the page of a paper or a grant. Default to paragraphs of 3-5 sentences. Use one-sentence paragraphs sparingly and only when the sentence carries real weight.

**Mathematically even sentence lengths.** Humans write in bursts and trails. Sentences run 6 words, 24 words, 11 words, 38 words — the variation is the voice. LLMs default to 18-24 words and stay there. When generating prose, vary sentence length deliberately. If three sentences in a row are within ±3 words of each other, break the pattern.

**Em-dash overuse.** One em-dash per paragraph is plenty. Two is suspect. Three is a tell. Em-dashes are not commas — use them for genuine interruption or emphatic aside, not as a rhythmic filler. When in doubt, prefer comma, colon, or period.

**Excessive markdown structure.** Bullet lists for everything, bold mid-sentence for emphasis, headers every two paragraphs. Prefer prose. Use bullets only when the items are genuinely parallel and discrete (an actual checklist, a list of parameters), use bold sparingly, and use headers only for documents with real sections. Journals and funders want continuous argument; a Methods section broken into fourteen bolded fragments reads as a form someone filled in.

**The "balanced perspective" tic.** "On one hand... on the other hand..." applied to every question, including ones with a clear answer. A scientist who has done the work has a position and should state it. In a piece that exists to argue for something — a proposal's significance section, a perspective, a review's recommendation — reflexive balancing reads as having no result. Note the difference between *balance* (a rhetorical tic, cut it) and *uncertainty* (a property of the evidence, keep it exactly as the evidence warrants).

**Wrap-up paragraphs that summarize and praise.** LLMs love to end any piece with a paragraph that recaps what was just said and gestures at its importance. Most pieces don't need this. End on the strongest concrete point, not a meta-summary.

## Hyphen discipline

LLMs over-hyphenate compound modifiers and apply hyphens where current style guides drop them. The rules:

**Keep the hyphen when:** the compound is a modifier directly before a noun.
- "data-driven approach" ✓
- "real-world data" ✓
- "high-resolution image" ✓
- "long-term project" ✓
- "well-known scientist" ✓
- "state-of-the-art method" ✓ (always — multi-word compound)

**Drop the hyphen when:** the compound is in predicate position (after the noun) and the meaning is unambiguous.
- "the approach is data driven" (some guides keep the hyphen; the house convention drops it)
- "the data are real world" → recast: "the data come from real-world deployments"
- "the image is high resolution" → drop hyphen
- "this is well known" ✓ no hyphen
- "the project is long term" → drop hyphen

**Prefer the closed form** for established compounds — LLMs over-hyphenate these:
- groundbreaking (not ground-breaking)
- longstanding (not long-standing)
- ongoing (not on-going)
- nonlinear (not non-linear)
- multidisciplinary (not multi-disciplinary)
- subfield (not sub-field)
- realtime (not real-time, in technical contexts) — but "real-time monitoring" stays hyphenated as a modifier
- pretrained (not pre-trained)
- finetune, finetuning (not fine-tune in technical contexts; field is split)
- workflow (not work-flow)

**Never hyphenate** adverb-adjective compounds ending in -ly:
- "highly accurate model" (not "highly-accurate model")
- "rapidly evolving field" (not "rapidly-evolving field")
- "newly developed algorithm" (not "newly-developed algorithm")

**The paradigm-shift case specifically.** "Paradigm shift" — when it survives the Tier-1 filter at all (rarely should) — takes no hyphen as a noun: "a paradigm shift in seismology". As a modifier before a noun, it would take one: "a paradigm-shift moment". But default: cut the phrase entirely, since it's a cliché in any form.

## What to keep — the voice on the other side of the filter

The goal is not sterile, stripped-down prose. These are the positive features the edit exists to protect:
- Specific, concrete nouns (not abstractions). "Nisqually liquefaction twin" beats "the geohazard system."
- Active verbs that name what was actually done. "We built X" beats "X was developed."
- Numbers where numbers belong. "15 million abstracts" beats "a vast corpus."
- One claim per sentence; one main idea per paragraph.
- Variable sentence length. Short. Then long, with subordinate clauses that carry the argument forward. Short again.
- Direct opinions where the author holds them. "I don't believe X" beats "Some have questioned X."
- Uncertainty stated as uncertainty. "Consistent with" is not a weaker way of saying "shows"; it is a different claim, and it is often the true one.
- Subordination is welcome. Longer sentences that carry an argument through a dependent clause, punctuated by short emphatic ones, beat a run of flat declaratives. A non-native English rhythm is a voice, not an error to normalise away.

## What the edit may never touch

This is the part that separates a prose filter for scientists from one for marketing copy. Everything below is **content**. It survives the edit unchanged, or the sentence is left alone and flagged.

- **Numbers, units and their precision.** 18.5 m does not become "about 19 metres" because the sentence scanned better. Sample sizes, *n*, confidence intervals, *p*-values, effect sizes, error bars, significant figures: all verbatim.
- **Hedges the evidence requires.** "Suggests", "is consistent with", "we did not observe", "in this dataset", "under these assumptions" are claims about strength of evidence. Never upgrade one to "shows", "confirms", "demonstrates" or "proves" — that is fabrication with better rhythm. Never add a hedge that was not there either; both directions misreport the work.
- **Negative and null results.** The phrasing that makes a result negative is the result. "We found no relationship" is not an awkward way of writing something more positive.
- **Limitations, caveats, exclusions and the description of what was left out.** These are the first casualties of an edit for concision and the last things a reader can afford to lose.
- **Attribution.** Who claimed what, who objected, who is cited. "The geostatistician and the auditor both object, for different reasons" carries two facts that "reviewers raised concerns" destroys.
- **Names of things.** Method names, variable and symbol names, code identifiers, file paths, defined terms, taxonomic and instrument names. `Clopper–Pearson` stays `Clopper–Pearson`. A term defined once is used the same way every time after: consistency beats variety, and elegant variation in a Methods section is a defect.
- **Quoted material.** Never cleaned, never modernised, never trimmed — including quoted reviewer comments and quoted prior work.
- **Disclosure statements**, including AI-assistance disclosure, funding, conflicts, data and code availability.
- **Structure a venue requires.** Some journals mandate a Conclusions section, some funders mandate named headings. The Tier-3 rule against wrap-up paragraphs yields to a required section — write the required one well instead of cutting it.

The rule that covers whatever this list missed: **if a sentence has to stay ugly to stay true, it stays ugly.** Where a cadence fix and a claim collide, the claim wins.

## Audit workflow (an existing draft)

1. Read the draft once for sense — what is it actually claiming, and to whom?
2. Scan for Tier-1 single words. Replace or cut.
3. Scan for Tier-2 phrases. Rewrite the surrounding sentence, not just the phrase.
4. Read aloud (mentally) for Tier-3 cadence. Check sentence-length variation, em-dash count, tricolon density.
5. Check hyphens against the rules above.
6. Check the edit against **What the edit may never touch**. Any change that moved a claim, a hedge, a number or an attribution gets reverted, even where the original sentence was uglier.
7. Produce the rewritten draft. Below it, list the changes by category (e.g. "Removed: 3 × 'delve', 1 'tapestry', 2 hedge preambles. Em-dashes 7 → 2. Broke 4 tricolons. Left: 5 × 'declared' — domain term.").
8. On a draft over 500 words with fewer than five real tells, **say so and change nothing**. "This reads as your voice, ship it" is a correct answer, and a reflex to edit on every pass is how an editor makes writing worse.

A long document is worth a mechanical first pass before the reading pass:

```bash
grep -oniwf assets/tell-words.txt draft.md | sort | uniq -c | sort -rn
```

Treat the output as candidates, never as a verdict. Much of what it returns will be a word doing structural work — a `declared` variable, a `robust` estimator in the statistical sense, `harness` when that is the literal name of the software. Cutting those makes the prose worse and the terminology wrong.

## Generation workflow (new prose)

1. Plan the piece — what is the claim, who is the audience, what should they do with it?
2. Draft naturally without checking the filter first. The filter is for the second pass; running it during composition produces careful, dead sentences.
3. Before producing the output, do a one-pass scan against Tier-1, Tier-2, and Tier-3.
4. Produce the cleaned draft.
5. Do not narrate the filter pass. Nobody needs to hear "I avoided 'delve'."

The exception: where an unusual register was asked for ("make it persuasive", "write the version for the press release"), some Tier-2 structures have a place. Even then, never use the Tier-1 single-word ornaments. The cliché vocabulary is always wrong; the rhetorical shapes sometimes earn their place in deliberately persuasive writing.

## Invoked by another agent, or inside a pipeline

When this skill is loaded by an agent writing a report, a panel summary, an issue body or any other machine-generated deliverable, two things change:

- **Return the prose alone.** Skip step 7 of the audit workflow. The change accounting exists for a person who wants to know what happened to their draft; in a pipeline nobody reads it, and it ends up published under a heading it does not belong to.
- **The honesty rules outrank every voice rule, and there is no author to ask.** A human writer can be asked whether a hedge was deliberate. An agent cannot, so it defaults to leaving the sentence alone. When a cadence fix and a claim collide, the claim wins and the ugly sentence ships.

## Reference files

- `references/strong-tells.md` — Top 150 highest-precision words with replacements column. Read when a plain alternative to a specific LLM word is needed.
- `references/kobak-full-list.md` — All 434 style-marker words from Kobak et al. (2025), organized by part of speech. Read for the comprehensive list, or to answer "is X on the list?"
- `references/phrase-patterns.md` — Extended phrase-pattern library beyond the Tier-2 list above. Read when auditing a long draft.
- `assets/tell-words.txt` — Plain-text grep list (one word per line). Use programmatically via `grep -wif assets/tell-words.txt draft.md` for a fast scan of a long document.

## Provenance

The empirical basis for this skill:

- Kobak, D., González-Márquez, R., Horvát, E.-Á., & Lause, J. (2025). Delving into LLM-assisted writing in biomedical publications through excess vocabulary. *Science Advances*, 11(27), eadt3813. (15M PubMed abstracts; 900 excess words annotated; 379 style markers in 2024.)
- Juzek, T. S., & Ward, Z. B. (2025). Why does ChatGPT "delve" so much? Exploring the sources of lexical overrepresentation in LLMs. *Proceedings of COLING 2025*, 6397-6411. (21 focal words validated against ChatGPT-3.5.)
- Liang, W. et al. (2024). Monitoring AI-modified content at scale: A case study on the impact of ChatGPT on AI conference peer reviews. *arXiv:2403.07183*.
- Reinhart, A. et al. (2025). Do LLMs write like humans? Variation in grammatical and rhetorical styles. *PNAS*. (Grammatical and rhetorical features beyond lexicon.)
- Geng, M., & Trotta, R. (2025). Human-LLM coevolution: Evidence from academic writing. *arXiv:2502.09606*. (Documented that "delve" frequency dropped after public awareness — confirms the list will drift.)
- Wikipedia "Signs of AI writing" registry (WikiProject AI Cleanup) — running era-by-era list, especially valuable for the mid-2024+ vocabulary shift away from "delve" toward "vibrant", "enduring", "fostering", "align with".

The list will drift. Geng & Trotta showed it's already drifting — `delve` is past its peak, while subtler tells like `vibrant`, `bolster`, `align with`, `enduring`, `fostering` are still active. Revisit this skill every 6-12 months against the current Berens lab CSV and the Wikipedia registry.
