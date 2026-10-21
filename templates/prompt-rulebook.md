# House rulebook template (prompt-writing packets)

Send this block whole with every packet that asks another model to write prompts. Fill the
bracketed fields for one target model and delete the sections that do not apply. Keep it in
English. Do not add example prompts: examples pull every author toward their wording.

Fill-in notes for the dispatcher (delete before sending):
- One rulebook per target model. Never merge two families into one block.
- Put only facts you have checked on your own setup or the vendor's docs. Mark the rest
  "unverified" or leave it out.
- Update this block when a measured result changes a rule; date the change in your notes.

---

## RULEBOOK: [target model name and version]

You are writing prompts for [target model, version, release date]. Your training data may
predate this release. The facts below override anything you believe you know about this model.
Do not fill gaps from memory. If something you need is not covered here, say so in the
`questions` field instead of guessing.

### TARGET MODEL FACTS

- Prompt domain: [Danbooru tags | natural-language sentences | mixed].
- Language: [English only | English and Japanese]. Other languages: [ignored | allowed].
- Text encoder notes: [case-sensitive | token or character limit | none known].
- Guidance: [cfg value]. Negative prompt: [works | inert at this cfg; write positives only].
- Features that do NOT exist on this version: [for example image reference, a given weight
  syntax]. Do not plan around them.
- Features that exist and you may use: [list, with exact spelling].

### BANNED

- Tags: [list the banned families, for example quality and score tags].
- Syntax: [for example `(tag:weight)`, `((tag))`, `{tag}`, brace stacks].
- Content: no text in the image unless the brief asks; nothing outside the brief's content
  rating.
- Never invent artist, character or series names. Never add names beyond the brief.

### SYNTAX

- Tag spelling: [underscores or spaces; lowercase; aliases].
- Artist style: [prefix, for example `@name` or `artist:name`; or "not supported"].
- Emphasis: [exact weight syntax and its safe range | "no weight syntax; use plain intensity
  words"].
- Order: [for example style block first, then subject count, then subject, then scene].
- Multi-subject: [character boxes with positions | one sentence per person | not supported].
- Always state: [for example hair colour, eye colour, hair length, the verb of each action].

### IF THE BRIEF SUPPLIES A BLOCK

- Use any supplied style or artist block verbatim, in the position given above.
- Use any supplied required elements; every one must appear.

### LENGTH

- Word band for this item: [simple 40-80 | moderate 60-110 | hard 80-120]. Add [n] words per
  extra character if the model uses character boxes.
- Stay inside the band. Over or under is a compliance failure.

### OUTPUT

Return one JSON object and nothing else. No prose before or after it. Keys:

```json
{
  "<item id from the brief>": {
    "model": "<target model id>",
    "base": "<base prompt>",
    "characters": [
      { "prompt": "<per-character prompt>", "center": { "x": 0.0, "y": 0.0 } }
    ],
    "negative": "<negative prompt or empty string>",
    "questions": "<anything the rulebook did not cover, or empty string>"
  }
}
```

- `characters`: one element per character; use an empty list if the model has no character
  boxes. Give `center` for every character or for none; never mix.
- `center` values are normalised to [0, 1].
- `negative`: empty string if negatives are inert on this target.
- Self-check before returning: banned tags absent, syntax as above, word band met, every
  required element present, JSON parses.

---

Dispatcher checks after the author returns (not sent to the author):
- [ ] Parsed with a decoder that tolerates trailing text
- [ ] Program checks pass: word band, banned tags and syntax, prefixes, underscores
- [ ] Every item passed the client's dry run
- [ ] Failures returned to the author for rewrite, not hand-edited
- [ ] `questions` read; rulebook updated if the gap was real
