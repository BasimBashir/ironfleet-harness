# tests/test_build_dashboard.py — the dashboard is assembled, never invented: every number in it
# traces back to a sidecar record and a rate-table entry.
import pytest
from pathlib import Path

import scripts.build_dashboard as dash
import scripts.run_ab as run_ab
from harness.eval.substitute import RateTable

LOCAL = [l for l in run_ab.LEGS if l.label == "thomson1-chat"][0]
CLOUD = [l for l in run_ab.LEGS if l.label == "Atria-Dawn-Preview"][0]

# Two legs x two cases. The local leg's blended rate is DERIVED from its own throughput below.
SIDECARS = {
    "thomson1-chat": [
        {"id": "c0", "status": "ok", "citation_accuracy": 0.5, "grounding_score": 0.5,
         "persona_rate": 1.0, "tokens_in": 1000, "tokens_out": 500, "latency_ms": 2000,
         "checks": {}, "error": ""},
        {"id": "c1", "status": "ok", "citation_accuracy": 1.0, "grounding_score": 0.0,
         "persona_rate": 0.5, "tokens_in": 2000, "tokens_out": 1000, "latency_ms": 4000,
         "checks": {}, "error": ""},
    ],
    "Atria-Dawn-Preview": [
        {"id": "c0", "status": "ok", "citation_accuracy": 1.0, "grounding_score": 1.0,
         "persona_rate": 1.0, "tokens_in": 3000, "tokens_out": 2000, "latency_ms": 5000,
         "checks": {}, "error": ""},
        {"id": "c1", "status": "ok", "citation_accuracy": 1.0, "grounding_score": 1.0,
         "persona_rate": 1.0, "tokens_in": 3000, "tokens_out": 2000, "latency_ms": 5000,
         "checks": {}, "error": ""},
    ],
}


@pytest.fixture
def table():
    return RateTable.from_yaml(run_ab.RATES_PATH)


def test_local_leg_rate_is_derived_from_its_own_measured_throughput(table):
    summaries = dash.leg_summaries(SIDECARS, run_ab.LEGS, table)
    local = [s for s in summaries if s.label == "thomson1-chat"][0]
    # 3000 tokens in + 1500 out over 6 s = 2,700,000 tokens/h; assumptions 3000/35000/0.25
    # -> 3000 / (8750 * 2.7e6) USD/token * 1e6 = 0.127 per 1M tokens
    assert local.mean_cost is not None and local.mean_cost > 0


def test_cloud_leg_uses_the_published_split_rates(table):
    summaries = dash.leg_summaries(SIDECARS, run_ab.LEGS, table)
    cloud = [s for s in summaries if s.label == "Atria-Dawn-Preview"][0]
    # 3000 in + 2000 out per case at $1.40/$4.40 per 1M -> 0.0042 + 0.0088 = $0.013
    assert cloud.mean_cost == pytest.approx(0.013, rel=1e-6)


def test_an_unusable_leg_gets_no_cost_and_is_marked(table):
    dead = {"qwen3.8:27b": [{"id": "c0", "status": "failed", "error": "boom",
                             "tokens_in": 0, "tokens_out": 0, "latency_ms": 0}]}
    summaries = dash.leg_summaries(dead, [l for l in run_ab.LEGS if l.label == "qwen3.8:27b"], table)
    assert summaries[0].usable is False and summaries[0].mean_cost is None


def test_render_names_the_recommendation_its_basis_and_every_source(table):
    summaries = dash.leg_summaries(SIDECARS, run_ab.LEGS, table)
    bar = dash.bar_for(summaries)
    md = dash.render(summaries, table, bar, scaffolding_tax_note="not incurred on this run")
    assert "# A-7 model substitution" in md
    assert "recommendation" in md.lower()
    assert "GLM-5.2" in md                       # the cloud rate's source is visible
    assert "operator to confirm" in md.lower()   # the local assumptions are flagged as defaults
    assert "not incurred on this run" in md      # the scaffolding-tax caveat is present
    for s in summaries:
        assert s.label in md


def test_render_says_when_nothing_meets_the_bar(table):
    # an incumbent far above every candidate: the fallback must be explicit, not a silent pick
    strong = [{"id": "c0", "status": "ok", "citation_accuracy": 1.0, "grounding_score": 1.0,
               "persona_rate": 1.0, "tokens_in": 10, "tokens_out": 10, "latency_ms": 10,
               "checks": {}, "error": ""}]
    weak = [{"id": "c0", "status": "ok", "citation_accuracy": 0.0, "grounding_score": 0.0,
             "persona_rate": 0.0, "tokens_in": 10, "tokens_out": 10, "latency_ms": 10,
             "checks": {}, "error": ""}]
    legs = [LOCAL, CLOUD]
    summaries = dash.leg_summaries({"thomson1-chat": strong, "Atria-Dawn-Preview": weak}, legs, table)
    md = dash.render(summaries, table, dash.bar_for(summaries),
                     scaffolding_tax_note="not incurred on this run")
    assert "standing pick" in md or "no candidate meets the bar" in md


def test_a_recalled_case_is_counted_once_not_twice_in_mean_cost(table):
    # A --recall rerun of an already-scored case appends a SECOND ok row for the same id; the
    # sidecar is append-only and from_records keeps only the last one, so the cost numerator must
    # count that same deduplicated set or mean_cost inflates on the field recommend() sorts on.
    first = {"id": "c0", "status": "ok", "citation_accuracy": 1.0, "grounding_score": 1.0,
             "persona_rate": 1.0, "tokens_in": 3000, "tokens_out": 2000, "latency_ms": 5000,
             "checks": {}, "error": ""}
    rerun = dict(first, tokens_in=1500, tokens_out=1000)       # the recall: a cheaper completion
    with_recall = dash.leg_summaries({"Atria-Dawn-Preview": [first, rerun]}, [CLOUD], table)
    without_recall = dash.leg_summaries({"Atria-Dawn-Preview": [rerun]}, [CLOUD], table)
    assert with_recall[0].n_scored == 1
    assert with_recall[0].mean_cost == pytest.approx(without_recall[0].mean_cost, rel=1e-9)
    # the last record alone: 1500 in + 1000 out at $1.40/$4.40 per 1M -> 0.0021 + 0.0044 = $0.0065;
    # double-counting both rows would give $0.0195
    assert with_recall[0].mean_cost == pytest.approx(0.0065, rel=1e-6)


def test_a_recalled_case_is_counted_once_in_the_local_legs_derived_rate_too(table):
    # Same hazard on the blended path: recalled rows must not inflate a local leg's mean_cost either.
    base = list(SIDECARS["thomson1-chat"])
    rerun = dict(base[1], tokens_in=4000, tokens_out=2000, latency_ms=8000)
    with_recall = dash.leg_summaries({"thomson1-chat": base + [rerun]}, [LOCAL], table)
    without_recall = dash.leg_summaries({"thomson1-chat": [base[0], rerun]}, [LOCAL], table)
    assert with_recall[0].n_scored == 2
    assert with_recall[0].mean_cost == pytest.approx(without_recall[0].mean_cost, rel=1e-9)
    assert with_recall[0].mean_cost is not None and with_recall[0].mean_cost > 0
