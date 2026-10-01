# src/harness/gate.py
from __future__ import annotations
import time
from typing import Awaitable, Callable
from pydantic import BaseModel
from harness.policy import RoutingTable, MatterPolicy, Classification
from harness.providers.config import ProviderConfig, ProviderRegistry
from harness.providers.provenance import ProvenanceReport, revision_verified
from harness.trace import TraceStore, DispatchRecord

Transport = Callable[[ProviderConfig, dict], Awaitable[dict]]

class LLMRequest(BaseModel):
    matter_ref: str
    task_class: str
    messages: list[dict]
    model: str | None = None
    classification: Classification = "LOCAL_PREFERRED"
    # Generous default cap: reasoning models burn thinking tokens against max_tokens, and local
    # servers (Ollama) apply their own small num_predict default when the field is omitted.
    # Providers enforce their own output limits; a strict API that rejects the value returns a
    # traced error rather than silent truncation. Override per request when needed.
    max_tokens: int = 128_000

class LLMResponse(BaseModel):
    content: str
    provider: str
    model: str
    usage: dict[str, int]
    provenance: ProvenanceReport

class EmbeddingRequest(BaseModel):
    matter_ref: str
    texts: list[str]
    model: str | None = None
    # The payload IS privileged text, so embeddings default to the strictest tier —
    # the inverse of LLMRequest's LOCAL_PREFERRED (spec §3).
    classification: Classification = "LOCAL_ONLY"
    max_texts: int = 64      # batch ceiling; over-long batches are REFUSED, never truncated

