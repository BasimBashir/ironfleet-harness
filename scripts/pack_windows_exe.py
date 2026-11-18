# scripts/pack_windows_exe.py - build dist/IronFleet: frozen app + data + web + bin
"""One command: python scripts/pack_windows_exe.py [--no-download]

Produces the self-contained app folder the installer packages:

    dist/IronFleet/
      IronFleet.exe + _internal/   frozen app (src/harness/ops/ironfleet_app.py)
      data/                        repo data/ tree (providers.yaml etc.)
      web/dist/                    the built React client
      bin/                         opencode.exe, llama-server.exe + DLLs, models/*.gguf

Downloads (cached under build/vendor/, skipped with --no-download):
  opencode v1.18.25 standalone  - the pin install_windows.ps1 enforces
  llama.cpp win-cpu-x64         - llama-server.exe + its DLLs
  ggml-org Qwen3-Reranker q8_0  - the rerank model (PREREQUISITES.md section 2)

Frozen harness modules live at _internal/harness/..., so depth-2 modules'
parents[2] resolves to _internal while depth-3 modules' parents[3] resolves to
the app root - data/ is staged at BOTH roots so every convention holds.
"""
from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DIST = REPO / "dist" / "IronFleet"
VENDOR = REPO / "build" / "vendor"

OPENCODE_TAG = "v1.18.25"
OPENCODE_ASSET = "opencode-windows-x64.zip"
LLAMACPP_TAG = "b12317"
LLAMACPP_ASSET = "llama-b12317-bin-win-cpu-x64.zip"
GGUF_REPO = "ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF"
GGUF_NAME = "qwen3-reranker-0.6b-q8_0.gguf"

HIDDEN = [
    "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets.auto", "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.protocols.websockets.websockets_impl", "uvicorn.lifespan.on",
    "uvicorn.lifespan.off", "anyio._backends._asyncio",
    "harness.api.__main__",
]

PYINSTALLER_ARGS = [
    "--noconfirm", "--clean", "--name", "IronFleet", "--icon",
    str(REPO / "scripts" / "ironfleet.ico"),
    "--paths", str(REPO / "src"),
    "--add-data", f"{REPO / 'src/harness/module_e/vendored/data'};harness/module_e/vendored/data",
    "--collect-all", "sqlite_vec",   # vec0.dll: the D4 hard dependency, invisible to import analysis
    # the guard_cli / tools-shim children import harness modules the app never imports
    # (guard_port missing = every opencode tool call blocked, 2026-11-12)
    "--collect-submodules", "harness",
    "--contents-directory", "_internal",
    "--distpath", str(REPO / "dist"), "--workpath", str(REPO / "build" / "pyinstaller"),
    "--specpath", str(REPO / "build" / "pyinstaller"),
    *sum([["--hidden-import", h] for h in HIDDEN], []),
    str(REPO / "src/harness/ops/ironfleet_app.py"),
]

def log(msg: str) -> None:
    print(msg, flush=True)

def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        log(f"  cached: {dest.name} ({dest.stat().st_size // (1024*1024)} MB)")
        return dest
    log(f"  downloading {url}")
    tmp = dest.parent / (dest.name + ".part")
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.rename(dest)
    log(f"  downloaded {dest.name} ({dest.stat().st_size // (1024*1024)} MB)")
    return dest

def extract_zip(zip_path: Path, into: Path) -> Path:
    """Extract into its own dir; zip-slip guard (archives are untrusted input)."""
    into.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as z:
        for info in z.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in Path(name).parts:
                raise SystemExit("FAIL: unsafe zip entry: " + info.filename)
            target = into / name
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as s, open(target, "wb") as f:
                    shutil.copyfileobj(s, f)
    return into

def stage_bin() -> None:
    """bin/: opencode.exe, llama-server + DLL siblings, models GGUF."""
    bin_dir = DIST / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    # Fail, never WARN: v1.0.0 shipped with no bin/ and fresh boxes fell back to
    # a stale global opencode and no rerank server (2026-11-17 Win11 test).
    oc = next((VENDOR / "opencode").rglob("opencode.exe"), None)
    if oc is None:
        raise SystemExit("FAIL: opencode.exe not in build/vendor - run once without --no-download")
    shutil.copy2(oc, bin_dir / "opencode.exe")
    log("  bin/opencode.exe staged")

    server = next(iter((VENDOR / "llamacpp").rglob("llama-server.exe")), None)
    if server is None:
        raise SystemExit("FAIL: llama-server.exe not in build/vendor - run once without --no-download")
    shutil.copy2(server, bin_dir / "llama-server.exe")
    dlls = list(server.parent.glob("*.dll"))
    for dll in dlls:
        shutil.copy2(dll, bin_dir / dll.name)
    log(f"  bin/llama-server.exe + {len(dlls)} DLLs staged")

    gguf_src = VENDOR / "gguf" / GGUF_NAME
    gguf_dst = bin_dir / "models" / GGUF_NAME
    gguf_dst.parent.mkdir(parents=True, exist_ok=True)
    if not gguf_src.is_file():
        raise SystemExit(f"FAIL: {GGUF_NAME} not in build/vendor - run once without --no-download")
    shutil.copy2(gguf_src, gguf_dst)
    log(f"  bin/models/{GGUF_NAME} staged")

