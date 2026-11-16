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
    # S7j-W (spec 13 §1.7): the client's tool schemas, carried verbatim. Until 2026-10-12
    # this boundary DROPPED them — the provider never saw a tool to call, so the ported
    # tools were unreachable through the gate for ANY model, however willing.
    tools: list[dict] = []
    tool_choice: str | None = None

class LLMResponse(BaseModel):
    # content is nullable on purpose: a reasoning model can spend its whole output budget on
    # reasoning_content and return an empty answer channel. That is a CAP failure, not an upstream
    # failure — callers that care (scripts/run_ab.py) distinguish it from a quality score of 0 by
    # keeping the response's tokens. Consumers that want a string must handle None themselves.
    content: str | None
    provider: str
    model: str
    usage: dict[str, int]
    provenance: ProvenanceReport
    # S7j-W (spec 13 §1.7): the model's requested tool calls, OpenAI message.tool_calls
    # shape carried verbatim. Live finding 2026-10-12: the batch transport kept only
    # content, so no model could ever exercise the tool path through the gate. The gate is
    # the provenance boundary, not the citation enforcer — the args are policed by the
    # mount's tool.execute.before guard hook.
    tool_calls: list[dict] = []

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


class RerankRequest(BaseModel):
    matter_ref: str
    query: str
    texts: list[str]
    model: str | None = None
    # R1 D3: rerank scores the DRAFT against PASSAGES — privileged text on both sides,
    # so the strictest tier is structural (the routing table cannot relax it).
    classification: Classification = "LOCAL_ONLY"
    max_texts: int = 64      # batch ceiling; over-long batches are REFUSED, never truncated

