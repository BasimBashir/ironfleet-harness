# mcp/harness/module_e/export_court.py — M9: court-format export, stdlib only.
# .docx via zipfile + minimal OOXML (no python-docx — §10 no-new-deps ruling);
# .pdf via a hand-rolled PDF 1.4 text writer (no reportlab/fpdf). The export
# carries the dossier facts + open deadlines for a matter; it never promises a
# court will accept it — maximum-defensibility framing only. Path must stay
# inside the workspace; ".." escapes are refused.
from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from harness.lifecycle import dossier as _dossier

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '</Types>')
_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    '</Relationships>')


def _para(text: str, *, heading: bool = False) -> str:
    style = '<w:pPr><w:pStyle w:val="Heading1"/></w:pPr>' if heading else ""
    return (f'<w:p>{style}<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>')


def _docx_bytes(paragraphs: list[tuple[str, bool]]) -> bytes:
    body = "".join(_para(t, heading=h) for t, h in paragraphs)
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           '<w:body>'
           '<w:sectPr/>' + body + '</w:body></w:document>')
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


def _pdf_bytes(lines: list[str]) -> bytes:
    """Minimal PDF 1.4: one page, Helvetica, one text block per line."""
    def esc(s: str) -> str:
        return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    stream = "BT /F1 10 Tf 50 780 Td 14 TL\n" + "".join(
        f"({esc(l)}) Tj T*\n" for l in lines) + "ET"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream".encode(),
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return out


def _safe_path(path: str, base_dir: str | Path) -> Path:
    p = Path(path)
    if not p.is_absolute():
        raise RuntimeError("export path must be absolute (local file only)")
    try:
        p.resolve().relative_to(Path(base_dir).resolve())
    except ValueError:
        raise RuntimeError(f"export path {path!r} escapes {base_dir} — refused")
    return p


def export_court_pack(con, matter: str, path: str, *, fmt: str = "pdf",
                      base_dir: str | Path = ".") -> dict:
    """Export the matter's facts + open deadlines in court-pack format.
    Platform variant: reads the SQL dossier; `base_dir` contains the path."""
    if fmt not in ("docx", "pdf"):
        raise RuntimeError(f"unknown format {fmt!r} (docx | pdf)")
    out_path = _safe_path(path, base_dir)
    facts = _dossier.read(con, matter, "facts")["events"]
    deadlines = _dossier.read(con, matter, "deadlines")["deadlines"]
    paragraphs = [(f"IN THE HIGH COURT OF NEW ZEALAND — matter {matter}", True),
                  ("FACTS (dossier register)", True)]
    paragraphs += [(f"{f.get('field')}: {f.get('value')}", False) for f in facts]
    paragraphs += [("OPEN DEADLINES (kernel-computed)", True)]
    paragraphs += [(f"{d.get('what')}: due {d.get('due')} ({d.get('rule', '')})", False)
                   for d in deadlines]
    paragraphs.append(("Not legal advice — a qualified NZ lawyer reviews before "
                       "filing. Dates computed by kernels, never by the model.", False))
    if fmt == "docx":
        data = _docx_bytes(paragraphs)
    else:
        data = _pdf_bytes([t for t, _h in paragraphs])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return {"path": str(out_path), "format": fmt,
            "paragraphs": len(paragraphs), "bytes": len(data)}
