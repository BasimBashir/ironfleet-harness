# OpenCode spike mounts (S4 / P0-5)

Source of truth for the two ports mounted on OpenCode 1.18.25 (pinned). The driver
[`scripts/run_spike_opencode.py`](../../../../scripts/run_spike_opencode.py) syncs these
into an ISOLATED workspace (`~/spike-ws/opencode`, its own git repo) and generates the
per-run files. Nothing here touches OpenCode's own repo — plugins/config/agents only.

| file | role |
|---|---|
| `opencode.json` | provider wiring: custom `ollama-local` (npm `@ai-sdk/openai-compatible`) → `http://127.0.0.1:11434/v1`, model `qwen3.8:27b`, `limit.output` 8192 (the parity cap), `share: disabled`, `autoupdate: false` |
| `ironfleet-guard.ts` | guard mount (template). Hooks: `tool.execute.before` (block decision), `tool.execute.after` (annotates tool results), `experimental.text.complete` (annotates model output — **experimental** hook, seam-stability datum). All checks delegate to the REAL guard via `guard_cli.py`; per-case authorities in `<ws>/allowed.json`; decisions appended to `<ws>/guard-log.jsonl`. `__SPIKE_WS__`/`__PYTHON__`/`__GUARD_CLI__` substituted at sync. Fails CLOSED on unreadable authorities and on guard_cli failure |

Generated at sync (not committed): `.opencode/agent/hunter.md` — frontmatter
(`mode: subagent`, `model: ollama-local/qwen3.8:27b`, permissions deny edit/bash/webfetch)
+ body = `PERSONA_PORT["system_prompt"]` **verbatim** from
[`harness.spike.persona_port`](../../persona_port.py).

Live-observed hazards (2026-09-01, recorded in SEAM_COUNT.md):
- provider id `ollama` collides with the builtin cloud provider → must be `ollama-local`;
- a workspace that is not its own git repo gets a sibling repo's instance attached;
- an inherited `PWD` env var (≠ cwd) steers instance resolution the same way.
