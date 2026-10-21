English | [中文](../zh/09-providers.md)

# Providers: local boxes, NovelAI, Midjourney, Civitai, GPT Image

Which backend gets which job, what each one costs, and the operating rules that keep paid
accounts safe. Local render boxes, two web apps driven through a browser pane, one paid cloud API
and one image model reached through a coding agent all sit behind the same root session.

> **TL;DR**
> - Route by the job, not by habit: Midjourney for all-ages artistic work, NovelAI V5 for
>   tag-precise anime, GPT Image for typesetting and hard control, the local boxes for everything
>   repeatable, Civitai only under a standing budget.
> - A free local box beats paid cloud for datasets, repeats and stability checks. Cloud is for
>   branching between directions, one image per direction.
> - Every paid call is quoted first, booked in a ledger, resumable, and fails closed.
> - Web apps are driven by a small subagent with exact prompts: submit once, report, never touch
>   the account. Logins stay the owner's. Downloads need consent.
> - Adult work, where it exists, runs in a separate private lane and is not covered here.

## Routing table

| Job | Backend | Reached through | Why this one |
|---|---|---|---|
| All-ages artistic image, no template look | Midjourney (V8.2 default, Niji 7 for anime) | Web app in the browser pane, operated by a subagent | Highest style ceiling; the account is the risk, so pacing rules apply |
| Tag-precise anime, named artist style | NovelAI V5 Full | API client with a ledger; web app for price probes | On V5 the artist string is the only style lever; free tier covers screening |
| Typesetting, outfit swaps, hard layout control | GPT Image | Codex's native image tool, dispatched through the terminal multiplexer; the web app in the pane is also allowed | Follows precise instructions; beat Flux Kontext on complex outfit swaps (2026-06-24) |
| Editing, natural-language scenes, realistic characters | Qwen-Image 2.1 | Local, a sidecar ComfyUI instance on Box A | Natural sentences, strong edit mode, 1024x1024 in about 4 s (0.37.0 sidecar) |
| Fast anime exploration, character LoRAs | Anima | Local, both boxes, through the intent router | 5 to 6 s warm on Box B in the fast lane (2026-10-06, before the 0.42.1 upgrade) |
| Finished quality images, pose lock, upscale and detailer | Illustrious / NoobAI | Local, Box A quality line; pose lock on one merge on Box B | Full detailer stack; style LoRA is the lever |
| Instruction edits (try-on, "change only X") | Flux Kontext, Qwen-Image-Edit-2511 | Local, Box B only | Specialist CLIs, not the generic planner |
| Datasets, repeats, stability checks | Box B | Local | Free; it sleeps when idle and wakes for work |
| Cloud fallback for a known local recipe, cloud video | Civitai | REST API through a quote-first client | Paid in Buzz; budget enforced on our side only |

## Rules for every provider

1. **Plan a cloud round by how many images the verdict needs, never by the budget ceiling.**
   Why: local renders are sunk cost and screening rounds saturate fast. On 2026-09-16 a proposal
   suggested a 2,000 Buzz cap for one wave; I cut it to 500. A cap is not a target.
2. **Prefer the free local box over paid cloud for datasets.**
   Why: about 420 Buzz once went to Civitai for a dataset Box B could have rendered for free
   (date not recorded).
3. **Quote, then spend, then book.** Every paid call gets a price before it runs, a ledger row
   after it, and a reconciliation at the end. Why: see the 257 Buzz case below.
4. **A paid request that times out or ends unconfirmed is `outcome_unknown`; never retry it
   automatically.** A human checks the provider side first. Why: a retry after a lost reply can
   charge twice.
5. **Credentials are read only when the request is built, go only into the request header, and
   never appear in argv, logs, error text or database rows.** Why: an older Civitai client put
   its token in argv, where any process list could read it. It was replaced.
6. **New tools that gain a cloud path default to plan, preset or dry run.** Auto-render is
   opt-in. Why: standing rule from the low-volume decision (2026-09-16).
7. **Logins are the owner's.** A login page, Cloudflare check or CAPTCHA stops the agent; the
   owner passes it in the pane. Nobody types credentials for the owner. Why: standing rule.
