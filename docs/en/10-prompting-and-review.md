English | [中文](../zh/10-prompting-and-review.md)

# Prompting and review

How prompts are written for each model family, how prompt writing is delegated to other models,
how per-model quirks are recorded, and who judges which images. The short version: rules are
scoped per family and measured on our own boxes; agents judge facts, the owner judges taste.

> **TL;DR**
> - Prompt rules do not travel between families. Anima, NovelAI, Qwen-Image and Midjourney each
>   have their own syntax, and a rule that helps one is noise or harm in another.
> - Every prompt, in any family, first gets five decisions (moment, sourced light, camera, one
>   style voice, muted colour with one accent), a lint before rendering, and a cropped check of
>   the output against eight AI-look signals.
> - When another model writes prompts, a house rulebook travels with the packet: target-model
>   facts, banned tags, syntax, a strict JSON output schema, and no example prompts.
> - A temperament card per checkpoint records priors and levers so nobody re-derives them.
> - Objective questions are judged by agents. Taste questions go to the owner in one triage
>   batch per round. A cheap-model pre-screen ranks but never crowns; machine gates only reject.
> - Taste is recorded as method: scene cards, a love / yes / no ledger, at least 3 seeds per A/B.

## Per-family prompt rules

### Anima (flow-matching, Qwen text encoder)

1. **No quality or score tags.** Drop the `masterpiece` / `best quality` / `amazing quality` /
   `very aesthetic` / `absurdres` / `highres` family and the `score_9` / `score_8_up` family.
   Why: same-seed A/B on 2026-07-17. `absurdres` alone was a complete no-op (RGB correlation
   0.92 to 0.93); the full quality block only reshuffled composition (correlation 0.72 to 0.76)
   with no gain in detail or prompt obedience. The engine keeps only `safe`. Owner rule since
   2026-08-23.
2. **No `_` in artist, character or series tags.** Write `character name`, not `character_name`.
   Required for those three kinds, preferred elsewhere. Why: owner rule 2026-08-23; other tags
   do not need rework.
3. **Prefix artist styles with `@`.** `@artist name`, not `artist name`. Why: that is how Anima
   triggers an artist style (owner rule 2026-08-23).
4. **No weight syntax.** `(token:1.5)` was a no-op over 3 seeds (correlation 0.90 to 0.98), and
   `(token:0.3)` desaturates colour words or deletes structure words. Use plain intensity words:
   "vivid, deeply saturated" added 0.18 to 0.25 saturation with stable composition (2026-07-17).
5. **English only.** Why: Chinese prompts were ignored (wrong head count, hair colour, scene) and
   two drifted images were caught by the tagger gate (2026-07-16/17). Japanese-script tags
   collapse into manga panels with fake text.
6. **Medium words bite only as a front-loaded, material-specific opening phrase.** A mid-sentence
   modifier does almost nothing. Why: measured 2026-07-17; face and hair stay locked by the anime
   prior either way.
7. **State verbs explicitly and write hair and eye colour every time.** Why: a clear umbrella
   without "holding overhead" was drawn closed; attributes the prompt does not pin drift across seeds.
8. **At cfg 1 the negative prompt is inert.** Distilled fast cards run at cfg 1; negatives only
   work on the quality card (cfg 4 to 4.5). Why: the sampler skips the unconditional pass at cfg 1.

These rules are Anima-only. The Illustrious / NoobAI scaffold keeps its own measured quality
tags.

### NovelAI V5

1. **The artist string is the only style lever.** Use the `artist:` prefix with the exact
   lowercase Danbooru spelling, aliases in brackets kept. The V5 encoder is case-sensitive.
   Why: V5 has no image reference, and style or medium modifier words scored zero love and broke
   faces in one 2026-09 round.
