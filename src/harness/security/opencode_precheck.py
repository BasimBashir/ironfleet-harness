from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from pydantic import BaseModel

LIFECYCLE = ("preinstall", "install", "postinstall", "prepare", "prepublish")
NATIVE_SUFFIXES = (".exe", ".dll", ".node", ".so", ".dylib")
DEP_FIELDS = ("dependencies", "devDependencies", "optionalDependencies")


class LifecycleFinding(BaseModel):
    tree: str
    path: str
    package: str
    script: str


class FloatingRange(BaseModel):
    tree: str
    file: str
    field: str
    spec: str


class NativeBinary(BaseModel):
    tree: str
    relpath: str
    sha256: str
    size: int


class TreeScan(BaseModel):
    tree: str
    root: str
    packages: int = 0
    missing_licence: int = 0
    vendored: int = 0
    lifecycle: list[LifecycleFinding] = []
    floating: list[FloatingRange] = []


class ScanResult(BaseModel):
    trees: list[TreeScan] = []
    native_binaries: list[NativeBinary] = []

    @property
    def critical_findings(self) -> int:
        return sum(len(t.lifecycle) for t in self.trees)

    @property
    def packages(self) -> int:
        return sum(t.packages for t in self.trees)

    @property
    def missing_licence(self) -> int:
        return sum(t.missing_licence for t in self.trees)

    @property
    def vendored(self) -> int:
        return sum(t.vendored for t in self.trees)

    @property
    def floating(self) -> list[FloatingRange]:
        return [f for t in self.trees for f in t.floating]


def owning_package(relpath: str) -> str:
    parts = relpath.replace("\\", "/").split("/")
    for i, part in enumerate(parts):
        if part == "node_modules" and i + 1 < len(parts):
            nxt = parts[i + 1]
            if nxt.startswith("@") and i + 2 < len(parts):
                return f"{nxt}/{parts[i + 2]}"
            return nxt
    return "(root)"


def scan_install_tree(tree: str, root: str, files: dict[str, str]) -> TreeScan:
    ts = TreeScan(tree=tree, root=root)
    for path, text in files.items():
        try:
            doc = json.loads(text)
        except ValueError:
            continue
        if not isinstance(doc, dict):
            continue
        ts.packages += 1
        name = doc.get("name") or owning_package(path) or path
        for script in (doc.get("scripts") or {}):
            if script in LIFECYCLE:
                ts.lifecycle.append(
                    LifecycleFinding(tree=tree, path=path, package=name, script=script))
        if "license" not in doc:
            ts.missing_licence += 1
        if "vendor/" in path.replace("\\", "/"):
            ts.vendored += 1
    return ts


def is_floating(spec: str) -> bool:
    s = (spec or "").strip()
    if not s or s in ("*", "latest", "x"):
        return True
    return s[0] in "^~><" or ".x" in s or ".*" in s


def _npm_spec(npm: str) -> str:
    rest = npm[1:] if npm.startswith("@") else npm
    _, _, spec = rest.partition("@")
    return spec


def scan_runtime_manifest(tree: str, path: str, text: str) -> list[FloatingRange]:
    try:
        doc = json.loads(text)
    except ValueError:
        return []
    if not isinstance(doc, dict):
        return []
    out: list[FloatingRange] = []
    for field in DEP_FIELDS:
        deps = doc.get(field)
        if not isinstance(deps, dict):
            continue
        for name, spec in deps.items():
            if is_floating(str(spec)):
                out.append(FloatingRange(tree=tree, file=path,
                                         field=f"{field}.{name}", spec=str(spec)))
    return out


def scan_opencode_json(tree: str, path: str, text: str) -> list[FloatingRange]:
    try:
        doc = json.loads(text)
    except ValueError:
        return []
    if not isinstance(doc, dict):
        return []
    out: list[FloatingRange] = []
    providers = doc.get("provider")
    if not isinstance(providers, dict):
        return []
    for pid, prov in providers.items():
        npm = prov.get("npm") if isinstance(prov, dict) else None
        if isinstance(npm, str):
            spec = _npm_spec(npm)
            if is_floating(spec):
                out.append(FloatingRange(tree=tree, file=path,
                                         field=f"provider.{pid}.npm",
                                         spec=spec or "(none)"))
    return out


