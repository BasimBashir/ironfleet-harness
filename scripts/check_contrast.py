"""WCAG 2.2 AA contrast check for design/system/tokens.css (D-4). Stdlib only.

Usage: python scripts/check_contrast.py [path/to/tokens.css]  -> exit 0 when every pair passes.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

TOKENS = Path(__file__).resolve().parents[1] / "design" / "system" / "tokens.css"
TEXT, UI = 4.5, 3.0  # SC 1.4.3 normal text; SC 1.4.11 non-text (borders, focus, meter fill)

STATES = ["s-waiting", "s-running", "s-blocked", "s-failed", "s-review", "s-done", "s-idle"]
SURFACES = ["bg", "surface", "raise"]
PAIRS: list[tuple[str, str, float]] = (
    [(fg, bg, TEXT) for fg in ["text", "muted", "accent", *STATES, "v-verified", "v-unverified"] for bg in SURFACES]
    + [("accent-text", "accent", TEXT), ("s-waiting", "s-waiting-bg", TEXT), ("text", "accent-soft", TEXT),
       ("accent", "accent-soft", TEXT), ("s-failed", "danger-bg", TEXT), ("text", "danger-bg", TEXT)]
    # selected table row (accent-soft) carries muted sub-lines + state chips; block banner carries muted body
    + [(fg, "accent-soft", TEXT) for fg in ["muted", *STATES, "v-verified", "v-unverified"]]
    + [("muted", "danger-bg", TEXT)]
    + [(fg, bg, UI) for fg in ["focus", "control-border", "accent"] for bg in SURFACES]
    + [("accent", "meter-track", UI)]
)


def _rgb(hex_: str) -> tuple[float, ...]:
    h = hex_.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _lum(hex_: str) -> float:
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in _rgb(hex_)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _block(css: str, selector: str) -> dict[str, str]:
    m = re.search(re.escape(selector) + r"\s*\{(.*?)\}", css, re.S)
    body = m.group(1) if m else ""
    return dict(re.findall(r"--([\w-]+)\s*:\s*(#[0-9a-fA-F]{3,6})\b", body))


def parse_tokens(css: str) -> dict[str, dict[str, str]]:
    """Colour tokens per theme; dark inherits every light token it does not override."""
    light = _block(css, ":root")
    return {"light": light, "dark": {**light, **_block(css, '[data-theme="dark"]')}}


def check(tokens: dict[str, dict[str, str]], pairs=PAIRS) -> list[tuple[str, str, str, float, float]]:
    return [(theme, fg, bg, round(r, 2), need)
            for theme, t in tokens.items() for fg, bg, need in pairs
            if (r := ratio(t[fg], t[bg])) < need]


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else TOKENS
    tokens = parse_tokens(path.read_text(encoding="utf-8"))
    for theme, t in tokens.items():
        for fg, bg, need in PAIRS:
            r = ratio(t[fg], t[bg])
            print(f"{theme:5} {fg:>15} on {bg:<13} {r:5.2f} {'ok' if r >= need else 'FAIL'} (>={need})")
    fails = check(tokens)
    print(f"{len(fails)} failing pair(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