2. **Weight syntax is `<weight>::<tags> ::`.** A bare `::` closes the block. Artist weights sit in
   1.2 to 1.5, never above 2.0. Braces multiply by 1.05 per pair, brackets divide by 1.05.
   Negative weights work on V4.5 and V5 (a negative weight on `hat` removes hats). Why: in a
   45-cell same-seed calibration matrix every single-artist string in the 1.2 to 1.5 band gave a
   distinct style (2026-08-27).
3. **The style block leads the base prompt and never goes into character captions.** Why:
   taken from the V4.5 mixing guide, kept for V5.
4. **Test community rules before adopting them.** "Cut V4.5 artist weights to a half or a third
   on V5" failed here: at 0.35 two loved artists lost their style entirely (2026-09-02).
5. **Use character boxes for every multi-character image, with hair and eye colour per box.**
   Why: a community report (one user, nine samples) put colour bleed at roughly 50 percent when
   characters share the base prompt; not re-measured here.
6. **Do not open with a quality boilerplate.** The site's quality toggle appends at the tail; turn
   it off or bracket `very aesthetic` for style purity. Why: quality tags push a digital look that
   hurts watercolour, pencil and retro styles.
7. **Some scene words invite text.** "neon signs" made the model write on the signs, and neither
   "no text" nor a negative `text` stopped it; "city lights blurred below" was clean (2026-09-17).
8. **Small artists do not work on V5.** Below about 50 to 100 posts the model cannot learn them.

### Qwen-Image 2.1

1. **Natural-language sentences, not Danbooru tags.** Why: Qwen-Image 2.1 has a natural-language
   domain only.
2. **At cfg 1 the negative prompt is a dead input.** "No text in the image" can only be a closing
   positive sentence, and that is a candidate strategy, not a guarantee (2026-09-21).
3. **One sentence per person in a two-person image** ("On the left ... On the right ...").
   Why: in a 54-image test (2026-10-07; two modes, three seeds, nine arms; judged by the agent)
   every head count was right, and the seven one-sentence-each arms (42 images) had zero attribute
   swaps. A single "respectively" sentence swapped eye colours and held objects.
4. **State hair length in every painterly-medium prompt.** Why: oil, pastel and watercolour
   sentences drew a short-haired boy 6 of 6 times; "long wavy" fixed it 6 of 6.
5. **Do not write hands for dynamic poses.** Why: no hand sentence gave 0 flawed images; with one,
   3 were flawed (2026-09-21).
6. **Control framing by what must be visible**, not by framing words. A held object implies waist
   up; shoes and walking imply full body.
7. **Strong two-person interaction fails.** Side-by-side contact worked 6 of 6; hugging from
   behind, carries and spins failed 0 of 24 and collapsed to a frontal embrace (2026-10-07).

Every Qwen rule carries one of four source tags: official, community (hypothesis), project
constraint, or "measured on this line, date". Only the last one is a fact here.

### Midjourney (V8.2, Niji 7)

1. **Full natural sentences: subject, action, setting, medium, light, composition, then
   parameters.** Why: skill order; never compared against the cookbook order, so treat it as soft.
2. **No quality words.** Why: same-seed pairs on 2026-10-14. None of 7 conditions beat the plain
   prompt. Resolution words made people photographic; render-platform words gave 3D faces. Ask for
   quality by naming a concrete medium and technique. `::` weights are effectively dead on V7, V8
   and Niji 7.
