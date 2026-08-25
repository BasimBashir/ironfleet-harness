# src/harness/gate.py
from __future__ import annotations
import time
from typing import Awaitable, Callable
from pydantic import BaseModel
from harness.policy import RoutingTable, MatterPolicy, Classification
from harness.providers.config import ProviderConfig, ProviderRegistry
from harness.providers.provenance import ProvenanceReport
from harness.trace import TraceStore, DispatchRecord

Transport = Callable[[ProviderConfig, dict], Awaitable[dict]]

class LLMRequest(BaseModel):
    matter_ref: str
    task_class: str
    messages: list[dict]
    model: str | None = None
    classification: Classification = "LOCAL_PREFERRED"
    max_tokens: int = 1024

class LLMResponse(BaseModel):
    content: str
    provider: str
    model: str
    usage: dict[str, int]
    provenance: ProvenanceReport

class GateRefusal(RuntimeError):
    pass

class EgressGate:
    """The single dispatch point (architecture doc §1). Nothing reaches any provider except
    through this layer; every dispatch is classified, admission-filtered, traced, and its
    provenance recorded honestly (verified=0 when unverifiable). Fail-closed by design."""

    def __init__(self, registry: ProviderRegistry, routing: RoutingTable,
                 trace: TraceStore, transport: Transport | None = None) -> None:
        self.registry, self.routing, self.trace = registry, routing, trace
        self._transport = transport or self._default_transport

    async def _default_transport(self, provider: ProviderConfig, payload: dict) -> dict:
        from harness.keychain import get_key
        from harness.providers.http_fetch import openai_fetch
        key = get_key(provider.name) or ""
        # No key -> NO Authorization header. A "Bearer " value with an empty token is an
        # illegal header (httpx LocalProtocolError) — local servers don't need auth anyway.
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        result = await openai_fetch(f"{provider.base_url.rstrip('/')}/chat/completions", headers, payload)
        if result is None:
            raise RuntimeError(f"provider {provider.name} call failed")
        return result

    def _provenance_of(self, provider: ProviderConfig, result: dict) -> ProvenanceReport:
        meta = result.get("_server_meta") or {}
        return ProvenanceReport(
            engine=meta.get("engine") or provider.engine or "",
            weights_revision=meta.get("weights_revision")
                or provider.declared_provenance.get("weights_revision", ""),
            backend=meta.get("backend", ""),
            verified=bool(meta.get("weights_revision")),
            raw={"source": "response-meta" if meta else "declared-only"},
        )

    async def dispatch(self, request: LLMRequest) -> LLMResponse:
        # classification travels on the request until the matters table exists
        policy = MatterPolicy(matter_ref=request.matter_ref, classification=request.classification)
        # matter classification policy comes from the matters table when it exists; the
        # routing table already encodes the request's task class.
        candidates = self.routing.route(request.task_class, policy, self.registry)
        if not candidates:
            self.trace.append(DispatchRecord(
                matter_ref=request.matter_ref, task_class=request.task_class,
                classification=request.classification, provider="-", model="-",
                status="refused", error="no eligible provider"))
            raise GateRefusal(f"no eligible provider for {request.task_class}")
        last_error = ""
        for cfg in candidates:
            model = request.model or cfg.model
            if not model:
                # A provider may serve many LLMs; the request must say which one — never guess.
                self.trace.append(DispatchRecord(
                    matter_ref=request.matter_ref, task_class=request.task_class,
                    classification=request.classification, provider=cfg.name, model="-",
                    status="refused", error=f"no model specified for provider {cfg.name}"))
                raise GateRefusal(f"no model specified for provider {cfg.name}")
            payload = {"model": model, "messages": request.messages, "max_tokens": request.max_tokens}
            t0 = time.monotonic()
            try:
                result = await self._transport(cfg, payload)
            except Exception as ex:                       # noqa: BLE001 — trace, then next candidate
                last_error = str(ex)
                self.trace.append(DispatchRecord(
                    matter_ref=request.matter_ref, task_class=request.task_class,
                    classification=request.classification, provider=cfg.name, model=payload["model"],
                    status="error", error=last_error, latency_ms=int((time.monotonic()-t0)*1000)))
                continue
            prov = self._provenance_of(cfg, result)
            usage = result.get("usage", {})
            self.trace.append(DispatchRecord(
                matter_ref=request.matter_ref, task_class=request.task_class,
                classification=request.classification, provider=cfg.name,
                model=result.get("model", payload["model"]),
                weights_revision=prov.weights_revision, engine=prov.engine,
                verified=1 if prov.verified else 0,
                tokens_in=usage.get("prompt_tokens", 0), tokens_out=usage.get("completion_tokens", 0),
                latency_ms=int((time.monotonic()-t0)*1000)))
            return LLMResponse(content=result["choices"][0]["message"]["content"],
                               provider=cfg.name, model=result.get("model", payload["model"]),
                               usage=usage, provenance=prov)
        raise GateRefusal(f"all candidates failed; last: {last_error}")
