# scripts/pack_macos_app.py — build IronFleet.app + IronFleet.dmg (macOS 1.0.1 parity)
"""One command: python scripts/pack_macos_app.py [--no-download] [--out DIR]

Produces a self-contained macOS app (Windows pack_windows_exe.py twin):

    dist/IronFleet.app/Contents/
      Info.plist
      MacOS/IronFleet            frozen app binary (ironfleet_app.py)
      data/  web/dist/  bin/ src/   runtime assets (_app_dir = Contents/)
      Frameworks/                PyInstaller collected tree (+ data/ twin)

Then packs dist/IronFleet.app into a UDZO DMG (+ .sha256). Default out dir is
repo dist/; pass --out to land the installer elsewhere (e.g. ironfleet-harness-osx).

Pins (match Windows 1.0.1):
  opencode v1.18.25 darwin-arm64/x64
  llama.cpp b12317 macos-arm64/x64
  ggml-org Qwen3-Reranker q8_0 GGUF
"""
from __future__ import annotations

import argparse
import platform
import plistlib
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DIST_APP = REPO / "dist" / "IronFleet.app"
CONTENTS = DIST_APP / "Contents"
MACOS_DIR = CONTENTS / "MacOS"
# PyInstaller's macOS .app bootloader looks for the collected tree in
# Contents/Frameworks (not MacOS/_internal) once the binary lives under
# Contents/MacOS — see PYI "Failed to load Python shared library .../Frameworks/Python".
FRAMEWORKS_DIR = CONTENTS / "Frameworks"
VENDOR = REPO / "build" / "vendor-macos"

OPENCODE_TAG = "v1.18.25"
LLAMACPP_TAG = "b12317"
GGUF_REPO = "ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF"
GGUF_NAME = "qwen3-reranker-0.6b-q8_0.gguf"

BUNDLE_ID = "ai.ironfleet.harness"
APP_VERSION = "1.0.2"

HIDDEN = [
    "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets.auto", "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.protocols.websockets.websockets_impl", "uvicorn.lifespan.on",
    "uvicorn.lifespan.off", "anyio._backends._asyncio",
    "harness.api.__main__",
]

DATA_KEEP = ["providers.yaml", "routing-a1.yaml", "module-e", "opencode-a1",
             "corpus", "eval/corpus_tool_trace.sqlite3"]


def log(msg: str) -> None:
    print(msg, flush=True)


def _arch() -> str:
    m = platform.machine().lower()
    if m in ("arm64", "aarch64"):
        return "arm64"
    if m in ("x86_64", "amd64"):
        return "x64"
    raise SystemExit(f"FAIL: unsupported macOS arch {m!r}")


def _opencode_asset() -> str:
    return f"opencode-darwin-{_arch()}.zip"


def _llamacpp_asset() -> str:
    # llama.cpp ships macOS builds as .tar.gz (not zip), arm64 or x64.
    return f"llama-{LLAMACPP_TAG}-bin-macos-{_arch()}.tar.gz"


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        log(f"  cached: {dest.name} ({dest.stat().st_size // (1024 * 1024)} MB)")
        return dest
    log(f"  downloading {url}")
    tmp = dest.parent / (dest.name + ".part")
    # Prefer curl: system certs on macOS; urllib often fails CERTIFICATE_VERIFY_FAILED
    # against the python.org framework install.
    curl = shutil.which("curl")
    if curl:
        r = subprocess.run(
            [curl, "-fL", "--retry", "3", "--connect-timeout", "30",
             "-o", str(tmp), url],
            capture_output=True, text=True)
        if r.returncode != 0:
            tmp.unlink(missing_ok=True)
            raise SystemExit(f"FAIL: curl download {url}: {r.stderr.strip() or r.stdout.strip()}")
    else:
        with urllib.request.urlopen(url, timeout=180) as resp, open(tmp, "wb") as f:
            while chunk := resp.read(1 << 20):
                f.write(chunk)
    tmp.rename(dest)
    log(f"  downloaded {dest.name} ({dest.stat().st_size // (1024 * 1024)} MB)")
    return dest


def extract_zip(zip_path: Path, into: Path) -> Path:
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


def extract_tar(tar_path: Path, into: Path) -> Path:
    into.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "r:*") as t:
        for m in t.getmembers():
            name = m.name.replace("\\", "/")
            if name.startswith("/") or ".." in Path(name).parts:
                raise SystemExit("FAIL: unsafe tar entry: " + m.name)
        t.extractall(into, filter="data")
    return into


