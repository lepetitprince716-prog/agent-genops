# Providers reference

Purpose: pick the backend for an image job and operate it without wasting money or risking an account.
Read when: a job could go to a cloud service, a web app in the browser pane, or a different local box.

## Route

| Job | Backend | Path |
|---|---|---|
| All-ages artistic image | Midjourney V8.2 (Niji 7 for anime) | Browser-pane operator subagent |
| Tag-precise anime, named artist style | NovelAI V5 Full | API client with ledger |
| Typesetting, outfit swap, hard layout | GPT Image | Codex worker in the multiplexer (web app in pane also allowed) |
| Edit, natural-language scene, realistic character | Qwen-Image 2.1 | Sidecar ComfyUI on Box A |
| Fast anime exploration, character LoRA | Anima | Intent router, either box |
| Finished quality image, pose lock | Illustrious / NoobAI | Box A quality line; pose lock on Box B |
| Instruction edit ("change only X") | Flux Kontext, Qwen-Image-Edit-2511 | Box B only |
| Dataset, repeats, stability check | Box B | Local, free |
| Cloud copy of a local recipe, cloud video | Civitai | Quote-first REST client |

- Default to local. Use cloud only to branch between directions, one image per direction.
- Size a cloud round by how many images the verdict needs. A cap is a ceiling, not a target.
- Adult work never goes to these backends. It runs in a separate private lane.

## Local boxes

- Let the router pick: Box A first; Box B when Box A has a non-empty queue, less than 40 percent of VRAM free, or no answer.
- Queue test renders on Box B without asking. Ask before using Box A.
- Run `--probe` first (exit 3 = HOLD, stop). Then rerun the same command with `--run`. Never run the engine command the router prints.
- Never load Qwen-Image into the production instance; use its sidecar.

## Every paid call

1. Ask: can a local box answer this for free? If yes, stop and go local.
2. Search the ledger for the batch id; count files in the output directory.
3. Take the price quote (free on Civitai; Anlas estimate on NovelAI).
4. Check caps. Over a cap: restate parameters and total, ask the owner, wait.
5. Run with the resume flag on.
6. Append one ledger row per saved image.
7. Reconcile: ledger rows = files = spec entries. Report any mismatch as a possible double run.

- Timeout or unconfirmed paid request: mark `outcome_unknown`. Never retry. Ask a human to check the provider side.
- Never put a credential in argv, logs, error text or a reply.
- Never paste a runnable paid command into a reply. If you must, include the resume flag and assume it already ran.

## Civitai

- Caps: 30 Buzz per request, 150 Buzz per local calendar day (this channel's ledger rows). Enforce client-side; fail closed before the network call.
- Inside caps: no per-image confirmation. Over a cap, batch probes, video, training: ask first.
- SFW only (`allowMatureContent=false`).
- Anima checkpoint goes in `diffuserModel`; a `model` field is silently dropped.
- At most 5 LoRAs, ecosystem must match the checkpoint. Sampler is not exposed.
- Use the workflow endpoint, not the "recipe" endpoint (3x the price, drops unknown fields silently).
- Download returned images without an Authorization header; save JPEG blobs as JPEG.
- Do not expect generation metadata from the public image endpoint (empty since 2026-08-25).

## NovelAI

- No model named: V5 Full, `high complexity`, light quality tags and negatives.
- Free tier = 1 image, pixels <= 1,048,576 (any shape), steps <= 28, no base image. img2img and Enhance are paid.
- Quote paid combinations in Anlas before calling. Ledger cap 300 Anlas per day; do not raise it.
- Send a custom User-Agent (the default Python signature gets 403/1010).
- One client, shared queue lock and ledger. No retry on HTTP 429.
- Keep a local manifest; the API keeps no history.
- V5 has no Vibe Transfer or Precise Reference (last checked 2026-09-02). Image-locked identity: use V4.5.
- Web price probe (read-only): read the Generate button text by script; blur the number field after editing (the site commits on blur); never refresh afterwards (the pane blocks the login check and the page falls back to guest prices); delete storage keys you created; never read the session token value.

## Midjourney

- Web app only. Human pace. No scripts, scraping, third-party API, account or payment changes, Turbo.
- All-ages only. Moderation reads each word, `--no` included. Blocked: rephrase, never resubmit the same text.
- End every prompt with `--relax`. Fast only when the owner waits and Relax queues past about 2 minutes, or for a Fast-only feature worth it. Keep >= 5 h of monthly Fast. Report Fast use at wrap-up.
- Verify speed from the submit response. Never open the settings panel.
- Never open a `/jobs/` URL. Stay on the create page; read job ids from page data.
- 403 on submit: blocked; wait 10 minutes. Failure after 200: resubmit once.
- More Cloudflare challenges in one day: slow down.
- Keep V8.2 prompt bodies under about 1,000 characters.

## Browser-pane operator packet

Dispatch one operator at a time, in the background. Haiku 5.5 default; Sonnet 5.5 for editor masks or odd pages.

```
Action: imagine | vary subtle | vary strong | upscale subtle | upscale creative | edit
Speed: relax | fast
Job (only for actions on an existing image): <job reference found in the feed>
Prompts (submit verbatim, in order; max 3):
1. <prompt ending with --relax>
```

Operator rules to include:
- Submit each prompt once, in order, >= 10 s apart. Never rewrite a prompt.
- Resize the pane at the start of the turn (phone layout under about 630 px).
- Per prompt: find input; click + type; separate read-only script check; Return + wait 10 s. Never put a script call inside a batched action.
- Read results every 45-60 s. <= 25 tool calls per packet.
- Login, CAPTCHA, Cloudflare: stop, report. Lost submission: report, do not resend.
- Do not download. Report URLs.
- Report <= 150 words: status per prompt, job URL, confirmed settings, moderation text verbatim.

Uploading a local reference: the root pushes base64 in 6,000-character chunks with a SHA-256 prefix check per chunk; the operator only clicks and runs the given snippet.

## GPT Image

- Dispatch to a Codex worker through the multiplexer. Never call it from the agent sandbox.
- Order it to use the native image tool, no drawing code, and to print an escape token if no image tool exists.
- Send only the delta (scene, pose, view, correction); the worker reads identity from spec files.
- Ask it to print the final prompt before generating.
- Local fixes: edit mode with "change only X, keep everything else".

## Downloads and logins

- Download only with consent for this batch or within a scope the owner gave. Report count, size, location.
- Stop the local receiver after use.
- Fetch originals only for picks; triage on thumbnails.
- Never type credentials. Login pages and bot checks are the owner's.

## Report

Backend used, image count, spend (quoted vs charged), ledger rows added, Fast time used, any `outcome_unknown`, any blocked page.
