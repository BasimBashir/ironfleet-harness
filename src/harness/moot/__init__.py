"""M6 platform: the moot gate's mechanical core (docs/enterprise/09).

Ported from ironfleet-legal/mcp (M6 plugin step): verify / objection / citator /
moot_checks, with objection's run-ledger inputs re-sourced from the platform's
deadlines and evidence dossier registers, and the gate verdict recorded in the
append-only audit chain. compare() and score() are the seeded-flaw bar."""
from harness.moot.gate import (SEVERITIES, compare, moot_check, record_verdict,
                              score)

__all__ = ["SEVERITIES", "compare", "moot_check", "record_verdict", "score"]
