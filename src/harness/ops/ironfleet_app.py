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

CREATE_NO_WINDOW = 0x08000000          # windowless child on Windows
OLLAMA_URL = "http://127.0.0.1:11434"
RERANK_URL = "http://127.0.0.1:8778/models"
RERANK_MODEL = "qwen3-reranker-0.6b-q8_0.gguf"


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
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


def ensure_ollama() -> None:
    """Ollama up on 11434 — spawn `ollama serve` only if nothing answers."""
    if _wait(f"{OLLAMA_URL}/api/tags", 2):
        _say("[app] ollama already up on 11434")
        return
    exe = shutil.which("ollama") or str(
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe")
    if not Path(exe).is_file():
        _say("[app] WARN: ollama not found — install Ollama first; chat/embedding "
             "providers will be unreachable until it is running")
        return
    _say(f"[app] starting ollama ({exe})")
    subprocess.Popen([exe, "serve"], creationflags=CREATE_NO_WINDOW,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not _wait(f"{OLLAMA_URL}/api/tags", 60):
        _say("[app] WARN: ollama did not answer within 60s — continuing anyway")


_llama_proc: subprocess.Popen | None = None


def ensure_llama_server(app_dir: Path) -> subprocess.Popen | None:
    """llama-server on 8778 for the rerank class — spawned from the bundle."""
    global _llama_proc
    if _wait(RERANK_URL, 2):
        _say("[app] llama-server already up on 8778")
        return None
    exe = app_dir / "bin" / "llama-server.exe"
    gguf = app_dir / "bin" / "models" / RERANK_MODEL
    if not exe.is_file() or not gguf.is_file():
        _say(f"[app] WARN: bundled llama-server/model missing — corpus rerank will "
             f"refuse (chat/drafting unaffected)")
        return None
    _say("[app] starting llama-server (rerank) on 8778")
    _llama_proc = subprocess.Popen(
        [str(exe), "-m", str(gguf), "--reranking", "--pooling", "rank",
         "--host", "127.0.0.1", "--port", "8778"],
        creationflags=CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

    def _open_browser() -> None:
        if _wait(f"{url}/healthz", 90):
            _say(f"[app] ready — opening {url}")
            webbrowser.open(url)

    threading.Thread(target=_open_browser, daemon=True).start()
    _say(f"[app] serving on {url} (Ctrl+C or close this window to stop)")
    try:
        Server(Config(app, host="127.0.0.1", port=port, log_level="warning")).run()
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