class RerankResponse(BaseModel):
    scores: list[float]
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
                 embedding_transport: Transport | None = None,
                 rerank_transport: Transport | None = None) -> None:
        self.registry, self.routing, self.trace = registry, routing, trace
        self._transport = transport or self._default_transport
        self._embedding_transport = embedding_transport or self._default_embedding_transport
        self._rerank_transport = rerank_transport or self._default_rerank_transport

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

    async def _default_rerank_transport(self, provider: ProviderConfig, payload: dict) -> dict:
        # llama-server's /rerank shape (query + documents -> index/score results); NOT an
        # OpenAI endpoint, so this transport lives beside the other two, not under them.
        from harness.keychain import get_key
        from harness.providers.http_fetch import openai_fetch
        key = get_key(provider.name) or ""
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        result = await openai_fetch(f"{provider.base_url.rstrip('/')}/rerank", headers, payload)
        if result is None:
            raise RuntimeError(f"provider {provider.name} rerank call failed")
        return result

    def _provenance_of(self, provider: ProviderConfig, result: dict) -> ProvenanceReport:
        meta = result.get("_server_meta") or {}
        declared_rev = provider.declared_provenance.get("weights_revision", "")
        reported_rev = meta.get("weights_revision", "")
        # S7d: dispatch-time evidence wins over the probe's registration-time finding,
        # which wins over nothing. Real endpoints send no _server_meta, so the live
        # value is the probe's; either way the trace records what actually held.
        # S6-2 + the live cloud case: a server-REPORTED revision verifies only when it
        # MATCHES the declared (pinned) one. But a real cloud endpoint reports no revision at
        # all — _server_meta is a test-only channel — so requiring a reported match here would
        # record verified=0 for a leg the probe admitted at verified=1 under the CR-3 cloud rule
        # (declared + saas), contradicting the admission and failing C6 on a healthy endpoint.
        # Absence is not evidence either way: carry the probe's verdict forward, and let live
        # evidence still override it when the endpoint does speak (a mismatch stays verified=0).
        if reported_rev:
            verified = revision_verified(reported_rev, declared_rev)
        else:
            verified = provider.discovered_verified
        return ProvenanceReport(
            engine=meta.get("engine") or provider.engine or "",
            weights_revision=reported_rev or declared_rev,
            backend=meta.get("backend") or provider.discovered_backend or "",
            verified=verified,
            raw={"source": "response-meta" if meta else "declared-only"},
        )

    def _live(self, request: LLMRequest, kind: str, **fields) -> None:
        # the live log sits beside trace.db; a trace stand-in without a path writes none
        root = getattr(getattr(self.trace, "db_path", None), "parent", None)
        if root is not None:
            from harness import live
            live.append(root, request.matter_ref, kind, task_class=request.task_class, **fields)

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
            if request.tools:
                payload["tools"] = request.tools
                if request.tool_choice:
                    payload["tool_choice"] = request.tool_choice
            if cfg.max_output_tokens is not None:          # S6-4: clamp, never raise
                payload["max_tokens"] = min(payload["max_tokens"], cfg.max_output_tokens)
            msgs = request.messages or []
            self._live(request, "llm.start", provider=cfg.name, model=payload["model"],
                       n_messages=len(msgs), tools=len(request.tools),
                       input=msgs[-1] if msgs else None)
            t0 = time.monotonic()
            try:
                result = await self._transport(cfg, payload)
            except Exception as ex:                       # noqa: BLE001 — trace, then next candidate
                last_error = str(ex)
                self._live(request, "llm.end", provider=cfg.name, model=payload["model"],
                           status="error", error=last_error,
                           ms=int((time.monotonic()-t0)*1000))
                self.trace.append(DispatchRecord(
                    matter_ref=request.matter_ref, task_class=request.task_class,
                    classification=request.classification, provider=cfg.name, model=payload["model"],
                    status="error", error=last_error, latency_ms=int((time.monotonic()-t0)*1000)))
                continue
            prov = self._provenance_of(cfg, result)
            # Ollama nests a per-provider breakdown inside usage (prompt_tokens_details:
            # {cached_tokens: 0}) that this layer's dict[str,int] contract rejects — a
            # live-only failure, since every offline test sends flat integer usage. Only the
            # scalar token counts are consumed by the trace, the sidecar and the proxy; keep
            # those as ints and drop the nested breakdown nothing reads.
            usage = {k: int(v) for k, v in (result.get("usage") or {}).items()
                     if isinstance(v, (int, float))}
            # R3 refine: reasoning tokens ride the nested details dict the flatten above
            # drops — read them before it is gone (0 when the upstream reports none).
            reasoning = int((((result.get("usage") or {})
                              .get("completion_tokens_details") or {})
                             .get("reasoning_tokens")) or 0)
            self.trace.append(DispatchRecord(
                matter_ref=request.matter_ref, task_class=request.task_class,
                classification=request.classification, provider=cfg.name,
                model=result.get("model", payload["model"]),
                weights_revision=prov.weights_revision, engine=prov.engine,
                backend=prov.backend,
                verified=1 if prov.verified else 0,
                tokens_in=usage.get("prompt_tokens", 0), tokens_out=usage.get("completion_tokens", 0),
                tokens_reasoning=reasoning,
                latency_ms=int((time.monotonic()-t0)*1000)))
            msg = result["choices"][0]["message"]
            self._live(request, "llm.end", provider=cfg.name,
                       model=result.get("model", payload["model"]), status="ok",
                       ms=int((time.monotonic()-t0)*1000),
                       tokens_in=usage.get("prompt_tokens", 0),
                       tokens_out=usage.get("completion_tokens", 0),
                       tokens_reasoning=reasoning,
                       content=msg.get("content"),
                       # thinking: NIM/DeepSeek name it reasoning_content, Ollama/OpenRouter reasoning
                       reasoning=msg.get("reasoning_content") or msg.get("reasoning"),
                       tool_calls=msg.get("tool_calls") or [],
                       finish_reason=result["choices"][0].get("finish_reason"))
            return LLMResponse(content=msg.get("content"),
                               provider=cfg.name, model=result.get("model", payload["model"]),
                               usage=usage, provenance=prov,
                               tool_calls=msg.get("tool_calls") or [])
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
            # Ollama nests a per-provider breakdown inside usage (prompt_tokens_details:
            # {cached_tokens: 0}) that this layer's dict[str,int] contract rejects — a
            # live-only failure, since every offline test sends flat integer usage. Only the
            # scalar token counts are consumed by the trace, the sidecar and the proxy; keep
            # those as ints and drop the nested breakdown nothing reads.
            usage = {k: int(v) for k, v in (result.get("usage") or {}).items()
                     if isinstance(v, (int, float))}
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

    async def rerank(self, request: "RerankRequest") -> "RerankResponse":
        # R1 D3: the third sibling of dispatch()/embed() — same routing, same admission
        # filter, same per-dispatch provenance and trace row; only the endpoint (/rerank)
        # and the payload (query + documents, no max_tokens) differ.
        if not request.texts:
            self.trace.append(DispatchRecord(
                matter_ref=request.matter_ref, task_class="rerank",
                classification=request.classification, provider="-", model="-",
                status="refused", error="empty rerank request"))
            raise GateRefusal("empty rerank request — nothing to score")
        if len(request.texts) > request.max_texts:
            self.trace.append(DispatchRecord(
                matter_ref=request.matter_ref, task_class="rerank",
                classification=request.classification, provider="-", model="-",
                status="refused",
                error=f"rerank batch {len(request.texts)} exceeds max_texts {request.max_texts}"))
            raise GateRefusal(
                f"rerank batch {len(request.texts)} exceeds max_texts {request.max_texts}")
        policy = MatterPolicy(matter_ref=request.matter_ref, classification=request.classification)
        candidates = self.routing.route("rerank", policy, self.registry)
        if not candidates:
            self.trace.append(DispatchRecord(
                matter_ref=request.matter_ref, task_class="rerank",
                classification=request.classification, provider="-", model="-",
                status="refused", error="no eligible provider"))
            raise GateRefusal("no eligible provider for rerank")
        last_error = ""
        for cfg in candidates:
            model = request.model or cfg.model
            if not model:
                self.trace.append(DispatchRecord(
                    matter_ref=request.matter_ref, task_class="rerank",
                    classification=request.classification, provider=cfg.name, model="-",
                    status="refused", error=f"no model specified for provider {cfg.name}"))
                raise GateRefusal(f"no model specified for provider {cfg.name}")
            payload = {"model": model, "query": request.query, "documents": request.texts}
            t0 = time.monotonic()
            try:
                result = await self._rerank_transport(cfg, payload)
            except Exception as ex:                       # noqa: BLE001 — trace, then next candidate
                last_error = str(ex)
                self.trace.append(DispatchRecord(
                    matter_ref=request.matter_ref, task_class="rerank",
                    classification=request.classification, provider=cfg.name, model=payload["model"],
                    status="error", error=last_error, latency_ms=int((time.monotonic()-t0)*1000)))
                continue
            results = result.get("results") or []
            bad = None
            if len(results) != len(request.texts):
                bad = (f"rerank endpoint returned {len(results)} results "
                       f"for {len(request.texts)} documents")
            else:
                # A reranker may return results in ANY order (relevance-sorted is the
                # norm); alignment is BY index — a value out of range or a duplicate
                # silently misaligns scores against passages (the S7e embed defect in
                # another shape), arrival order never can.
                seen: set[int] = set()
                for i, r in enumerate(results):
                    idx = r.get("index", i)
                    if not isinstance(idx, int) or not 0 <= idx < len(request.texts):
                        bad = (f"rerank response index out of range at position {i}: "
                               f"{idx!r} (0..{len(request.texts) - 1})")
                        break
                    if idx in seen:
                        bad = f"rerank response repeats index {idx}"
                        break
                    seen.add(idx)
            if bad is not None:
                # A reversed or repeated index silently misaligns scores against passages —
                # the exact S7e embed defect in another shape. Fail to the next candidate.
                last_error = bad
                self.trace.append(DispatchRecord(
                    matter_ref=request.matter_ref, task_class="rerank",
                    classification=request.classification, provider=cfg.name, model=payload["model"],
                    status="error", error=last_error, latency_ms=int((time.monotonic()-t0)*1000)))
                continue
            prov = self._provenance_of(cfg, result)
            usage = {k: int(v) for k, v in (result.get("usage") or {}).items()
                     if isinstance(v, (int, float))}
            self.trace.append(DispatchRecord(
                matter_ref=request.matter_ref, task_class="rerank",
                classification=request.classification, provider=cfg.name,
                model=result.get("model", payload["model"]),
                weights_revision=prov.weights_revision, engine=prov.engine,
                backend=prov.backend,
                verified=1 if prov.verified else 0,
                tokens_in=usage.get("prompt_tokens", 0), tokens_out=0,   # no completion tokens
                latency_ms=int((time.monotonic()-t0)*1000)))
            ordered = sorted(results, key=lambda r: r["index"])
            return RerankResponse(
                scores=[float(r["relevance_score"]) for r in ordered],
                provider=cfg.name, model=result.get("model", payload["model"]),
                usage=usage, provenance=prov)
        raise GateRefusal(f"all rerank candidates failed; last: {last_error}")
