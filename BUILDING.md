# BUILDING.md — the Windows exe + installer build chain

Everything needed to produce `dist/IronFleet-Setup.exe`, install it in place,
and prove the result works. Written for a fresh session (human or Claude):
follow top to bottom; nothing else is required. Last full verified run:
2026-11-12 (m1-security-hardening atop 49ba1bc, uncommitted).

## Where things live (this box)

| What | Where |
|---|---|
| Repo | `C:\Users\mianx\OneDrive\Desktop\IronFleet harness\harness-core` (env may report "not a git repository" — git works anyway) |
| venv python | `.venv\Scripts\python.exe` (PyInstaller lives here) |
| Web client | `web/` — `npm run build` (vite) → `web/dist` |
| Inno Setup 6 | `C:\Users\mianx\AppData\Local\Programs\Inno Setup 6\ISCC.exe` |
| Installer script | `scripts/ironfleet-setup.iss` (AppId `7C1F2E4A-9B36-4D58-8A21-54E3F0B6C9D2`) |
| Packer | `scripts/pack_windows_exe.py` |
| Vendor cache | `build/vendor/` (opencode / llamacpp / gguf archives; `--no-download` reuses) |
| Install target | `%LOCALAPPDATA%\Programs\IronFleet` — NEVER `%TEMP%` (the installer rejects Temp-pinned dirs) |
| User data | `%LOCALAPPDATA%\IronFleet\harness` + model-settings.json there; API keys in Windows Credential Manager — all outside `{app}`, survive every reinstall |

## Pins (kept in scripts/pack_windows_exe.py)

- opencode `v1.18.25` standalone (`opencode-windows-x64.zip`)
- llama.cpp `b12317` win-cpu-x64 (`llama-server.exe` + sibling DLLs)
- rerank model `ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF` → `qwen3-reranker-0.6b-q8_0.gguf`

## The chain, in order

1. Tests: `.venv/Scripts/python.exe -m pytest tests/test_corpus_ingest.py tests/test_statute_ingest.py tests/test_ironfleet_app_dash_c.py -q`
   (pytest with file paths; never `-m tests.x` — site-packages `tests` shadows the namespace package)
2. Web client, if `web/src` changed: `cd web && npm run build`
3. Pack: `.venv/Scripts/python.exe scripts/pack_windows_exe.py --no-download`
   (~6 min PyInstaller + staging; drop the flag only for a first-ever build to download the vendor caches)
4. Installer: `"/c/Users/mianx/AppData/Local/Programs/Inno Setup 6/ISCC.exe" scripts/ironfleet-setup.iss`
   → `dist/IronFleet-Setup.exe`
5. Silent reinstall (kill `IronFleet.exe` and `llama-server.exe` first — install files are locked while running):
   `./dist/IronFleet-Setup.exe //VERYSILENT //NORESTART //SUPPRESSMSGBOXES //LOG="C:\Users\mianx\AppData\Local\Temp\ifsetup.log"`
   (git-bash needs the doubled slashes)
6. Verify the install log contains:
   `Directory for uninstall files: C:\Users\mianx\AppData\Local\Programs\IronFleet`
   2026-11-12 trap: Inno overwrites but never deletes, so a rebuilt `web/dist`
   leaves the previous hashed bundle behind in the installed dir. Harmless
   (`index.html` points at the new one) but delete unreferenced
   `web/dist/assets/index-*.js` files so staleness doesn't accumulate.

## What staging MUST carry (the nothing-left-behind contract)

`pack_windows_exe.py stage()` mirrors what the frozen app reads at runtime.
When the code grows a new runtime read, add it to the reader AND to this
whitelist — both sides, or it breaks only in the installed exe:

