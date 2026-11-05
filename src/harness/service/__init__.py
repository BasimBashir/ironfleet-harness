"""Application services (M3): the TUI's backend extracted as plain functions —
no Textual, no print. The TUI formats and echoes; the CLI or a future API calls
the same functions. split_plan is re-exported here because the dispatch worker
and the tests share one rule."""
from harness.service.sessions import split_plan

__all__ = ["split_plan"]