class EmbeddingResponse(BaseModel):
    vectors: list[list[float]]
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
                 trace: TraceStore, transport: Transport | None = None,
                 embedding_transport: Transport | None = None) -> None:
        self.registry, self.routing, self.trace = registry, routing, trace
        self._transport = transport or self._default_transport
        self._embedding_transport = embedding_transport or self._default_embedding_transport

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

    async def _default_embedding_transport(self, provider: ProviderConfig, payload: dict) -> dict:
        from harness.keychain import get_key
        from harness.providers.http_fetch import openai_fetch
        key = get_key(provider.name) or ""
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        result = await openai_fetch(f"{provider.base_url.rstrip('/')}/embeddings", headers, payload)
        if result is None:
            raise RuntimeError(f"provider {provider.name} embeddings call failed")
        return result

    def _provenance_of(self, provider: ProviderConfig, result: dict) -> ProvenanceReport:
        meta = result.get("_server_meta") or {}
        return ProvenanceReport(
            engine=meta.get("engine") or provider.engine or "",
            weights_revision=meta.get("weights_revision")
                or provider.declared_provenance.get("weights_revision", ""),
            # S7d: dispatch-time evidence wins over the probe's registration-time finding,
            # which wins over nothing. Real endpoints send no _server_meta, so the live
            # value is the probe's; either way the trace records what actually held.
            backend=meta.get("backend") or provider.discovered_backend or "",
            # S6-2: probe semantics at dispatch time — a server-reported revision only
            # verifies when it MATCHES the declared (pinned) one, not merely exists.
            verified=revision_verified(meta.get("weights_revision", ""),
                                       provider.declared_provenance.get("weights_revision", "")),
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
            if cfg.max_output_tokens is not None:          # S6-4: clamp, never raise
                payload["max_tokens"] = min(payload["max_tokens"], cfg.max_output_tokens)
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
                backend=prov.backend,
                verified=1 if prov.verified else 0,
                tokens_in=usage.get("prompt_tokens", 0), tokens_out=usage.get("completion_tokens", 0),
                latency_ms=int((time.monotonic()-t0)*1000)))
            return LLMResponse(content=result["choices"][0]["message"]["content"],
                               provider=cfg.name, model=result.get("model", payload["model"]),
                               usage=usage, provenance=prov)
        raise GateRefusal(f"all candidates failed; last: {last_error}")

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        # A-4 (spec §3): the embedding dispatch path. Routing, admission, provenance, and
        # the trace row are shared with dispatch(); only the endpoint (/embeddings), the
        # payload (input list, no max_tokens), and the response shape differ.
        if not request.texts:
            self.trace.append(DispatchRecord(
                matter_ref=request.matter_ref, task_class="embedding",
                classification=request.classification, provider="-", model="-",
                status="refused", error="empty embedding request"))
            raise GateRefusal("empty embedding request — nothing to embed")
        if len(request.texts) > request.max_texts:
            # Refuse, never truncate: a prefix-embedded batch produces an index that looks
            # complete and is not.
            self.trace.append(DispatchRecord(
                matter_ref=request.matter_ref, task_class="embedding",
                classification=request.classification, provider="-", model="-",
                status="refused",
                error=f"embedding batch {len(request.texts)} exceeds max_texts {request.max_texts}"))
            raise GateRefusal(
                f"embedding batch {len(request.texts)} exceeds max_texts {request.max_texts}")
        policy = MatterPolicy(matter_ref=request.matter_ref, classification=request.classification)
        candidates = self.routing.route("embedding", policy, self.registry)
        if not candidates:
            self.trace.append(DispatchRecord(
                matter_ref=request.matter_ref, task_class="embedding",
                classification=request.classification, provider="-", model="-",
                status="refused", error="no eligible provider"))
            raise GateRefusal("no eligible provider for embedding")
        last_error = ""
        for cfg in candidates:
            model = request.model or cfg.model
            if not model:
                self.trace.append(DispatchRecord(
                    matter_ref=request.matter_ref, task_class="embedding",
                    classification=request.classification, provider=cfg.name, model="-",
                    status="refused", error=f"no model specified for provider {cfg.name}"))
                raise GateRefusal(f"no model specified for provider {cfg.name}")
            payload = {"model": model, "input": request.texts}
            t0 = time.monotonic()
            try:
                result = await self._embedding_transport(cfg, payload)
            except Exception as ex:                       # noqa: BLE001 — trace, then next candidate
                last_error = str(ex)
                self.trace.append(DispatchRecord(
                    matter_ref=request.matter_ref, task_class="embedding",
                    classification=request.classification, provider=cfg.name, model=payload["model"],
                    status="error", error=last_error, latency_ms=int((time.monotonic()-t0)*1000)))
                continue
            data = result.get("data") or []
            bad = None
            if len(data) != len(request.texts):
                bad = (f"embedding endpoint returned {len(data)} vectors "
                       f"for {len(request.texts)} inputs")
            else:
                for i, d in enumerate(data):
                    if d.get("index", i) != i:
                        bad = (f"embedding response misaligned at position {i}: "
                               f"index={d.get('index')!r}, expected {i}")
                        break
            if bad is not None:
                # A short or misordered response corrupts the index while appearing to
                # succeed — each vector's position ties it to its input text, so fail to
                # the next candidate rather than embedding garbage.
                last_error = bad
                self.trace.append(DispatchRecord(
                    matter_ref=request.matter_ref, task_class="embedding",
                    classification=request.classification, provider=cfg.name, model=payload["model"],
                    status="error", error=last_error, latency_ms=int((time.monotonic()-t0)*1000)))
                continue
            prov = self._provenance_of(cfg, result)
            usage = result.get("usage", {})
            self.trace.append(DispatchRecord(
                matter_ref=request.matter_ref, task_class="embedding",
                classification=request.classification, provider=cfg.name,
                model=result.get("model", payload["model"]),
                weights_revision=prov.weights_revision, engine=prov.engine,
                backend=prov.backend,
                verified=1 if prov.verified else 0,
                tokens_in=usage.get("prompt_tokens", 0), tokens_out=0,   # no completion tokens
                latency_ms=int((time.monotonic()-t0)*1000)))
            return EmbeddingResponse(
                vectors=[d["embedding"] for d in data],
                provider=cfg.name, model=result.get("model", payload["model"]),
                usage=usage, provenance=prov)
        raise GateRefusal(f"all embedding candidates failed; last: {last_error}")