3. **Write wanted things positively.** `--no` words are moderated one by one ("no modern
   clothing" reads as "no clothing").
4. **Weirdness at most 100 with characters.** Why: at 250 faces turned cartoon (2026-10-14).
   1,000 to 3,000 is for composition ideas only.
5. **Edit with `--edit <image> --ar <original ratio> --raw`.** Without the original ratio it
   outputs 1:1 and re-lays-out the picture. It is not pixel editing; paste the patch back with a
   mask when the rest must stay untouched.
6. **Niji 7 is literal.** An unspecified background stays empty: write hair, clothes, scene, light
   and method.
7. **Write the age you want to see.** "adult woman" alone came out younger in anime-faced styles;
   "in her thirties, mature face" fixed it (2026-10-15).
8. **Seed floor for A/B: 3.8/255 mean pixel difference on V8.2 reruns, 8.6/255 on Niji 7.**
   Effects smaller than that are noise.

## Removing the AI look (every prompt)

The per-family rules above are syntax. This step sits before them and applies to every family,
because the cause is the same everywhere: a vague request gives the model no decisions, so it
falls back to the mode of its training data. That mode is the AI look: a centred bust looking at
the camera, soft light from nowhere, oversaturated colour, detail spread evenly over the frame.

1. **Make five decisions before writing the prompt.** Fill whatever the request leaves open
   yourself instead of asking, and show the five in one line so the owner can correct them.

   | Decision | Write it as | Does not count |
   |---|---|---|
   | Moment | One thing happening right now, an action half done | standing, smiling, looking at the camera |
   | Light | One physical source (lamp, window, sky, fire) and where it falls on the subject | soft light, nice light, cinematic lighting |
   | Camera | Distance plus angle; the gaze may leave the camera | centred bust plus eye contact; a tiny figure in a wide shot |
   | Style | One voice: an artist string, an `@artist` tag, a style LoRA, or one named medium | more than three artists; medium modifier words standing in for an artist |
   | Colour | A muted base plus exactly one accent, placed on a named object | vibrant, colourful, saturation everywhere |

   Then name the reflex answer, the picture you would draw without thinking. Do not draw it: at
   least two of the five decisions must differ from it. Why: the reflex answer is the
   distribution mode by another name.
2. **Keep attractor tokens out.** Quality tags (`masterpiece`, `best quality`, `absurdres`, `8k`,
   the `score_*` family) and look attractors (`bokeh`, `glowing`, `lens flare`, `sparkles`,
   `cinematic` / `dramatic` / `volumetric lighting`, `hyperrealistic`, `shiny skin`,
   `perfect face`, `vibrant colors`). Add `no text` to the positive and
   `signature, watermark, artist name` to the negative where negatives work. Give detail only to
   the spot the eye lands on first. Words the owner typed stay; mention once that they attract
   the look.
3. **Lint before rendering.** Keep the token lists and the five decisions as data in one rules
   file and check every prompt against it: zero errors before a render, and one written reason
   for each warning you keep. Natural-language families can share one lint line; syntax rules
   for another family do not apply to them. Why: a stock `1girl, solo, ...` template that agents
   copied from a fast-lane runbook failed two error rules (no camera decision, no light source)
   the first time it was linted. A lint that passes says only that nothing looks AI at a
   glance; it says nothing about taste.
4. **Check the output against eight signals, cropped at full size.** Composition (centred,
   frontal, posed?), light (can you tell where it comes from, do the shadows agree?), colour
   (oversaturated, glowing, hazy, or the model's default grade?), surface (plastic skin,
   oversharpened, melting lines?), selection (detail spread evenly, nowhere for the eye to
   rest?), structure (hands, hair ends, accessories, extra ears or limbs?), text (signature,
   watermark, fake letters?), and the moment (with the prompt hidden, what is this picture
   about?).
5. **Fix the cause, re-roll once.** A hit changes the one decision that caused it (another light,
   another camera, a token removed), not more adjectives. Re-roll at most once by default, then
   deliver and say which signals remain. Structural errors go to a repair pass, not a re-roll.
   Why: piling on descriptors moves the prompt further from a decision.

This is the light, per-image version. A full round of concept cards, a taste ledger and
distillation is the heavy version; use it when a direction is being explored, not for one image.

## Delegated prompt writing

Author models write prompts well but know the target model badly. Their training data predates
the release (NovelAI V5 came out on 2026-08-21), so they fall back to old habits: quality-tag
boilerplate, dead brace-stack artist mixes, and features that do not exist on the new version.

1. **A house rulebook travels whole with every prompt-writing packet.** It says the facts in it
   override the author's memory and that gaps must be named, not guessed. Template:
   [`templates/prompt-rulebook.md`](../../templates/prompt-rulebook.md).
2. **The brief carries visual intent and a required-element list only, never an example prompt.**
   Why: an example pulls every author toward its wording (anti-bias rule from the tournament).
3. **Source briefs from already-verified direction cards and quote their slots mechanically.**
   Why: on 2026-07-02 a hand-paraphrased intent dropped a "small figure, negative space" slot and a
   reviewer correctly ranked the wrong winner.
4. **Word bands by difficulty: simple 40 to 80, moderate 60 to 110, hard 80 to 120.** Add about
   20 per extra character on NovelAI.
5. **Output is strict JSON.** Parse with a tolerant decoder that ignores trailing chatter, then
   pass every item through the client's dry run before any render.
6. **Objective compliance is checked by a program**: word count, banned syntax, `@` prefix,
   underscores. It never enters the blind scoring.
7. **Do not hand-edit an author's wording to pass lint.** Return it for rewrite.

### Picking authors: the double-blind tournament

1. Pick 3 briefs of different difficulty, 2 checkpoints and 2 seeds.
2. Each author writes all briefs. The orchestrator alone holds the author-to-letter mapping.
3. Two independent reviewer models see only the brief and the images, never the prompts
   (wording style would reveal the author).
4. Score six dimensions 0 to 2: intent, composition, colour lock, anatomy, aesthetics,
   cleanliness.
5. Accept the round only if reviewer agreement (Pearson) is above 0.6. Then reveal.

The 2026-07-17 run (4 authors x 3 briefs x 2 checkpoints x 2 seeds) reached Pearson 0.69 with a
mean gap of 0.85 points on a 0 to 12 scale. Ranking: Grok 11.46, Codex luna 11.00, Claude Sonnet
10.92 (strongest on emotional single-figure briefs), a DeepSeek model 10.50 (word-count drift,
trailing chatter). Grok has been paused since 2026-10-13, so the default author list is stale;
re-run the tournament before moving a ranking to a new channel or model version.

## Model temperament cards

A temperament card records one checkpoint's priors so each session stops re-deriving them: body,
exposure and fabric priors, best and avoid shot types, LoRA strengths, extra negatives and flags.
The router reads the card: `lookup` prints it, `neg-add` returns negatives that are appended to
the recipe negative (never replacing it), `flags` returns switches such as disabling FreeU.

1. **A quirk enters a card only if it is reproducible, base-attributable and actionable.** At
   least 2 independent seeds on the same base, an A/B against a known-good base with the same
   prompt, seed and LoRA, and a concrete lever. "Feels off" without a lever is an observation.
2. **Workers write candidate files; only the root merges.** The root opens the evidence images,
   confirms the claim visually and stamps the merge date.
3. **Never fix a quirk by changing engine thresholds or sampler constants.** A card adapts routing
   and negatives around a base only.
4. **Newer dated evidence wins over an older card field.** Update the card; do not fork it.

Example from a seeded card (2026-07-01): a 3D-styled Illustrious merge has excellent hands, feet
and faces but a stubborn hip-waist prior that weighted negatives only soften. The card routes it to
upper-body, close-up and hand shots, and sends full-body shots to other bases. Some bases
over-expose under FreeU and carry a `no_freeu` flag.

## The review loop

1. **Judge objective questions yourself.** Prompt obedience, head count, stray text, composition
   against the brief, obvious defects: the agent crops, judges and records. Why: the owner asked
   for it on 2026-10-06 after a round of collages sent to chat.
2. **Taste questions go to the owner in a triage page, one batch per round.** Default every image
   to yes; the owner marks only love and no. Why: on 2026-09-05 one scene was judged 58 times
   image by image, and the interaction cost outweighed the information.
3. **Decisions that need a yes (spend, large downloads, direction forks) go to an inbox, not into
   chat turns.** Why: decisions stalled waiting for chat replies.
4. **Deliver media by link, never by loading it into the conversation.** Reading an image to judge
   it yourself is fine. Why: media in context is expensive and vanishes at compaction.
5. **A cheap-model pre-screen ranks but never crowns.** It reads the contact sheet itself, scores
   four pass/fail axes per tile (anatomy, composition, fit to intent, identity), and returns a
   top-3 shortlist as JSON. The root audits it: every tile once, every top-3 pick passes its axes,
   notes cite observations, nothing deleted. Why: scalar aesthetic predictors rank the bland
   baseline above artistic candidates.
6. **Machine gates only eliminate.** SFW tagger, defect floor, identity distance: each can reject,
   none can promote. Why: on 2026-07-03 structurally melted images passed the QC gate with zero
   flags; on 2026-08-04 a face collapse passed 10 of 10 identity checks and only the owner caught
   it.
7. **When an agent judges, it compares pairs, in both orders.** Accept a pick only if both orders
   agree; write the visible evidence first. Why: a model's accuracy falls about 7x when shown four
   or more images at once.
8. **Do a pixel diff before reading same-seed contact sheets.** Why: on 2026-07-17 a "detail
   variant" was read off thumbnails; the pixels were identical.

## Recording taste (method only)

1. **Write a scene card before rendering.** It is model-independent: first line (what the viewer
   learns), the cut into the subject, the reflex answer struck out, composition, lens, light,
   colour, method, avoid list. It lives next to the image.
2. **Write a quantification report per model.** Before: what was kept, discounted, dropped. After:
   did the first line happen, item checks, and a diagnosis that separates a flat card (taste
   problem) from a model that failed to draw it (translation problem).
3. **Verdicts go into a love / yes / no ledger.** Love is truly loved, yes is acceptable but not
   main-line, no is rejected. A "no" carries one-click reason chips (style, nonsense, face, hands,
   figure, composition, foreign object).
4. **The ledger is the only yardstick for "did it get better".** Report love rate by line, tag and
   reason.
5. **An A/B needs at least 3 seeds.** One sample proves nothing: GPU run-time and image variance
   both swamp it.
6. **Re-audit the taste profile after 50 new verdicts or any overturned veto.**
7. **Seal predictions.** When an agent guesses the owner's pick, commit the guess before the owner
   answers.

## Real cases

- **2026-07-17, Anima quality tags.** A same-seed A/B found zero quality gain: without the tags
  the images were near-pixel twins, and the tags added composition noise. The rule became
  permanent on 2026-08-23.
- **2026-09-01/02, prompt budget.** Turning the prompt budget toward the person (task in hand,
  gaze, one hair detail, two material words, light on the figure) moved a NovelAI round's love
  rate from 0.03 to 0.40 with the same artists. Medium and close shots kept 15 of 16; wide scenes
  kept 1 of 12.
- **2026-07-18, a prior that would not move.** Half-worn gloves: 3 strategies x 24 cells all
  failed. Rule: stop fighting a prior; drop the concept or change tool.

## Tried and dropped

- Quality tags on Anima and Midjourney (measured no gain, 2026-07-17 and 2026-10-14).
- `BREAK` for multi-subject separation on Anima: it did nothing.
- Scalar aesthetic scores to rank artistic candidates: floor filter only.
- Asking the owner to score attributes one by one: no evidence it helps; weights are inferred from
  choices.
- Feeding liked example images into a judging prompt: few-shot scored lowest on personal taste.
- An external model counting fingers and toes: it confirmed "5 toes" on a six-toe image
  (2026-07-16). Digits are counted on 2x crops by the root.

## See also

- [09-providers.md](09-providers.md): routing and budgets
- [07-performance.md](07-performance.md): A/B method and variance
- [03-dispatch.md](03-dispatch.md): packets and external workers
- [`templates/prompt-rulebook.md`](../../templates/prompt-rulebook.md)
