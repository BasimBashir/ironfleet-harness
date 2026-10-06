# src/harness/eval/substitute.py — A-7 model substitution: the pure core (spec §§2.1, 4, 5).
# No network, no filesystem beyond the rate table: every function here is unit-testable.
from __future__ import annotations
from typing import Literal
from pathlib import Path
import yaml
from pydantic import BaseModel, Field


class ModelUnderTest(BaseModel):
    """One leg of the A/B. Everything the runner and dashboard need to identify, pace and price it."""
    label: str                                   # short name used in tables and sidecars
    role: Literal["incumbent", "candidate"] = "candidate"
    provider: str                                # provider name registered through the probe
    model: str                                   # model id the endpoint serves
    engine: str                                  # ollama | cloud | ... — drives probe provenance
    context_window: int = 0                      # declared; the cloud leg's is published
    output_cap: int                              # max_tokens on every dispatch this leg makes
    rate_key: str                                # key into the RateTable
    min_interval_s: float = 0.0                  # pacing to stay under a per-minute rate limit
    retry_attempts: int = 3


class RateEntry(BaseModel):
    """USD per 1M tokens, with the source of the number attached to it."""
    in_per_m: float
    out_per_m: float
    cached_in_per_m: float = 0.0
    blended: bool = False          # local legs: one amortized rate for input and output alike
    source: str
    as_billed_note: str = ""       # e.g. a promotional free tier — shown, never used for ranking
    # Blended (local) legs only — see Task 2 for the derivation from measured throughput.
    amortization: dict | None = None

    def require_source(self) -> None:
        if not self.source:
            raise ValueError("a rate without a source is an unsourced price — refused")


class RateTable(BaseModel):
    rates: dict[str, RateEntry]

    @classmethod
    def from_yaml(cls, path: Path) -> "RateTable":
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or "rates" not in doc:
            raise ValueError(f"rate table {path}: missing a top-level 'rates' section")
        table = cls(rates={k: RateEntry(**v) for k, v in doc["rates"].items()})
        for rate in table.rates.values():
            rate.require_source()
        return table

    def require(self, key: str) -> RateEntry:
        """A leg referencing an unknown rate must fail before any model is billed a token."""
        if key not in self.rates:
            raise KeyError(f"rate table has no entry for {key!r}")
        return self.rates[key]


def cost_of(tokens_in: int, tokens_out: int, tokens_cache: int, rate: RateEntry) -> dict[str, float]:
    """{'in', 'out', 'total'} in USD. Cached input is billed at its own rate and clamped to what
    was actually sent — an endpoint cannot cache more than it received."""
    M = 1_000_000.0
    if rate.blended:
        # The machine does not distinguish prompt from completion tokens; one rate prices both.
        in_c = tokens_in / M * rate.in_per_m
        out_c = tokens_out / M * rate.out_per_m
        return {"in": in_c, "out": out_c, "total": in_c + out_c}
    cached = max(0, min(tokens_cache, tokens_in))
    billable = tokens_in - cached
    in_c = billable / M * rate.in_per_m + cached / M * rate.cached_in_per_m
    out_c = tokens_out / M * rate.out_per_m
    return {"in": in_c, "out": out_c, "total": in_c + out_c}
