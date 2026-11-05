"""legislation.govt.nz whole.html -> statute .md in the ingest convention.

parse_provisions (harness.ingest_generic) splits provisions on BARE lines matching
`^\\d{1,3}[A-Z]{0,2} <Title>$` (track-b plan 2026-11-05 §3.1), and detect_kind needs
PCO furniture ("Version as at ...") inside the first 8000 chars. PCO whole.html
duplicates every heading three times (side-nav, TOC table, body) — the nav/TOC
subtrees are skipped wholesale so only body headings survive. Stdlib only: the
downloaded files are untrusted input and the parser never executes anything.
"""
from __future__ import annotations

import argparse
import re
from html.parser import HTMLParser

_SKIP_CLASS = re.compile(r"toc|side-nav|navigation|mobileNav|cookie|banner|footer|header|search",
                         re.IGNORECASE)
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
# normalise "<num><Title>" span joins so the section-line regex sees "38 Title"
_NUM_TITLE = re.compile(r"^(\d{1,3}[A-Z]{0,2})(?=[A-Z(])")


_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
         "meta", "param", "source", "track", "wbr"}


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        # stack of open skipped tags: void tags never push, so a stray <img>
        # inside skipped markup cannot wedge the skip state open forever
        self.skip_stack: list[str] = []
        self.raw_skip = False                     # inside <script>/<style>
        self.in_heading = False
        self.head_buf: list[str] = []
        self.lines: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.raw_skip = True
            return
        classes = " ".join(v for k, v in attrs if k == "class" and v)
        if self.skip_stack or _SKIP_CLASS.search(classes):
            if tag not in _VOID:
                self.skip_stack.append(tag)
            return
        if tag in _HEADINGS:
            self.in_heading = True
            self.head_buf = []
        elif tag == "br" and not self.in_heading:
            self.lines.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag == "br" and not self.skip_stack and not self.raw_skip and not self.in_heading:
            self.lines.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.raw_skip = False
            return
        if self.skip_stack:
            if tag in self.skip_stack:
                while self.skip_stack and self.skip_stack[-1] != tag:
                    self.skip_stack.pop()
                self.skip_stack.pop()             # drop the closer itself
            return
        if tag in _HEADINGS and self.in_heading:
            txt = _NUM_TITLE.sub(r"\1 ", " ".join("".join(self.head_buf).split()))
            if txt:
                self.lines.append(f"\n{txt}\n")
            self.in_heading = False
            self.head_buf = []

    def handle_data(self, data):
        if self.skip_stack or self.raw_skip:
            return
        if self.in_heading:
            self.head_buf.append(data)
        else:
            self.lines.append(data)


def html_to_statute_text(html: str) -> str:
    p = _Extractor()
    p.feed(html)
    body = re.sub(r"[ \t]+", " ", "".join(p.lines))
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def build_md(text: str, title: str, as_at: str, source_url: str, retrieved: str) -> str:
    header = (f"# {title} (NZ)\n\n**Jurisdiction:** NZ\n"
              f"**Version as at:** {as_at}\n**Source:** {source_url}\n"
              f"**Retrieved:** {retrieved}\n"
              f"**Licence:** CC BY 4.0 (Crown copyright, legislation.govt.nz)\n\n---\n\n")
    return header + text + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("html", type=str)
    ap.add_argument("out", type=str)
    ap.add_argument("--title", required=True)
    ap.add_argument("--as-at", required=True, dest="as_at")
    ap.add_argument("--source-url", required=True, dest="source_url")
    ap.add_argument("--retrieved", default="2026-11-05 (PCO website)")
    args = ap.parse_args()
    from pathlib import Path
    html = Path(args.html).read_text(encoding="utf-8")
    md = build_md(html_to_statute_text(html), args.title, args.as_at,
                  args.source_url, args.retrieved)
    Path(args.out).write_text(md, encoding="utf-8")
    print(f"[html2statute_md] {args.out}: {len(md.split())} words")


if __name__ == "__main__":
    main()
