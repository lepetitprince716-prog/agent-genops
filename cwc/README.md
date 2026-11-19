# comfyui-workflow-compiler

`cwc` turns a ComfyUI API graph, written by a coding agent or by hand, into a native
canvas workflow: grouped, laid out by a chosen preset, routed with native link reroutes,
and checked to export the same prompt it was compiled from. Planned next: an in-canvas
guide, and tidying an existing canvas without changing anything but geometry.

Status: pre-alpha. `cwc compile` runs the whole pipeline (normalize, instantiate,
annotate, layout, route, verify) and writes the canvas, the API prompt and a report;
`cwc node`, `cwc learn` and `cwc render` are available too. Tidying an existing canvas,
in-canvas notes and the guide, PNG embedding and extraction, and live checks against a
running frontend are not available as commands yet. Details: `docs/ARCHITECTURE.md`
(modules and layout rules), `docs/m0-findings.md` (what the real frontend does),
`docs/m1-templates.md` (widget templates and their evaluation) and
`docs/m2-frontend-facts.md` (groups, node boxes and links as the frontend stores them).

## For agents

1. `cwc guide` prints the authoring reference: the input format, every `_meta` and `_workflow`
   key with its effect, and an example with an optional module.
2. Write the API prompt and run `cwc compile GRAPH.json -o out`. Errors and warnings go to
   stderr with a hint each; `--json` gives the same list as `finding_list`.
3. Fix and compile again until the summary line says `ok`; `cwc render` draws the canvas.

## Commands

```
cwc node     [TYPE | --search KW] [--nodedefs FILE|URL] [--json]
cwc compile  GRAPH.json -o DIR [--nodedefs FILE|URL] [--preset NAME] [--all-enabled]
             [--allow-unknown] [--json]
cwc presets  [--json]
cwc guide
cwc learn    FILE [FILE ...] -o FILE [--nodedefs FILE|URL] [--json]
cwc render   GRAPH.ui.json -o OUT.svg [--nodedefs FILE|URL] [--json]
```

- `node` shows one node definition or searches the definitions.
- `compile` turns an authoring graph into a canvas and its API prompts.
  `--preset` takes one of `bento`, `swimlanes`, `cockpit-split`, `tower-preview`,
  `stepped`, or `auto`, which chooses by the number of nodes, optional modules and control
  branches.
- `presets` lists the presets, what each looks like, when to pick it, and the rules of `auto`.
- `guide` prints the authoring guide.
- `learn` learns widget templates from canvases paired with their API prompts.
- `render` draws a canvas as an SVG, without a browser.

`compile` writes every error and warning to stderr with its hint, and `--json` lists them
in `finding_list` next to the `findings` counts. A successful run ends with one stderr line:
the preset (and why, under `auto`), the number of groups, optional modules and warnings, and
the `cwc render` command that previews the canvas.

Inputs that used to pass and now do not, or now warn:

- A `_meta` key that starts with `ui_` but is not one of cwc's keys is an error (E7, exit 3)
  that names the closest key. It used to be a warning, and the misspelt key did nothing.
- A key cwc accepts but does not use yet (`ui_locked`, `ui_expose`, `ui_note`,
  `_workflow.title`, `_workflow.locale`, `_workflow.groups.<id>.note`) is named in one info
  finding (E8) per compile, one line on stderr that lists the keys and the nodes that set them,
  and in the report of a successful compile with the keys one by one in `data.keys`. The exit
  code and `ok` do not change.

The authoring checks of `compile` report these codes (the report's `title` field carries the
same text; the other code families check the canvas):

| Code | Meaning |
|---|---|
| E1 | unknown node type |
| E2 | input name not defined for the node type |
| E3 | required input without a declared default is missing |
| E4 | link connects incompatible types |
| E5 | literal value has the wrong type, is out of range, or is not a known option |
| E6 | link points at a missing node or output, or names an ambiguous output |
| E7 | graph structure is invalid (cycle, bad id, bad _workflow, mixed optional group) |
| E8 | authoring key is accepted but has no effect yet |

E7 also covers `_meta` keys cwc does not know: an error for one that starts with `ui_`, a
warning for any other.

