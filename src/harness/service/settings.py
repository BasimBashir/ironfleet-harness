# src/harness/service/settings.py — admin model/provider settings (M13.7)
"""The admin Settings tab's backing store. Providers ship as data
(data/providers.yaml, read by bootstrap._provider_specs); this layer holds the
ADMIN's persisted overrides — base_url/model per provider row (validated by the
same rules the env override draws), the API key (write-only, into the existing
keychain), a manual per-stage assignment, and the Test probe. Overrides live in
<store_root>/model-settings.json so they survive restarts without editing the
repo's YAML; bootstrap.build_gate applies the assignment at gate build.
Dispatch-side availability fallback is already gate.py's (candidates walk)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from harness.bootstrap import _provider_specs, _validate_url_override
from harness.keychain import delete_key, get_key, set_key
from harness.policy import LOCAL_ONLY_TASKS
from harness.service import authz
from harness.workflow import audit

PERM = "user.admin"
_LOCAL_ENGINES = ("mlx-lm", "vllm", "llamacpp", "ollama")


def _file(store_root) -> Path:
    return Path(store_root) / "model-settings.json"


def _load(store_root) -> dict:
    try:
        doc = json.loads(_file(store_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}          # a corrupt settings file must not take the API down
    return doc if isinstance(doc, dict) else {}


def _save(store_root, doc: dict) -> None:
    _file(store_root).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def _audit(con, principal: dict, action: str, target: str) -> None:
    con.execute("BEGIN IMMEDIATE")
    try:
        audit.append(con, matter_id="", actor=principal["username"], action=action,
                     target=target, inputs_digest=target)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def _spec(name: str, saved: dict) -> dict:
    for s in _provider_specs(saved=saved):
        if s["name"] == name:
            return s
    raise authz.not_found("not_found", f"unknown provider {name}")


def _url(engine: str, url: str) -> str:
    # the same trust line the env override draws: local engines loopback-only;
    # cloud rows https to any host, no userinfo (matter text + key would egress)
    if engine in _LOCAL_ENGINES:
        try:
            return _validate_url_override("base_url", url, set())
        except ValueError as e:
            raise authz.ServiceError(422, "validation_failed", str(e)) from None
    from urllib.parse import urlparse
    u = urlparse(url)
    if u.scheme == "https" and u.hostname and not u.username and not u.password:
        return url
    raise authz.ServiceError(422, "validation_failed",
                             "cloud provider URLs must be https without userinfo")


def view(con, principal: dict, *, store_root) -> dict:
    authz.require(con, principal, PERM)
    saved = _load(store_root)
    custom = {c.get("name") for c in saved.get("custom") or [] if isinstance(c, dict)}
    providers = [{
        "name": s["name"], "base_url": s["base_url"], "model": s["model"],
        "engine": s["engine"], "kind": s["kind"],
        "tier": "local" if s["engine"] in _LOCAL_ENGINES else "cloud",
        "context_window": s["context_window"], "custom": s["name"] in custom,
        "has_key": bool(get_key(s["name"])),   # probe stores "" for keyless locals
    } for s in _provider_specs(saved=saved)]
    from harness.cli import default_routing
    import yaml
    rdoc = yaml.safe_load(Path(default_routing()).read_text(encoding="utf-8")) or {}
    assign = saved.get("assign") or {}
    stages = [{"task_class": r.get("task_class"),
               "local_only": r.get("local_only", []),
               "local_preferred": r.get("local_preferred", []),
               "cloud_permitted": r.get("cloud_permitted", []),
               "assign": assign.get(r.get("task_class")),
               "local_only_task": r.get("task_class") in LOCAL_ONLY_TASKS}
              for r in rdoc.get("rules", []) if r.get("task_class")]
    return {"providers": providers, "stages": stages}


def add_provider(con, principal: dict, body: dict, *, store_root) -> dict:
    """M13.7 '+': an admin-added provider row, persisted to model-settings.json
    "custom" and merged into the registry by bootstrap._provider_specs."""
    authz.require(con, principal, PERM)
    name, engine, model = (str(body.get(k) or "").strip() for k in ("name", "engine", "model"))
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", name):
        raise authz.ServiceError(422, "validation_failed",
                                 "name: lowercase letters, digits and '-' (max 40)")
    if engine not in (*_LOCAL_ENGINES, "cloud") or not model:
        raise authz.ServiceError(422, "validation_failed",
                                 f"engine must be one of {', '.join((*_LOCAL_ENGINES, 'cloud'))}"
                                 " and model is required")
    saved = _load(store_root)
    if name in {s["name"] for s in _provider_specs(saved=saved)}:
        raise authz.ServiceError(409, "conflict", f"provider {name} exists")
    row = {"name": name, "base_url": _url(engine, str(body.get("base_url") or "")),
           "model": model, "engine": engine, "kind": "chat",
           # cloud admission (CR-3) needs a declared revision; the model id is the pin,
           # as data/providers.yaml does for nvidia-nim
           "weights_revision": model if engine == "cloud" else ""}
    saved.setdefault("custom", []).append(row)
    if body.get("api_key"):
        set_key(name, str(body["api_key"]))
    _save(store_root, saved)
    _audit(con, principal, "settings.provider_added", name)
    return {"name": name, "base_url": row["base_url"], "model": model,
            "has_key": bool(get_key(name))}


def delete_provider(con, principal: dict, name: str, *, store_root) -> None:
    """Remove an admin-added row, its key, and any stage assignment naming it. Stock rows
    ship in data/providers.yaml and are refused."""
    authz.require(con, principal, PERM)
    saved = _load(store_root)
    custom = [c for c in saved.get("custom") or [] if isinstance(c, dict)]
    if name not in {c.get("name") for c in custom}:
        _spec(name, saved)                        # unknown -> 404
        raise authz.ServiceError(409, "conflict", f"{name} is built in and cannot be removed")
    saved["custom"] = [c for c in custom if c.get("name") != name]
    saved["assign"] = {k: v for k, v in (saved.get("assign") or {}).items() if v != name}
    _save(store_root, saved)
    try:
        delete_key(name)
    except Exception:  # noqa: BLE001 — no stored key is the common case (keyring raises)
        pass
    _audit(con, principal, "settings.provider_deleted", name)


def put_provider(con, principal: dict, name: str, body: dict, *, store_root) -> dict:
    authz.require(con, principal, PERM)
    saved = _load(store_root)
    s = _spec(name, saved)
    custom = next((c for c in saved.get("custom") or []
                   if isinstance(c, dict) and c.get("name") == name), None)
    # a custom row is edited in place; a stock row gets an override entry
    row = custom if custom is not None else saved.setdefault("providers", {}).setdefault(name, {})
    if body.get("base_url"):
        row["base_url"] = _url(s["engine"], body["base_url"])
    if body.get("model"):
        row["model"] = str(body["model"])
        if custom is not None and s["engine"] == "cloud":
            row["weights_revision"] = row["model"]
    if body.get("api_key"):
        set_key(name, str(body["api_key"]))
    _save(store_root, saved)
    _audit(con, principal, "settings.provider_updated", name)
    return {"name": name, "base_url": row.get("base_url", s["base_url"]),
            "model": row.get("model", s["model"]), "has_key": bool(get_key(name))}


async def _probe_one(name: str, spec: dict) -> dict:
    """Module-level seam: tests monkeypatch this (the real probe dials the network).
    Probe-only: no registry upsert, and a throwaway keychain so Test never stores.
    async def, NOT asyncio.run — the route runs on the ASGI loop (live E2E round 2
    caught the nested-loop RuntimeError the monkeypatched suites never see)."""
    from harness.providers.http_fetch import openai_fetch
    from harness.providers.probe import register_provider
    res = await register_provider(
        name, spec["base_url"], get_key(name) or "", model=spec["model"],
        engine=spec["engine"], kind=spec["kind"], declared=spec["declared"],
        fetch=openai_fetch, keychain_set={})
    out = {"name": name, "reachable": res.reachable, "auth_ok": res.auth_ok,
           "admission": res.admission, "verified": res.provenance.verified,
           "models": len(res.models)}
    # A cloud model list (NIM's) answers WITHOUT a key, so the probe alone passed a keyless
    # row; one 1-token chat with the stored key is the real auth check (Test only, not boot).
    if spec["engine"] not in _LOCAL_ENGINES and res.admission != "refused":
        key, errs = get_key(name) or "", []
        ok = bool(key) and await openai_fetch(
            f"{spec['base_url'].rstrip('/')}/chat/completions",
            {"Authorization": f"Bearer {key}"},
            {"model": spec["model"], "messages": [{"role": "user", "content": "ping"}],
             "max_tokens": 1}, errors=errs) is not None
        if not ok:
            out.update(auth_ok=False, admission="refused",
                       error=errs[0] if errs else "no API key set")
    return out


async def test_provider(con, principal: dict, name: str, *, store_root) -> dict:
    authz.require(con, principal, PERM)
    return await _probe_one(name, _spec(name, _load(store_root)))


def put_assign(con, principal: dict, task_class: str, provider: str | None, *,
               store_root) -> dict:
    authz.require(con, principal, PERM)
    import yaml
    from harness.cli import default_routing
    saved = _load(store_root)
    engines = {s["name"]: s["engine"] for s in _provider_specs(saved=saved)}
    if provider is not None and provider not in engines:
        raise authz.ServiceError(422, "validation_failed", f"unknown provider {provider}")
    rdoc = yaml.safe_load(Path(default_routing()).read_text(encoding="utf-8")) or {}
    if task_class not in {r.get("task_class") for r in rdoc.get("rules", [])}:
        raise authz.ServiceError(422, "validation_failed", f"unknown task_class {task_class}")
    # A-4: privileged text never embeds/reranks off-box — policy.route would drop it anyway
    if provider is not None and task_class in LOCAL_ONLY_TASKS \
            and engines[provider] not in _LOCAL_ENGINES:
        raise authz.ServiceError(422, "validation_failed",
                                 f"{task_class} is local-only; {provider} is a cloud provider")
    if provider is None:
        saved.setdefault("assign", {}).pop(task_class, None)
    else:
        saved.setdefault("assign", {})[task_class] = provider
    _save(store_root, saved)
    _audit(con, principal, "settings.assigned", task_class)
    return {"task_class": task_class, "assign": (saved.get("assign") or {}).get(task_class)}
