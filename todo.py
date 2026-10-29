#!/usr/bin/env python3
"""Local todo server.

Serves app.html and owns all writes to data.json, keeping rolling timestamped
backups as it goes.

    python3 todo.py            # start + open browser
    python3 todo.py --no-open  # start only
"""
import json
import os
import shutil
import sys
import threading
import webbrowser
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data.json"
APP = HERE / "app.html"
BACKUPS = HERE / "backups"

DEFAULT_PORT = 8765
BACKUP_INTERVAL = 300      # seconds between rolling backups
BACKUP_KEEP = 200          # how many backup files to retain

_lock = threading.RLock()  # reentrant: the conflict check and the save share it
_last_backup = 0.0


def empty_data():
    return {
        "version": 1,
        "updated": uuid.uuid4().hex,
        "projects": [{"id": "p-inbox", "name": "Inbox", "color": "#6366f1"}],
        "tasks": [],
    }


def read_data():
    if not DATA.exists():
        return empty_data()
    try:
        return json.loads(DATA.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return empty_data()


def write_atomic(path, text):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def rotate_backup():
    """Snapshot the current data.json, at most once per BACKUP_INTERVAL."""
    global _last_backup
    import time

    if not DATA.exists():
        return
    now = time.time()
    if now - _last_backup < BACKUP_INTERVAL:
        return
    _last_backup = now
    BACKUPS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(DATA, BACKUPS / f"data-{stamp}.json")
    snaps = sorted(BACKUPS.glob("data-*.json"))
    for old in snaps[:-BACKUP_KEEP]:
        old.unlink(missing_ok=True)


def conflict_files():
    """Dropbox forks a file into '… (X's conflicted copy 2026-01-01).ext' when two
    machines write it at once. The app would never notice on its own, so surface it."""
    found = []
    for base in (HERE, BACKUPS):
        if not base.exists():
            continue
        for f in base.iterdir():
            if "conflicted copy" in f.name.lower():
                found.append(f.name)
    return sorted(found)


def save_data(data):
    with _lock:
        rotate_backup()
        data["updated"] = uuid.uuid4().hex
        write_atomic(DATA, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return data["updated"]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if "/api/" in (self.path or ""):
            return
        sys.stderr.write("  %s\n" % (fmt % args))

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html", "/app.html"):
            if not APP.exists():
                return self._send(500, b"app.html is missing")
            return self._send(200, APP.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/data":
            body = json.dumps(read_data(), ensure_ascii=False).encode("utf-8")
            return self._send(200, body, "application/json; charset=utf-8")
        if path == "/api/health":
            body = json.dumps({"app": "todo", "directory": str(HERE),
                               "pid": os.getpid(), "conflicts": conflict_files()}).encode("utf-8")
            return self._send(200, body, "application/json; charset=utf-8")
        if path == "/api/backups":
            BACKUPS.mkdir(exist_ok=True)
            names = sorted((p.name for p in BACKUPS.glob("data-*.json")), reverse=True)
            body = json.dumps(names[:50]).encode("utf-8")
            return self._send(200, body, "application/json; charset=utf-8")
        return self._send(404, b"not found")

    def do_PUT(self):
        if self.path.split("?")[0] != "/api/data":
            return self._send(404, b"not found")
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict) or "tasks" not in payload:
                raise ValueError("payload must be an object with a tasks array")
        except (ValueError, json.JSONDecodeError) as exc:
            return self._send(400, str(exc).encode("utf-8"))

        # A browser PUTs the whole document, so a stale tab would silently wipe
        # newer work that arrived from another machine. Refuse the write when the
        # file on disk has moved on from what this tab last read.
        base = self.headers.get("X-Base-Updated")
        with _lock:
            current = read_data()
            live = current.get("updated")
            if base and live and base != live:
                body = json.dumps({"conflict": True, "updated": live,
                                   "data": current}, ensure_ascii=False).encode("utf-8")
                return self._send(409, body, "application/json; charset=utf-8")
            updated = save_data(payload)

        body = json.dumps({"ok": True, "updated": updated}).encode("utf-8")
        return self._send(200, body, "application/json; charset=utf-8")


def main():
    open_browser = "--no-open" not in sys.argv

    # A fixed port keeps the Tailscale route and bookmarks pointed at this server.
    port = DEFAULT_PORT
    url = f"http://127.0.0.1:{port}/"
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as exc:
        raise SystemExit(f"Cannot listen on {url}: {exc}")

    if not DATA.exists():
        save_data(empty_data())

    print(f"\n  todo  →  {url}")
    print(f"  data  →  {DATA}")
    print("  quit  →  control-C\n")

    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped\n")


if __name__ == "__main__":
    main()