def vendor() -> None:
    log("== vendor downloads (macOS) ==")
    oc = _opencode_asset()
    oc_base = "https://github.com/sst/opencode/releases/download/" + OPENCODE_TAG
    download(oc_base + "/" + oc, VENDOR / "opencode" / oc)
    extract_zip(VENDOR / "opencode" / oc, VENDOR / "opencode" / "x")

    ll = _llamacpp_asset()
    ll_base = "https://github.com/ggml-org/llama.cpp/releases/download/" + LLAMACPP_TAG
    download(ll_base + "/" + ll, VENDOR / "llamacpp" / ll)
    extract_tar(VENDOR / "llamacpp" / ll, VENDOR / "llamacpp" / "x")

    download("https://huggingface.co/" + GGUF_REPO + "/resolve/main/" + GGUF_NAME,
             VENDOR / "gguf" / GGUF_NAME)


def stage_bin() -> None:
    """bin/: opencode, llama-server + dylib siblings, models GGUF."""
    bin_dir = CONTENTS / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    oc = next((p for p in (VENDOR / "opencode").rglob("opencode") if p.is_file()), None)
    if oc is None:
        raise SystemExit("FAIL: opencode not in build/vendor-macos — run once without --no-download")
    dst = bin_dir / "opencode"
    shutil.copy2(oc, dst)
    dst.chmod(dst.stat().st_mode | 0o111)
    log("  bin/opencode staged")

    server = next(iter((VENDOR / "llamacpp").rglob("llama-server")), None)
    if server is None or not server.is_file():
        raise SystemExit("FAIL: llama-server not in build/vendor-macos — run once without --no-download")
    shutil.copy2(server, bin_dir / "llama-server")
    (bin_dir / "llama-server").chmod((bin_dir / "llama-server").stat().st_mode | 0o111)
    # Sibling shared libs next to the binary (install_name / rpath).
    n_libs = 0
    for pat in ("*.dylib", "*.so"):
        for lib in server.parent.glob(pat):
            shutil.copy2(lib, bin_dir / lib.name)
            n_libs += 1
    log(f"  bin/llama-server + {n_libs} shared libs staged")

    gguf_src = VENDOR / "gguf" / GGUF_NAME
    gguf_dst = bin_dir / "models" / GGUF_NAME
    gguf_dst.parent.mkdir(parents=True, exist_ok=True)
    if not gguf_src.is_file():
        raise SystemExit(f"FAIL: {GGUF_NAME} not in build/vendor-macos — run once without --no-download")
    shutil.copy2(gguf_src, gguf_dst)
    log(f"  bin/models/{GGUF_NAME} staged")


