"""html2statute_md — fixture snippet test (track-b plan §3.1: one small test)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from html2statute_md import build_md, html_to_statute_text  # noqa: E402

FIXTURE = """
<html><body>
<nav class="legislation-side-nav"><img src="x.png"><a class="legislation-side-nav__link--prov"
 href="#x">Implied indemnity of trustees</a></nav>
<table><tr><td class="tocColumn1"><span>38</span></td>
<td class="tocColumn2"><span class="tocProvHeading"><a class="toc"
 href="#x">Implied indemnity of trustees</a></span></td></tr></table>
<div class="prov"><h5><span class="num">38</span><span class="label">Implied indemnity of trustees</span></h5>
<div class="prov-body"><p>Where trustees acting jointly incur liabilities.</p>
<p>Line one<br>line two.</p></div></div>
</body></html>
"""


def test_bare_section_line_and_toc_skipped():
    text = html_to_statute_text(FIXTURE)
    assert "38 Implied indemnity of trustees" in text      # bare section heading
    assert "tocColumn1" not in text and "href" not in text  # nav/TOC skipped
    assert "Where trustees acting jointly incur liabilities." in text
    assert "Line one\nline two." in text                    # br kept as break


def test_void_element_inside_skipped_nav_does_not_wedge_skip():
    # regression: <img> in a skipped subtree must not keep the skip open forever
    text = html_to_statute_text(FIXTURE)
    assert "Implied indemnity of trustees" in text          # body content survives
    assert "Where trustees" in text                         # text after the nav survives


def test_header_carries_pco_furniture():
    md = build_md("38 Implied indemnity of trustees\n\nBody.", "Trustee Act 1956",
                  "30 January 2021", "https://example/whole.html", "2026-11-05")
    assert "Version as at:** 30 January 2021" in md[:8000]  # detect_kind furniture
    assert md.count("Implied indemnity of trustees") == 1  # the bare section line
