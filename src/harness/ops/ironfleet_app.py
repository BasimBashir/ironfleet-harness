# src/harness/ops/ironfleet_app.py — the desktop app entry (one icon, everything up)
"""The exe the desktop icon launches: bring the local services up, seed the
admin once, serve the API with the LIVE worker, open the browser.

Everything repo-relative stays repo-tree-shaped: in the frozen onedir bundle the
convention `Path(__file__).parents[N] -> repo root` resolves to the app folder,
so `data/`, `web/dist` and `bin/` (opencode, llama-server, the rerank GGUF) sit
beside IronFleet.exe. What this module adds over `python -m harness.api serve`:

1. ollama on 11434 — spawned (windowless) if nothing answers; found via PATH or
   the OllamaSetup install dir. Left running on exit: it is a machine service,
   and its own installer already registers a login autostart.
2. llama-server on 8778 (rerank, PREREQUISITES.md §2: `--reranking --pooling
   rank` + the ggml-org qwen3-reranker GGUF) — spawned from the bundle, killed
   on clean exit (it is ours alone; a hard console close leaves it serving,
   harmless, and the next start reuses it).
3. opencode — the bundled standalone binary wins PATH, so shutil.which() in
   harness.substrate.run finds it without Node/npm on the machine.
4. admin seed — reuses harness.api.__main__.main(["seed-operator"]) verbatim
   (same mkdir fix, same HARNESS_OPERATOR_PASSWORD semantics); with no password
   env set, one is generated and printed ONCE, like dev_m8.
"""
from __future__ import annotations

import atexit
import os
import platform
import runpy
import secrets
import shutil
import socket
import string
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.request import urlopen

# Windowless child spawn is Windows-only; on macOS/Linux a non-zero creationflags
# raises ValueError (Python 3.13+), which would abort boot before the API starts.
_POPEN_KW: dict = (
    {"creationflags": 0x08000000} if platform.system() == "Windows" else {}
)
_IS_WIN = platform.system() == "Windows"
_LLAMA_BIN = "llama-server.exe" if _IS_WIN else "llama-server"
OLLAMA_URL = "http://127.0.0.1:11434"
RERANK_URL = "http://127.0.0.1:8778/models"
RERANK_MODEL = "qwen3-reranker-0.6b-q8_0.gguf"


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        # Windows onedir: IronFleet.exe sits beside data/, web/, bin/.
        # macOS .app: binary is Contents/MacOS/IronFleet, collected tree is
        # Contents/Frameworks (PyInstaller bootloader rule). Depth-2 modules
        # (harness/cli.py) resolve parents[2] → Contents, so runtime assets
        # (data/, web/, bin/, src/) are staged at Contents — return that root.
        p = Path(sys.executable).resolve().parent
        if sys.platform == "darwin" and p.name == "MacOS":
            return p.parent
        return p
    return Path(__file__).resolve().parents[3]      # unfrozen dev run: repo root


def _wait(url: str, timeout_s: float) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            urlopen(url, timeout=2).read(64)
            return True
        except Exception:
            time.sleep(1)
    return False


def _say(msg: str) -> None:
    print(msg, flush=True)


def _ollama_candidates() -> list[Path]:
    found: list[Path] = []
    which = shutil.which("ollama")
    if which:
        found.append(Path(which))
    if _IS_WIN:
        found.append(Path(os.environ.get("LOCALAPPDATA", ""))
                     / "Programs" / "Ollama" / "ollama.exe")
    else:
        found.append(Path("/Applications/Ollama.app/Contents/Resources/ollama"))
        found.append(Path.home() / "Applications" / "Ollama.app"
                     / "Contents" / "Resources" / "ollama")
    return found