8. **Downloads to disk need consent, per batch or within a scope the owner gave.** Report count,
   size and location. Why: standing rule. Midjourney images my own project generated are the one
   waived scope (2026-10-19).
9. **Adult work stays out of these backends.** Where it exists it runs in a separate private
   lane with its own gates. Why: Midjourney moderation can ban the account, and the Civitai
   channel is fixed to SFW at the request level.

## Local boxes

1. **Box A first, Box B when Box A is busy.** The router computes which boxes can serve the
   request (base model, LoRA, route), then scans Box A. Busy means a non-empty queue, less than
   40 percent of VRAM free, or no answer. Why: Box A is the owner's gaming PC; a game shows up as VRAM
   use, and agents yield to it.
2. **Test renders go to Box B without asking; Box A asks first.** Why: delegation given on
   2026-09-30, scoped to Box B and test images.
3. **Run through the router, never the engine command it prints.** Use `--probe` (read-only,
   exit code 3 on HOLD), then the same command with `--run`. Why: the printed sub-command skips
   the idle wait, VRAM lease and result recording.
4. **Qwen-Image runs as a sidecar, never inside the production instance.** It has its own model
   root, custom-node whitelist and loopback-only port. Why: isolation; the sidecar venv inherits
   the production venv, so upgrading production in place also changes the sidecar.

The per-line recipes live in the line pages. ComfyUI on both boxes is 0.42.1 as of 2026-10-20.

## NovelAI

1. **Default to V5 Full with `high complexity` when no model is named.** Carry only a light set of
   quality tags and negatives. Why: owner decision 2026-09-17; the V5 quality switch pulls images
   toward sameness.
2. **Screening rounds use the free tier, judged by pixel count.** Free means one image, at most
   1,048,576 pixels in any shape, at most 28 steps, no base image. Why: measured on the live
   Generate button on 2026-09-30: 512x768 and 960x1088 cost 0, 1088x1024 is charged. The older
   "three size presets" rule was void from that day. img2img and Enhance are never free.
3. **Quote paid combinations in Anlas before calling them.** The local ledger caps at 300 Anlas a
   day; do not raise it casually. Why: standing rule.
4. **Send a custom User-Agent.** Why: on 2026-08-25/27 the CDN rejected the default Python
   signature with 403/1010.
5. **Keep a local manifest; the API keeps no history.** Why: without it a render cannot be traced.
6. **One caller, no retry on HTTP 429.** All calls go through one client with a shared queue lock
   and ledger. Why: a second ad hoc caller races the ledger and the rate limit.
7. **V5 has no image reference.** No Vibe Transfer, no Precise Reference as of 2026-09-02 (the V5
   encode call returned HTTP 500 on 2026-08-28, uncharged). A job that needs image-locked
   identity targets V4.5. Later status not re-checked.
8. **To keep a chosen composition, upscale the draft and img2img it.** A free 832x1216 draft,
   LANCZOS to 1280x1856, 28 steps, strength 0.4, noise 0, about 11 s. Why: the same seed at
   another size is a different image (2026-09-23). This step is paid; quote first.

One measured day had 370+ images with zero HTTP 402, so the "190 per day" community
estimate was too conservative.

## Midjourney

1. **Web app only, human pace.** One click per step, no scripts, no scraping, no third-party API,
   no account, plan or payment changes, no Turbo. Why: anti-ban; the account is the asset.
2. **All-ages only. Moderation reads each word, including words inside `--no`.** If blocked,
   rephrase; never resubmit the same text. Why: repeated blocks risk a warning or a ban. One
   prompt containing "bare black trees" came back `softban: true` on 2026-10-15 (cause unproven).
3. **Default to Relax by ending every prompt with `--relax`.** Use Fast only when the owner is
   waiting on this image and Relax queues past about 2 minutes, or for a Fast-only feature worth
   it. Keep at least 5 hours of the monthly Fast allowance untouched and report Fast use at
   wrap-up. Why: on the Standard plan Relax is unlimited and Fast is about 15 hours a month.
4. **Verify speed from the submit response, not the settings panel.** Why: 21 of 21 jobs read
   back as relaxed on 2026-10-15, while subagent clicks on the settings icon were stopped by the
   automatic permission reviewer on 2026-10-14.