def inventory_native_binaries(tree: str, root: Path) -> list[NativeBinary]:
    out: list[NativeBinary] = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in NATIVE_SUFFIXES:
            try:
                data = p.read_bytes()
            except OSError:
                continue
            out.append(NativeBinary(tree=tree,
                                    relpath=str(p.relative_to(root)).replace("\\", "/"),
                                    sha256=hashlib.sha256(data).hexdigest(),
                                    size=len(data)))
    return out


def write_manifest(res: ScanResult, path: Path) -> None:
    lines = [f"{b.sha256}  {b.tree}/{b.relpath}" for b in res.native_binaries]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_scan_json(res: ScanResult, path: Path) -> None:
    Path(path).write_text(res.model_dump_json(indent=2) + "\n",
                          encoding="utf-8", newline="\n")


def write_mechanical(res: ScanResult, path: Path) -> None:
    lines = [
        "# OpenCode supply-chain mechanical scan (S7a / A-8)",
        "",
        f"- trees scanned: {', '.join(t.tree for t in res.trees)}",
        f"- packages scanned: {res.packages}",
        f"- vendored: {res.vendored}",
        f"- missing licence fields: {res.missing_licence}",
        f"- lifecycle scripts (CRITICAL until adjudicated): {res.critical_findings}",
        f"- floating runtime ranges: {len(res.floating)}",
        f"- native binaries inventoried: {len(res.native_binaries)}",
    ]
    for t in res.trees:
        lines += [f"## tree {t.tree} — {t.root}",
                  f"- packages: {t.packages} · missing licence: {t.missing_licence} · vendored: {t.vendored}",
                  "- lifecycle:"]
        lines += [f"  - {f.package} · {f.script} · {f.path}" for f in t.lifecycle] or ["  - none"]
        lines += ["- floating:"]
        lines += [f"  - {f.file} · {f.field} · {f.spec}" for f in t.floating] or ["  - none"]
        natives = [b for b in res.native_binaries if b.tree == t.tree]
        lines += [f"- native binaries: {len(natives)}"]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _read_texts(pattern: str, root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)).replace("\\", "/"):
            p.read_text(encoding="utf-8", errors="ignore")
            for p in sorted(root.rglob(pattern))}


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="OpenCode (A-8) supply-chain mechanical scan")
    p.add_argument("outdir")
    p.add_argument("--tree", action="append", default=[], metavar="LABEL=PATH")
    p.add_argument("--runtime-manifest", action="append", default=[], metavar="LABEL=PATH")
    p.add_argument("--opencode-json", action="append", default=[], metavar="LABEL=PATH")
    a = p.parse_args(argv)

    def _fail(msg: str) -> int:
        print(f"error: {msg}", file=sys.stderr)
        return 2

    for spec in a.tree:
        label, _, root = spec.partition("=")
        if not Path(root).is_dir():
            return _fail(f"--tree {label}: not a directory: {root}")
    for opt in ("--runtime-manifest", "--opencode-json"):
        for spec in getattr(a, opt[2:].replace("-", "_")):
            label, _, path = spec.partition("=")
            if not Path(path).is_file():
                return _fail(f"{opt} {label}: not a file: {path}")

    res = ScanResult()
    for spec in a.tree:
        label, _, root = spec.partition("=")
        rootp = Path(root)
        ts = scan_install_tree(label, str(rootp), _read_texts("package.json", rootp))
        res.trees.append(ts)
        res.native_binaries.extend(inventory_native_binaries(label, rootp))

    def _tree_for(label: str, root: str) -> TreeScan:
        for t in res.trees:
            if t.tree == label:
                return t
        ts = TreeScan(tree=label, root=root)
        res.trees.append(ts)
        return ts

    for spec in a.runtime_manifest:
        label, _, path = spec.partition("=")
        pth = Path(path)
        _tree_for(label, str(pth.parent)).floating += \
            scan_runtime_manifest(label, str(pth), pth.read_text(encoding="utf-8", errors="ignore"))
    for spec in a.opencode_json:
        label, _, path = spec.partition("=")
        pth = Path(path)
        _tree_for(label, str(pth.parent)).floating += \
            scan_opencode_json(label, str(pth), pth.read_text(encoding="utf-8", errors="ignore"))

    outdir = Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    write_scan_json(res, outdir / "scan.json")
    write_mechanical(res, outdir / "mechanical-scan.md")
    write_manifest(res, outdir / "sha256-manifest.txt")
    print(f"scanned {res.packages} package.json files across {len(res.trees)} trees -> {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