def ensure_ollama() -> None:
    """Ollama up on 11434 — spawn `ollama serve` only if nothing answers."""
    if _wait(f"{OLLAMA_URL}/api/tags", 2):
        _say("[app] ollama already up on 11434")
        return
    exe = next((p for p in _ollama_candidates() if p.is_file()), None)
    if exe is None:
        _say("[app] WARN: ollama not found — install Ollama first; chat/embedding "
             "providers will be unreachable until it is running")
        return
    _say(f"[app] starting ollama ({exe})")
    subprocess.Popen([str(exe), "serve"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     **_POPEN_KW)
    if not _wait(f"{OLLAMA_URL}/api/tags", 60):
        _say("[app] WARN: ollama did not answer within 60s — continuing anyway")


_llama_proc: subprocess.Popen | None = None


def ensure_llama_server(app_dir: Path) -> subprocess.Popen | None:
    """llama-server on 8778 for the rerank class — spawned from the bundle."""
    global _llama_proc
    if _wait(RERANK_URL, 2):
        _say("[app] llama-server already up on 8778")
        return None
    exe = app_dir / "bin" / _LLAMA_BIN
    gguf = app_dir / "bin" / "models" / RERANK_MODEL
    if not exe.is_file() or not gguf.is_file():
        _say(f"[app] WARN: bundled llama-server/model missing — corpus rerank will "
             f"refuse (chat/drafting unaffected)")
        return None
    _say("[app] starting llama-server (rerank) on 8778")
    _llama_proc = subprocess.Popen(
        [str(exe), "-m", str(gguf), "--reranking", "--pooling", "rank",
         "--host", "127.0.0.1", "--port", "8778"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        **_POPEN_KW)
    if not _wait(RERANK_URL, 120):
        _say("[app] WARN: llama-server did not answer within 120s — continuing anyway")
    return _llama_proc


def stop_llama_server() -> None:
    if _llama_proc is not None and _llama_proc.poll() is None:
        _llama_proc.terminate()


def pick_port(preferred: int) -> int:
    for port in (preferred, preferred + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit(f"FAIL: both ports {preferred} and {preferred + 1} are taken")


def seed_admin_if_needed(root: Path) -> str | None:
    """First run: create admin. Returns the generated password, if we generated one."""
    from harness.service import system
    try:
        con = system.open_db(root)
        try:
            n = con.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        finally:
            con.close()
    except Exception:
        n = 0                       # no platform.db yet — seed below creates it
    if n:
        return None
    generated = None
    if not os.environ.get("HARNESS_OPERATOR_PASSWORD"):
        generated = "".join(secrets.choice(string.ascii_letters + string.digits)
                            for _ in range(14))
        os.environ["HARNESS_OPERATOR_PASSWORD"] = generated
    from harness.api import __main__ as api_main
    api_main.main(["seed-operator"])
    return generated


def _want_desktop_window() -> bool:
    """Native desktop window (WKWebView / WebView2) unless explicitly forced to browser."""
    if os.environ.get("IRONFLEET_USE_BROWSER", "").strip() in ("1", "true", "yes"):
        return False
    try:
        import webview  # noqa: F401
        return True
    except ImportError:
        return False


def _run_api_server(server) -> None:
    server.run()


def main() -> int:
    from harness.paths import resolve_store_root

    app_dir = _app_dir()
    bindir = app_dir / "bin"
    if bindir.is_dir():                               # bundled opencode wins PATH
        os.environ["PATH"] = f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"

    root, source = resolve_store_root()
    _say(f"=== IronFleet === store {root} (source: {source})")

    ensure_ollama()
    ensure_llama_server(app_dir)
    atexit.register(stop_llama_server)

    generated = seed_admin_if_needed(root)
    if generated:
        _say("")
        _say(f"  Your administrator password (shown once — copy it now): {generated}")
        _say("")

    port = pick_port(8765)
    url = f"http://127.0.0.1:{port}"

    from uvicorn import Config, Server
    from harness.api.app import create_app
    web_dist = app_dir / "web" / "dist"
    app = create_app(root, web_dist=str(web_dist) if (web_dist / "index.html").is_file() else None,
                     worker="live")
    server = Server(Config(app, host="127.0.0.1", port=port, log_level="warning"))

    use_window = _want_desktop_window()
    if use_window:
        # Desktop shell: API on a background thread; native window on the main
        # thread (required on macOS). Closing the window stops the server.
        _say(f"[app] serving on {url} — opening desktop window")
        api_thread = threading.Thread(target=_run_api_server, args=(server,), daemon=True)
        api_thread.start()
        if not _wait(f"{url}/healthz", 90):
            _say("[app] WARN: API did not become ready within 90s")
        try:
            import webview
            webview.create_window(
                "IronFleet",
                url,
                width=1440,
                height=900,
                min_size=(1024, 700),
            )
            webview.start()
        except Exception as ex:
            _say(f"[app] WARN: desktop window failed ({ex}) — falling back to browser")
            webbrowser.open(url)
            try:
                api_thread.join()
            except KeyboardInterrupt:
                pass
        finally:
            server.should_exit = True
            stop_llama_server()
        return 0

    def _open_browser() -> None:
        if _wait(f"{url}/healthz", 90):
            _say(f"[app] ready — opening browser {url}")
            webbrowser.open(url)

    threading.Thread(target=_open_browser, daemon=True).start()
    _say(f"[app] serving on {url} (Ctrl+C or close this window to stop)")
    try:
        server.run()
    finally:
        stop_llama_server()
    return 0


def run_dash_c(argv: list[str]) -> bool:
    """Frozen, sys.executable IS this exe, so children spawned as `exe -c code`
    (ingest_generic's parse child), `exe -m pkg.mod` (the module_e tools shim) or
    `exe script.py` (module_e guard_cli) must act as python, not relaunch the app."""
    if len(argv) < 2:
        return False
    a1 = argv[1]
    if a1 == "-c" and len(argv) >= 3:
        sys.argv = ["-c", *argv[3:]]
        exec(compile(argv[2], "<string>", "exec"), {"__name__": "__main__"})
        return True
    if a1 == "-m" and len(argv) >= 3:
        sys.argv = argv[2:]
        runpy.run_module(argv[2], run_name="__main__", alter_sys=True)
        return True
    if a1.lower().endswith(".py") and Path(a1).is_file():
        sys.argv = argv[1:]
        code = Path(a1).read_text(encoding="utf-8")
        exec(compile(code, a1, "exec"), {"__name__": "__main__", "__file__": a1})
        return True
    return False


if __name__ == "__main__":
    sys.exit(0 if run_dash_c(sys.argv) else main())