# data/ entries the frozen app actually reads at runtime (all other data/ trees -
# the 2.2 GB eval corpora, golden_cases, opencode-audit - are dev-only and stay out).
DATA_KEEP = ["providers.yaml", "routing-a1.yaml", "module-e", "opencode-a1",
             "corpus", "eval/corpus_tool_trace.sqlite3"]

def stage() -> None:
    """Repo-tree staging onto the frozen layout (data/ at both roots, web/dist at root)."""
    log("staging runtime data/ (whitelist) and web/dist onto the frozen layout")
    if (REPO / "data").is_dir():
        for root in (DIST, DIST / "_internal"):
            for entry in DATA_KEEP:
                src = REPO / "data" / entry
                dst = root / "data" / entry
                if src.is_dir():
                    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"),
                                    dirs_exist_ok=True)
                elif src.is_file():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    if dst.suffix == ".sqlite3":
                        # ship the schema only: the dev box's dispatch log (matter refs,
                        # models, errors) is not the user's
                        con = sqlite3.connect(dst)
                        for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                            con.execute(f"DELETE FROM [{t}]")
                        con.commit()
                        con.execute("VACUUM")
                        con.close()
    web_src = REPO / "web" / "dist"
    web_dst = DIST / "web" / "dist"
    if web_src.is_dir():
        shutil.copytree(web_src, web_dst, dirs_exist_ok=True)
        log(f"  web/dist staged ({sum(1 for _ in web_dst.rglob('*'))} files)")
    # The mount renders plugins from ROOT/src templates (mount.py GUARD_TEMPLATE,
    # TOOLS_TEMPLATE, GUARD_CLI) — frozen ROOT is the app folder, so stage them at
    # the app-root src/ layout the dev tree has.
    for rel in ("harness/module_e/ironfleet-guard-s7c.ts",
                "harness/module_e/guard_cli.py",
                "harness/substrate/ironfleet-tools.ts"):
        src = REPO / "src" / rel
        dst = DIST / "src" / rel
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    log("  src/ mount templates staged (guard ts, guard_cli.py, tools ts)")

def build() -> None:
    log("building the frozen app with PyInstaller (a few minutes)")
    r = subprocess.run([sys.executable, "-m", "PyInstaller"] + PYINSTALLER_ARGS, cwd=REPO)
    if r.returncode != 0:
        raise SystemExit("FAIL: PyInstaller exited " + str(r.returncode))

def vendor() -> None:
    log("== vendor downloads ==")
    oc_base = "https://github.com/sst/opencode/releases/download/" + OPENCODE_TAG
    download(oc_base + "/" + OPENCODE_ASSET, VENDOR / "opencode" / OPENCODE_ASSET)
    extract_zip(VENDOR / "opencode" / OPENCODE_ASSET, VENDOR / "opencode" / "x")
    ll_base = "https://github.com/ggml-org/llama.cpp/releases/download/" + LLAMACPP_TAG
    download(ll_base + "/" + LLAMACPP_ASSET, VENDOR / "llamacpp" / LLAMACPP_ASSET)
    extract_zip(VENDOR / "llamacpp" / LLAMACPP_ASSET, VENDOR / "llamacpp" / "x")
    download("https://huggingface.co/" + GGUF_REPO + "/resolve/main/" + GGUF_NAME,
             VENDOR / "gguf" / GGUF_NAME)

def main() -> int:
    dl = "--no-download" not in sys.argv
    if "--stage-only" in sys.argv:
        stage()
        stage_bin()
        log("DONE: re-staged dist/IronFleet")
        return 0
    if dl:
        vendor()
    build()          # PyInstaller wipes dist/IronFleet, so bin/ is re-staged every time
    stage()
    stage_bin()
    log("DONE: dist/IronFleet")
    return 0

if __name__ == "__main__":
    sys.exit(main())
