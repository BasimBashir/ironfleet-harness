from __future__ import annotations

import hashlib
import json
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
    return s[0] in "^~" or s.startswith(">=")


def _npm_spec(npm: str) -> str:
    rest = npm[1:] if npm.startswith("@") else npm
    _, _, spec = rest.partition("@")
    return spec


def scan_runtime_manifest(tree: str, path: str, text: str) -> list[FloatingRange]:
    try:
        doc = json.loads(text)
    except ValueError:
        return []
    out: list[FloatingRange] = []
    for field in DEP_FIELDS:
        for name, spec in (doc.get(field) or {}).items():
            if is_floating(str(spec)):
                out.append(FloatingRange(tree=tree, file=path,
                                         field=f"{field}.{name}", spec=str(spec)))
    return out


def scan_opencode_json(tree: str, path: str, text: str) -> list[FloatingRange]:
    try:
        doc = json.loads(text)
    except ValueError:
        return []
    out: list[FloatingRange] = []
    for pid, prov in (doc.get("provider") or {}).items():
        npm = prov.get("npm") if isinstance(prov, dict) else None
        if isinstance(npm, str):
            spec = _npm_spec(npm)
            if is_floating(spec):
                out.append(FloatingRange(tree=tree, file=path,
                                         field=f"provider.{pid}.npm",
                                         spec=spec or "(none)"))
    return out