5. **Never open a job URL directly.** Stay on the create page and read job ids from page data.
   Why: on 2026-10-13 loading a job page triggered two Cloudflare checks; the second needed the
   owner.
6. **A rising rate of Cloudflare challenges in one day means slow down.** Fewer full page loads,
   longer gaps, fewer packs. Why: the browser's suspicion score climbs.
7. **A 403 on submit is a block, not a server error.** Wait 10 minutes. A failure after a 200 may
   be resubmitted once. Why: on 2026-10-14 a pack burned 51 calls retrying against 403s.
8. **Keep prompt bodies under about 1,000 characters on V8.2.** Why: bodies of 908 and 1,018
   characters passed unchanged; 1,031 and 1,043 were silently rewritten and lost words
   (2026-10-19). Niji 7 kept 1,043.

## Civitai

1. **Free what-if quote before every paid submit.** Why: the price depends on engine, size and
   LoRA count, and the quote costs nothing.
2. **Standing budget: at most 30 Buzz per request and 150 Buzz per local calendar day.** Inside it, no
   per-image confirmation. Over a cap, batch probes and video still ask first. Why: owner decision
   2026-09-30; per-image confirmation was the main reason cloud rendering was slow.
3. **Enforce the budget client-side and fail closed.** Why: Civitai has no server-side spending cap
   for an API key. A breach must stop before the network call.
4. **One ledger row per saved image; daily totals count that channel's rows by local calendar
   day.** Why: the ledger is the only spend record we control.
5. **Check the ledger and output directory before any paid run, run with `--resume` by default,
   and reconcile afterwards: ledger rows = rendered files = spec entries.** Extras mean a double
   run. Why: the 257 Buzz case below.
6. **A paid command pasted into a chat reply may already have been run.** Either do not paste it,
   or paste it with `--resume` and assume it ran. Why: the chat app adds a Run button to code
   blocks.
7. **Know the silent field traps.** The Anima checkpoint goes in `diffuserModel`; a `model` field
   is dropped without error. At most 5 LoRAs per call, ecosystem matching the checkpoint. The
   cloud channel does not expose the sampler (it runs euler/simple). Why: each was found by
   reading back the workflow after a paid run (2026-09).

Prices seen (re-check with a quote): an 832x1216 smoke quoted and charged 15 Buzz in 33.7 s
(2026-09-30); a five-LoRA stack 18 Buzz; SDXL text-to-image 4 Buzz through the workflow
endpoint; video from 133 Buzz per 5 s (ltx2) to 1,500 (wan) in 2026-08.

## GPT Image

1. **Reach it through a Codex worker in the multiplexer, never from inside the agent sandbox.**
   The root decides the change and reviews the image; Codex generates. Why: an earlier method that ran
   Codex directly from the sandbox (written 2026-06-22) was voided. Cost seen: about 30k to 70k Codex tokens and 2 to 4
   minutes per image.
2. **Demand the native image tool and give an escape token.** Why: a Codex worker wrote code
   that drew polygon blobs instead of calling the image tool (recorded by 2026-06-20).
3. **Send the delta, not the identity.** The worker reads the spec files; the packet carries only
   scene, pose, view and corrections. Ask it to print its final prompt before generating. Why:
   identity has one source of truth, and the hair line was the line most often dropped.
4. **For local fixes use edit mode with a "change only X, keep everything else" contract.** Why:
   it drifted less than a re-roll; one edit changed only the shoes.

## Procedure: browser-pane operator packet

The root writes prompts and judges images. A small subagent (Haiku 5.5 by default, Sonnet 5.5
for editor masks or odd pages) only submits and reads results. One operator at a time, because
the pane is shared. Dispatch it in the background.

1. Write the packet: action (imagine, vary, upscale, edit), speed suffix on every prompt, the job
   to act on if any, then at most 3 prompts marked "submit verbatim, in order".
2. The operator resizes the pane at the start of its turn (the viewport resets between turns; under
   about 630 px the site shows a phone layout).
3. Per prompt, four calls: find the input, click and type, a separate read-only script call that
   confirms the text landed, then Return and wait 10 seconds. Script calls never go inside a
   batched action.