`--nodedefs URL` reads `<URL>/api/object_info` from a running ComfyUI server. It follows at most
three redirects, only to `http` or `https`, and never from `https` to `http`. It does not judge
where the server or a redirect points: a server on this machine or the local network is the usual
source, so name only a server you trust.

## Input limits

Inputs are checked once at the edge, and one past a limit below is refused with a message that
names the limit. The limits are far above real workflows (large canvases are a few hundred nodes
and a few megabytes). A JSON file is read up to the file limit, then refused at the document
limit. The values are the constants in `src/cwc/ingest/limits.py`, `src/cwc/ingest/png.py`, `src/cwc/nodedefs/derive.py`,
`src/cwc/nodedefs/registry.py` and `src/cwc/nodedefs/learn.py`.

| Input | Limit | Past it |
|---|---|---|
| An input file (canvas, authoring file, PNG), read | 256 MiB, also for a pipe or a file that grows | I3, exit 3 |
| A JSON document, or the text of one PNG chunk | 64 MiB | I3, exit 3 |
| The compressed text chunks of one PNG, inflated, in all | 64 MiB | I3, exit 3 |
| Nesting of JSON arrays and objects | 64 levels | I3, exit 3 |
| Canvas nodes, or authoring entries | 5000 | I3, exit 3 |
| Canvas links | 20000 | I3, exit 3 |
| A canvas node, link, slot or reroute id (integer or digit string) | 32 digits | I1, exit 3 |
| An authoring key made of digits | 32 digits | E7, exit 3 |
| A canvas coordinate or size (nodes, groups, reroutes) | at most 1e9 in absolute value | I1, exit 3 |
| A node definition source (file, URL response, or gzip once inflated) | 64 MiB, 64 levels deep | D1, exit 4 |
| A URL source: redirects followed, only to http or https, never https to http | 3 | D1, exit 4 |
| An Autogrow `min` or `max` in a node definition | 1000 | D1, exit 4 |
| The slots of one Autogrow group (template inputs times `max`) | 10000 | D1, exit 4 |
| `learn`: widget values times candidate names of one node, aligned | 250000 cells | the node votes on its length only (`too_large`), no error |

An integer larger than a float holds is no longer an internal error either: in a widget it gets
the usual range finding, in a canvas coordinate it is past the limit above.

## Planned

These commands are not in `cwc --help` yet.

```
cwc beautify messy.ui.json [--preset ...] [--regroup] -o out/
cwc check    x.ui.json [--api x.api.json] [--live URL] [--publish]
cwc embed    x.ui.json --image cover.png -o x.workflow.png
cwc extract  image.png -o out/
cwc snapshot --from URL [--via-frontend] -o nodedefs.json
```

The core needs Python 3.10 or newer and nothing outside the standard library.
Playwright is needed only for the real-frontend checks in `tools/oracle/`.

`cwc/` is one folder of a larger repository. Paths on this page and in `docs/` (`src/`,
`tests/`, `tools/`) are relative to this folder, and the commands in them run from here:
`python3 -m unittest discover -s tests` runs the tests.

## Milestones

| Milestone | What it covers | Status |
|---|---|---|
| M0 | Real-frontend oracle; measures the constants the layout depends on (`tools/oracle/`, `docs/m0-findings.md`) | done |
| M1 | Instantiation and equivalence; an API graph becomes a canvas that exports the same prompt (`docs/m1-templates.md`) | done |
| M2 | The five presets, layout and native link routing checks (`docs/ARCHITECTURE.md`, `docs/m2-frontend-facts.md`) | done |
| M3 | Reroute routing second round, in-canvas notes and guide, lossless tidy of an existing canvas, embed and extract | planned |
| M4 | A skill package for coding agents and a showcase of workflows | planned |
| M5 | Optional extensions after the first release | planned |

## Licence

The tool is licensed under the Apache License 2.0 (`LICENSE`).

Files that `cwc` produces for you (`.ui.json`, `.api.json`, `.guide.md`, `.svg`, `.png`
and reports) belong to the author of the workflow and are not covered by this licence.
See `LICENSE-OUTPUTS.md`.

No code or copyrighted data from GPL or AGPL projects is copied into this repository.
The bundled core node snapshot keeps only interoperability facts (names, types, order).