def stage() -> None:
    """Repo-tree staging onto the frozen layout (data/ at Contents + Frameworks).

    Dual data/ roots match Windows (app root + _internal): depth-2 modules resolve
    to Contents/, while PyInstaller-collected depth under Frameworks needs its twin.
    """
    log("staging runtime data/ (whitelist) and web/dist onto Contents/")
    if not (REPO / "data").is_dir():
        raise SystemExit("FAIL: repo data/ missing")
    # data/eval/ is gitignored; ensure an empty tool-trace schema exists for staging.
    trace_src = REPO / "data" / "eval" / "corpus_tool_trace.sqlite3"
    if not trace_src.is_file():
        sys.path.insert(0, str(REPO / "src"))
        from harness.trace import TraceStore  # noqa: WPS433 — packer-only seed
        TraceStore(trace_src)  # creates parent + empty dispatches schema
        log("  seeded empty data/eval/corpus_tool_trace.sqlite3 (gitignored on this box)")
    # Frameworks may not exist yet during --stage-only after a partial wipe; ensure it.
    FRAMEWORKS_DIR.mkdir(parents=True, exist_ok=True)
    for root in (CONTENTS, FRAMEWORKS_DIR):
        for entry in DATA_KEEP:
            src = REPO / "data" / entry
            dst = root / "data" / entry
            if not src.exists():
                raise SystemExit(f"FAIL: required data/{entry} missing in repo")
            if src.is_dir():
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"),
                                dirs_exist_ok=True)
            elif src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                if dst.suffix == ".sqlite3":
                    # Ship schema only — never the dev box dispatch/usage history.
                    # Flush WAL into the main file first: a bare copy2 of a WAL DB can
                    # leave an empty shell with no tables (TraceStore opens with WAL).
                    con = sqlite3.connect(dst)
                    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                        con.execute(f"DELETE FROM [{t}]")
                    con.commit()
                    con.execute("VACUUM")
                    tables = [t for (t,) in con.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'")]
                    con.close()
                    if "dispatches" not in tables:
                        raise SystemExit(
                            f"FAIL: {dst} has no dispatches table after empty-ship wipe"
                        )
                    # Drop leftover sidecars so the .app doesn't ship -wal/-shm.
                    for side in (dst.with_name(dst.name + "-wal"),
                                 dst.with_name(dst.name + "-shm")):
                        side.unlink(missing_ok=True)
    # v1.0.1 continue_loop_on_deny: without this, stages end [NO DELIVERABLE] after a refuse.
    for root in (CONTENTS, FRAMEWORKS_DIR):
        oc = root / "data" / "opencode-a1" / "opencode.json"
        text = oc.read_text(encoding="utf-8") if oc.is_file() else ""
        if "continue_loop_on_deny" not in text:
            raise SystemExit(
                f"FAIL: {oc} missing experimental.continue_loop_on_deny "
                "(build from c229380+ data/opencode-a1)"
            )
    log("  data/ whitelist staged at Contents/ and Frameworks/ (sqlite emptied)")

    web_src = REPO / "web" / "dist"
    web_dst = CONTENTS / "web" / "dist"
    if not (web_src / "index.html").is_file():
        raise SystemExit("FAIL: web/dist missing — run `cd web && npm ci && npm run build` first")
    shutil.copytree(web_src, web_dst, dirs_exist_ok=True)
    log(f"  web/dist staged ({sum(1 for _ in web_dst.rglob('*'))} files)")

    for rel in ("harness/module_e/ironfleet-guard-s7c.ts",
                "harness/module_e/guard_cli.py",
                "harness/substrate/ironfleet-tools.ts"):
        src = REPO / "src" / rel
        dst = CONTENTS / "src" / rel
        if not src.is_file():
            raise SystemExit(f"FAIL: mount template missing: src/{rel}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    log("  src/ mount templates staged (guard ts, guard_cli.py, tools ts)")


def install_app_icon() -> None:
    """Copy scripts/ironfleet.icns into Contents/Resources for Dock / Finder."""
    src = REPO / "scripts" / "ironfleet.icns"
    if not src.is_file():
        log(f"  WARN: missing app icon {src} — Dock will show the default executable glyph")
        return
    resources = CONTENTS / "Resources"
    resources.mkdir(parents=True, exist_ok=True)
    dest = resources / "AppIcon.icns"
    shutil.copy2(src, dest)
    log(f"  app icon staged ({dest.stat().st_size // 1024} KB)")


def write_info_plist() -> None:
    plist = {
        "CFBundleName": "IronFleet",
        "CFBundleDisplayName": "IronFleet",
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleVersion": APP_VERSION,
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundlePackageType": "APPL",
        "CFBundleExecutable": "IronFleet",
        "CFBundleIconFile": "AppIcon",
        "CFBundleInfoDictionaryVersion": "6.0",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "LSUIElement": False,
    }
    path = DIST_APP / "Contents" / "Info.plist"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(plist, fmt=plistlib.FMT_XML))
    log(f"  Info.plist written ({APP_VERSION})")


def build() -> None:
    """PyInstaller onedir into a staging folder, then move into the .app MacOS dir."""
    if platform.system() != "Darwin":
        raise SystemExit("FAIL: pack_macos_app.py must run on macOS (PyInstaller cannot cross-compile)")
    log("building the frozen app with PyInstaller (a few minutes)")
    stage_root = REPO / "dist" / "IronFleet-macos-stage"
    if stage_root.exists():
        shutil.rmtree(stage_root)
    args = [
        "--noconfirm", "--clean", "--name", "IronFleet",
        "--paths", str(REPO / "src"),
        "--add-data", f"{REPO / 'src/harness/module_e/vendored/data'}:harness/module_e/vendored/data",
        "--collect-all", "sqlite_vec",
        "--collect-all", "apsw",  # macOS python.org sqlite3 lacks enable_load_extension
        "--collect-all", "webview",  # native desktop window (WKWebView)
        "--collect-all", "keyring",  # macOS Keychain backend for NIM keys (fail.Keyring = 502)
        "--collect-submodules", "harness",
        "--hidden-import", "webview",
        "--hidden-import", "webview.platforms.cocoa",
        "--hidden-import", "keyring.backends.macOS",
        "--contents-directory", "_internal",
        "--distpath", str(stage_root.parent),
        "--workpath", str(REPO / "build" / "pyinstaller-macos"),
        "--specpath", str(REPO / "build" / "pyinstaller-macos"),
        *sum([["--hidden-import", h] for h in HIDDEN], []),
        str(REPO / "src/harness/ops/ironfleet_app.py"),
    ]
    # Force the onedir name so we know where PyInstaller lands it.
    r = subprocess.run([sys.executable, "-m", "PyInstaller", *args], cwd=REPO)
    if r.returncode != 0:
        raise SystemExit("FAIL: PyInstaller exited " + str(r.returncode))

    built = REPO / "dist" / "IronFleet"
    if not (built / "IronFleet").is_file():
        raise SystemExit(f"FAIL: expected PyInstaller binary at {built / 'IronFleet'}")

    if DIST_APP.exists():
        shutil.rmtree(DIST_APP)
    MACOS_DIR.mkdir(parents=True, exist_ok=True)
    # Binary stays in MacOS (Finder / launchd entry point). Collected tree goes to
    # Frameworks — required by the Darwin bootloader inside a .app bundle.
    binary = built / "IronFleet"
    shutil.move(str(binary), str(MACOS_DIR / "IronFleet"))
    internal = built / "_internal"
    if FRAMEWORKS_DIR.exists():
        shutil.rmtree(FRAMEWORKS_DIR)
    if internal.is_dir():
        shutil.move(str(internal), str(FRAMEWORKS_DIR))
    else:
        raise SystemExit("FAIL: PyInstaller did not emit _internal/")
    # Any leftover onedir siblings (rare) land next to the binary.
    for child in list(built.iterdir()):
        dest = MACOS_DIR / child.name
        if dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        shutil.move(str(child), str(dest))
    shutil.rmtree(built, ignore_errors=True)
    install_app_icon()
    write_info_plist()
    log(f"  staged app binary at {MACOS_DIR / 'IronFleet'}")
    log(f"  staged Frameworks at {FRAMEWORKS_DIR}")


def make_dmg(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    dmg = out_dir / f"IronFleet-{APP_VERSION}-mac.dmg"
    staging = out_dir / "_dmg_stage"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    shutil.copytree(DIST_APP, staging / "IronFleet.app", symlinks=True)
    # Applications symlink — standard drag-to-install UX.
    (staging / "Applications").symlink_to("/Applications")
    if dmg.exists():
        dmg.unlink()
    log(f"==> DMG {dmg}")
    r = subprocess.run([
        "hdiutil", "create",
        "-volname", "IronFleet",
        "-srcfolder", str(staging),
        "-ov", "-format", "UDZO",
        str(dmg),
    ], capture_output=True, text=True)
    shutil.rmtree(staging, ignore_errors=True)
    if r.returncode != 0:
        raise SystemExit(f"FAIL: hdiutil: {r.stderr.strip() or r.stdout.strip()}")
    # sha256 beside the artifact (unsigned release contract, M11).
    digest = subprocess.check_output(["shasum", "-a", "256", str(dmg)], text=True).split()[0]
    (out_dir / f"{dmg.name}.sha256").write_text(f"{digest}  {dmg.name}\n", encoding="utf-8")
    log(f"==> checksum: {digest}  {dmg.name}")
    return dmg


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-download", action="store_true",
                    help="reuse build/vendor-macos caches")
    ap.add_argument("--stage-only", action="store_true",
                    help="re-stage data/web/bin onto an existing .app")
    ap.add_argument("--out", type=Path, default=None,
                    help="directory for the DMG + .sha256 (default: repo dist/)")
    args = ap.parse_args(argv)

    out_dir = args.out.resolve() if args.out else (REPO / "dist")

    if args.stage_only:
        if not (MACOS_DIR / "IronFleet").is_file():
            raise SystemExit("FAIL: no existing IronFleet.app — run a full build first")
        stage()
        stage_bin()
        install_app_icon()
        write_info_plist()
        dmg = make_dmg(out_dir)
        log(f"DONE: {dmg}")
        return 0

    if not args.no_download:
        vendor()
    build()
    stage()
    stage_bin()
    dmg = make_dmg(out_dir)
    log(f"DONE: {dmg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
