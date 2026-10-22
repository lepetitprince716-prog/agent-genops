# Prompt rules reference

Purpose: write or check a prompt for one model family, and delegate prompt writing to another model.
Read when: you write a prompt, review an author model's output, or build a prompt-writing packet.

Rules are scoped per family. Never carry a rule across families. The one exception is the AI-look step below, which runs first for every family.

## Every prompt: remove the AI look

1. Make five decisions before writing: moment (an action half done), light (one physical source and where it falls), camera (distance plus angle), style (one voice), colour (muted base plus one accent on a named object). Fill gaps yourself; show the five in one line.
2. Name the reflex answer (the picture you would draw without thinking). At least two decisions must differ from it. Then tell the scene in one real-world sentence (who, where, why); if it does not hold up, change it. Hang the accent and the light on things already in the scene, never on an added prop.
3. No quality tags, no look attractors (`bokeh`, `glowing`, `lens flare`, `sparkles`, `cinematic lighting`, `hyperrealistic`, `shiny skin`, `perfect face`, `vibrant colors`). Add `no text`; negative `signature, watermark, artist name` where negatives work. Every noun gets drawn, sometimes several times, and so does the object a verb implies: colour goes on something already present (a yellow scarf, not `one yellow umbrella outside the window`, which drew open umbrellas indoors), and an action is written as which body part touches what (`pressing her palm against the window glass`, not `wiping fog off the window`, which drew a handkerchief and steam).
4. Lint against the rules file before rendering: zero errors, one written reason per kept warning.
5. After rendering, crop at full size and check eight signals plus plausibility: composition, light, colour, surface, selection, structure, text, moment, and whether the scene makes sense in the real world. An umbrella open indoors, a prop from nowhere or an action that does not match its object is a hard fail, on par with a structural error.
6. A hit changes the decision that caused it. Re-roll at most once, then deliver and name what remains. Structural errors go to repair.

Full text and reasons: `docs/en/10-prompting-and-review.md` § "Removing the AI look".

## Anima

- No quality or score tags: drop `masterpiece`, `best quality`, `amazing quality`, `very aesthetic`, `absurdres`, `highres`, `score_9`, `score_8_up` and kin. Engine keeps only `safe`.
- No `_` in artist, character or series tags (`character name`). Other tags: preferred, not required.
- Artist styles get `@` (`@artist name`).
- No weight syntax: no `(x:1.5)`, `((x))`, `{x}`. Use plain intensity or size words.
- English only. No Japanese-script tags.
- Medium words: one front-loaded, material-specific opening phrase. Mid-sentence modifiers do nothing.
- Always write hair and eye colour. Write state verbs ("holding overhead").
- cfg 1 cards (distilled fast lane): negatives are inert; write only positives. Quality card (cfg 4-4.5): short negatives allowed.
- Restate framing at the end of long prompts.

## Illustrious / NoobAI

- Danbooru tags only; keep the line's own measured quality scaffold.
- Style LoRA is the main style lever.
- `official art` can trigger multi-view layouts: add multi-view negatives.
- Lock weak colours by leading with the colour and negating the wrong one.

## NovelAI V5

- Style lever: the artist string. `artist:` prefix, exact lowercase Danbooru spelling, bracketed aliases kept. Case-sensitive encoder.
- Weight syntax: `<weight>::<tags> ::`. Bare `::` closes. Artist weights 1.2-1.5, never > 2.0.
- Braces x1.05 per pair, brackets /1.05 per pair. Negative weights allowed on V4.5/V5.
- Style block first in the base prompt. Never inside character captions.
- Subject-count tags (`1girl`) only in the base prompt. Character boxes use `girl` / `boy`.
- Multi-character: always character boxes, hair and eye colour per box.
- No `@`, no `(tag:weight)`.
- Do not open with quality boilerplate. Default: `high complexity`, light quality tail, short negatives that keep `text`, `watermark`, `signature`.
- Avoid scene words that invite text ("neon signs").
- Do not use style, medium or era modifier words for style; use the artist string.
- Skip artists below about 50-100 posts. Judge artist reach by commercial record, never by post count.
- Test community weight rules with a low arm before adopting.