4. Read results every 45 to 60 seconds. Whole packet: about 25 tool calls at most.
5. On a login, CAPTCHA or Cloudflare page: stop and report. On a lost submission: report, do not
   resend.
6. Report in under 150 words: status per prompt, job URL, settings confirmed, any moderation text
   verbatim.

## Procedure: paid Civitai render

1. Search the ledger for the batch id and count files in the output directory.
2. Take the free quote. Compare it with 30 per request and with today's ledger total plus the
   quote against 150.
3. Inside both caps: render with `--resume`, append the ledger row. Outside, or a batch probe, or
   video: restate parameters and total, and ask.
4. Reconcile ledger rows, files and spec entries. Report any mismatch as a possible double run.

## Checklist before any paid call

- [ ] Could a local box answer the same question for free?
- [ ] How many images does the verdict need? Is the plan that number?
- [ ] Quote taken, both caps checked, ledger and output directory searched?
- [ ] Resume flag on?
- [ ] No credential in argv, logs or the reply?
- [ ] If a download follows: consent given for this batch?

## Real cases

- **2026-09-05, 257 Buzz double run.** Two paid probe commands were pasted into a reply. The owner
  clicked the Run button on the block and then approved in the inbox, and the agent ran them
  again. 6 Anima and 13 Illustrious images rendered twice. Rule: ledger check first, `--resume`
  by default, reconcile counts, treat pasted commands as already run.
- **Date not recorded, about 420 Buzz on a dataset.** A no-LoRA dataset went to Civitai while
  Box B was idle and free. Rule: datasets go local.
- **2026-10-13, job page.** Loading a Midjourney job URL raised two Cloudflare checks. Rule: stay
  on the create page.
- **Date not recorded, runaway packs.** A Haiku pack of 3 prompts used 49 calls and flipped pages into a
  Cloudflare check; another pack used 51 calls against 403s that looked like server errors. Rule:
  25-call cap, no job pages, read the submit status code.
- **2026-10-19, truncated upload.** A Haiku subagent copied 1,643 of about 20,000 base64 characters
  of a reference image, three times in a row. Rule: the root pushes 6,000-character chunks, each
  checked by a SHA-256 prefix; the subagent only clicks and runs the given snippet.
- **2026-09-30, NovelAI cost estimator.** The old formula priced 1536x1024 at 23 steps at 8 Anlas;
  the site charged 39. Earlier, a ledger "used 638" (2026-09-01) was mostly free images booked as
  paid. Rule: use the site's formula and the pixel rule.
- **2026-08-25, Civitai metadata gone.** The public image endpoint returned empty generation
  metadata for 10 of 10 images, with and without a token. Rule: do not assume the REST API returns
  recipes.

## Tried and dropped

- Per-image confirmation for Civitai: replaced by the standing budget (2026-09-30).
- NovelAI free-tier rule by size presets: replaced by the pixel rule (2026-09-30).
- Judging an artist's reach by Danbooru post count: commercial illustrators sit low there. A
  500-post threshold excluded every wanted candidate (they had 164 to 490 posts). The same
  mistake happened on 2026-08-27 and 2026-09-17.
- Harvesting niche artists (8 to 99 posts) for NovelAI: 49 images, 6 hits, and V5 cannot learn
  them (stopped 2026-09-17).
- The Civitai "recipe" endpoint: 12 Buzz for an image that costs 4 through the workflow endpoint,
  and it silently drops unknown fields.
- The Civitai MCP `submit_workflow` tool: it dropped steps across three transports. Direct REST
  with the same token works.
- Changing Midjourney speed in the settings panel, and its Download button: replaced by the
  `--relax` suffix and a token-protected local receiver.

## See also

- [06-render-discipline.md](06-render-discipline.md): smoke before batch, GPU etiquette
- [08-inventory.md](08-inventory.md): ledgers, archive, quotas
- [10-prompting-and-review.md](10-prompting-and-review.md): prompt rules per family and the
  review loop
- [11-safety-and-privacy.md](11-safety-and-privacy.md): managed egress and secrets
- [03-dispatch.md](03-dispatch.md): subagent tiers and external workers
