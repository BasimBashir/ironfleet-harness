# tests/test_substitute.py — A-7 model substitution: rates, cost, bar, recommendation
from pathlib import Path
import pytest
from harness.eval.substitute import ModelUnderTest, RateEntry, RateTable, cost_of


def _cloud_rate():
    return RateEntry(in_per_m=1.40, out_per_m=4.40, cached_in_per_m=0.26, source="test")


def _local_rate():
    return RateEntry(blended=True, in_per_m=0.05, out_per_m=0.05, source="test")


def test_cloud_cost_splits_input_and_output():
    c = cost_of(tokens_in=1_000_000, tokens_out=500_000, tokens_cache=0, rate=_cloud_rate())
    assert c["in"] == pytest.approx(1.40)
    assert c["out"] == pytest.approx(2.20)
    assert c["total"] == pytest.approx(3.60)


def test_cloud_cached_input_uses_the_cached_rate_and_is_clamped_to_tokens_in():
    # an endpoint cannot cache more than it was sent; the billable split never goes negative
    c = cost_of(tokens_in=1_000_000, tokens_out=0, tokens_cache=400_000, rate=_cloud_rate())
    assert c["in"] == pytest.approx(0.6 * 1.40 + 0.4 * 0.26)
    assert c["total"] == pytest.approx(c["in"])
    clamped = cost_of(tokens_in=100, tokens_out=0, tokens_cache=9_000, rate=_cloud_rate())
    assert clamped["in"] == pytest.approx(0.0001 * 0.26)   # cache clamped to the 100 sent


def test_local_blended_rate_is_one_rate_for_in_and_out():
    c = cost_of(tokens_in=1_000_000, tokens_out=1_000_000, tokens_cache=0, rate=_local_rate())
    assert c["in"] == pytest.approx(0.05)
    assert c["out"] == pytest.approx(0.05)
    assert c["total"] == pytest.approx(0.10)


def test_zero_tokens_cost_zero():
    assert cost_of(0, 0, 0, _cloud_rate())["total"] == 0.0


def test_rate_table_loads_from_yaml_and_requires_a_source(tmp_path):
    p = tmp_path / "rates.yaml"
    p.write_text(
        "rates:\n"
        "  cloud:\n"
        "    in_per_m: 1.40\n"
        "    out_per_m: 4.40\n"
        "    cached_in_per_m: 0.26\n"
        "    source: GLM-5.2 published\n", encoding="utf-8")
    table = RateTable.from_yaml(p)
    assert table.rates["cloud"].in_per_m == pytest.approx(1.40)
    bad = tmp_path / "bad.yaml"
    bad.write_text("rates:\n  cloud:\n    in_per_m: 1.0\n    out_per_m: 2.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source"):
        RateTable.from_yaml(bad)


def test_model_under_test_defaults_and_roles():
    m = ModelUnderTest(label="x", provider="p", model="m", engine="ollama", output_cap=16384,
                       rate_key="local")
    assert m.role == "candidate" and m.retry_attempts >= 1 and m.min_interval_s == 0.0


from harness.eval.substitute import amortized_rate_entry, measured_tokens_per_hour


def _blank_local_rate():
    return RateEntry(blended=True, in_per_m=0.0, out_per_m=0.0, source="derived",
                     amortization={"hardware_cost_usd": 3000.0, "service_life_hours": 35000.0,
                                   "utilization": 0.25})


def test_measured_throughput_is_tokens_over_seconds_scaled_to_hours():
    assert measured_tokens_per_hour(tokens_in=3600, tokens_out=3600, seconds=3600.0) == 7200.0


def test_amortized_rate_uses_measured_throughput_and_declared_financials():
    # 3000 USD over (35000 h x 0.25 x 7200 tokens/h = 63e6 tokens) = 4.762e-5 USD/token
    # = 47.62 USD per 1M. (The task brief printed 240.0 here with the same formula and inputs —
    # a hand-arithmetic slip: 3000/63e6 is 4.762e-5, and 240 would need served = 12.5e6 tokens,
    # which these inputs cannot produce. Corrected to match the brief's own formula; see the
    # task-2 report.)
    rate = amortized_rate_entry(_blank_local_rate(), tokens_in=3600, tokens_out=3600,
                                latency_ms_sum=3_600_000.0)
    assert rate.in_per_m == pytest.approx(3000.0 / (35000.0 * 0.25 * 7200.0) * 1_000_000)
    assert rate.out_per_m == pytest.approx(3000.0 / (35000.0 * 0.25 * 7200.0) * 1_000_000)
    assert rate.blended
    assert "derived" in rate.source


def test_amortized_rate_rejects_a_non_blended_rate():
    with pytest.raises(ValueError, match="blended"):
        amortized_rate_entry(_cloud_rate(), 100, 100, 1000.0)


def test_amortized_rate_rejects_zero_throughput():
    # nothing was served: dividing by zero throughput would invent a price
    with pytest.raises(ValueError, match="throughput"):
        amortized_rate_entry(_blank_local_rate(), 0, 0, 0.0)
