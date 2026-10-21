# Review loop reference

Purpose: decide who judges an image, deliver it for review, collect verdicts and record taste.
Read when: renders are done and need a verdict, a pick, a ranking, or an A/B conclusion.

## Who judges what

| Question | Judge | How |
|---|---|---|
| Prompt obeyed, head count, stray text, framing, obvious defect | Root agent | Crop, judge, record |
| Finger and toe count | Root agent | 2x crops only, never a full frame or grid tile |
| SFW | Deterministic tagger gate | Never a model opinion |
| Identity drift | Identity metric, then the owner | Metric can only reject |
| Which is better, which becomes default, love | Owner | Triage page |
| Spend, large download, direction fork | Owner | Inbox entry |

## Delivery

1. Deliver media by link. Never load images or video into the conversation for the owner. Reading an image to judge it yourself is fine.
2. Register one batch per round. Do not split by count. Do not send collages to chat for the owner to pick from.
3. Register batches from the main checkout so the review service can see them.
4. Taste batches: few candidates, content rotated, nothing the owner already judged.
5. Triage page: every item defaults to yes; the owner marks love and no.
6. Read the result file yourself. Do not ask the owner whether they are done.
7. `pending` non-empty = owner unfinished. Never treat pending as rejected.
8. Read both `love` and `yes` to get every approved item.
9. No pane available (headless, cron): hand clickable local links.

## Machine gates

- Gates only eliminate. No gate promotes, crowns or sets a tier.
- Fail closed: unverifiable check = reject; missing score = fail.
- Never skip the visual pre-screen or human review because a gate dropped nothing.
- Scalar aesthetic scores: floor filter only. Never rank artistic candidates with them.

## Cheap-model pre-screen

Input: contact sheet path, direction intent quoted verbatim from the card (never paraphrased), optional identity spec.

Reviewer must:
1. Read the sheet file itself; set `sheet_read_verified: true`.
2. Per tile, pass/fail on anatomy, composition, intent fit, identity (null if no spec), plus one note citing the decisive observation.
3. Shortlist a top 3 among tiles passing all applicable axes, ranked by intent delivery, not brightness or polish.
4. Fewer than 3 pass: shortlist only passers. None pass: shortlist the least defective and say so.
5. Output one JSON object, no prose. No prompt edits. No SFW judgement.

Root audit: JSON validates; every tile appears once; every top-3 tile passes its axes; notes cite observations, not scores; nothing deleted or moved.

The shortlist is a ranking. The owner crowns.

## Agent-as-judge

- Compare two images at a time. Judge in both orders; accept only if both agree.
- Write visible evidence first, then a binary choice per dimension, then combine.
- Four candidates: six pairwise comparisons; break cycles by win count.
- Never put liked example images in the judging prompt.
- Same-seed comparisons: pixel diff (hash or mean difference) before reading thumbnails.
- When guessing the owner's pick, commit the guess before the owner answers.

## Recording taste

- Scene card next to each image, before rendering: first line, cut, struck-out reflex answer, composition, lens, light, colour, method, avoid list.
- Quantification report per model: kept / discounted / dropped before; first line achieved (yes/partial/no), item checks, diagnosis (flat card vs model failure) after.
- Verdicts: love (truly loved) / yes (acceptable, not main line) / no (rejected). "no" carries reason chips: style, nonsense, face, hands, figure, composition, foreign_object.
- Build the ledger from verdict batches. Report love rate by line, tag, reason. The ledger is the only "did it improve" yardstick.
- A/B: >= 3 seeds per arm, one variable changed. Publish counts out of N seeds; state what changed together.
- Re-audit the taste profile after 50 new verdicts or any overturned veto.
- Do not write the owner's preferences into shared docs. Record method and counts only.

## Stop conditions

- Owner has pending items: wait; do not book the round.
- Pre-screen JSON fails audit: discard its ranking; do not use it.
- Two judges disagree on order: no pick; report both.

## Report

Batch id and URL, counts of love / yes / no / pending, reason-chip counts, any gate rejections with reasons, ledger rebuilt (yes/no).
