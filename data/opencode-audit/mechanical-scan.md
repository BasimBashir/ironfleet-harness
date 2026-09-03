# OpenCode supply-chain mechanical scan (S7a / A-8)

- trees scanned: t1, t2, t3, spike
- packages scanned: 56
- vendored: 0
- missing licence fields: 20
- lifecycle scripts (CRITICAL until adjudicated): 7
- floating runtime ranges: 2
- native binaries inventoried: 8
## tree t1 — C:\Users\mianx\OneDrive\Desktop\opencode-audit\fresh\node_modules
- packages: 3 · missing licence: 2 · vendored: 0
- lifecycle:
  - opencode-ai · postinstall · opencode-ai/package.json
- floating:
  - none
- native binaries: 3
## tree t2 — C:\Users\mianx\.config\opencode
- packages: 50 · missing licence: 16 · vendored: 0
- lifecycle:
  - msgpackr · prepare · node_modules/msgpackr/package.json
  - msgpackr-extract · install · node_modules/msgpackr-extract/package.json
  - undici · prepare · node_modules/undici/package.json
  - uuid · prepare · node_modules/uuid/package.json
  - which · prepublish · node_modules/which/package.json
- floating:
  - C:\Users\mianx\.config\opencode\package.json · dependencies.@ai-sdk/openai-compatible · ^3.0.41
- native binaries: 2
## tree t3 — C:\Users\mianx\AppData\Roaming\npm\node_modules\opencode-ai
- packages: 3 · missing licence: 2 · vendored: 0
- lifecycle:
  - opencode-ai · postinstall · package.json
- floating:
  - none
- native binaries: 3
## tree spike — src\harness\spike\candidates\opencode
- packages: 0 · missing licence: 0 · vendored: 0
- lifecycle:
  - none
- floating:
  - src\harness\spike\candidates\opencode\opencode.json · provider.ollama-local.npm · (none)
- native binaries: 0
