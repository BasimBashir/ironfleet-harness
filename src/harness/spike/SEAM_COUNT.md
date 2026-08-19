# SEAM COUNT — spike integration-point ledger (template)

> **"Seam"** = one integration point where IronFleet behaviour attaches to the adopted
> harness WITHOUT touching its core: a hook registration, plugin entry, config file, or
> subagent manifest. Each row is a thing Module E (A-2/B-5) must build and maintain.
>
> **How the count reprices Module E:** Module E is priced at 48h assuming a fixed number
> of attachment points. Actual seam count × observed effort-per-seam from the spike
> replaces that estimate: `Module E (repriced) = seams × median-hours-per-seam observed
> in the 2-day run`, with each `core-fork? = yes` row additionally pricing the ongoing
> fork-maintenance burden (tracked in the M0 tie-break, CR-2a). Record rows during the
> run, not after.

## OpenCode

| seam | file/hook touched | core-fork? |
|---|---|---|
| _(guard hook: …)_ | `.opencode/…` / hook name |  |
| _(persona subagent: …)_ | `.opencode/agent/hunter.md` |  |

## OpenHands

| seam | file/hook touched | core-fork? |
|---|---|---|
| _(guard handler: …)_ | event handler name |  |
| _(persona subagent: …)_ | `.openhands/agents/hunter.yaml` |  |

## dsh
_(runs only after the P0-6 pre-check clears)_

| seam | file/hook touched | core-fork? |
|---|---|---|
| _(guard plugin: …)_ | `plugins/ironfleet-…/guard.ts` on tools/post-execute |  |
| _(persona subagent: …)_ | `plugins/…/manifest.json` |  |
