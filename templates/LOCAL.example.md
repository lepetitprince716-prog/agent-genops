# LOCAL.md for the agent-genops skill

Copy this file to `~/.config/agent-genops/LOCAL.md` and fill it in. The skill reads it before
anything else, and its facts beat the defaults in the skill. It names your machines, paths and
tools, so it stays on your machine and never goes into a repository.

Write `none` where you have nothing. For a role marked `none`, the skill uses the fallback in the
roles table of `SKILL.md`, or asks you. Date what you check; a stale fact gets probed again.

Updated: `<YYYY-MM-DD>`

## Paths

| What | Path |
|---|---|
| agent-genops clone (the skill reads `templates/` from it) | `<path to your clone, or none>` |
| Machine registry (a filled copy of `templates/fleet.example.yaml`) | `<path, or none>` |
| Outputs root | `<path>` |
| Ledgers | `<path>` |

## Roles

The example values fit one machine that runs both the agent and ComfyUI on its default port.
Replace them with your own commands.

| Role | Your command or tool | Notes |
|---|---|---|
| Intent router: print the plan, probe, run | `none` | graphs go to `POST /prompt` |
| Box probe | `GET http://127.0.0.1:8188/queue` | idle when no job is running or pending |
| Free VRAM | `GET http://127.0.0.1:8188/system_stats` | |
| Models and nodes | `GET http://127.0.0.1:8188/object_info` | each loader's inputs list the files it can load |
| Results | `GET http://127.0.0.1:8188/history/<prompt_id>` | |
| Model index: status, refresh, lookup | `none` | |
| Output isolation | `none` | copy each job's outputs into its own folder by prompt ID |
| Ledgers | `<ledgers path>/spend.csv` | one row per paid image |
| Review page | `none` | a contact sheet works |
| Task tracker | `none` | |
| Worker launcher for other vendors' CLIs | `none` | lanes run in the root |
| Network wrappers | `none` | plain ssh and curl |
| MCP server for the render boxes | `none` | |

## Machines

| Name | Roles | GPU and VRAM | How to reach it | The owner also uses it for |
|---|---|---|---|---|
| `<name>` | Controller, render box | `<GPU>, <GB>` | `127.0.0.1:8188` | `<gaming, work, nothing>` |

## Budgets and approvals

- Paid renders, per service: `<cap per run>`, `<cap per day>`.
- GPU work longer than `<minutes>` needs the owner's yes.
- Machines the agent asks about before every use: `<names, or none>`.
