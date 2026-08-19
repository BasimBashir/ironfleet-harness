import pytest

@pytest.fixture
def harness_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "home"))
    return tmp_path / "home"

@pytest.fixture
def fake_transport():  # canned OpenAI-compatible completion, used across tests
    async def _call(provider, payload):
        return {
            "id": "chatcmpl-test", "object": "chat.completion",
            "model": payload["model"],
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "mock answer citing [Act, s 1]"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "_server_meta": {"engine": provider.engine or "unknown",
                              "weights_revision": provider.declared_provenance.get("weights_revision", "")},
        }
    return _call
