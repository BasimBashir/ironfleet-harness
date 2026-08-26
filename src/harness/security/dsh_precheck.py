from __future__ import annotations
import json, sys
from pathlib import Path
from pydantic import BaseModel

LIFECYCLE = ("preinstall", "postinstall", "prepare", "prepublish")

class PrecheckReport(BaseModel):
    packages: int = 0
    lifecycle_scripts: list[tuple[str, str]] = []
    missing_licence: int = 0
    vendored: int = 0
    critical_findings: int = 0

def scan_package_jsons(files: dict[str, str]) -> PrecheckReport:
    rep = PrecheckReport()
    for path, text in files.items():
        try:
            doc = json.loads(text)
        except ValueError:
            continue
        rep.packages += 1
        name = doc.get("name", Path(path).parent.name)
        for script in (doc.get("scripts") or {}):
            if script in LIFECYCLE:
                rep.lifecycle_scripts.append((name, script))
                if path == "package.json":
                    rep.critical_findings += 1          # root-level install-time execution
        if "license" not in doc:
            rep.missing_licence += 1
        if "vendor/" in path.replace("\\", "/"):   # Path.relative_to yields backslashes on Windows
            rep.vendored += 1
    return rep

def write_precheck_report(rep: PrecheckReport, path: Path) -> None:
    Path(path).write_text(
        f"# DSH supply-chain pre-check (P0-6)\n\n- packages scanned: {rep.packages}\n"
        f"- vendored: {rep.vendored}\n- missing licence fields: {rep.missing_licence}\n"
        f"- lifecycle scripts: {rep.lifecycle_scripts}\n- critical findings: {rep.critical_findings}\n\n"
        "Gate: dsh enters the spike only if critical_findings == 0 and licence questions are resolved.\n",
        encoding="utf-8")

if __name__ == "__main__":
    repo = Path(sys.argv[1])
    files = {str(p.relative_to(repo)): p.read_text(encoding="utf-8", errors="ignore")
             for p in repo.rglob("package.json")}
    rep = scan_package_jsons(files)
    write_precheck_report(rep, Path("dsh_precheck_report.md"))
    print(f"scanned {rep.packages} package.json files -> dsh_precheck_report.md")
