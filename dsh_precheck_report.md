# DSH supply-chain pre-check (P0-6)

- packages scanned: 256
- vendored: 9
- missing licence fields: 13
- lifecycle scripts: [('@deepseek-ai/dsh-root', 'postinstall'), ('@deepseek-ai/dsh-subprocess-local', 'postinstall')]
- critical findings: 1

Gate: dsh enters the spike only if critical_findings == 0 and licence questions are resolved.
