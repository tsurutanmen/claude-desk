"""Claude Desk: one local endpoint the desktop wallpaper reads.

Collects what the Claude Code mods and the voice listener write under
~/.claude/session-dash/, plus the state of the homedot agents (when they run), into GET /state.
Listens on 127.0.0.1 only and answers only requests addressed to this PC.
"""
import hmac
import json
import os
import pathlib
import secrets
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("CLAUDE_DESK_PORT", "8795"))
HOME = pathlib.Path(os.environ.get("CLAUDE_DESK_DIR", pathlib.Path.home() / ".claude" / "session-dash"))
DOTS = {} if os.environ.get("CLAUDE_DESK_NO_DOTS") else {"self": 8790, "group": 8792}
SHOW_FOR_S = 3 * 60 * 60
HERE = pathlib.Path(__file__).parent
# Optional settings beside this file: {"wallpaper_engine_project": "<Wallpaper Engine's copy of wallpaper/>"}
SETTINGS = json.loads((HERE / "desk.config.json").read_text(encoding="utf-8")) if (HERE / "desk.config.json").exists() else {}
WE_PROJECT = pathlib.Path(SETTINGS["wallpaper_engine_project"]) if SETTINGS.get("wallpaper_engine_project") else None


def desk_key():
    """A secret the wallpaper sends with each read.

    The answer carries Access-Control-Allow-Origin: * (the wallpaper is a file:// page),
    so without a key any web page open in a browser could read it. The key goes to
    key.js beside the wallpaper's index.html: a local file, which no web page can read.
    """
    f = HOME / "desk.key"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(secrets.token_urlsafe(24), encoding="utf-8")
    key = f.read_text(encoding="utf-8").strip()
    for folder in (HERE / "wallpaper", WE_PROJECT):
        if folder and folder.exists():
            (folder / "key.js").write_text(f'window.DESK_KEY = "{key}";\n', encoding="utf-8")
    return key


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def sessions():
    now = time.time() * 1000
    out = []
    for f in (HOME / "sessions").glob("*.json"):
        s = read_json(f)
        if s and not s.get("isEnded") and now - s.get("at", 0) < SHOW_FOR_S * 1000:
            out.append(s)
    return sorted(out, key=lambda s: -s["at"])


def dots(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2) as r:
            st = json.loads(r.read())
    except Exception:
        return None
    running = [t for t in st.get("tasks", []) if t.get("status") == "running"]
    waiting = sum(1 for t in st.get("tasks", []) if t.get("status") == "pending")
    pending = [a for a in st.get("approvals", []) if a.get("status") == "pending"]
    return {
        "name": (st.get("dot") or {}).get("name", "ドット"),
        "status": st.get("status"),
        "paused": st.get("paused"),
        "running": [{"id": t["id"], "title": t.get("title")} for t in running[:5]],
        "waiting": waiting,
        "approvals": len(pending),
        "last": (st.get("activity") or [{}])[0].get("text") if st.get("activity") else None,
    }


def state():
    return {
        "at": time.time() * 1000,
        "sessions": sessions(),
        "today": (read_json(HOME / "today.json") or {}).get("line"),
        "limits": read_json(HOME / "limits.json", []),
        "wake": read_json(HOME / "wake.json"),
        "dots": {k: dots(p) for k, p in DOTS.items()},
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("Host", "") not in (f"127.0.0.1:{PORT}", f"localhost:{PORT}"):
            return self.send_error(403)
        url = urllib.parse.urlsplit(self.path)
        if url.path != "/state":
            return self.send_error(404)
        given = urllib.parse.parse_qs(url.query).get("k", [""])[0]
        if not KEY or not hmac.compare_digest(given, KEY):
            return self.send_error(403)
        data = json.dumps(state(), ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")  # the wallpaper is a file:// page
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


KEY = ""

if __name__ == "__main__":
    KEY = desk_key()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
