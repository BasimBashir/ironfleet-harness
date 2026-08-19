from __future__ import annotations
import keyring
SERVICE = "ironfleet-harness"
_kv: dict[str, str] | None = None      # tests substitute a dict

def set_key(provider: str, key: str) -> None:
    if isinstance(_kv, dict): _kv[provider] = key
    else: keyring.set_password(SERVICE, provider, key)

def get_key(provider: str) -> str | None:
    if isinstance(_kv, dict): return _kv.get(provider)
    return keyring.get_password(SERVICE, provider)

def delete_key(provider: str) -> None:
    if isinstance(_kv, dict): _kv.pop(provider, None)
    else: keyring.delete_password(SERVICE, provider)
