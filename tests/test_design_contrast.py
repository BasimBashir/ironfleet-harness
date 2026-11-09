"""D-4: WCAG 2.2 AA contrast for the design-system tokens (light + dark)."""
from pathlib import Path

import pytest

import scripts.check_contrast as cc

TOKENS = Path(__file__).resolve().parents[1] / "design" / "system" / "tokens.css"


def test_ratio_known_values():
    assert cc.ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert cc.ratio("#ffffff", "#ffffff") == pytest.approx(1.0)
    assert cc.ratio("#767676", "#ffffff") == pytest.approx(4.54, abs=0.01)  # the classic AA edge grey
    assert cc.ratio("#fff", "#000") == cc.ratio("#000000", "#ffffff")  # 3-digit hex, order-free


def test_parse_tokens_dark_inherits_light():
    css = """:root{ --bg:#ffffff; --text:#111111; --row:28px; }
    [data-theme="dark"]{ --bg:#000000; }
    [data-mode="self-rep"]{ --row:40px; }"""
    t = cc.parse_tokens(css)
    assert t["light"] == {"bg": "#ffffff", "text": "#111111"}
    assert t["dark"] == {"bg": "#000000", "text": "#111111"}


def test_check_reports_failing_pair():
    tokens = {"light": {"a": "#777777", "b": "#ffffff"}, "dark": {"a": "#777777", "b": "#ffffff"}}
    fails = cc.check(tokens, pairs=[("a", "b", 4.5)])
    assert [(f[0], f[1], f[2]) for f in fails] == [("light", "a", "b"), ("dark", "a", "b")]
    assert cc.check(tokens, pairs=[("a", "b", 3.0)]) == []


def test_design_system_tokens_meet_wcag_aa_in_both_themes():
    tokens = cc.parse_tokens(TOKENS.read_text(encoding="utf-8"))
    for theme in ("light", "dark"):
        missing = {n for p in cc.PAIRS for n in p[:2]} - tokens[theme].keys()
        assert not missing, f"{theme}: pairs name undeclared tokens {sorted(missing)}"
    assert cc.check(tokens) == []