- `data/` whitelist `DATA_KEEP` (providers.yaml, routing-a1.yaml, module-e,
  opencode-a1, corpus, eval/corpus_tool_trace.sqlite3) staged at BOTH roots:
  `dist/IronFleet/data` and `dist/IronFleet/_internal/data` (depth-2 modules'
  `parents[2]` resolves to `_internal`; depth-3 modules' `parents[3]` to the app root).
- `web/dist` → `dist/IronFleet/web/dist`.
- `src/` mount templates → `dist/IronFleet/src/...` at the app root (what
  `mount.py`'s `ROOT = Path(__file__).parents[3]` resolves to frozen):
  `harness/module_e/ironfleet-guard-s7c.ts`, `harness/module_e/guard_cli.py`,
  `harness/substrate/ironfleet-tools.ts`.
  **2026-11-12 trap: a template read by mount.py but absent here dies with
  FileNotFoundError at execution time (stage intake · ingestor).**
- `bin/` via `stage_bin()`: opencode.exe, llama-server.exe + DLL siblings,
  `models/qwen3-reranker-0.6b-q8_0.gguf`.

## The frozen-exe contract (why child spawns work)

Frozen, `sys.executable` IS `IronFleet.exe`, so every `[sys.executable, ...]`
child must go through `run_dash_c()` (`src/harness/ops/ironfleet_app.py`),
which dispatches three shapes instead of relaunching the app (a relaunch dies
on "both ports 8765 and 8766 are taken"):

| Shape | Consumer | Dispatch |
|---|---|---|
| `exe -c CODE args` | ingest_generic parse child | `exec` the code |
| `exe -m pkg.mod args` | module_e tools shim (`ironfleet-tools.ts` spawnSync) | `runpy.run_module(..., alter_sys=True)` |
| `exe script.py args` | module_e guard (`ironfleet-guard-s7c.ts` → `guard_cli.py`) | `exec` the file with `__file__` set |

Any new spawn shape = extend `run_dash_c` + add a test in
`tests/test_ironfleet_app_dash_c.py`. Related frozen facts: `mount.py PYTHON`
is frozen-aware (`Path(sys.executable)` when `sys.frozen`, else
`.venv/Scripts/python.exe`); `--collect-all sqlite_vec` (vec0.dll is invisible
to import analysis); the HIDDEN imports list (uvicorn loops/protocols, anyio
asyncio backend, `harness.api.__main__`); `--add-data` for module_e vendored data;
`--collect-submodules harness` — **2026-11-12 trap: the guard (`guard_cli.py` →
`guard_port`) and tools shim (`-m harness.module_e.dispatch`) import modules the app
never imports, so without it every opencode tool call fails in the exe (guard-log
`guard_cli failed … ModuleNotFoundError`; stage ends `[NO DELIVERABLE]`) while dev runs work.**
Post-install check: `IronFleet.exe <app>/src/harness/module_e/guard_cli.py in.json out.json`
must exit 0.

## Post-install verification ladder

1. Spot checks in the installed dir: `_internal/sqlite_vec/vec0.dll`,
   `web/dist/index.html`, `bin/opencode.exe`,
   `src/harness/module_e/ironfleet-guard-s7c.ts`.
2. Smoke boot (one-shot pattern `%TEMP%\ifverify.py`): launch the exe, wait for
   `serving on` in its stdout log, POST `/api/v1/auth/login`
   `{username,password}` → top-level `{token}`, GET `/api/v1/matters`
   (Bearer) → paged `{items:[...]}`. The user's own node process holds port
   8765; the app then serves 8766 (or 8767).
3. Execution check (one-shot pattern `%TEMP%\ifexec.py`): POST
   `/api/v1/matters/{mid}/executions` `{task_text}` (202) → poll
   GET `/api/v1/executions/{eid}` until the first task settles; intake must
   pass with no FileNotFoundError. Leave the app running while an execution
   progresses — the live worker lives inside it.

## Runtime deps NOT inside the exe

ollama on 11434 (machine service; spawned windowless if absent, left running
on exit), bundled llama-server on 8778 (rerank; killed on clean exit), bundled
opencode.exe wins PATH. Updates install in place over the stable AppId with
`ignoreversion`; user data stays outside `{app}` (see table above).
