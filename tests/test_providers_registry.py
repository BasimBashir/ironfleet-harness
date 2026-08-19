from harness.keychain import set_key, get_key
from harness.providers.config import ProviderConfig, ProviderRegistry

def test_keychain_round_trip(monkeypatch):
    store: dict[str, str] = {}
    monkeypatch.setattr("harness.keychain._kv", store)
    set_key("mini1", "secret")
    assert get_key("mini1") == "secret"

def test_registry_upsert_get_list():
    reg = ProviderRegistry()
    cfg = ProviderConfig(name="mini1", base_url="http://mini1:8080/v1", engine="mlx-lm", tier="local")
    reg.upsert(cfg)
    assert reg.get("mini1").engine == "mlx-lm"
    assert [c.name for c in reg.list()] == ["mini1"]
    cfg2 = ProviderConfig(name="mini1", base_url="http://mini1:8080/v1", engine="mlx-lm",
                          tier="local", admitted="mechanical-only")
    reg.upsert(cfg2)
    assert reg.get("mini1").admitted == "mechanical-only"   # upsert replaces
