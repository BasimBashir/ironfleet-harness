# Harness

Phase 0 foundation package for IronFleet harness-core.

## Installation

```bash
pip install -e ".[dev]"
```

## Development

Tests use pytest with async support configured in `pyproject.toml`. Run tests with `pytest` from the repo root.

Fixtures:
- `harness_home`: Provides isolated `HARNESS_HOME` environment variable
- `fake_transport`: Mock OpenAI-compatible completion for testing