## Qwen-Image 2.1

- Natural-language sentences. No Danbooru tags.
- cfg 1: negatives are dead. "No text" only as a closing positive sentence (not guaranteed).
- Two people: one sentence per person, positions stated ("On the left ... On the right ..."). Never one "respectively" sentence.
- Painterly media (oil, pastel, watercolour): always state hair length.
- Dynamic poses: do not write hands.
- Framing: name what must be visible (held object, shoes); framing words barely work.
- Do not attempt strong two-person interaction (carries, hugs from behind, spins).
- Tag each new rule with its source: official, community (hypothesis), project constraint, or measured with date.

## Midjourney

- Full sentences: subject, action, setting, medium, light, composition, parameters last.
- No quality words. Ask for quality by naming a concrete medium and technique. `::` weights are dead.
- Write wanted things positively; `--no` words are moderated individually.
- Weirdness <= 100 with characters.
- Edit: `--edit <image> --ar <original ratio> --raw` plus "Change X into Y. Keep everything else unchanged."
- Niji 7: write background, hair, clothes, light and method; unspecified means empty.
- Write the visible age you want ("in her thirties, mature face").
- Body under about 1,000 characters on V8.2.
- Text on images is added in post by a local tool, never generated.

## Delegated prompt writing

1. Pick the author (see table). If the default author is unavailable, use the next row; re-run the tournament before trusting a new channel.
2. Fill `templates/prompt-rulebook.md` for the target model. Send it whole.
3. Write the brief: visual intent plus a required-element list. Quote direction-card slots verbatim. No example prompts, no hinted phrasing.
4. Declare the target model and the word band: simple 40-80, moderate 60-110, hard 80-120 (+20 per extra NovelAI character).
5. Require strict JSON. Parse with a decoder that ignores trailing text.
6. Run program checks: word band, banned syntax, `@`, underscores, quality tags, JSON shape.
7. Run every item through the client dry run before rendering.
8. Lint fails: return to the author for rewrite. Never hand-edit wording to pass.

| Brief type | Author in the 2026-07-17 tournament (outdated) |
|---|---|
| Emotional or narrative single figure | Claude Sonnet (subagent) |
| Composition-sensitive batch | Grok (paused since 2026-10-13) |
| Fallback | Codex |

This selection is outdated: Grok workers are paused and the Codex channel now serves image generation only. Route new prompt-writing lanes through the dispatch rules in `dispatch.md` (default external worker: Cursor Composer 2.5), and re-run the blind tournament before trusting a ranking on a new channel or model version.

Author channel quirks: Codex may hang on a model cache (kill, retry once); close stdin for background Codex; Sonnet may append `Negative:` instead of a JSON field (split it).

## Double-blind tournament (author selection)

1. 3 briefs of mixed difficulty x 2 checkpoints x 2 seeds.
2. Orchestrator alone holds the author-to-letter mapping.
3. Two independent reviewer models see brief + images only, never prompts.
4. Score 0-2 on intent, composition, colour lock, anatomy, aesthetics, cleanliness.
5. Accept only if reviewer Pearson > 0.6. Then reveal.
6. Keep objective compliance out of the blind score.

## Temperament cards

- Before choosing parameters for a base, look up its card. Append its negatives to the recipe negative; never replace.
- Add a quirk only with: >= 2 seeds on the same base, A/B against a known-good base (same prompt, seed, LoRA), a concrete lever.
- Workers write candidate files with evidence paths. Only the root merges, after opening the images.
- Never change engine thresholds or sampler constants to fix a quirk.
- Newer dated evidence replaces an older field.

## Stop conditions

- A prior beats the prompt across several strategies and seeds: stop, drop the concept or change tool.
- Author cannot supply the required elements: rewrite the brief.
- Any rule you are about to apply comes from another family: stop.
