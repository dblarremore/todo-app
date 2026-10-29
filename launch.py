#!/usr/bin/env python3
"""Start Todo on its designated host, or open that host from another Mac."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
HOST = os.environ.get("TODO_HOST", "a414").lower()
PORT = 8765
HTTPS_PORT = 8443
LOCAL = f"http://127.0.0.1:{PORT}"
LOG = Path.home() / "Library/Logs/todo-app.log"


def run(args, timeout=15):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or
                           f"Command failed: {args[0]}")
    return result.stdout


def health(url):
    try:
        return json.loads(run(["/usr/bin/curl", "--noproxy", "*", "--fail",
                               "--silent", "--show-error", "--max-time", "5",
                               url + "/api/health"], timeout=7))
    except (RuntimeError, ValueError, subprocess.TimeoutExpired):
        return {}


def local_server():
    info = health(LOCAL)
    if info.get("app") == "todo" and info.get("directory") == str(HERE):
        return info
    with socket.socket() as sock:
        sock.settimeout(1)
        occupied = sock.connect_ex(("127.0.0.1", PORT)) == 0
    if occupied:
        raise RuntimeError(f"Port {PORT} belongs to another server (possibly the "
                           "old Dropbox copy). Stop that server before launching this copy.")
    return None


def start_server():
    if local_server():
        return
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as log:
        process = subprocess.Popen([sys.executable, "-u", str(HERE / "todo.py"),
                                    "--no-open"], cwd=HERE, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=log, start_new_session=True)
    for _ in range(50):
        info = health(LOCAL)
        if info.get("app") == "todo" and info.get("directory") == str(HERE):
            return
        if process.poll() is not None:
            break
        time.sleep(0.1)
    raise RuntimeError(f"Todo did not start. See {LOG}")


def check_serve_config(config, address):
    """Never replace an unrelated service or reuse a publicly exposed port."""
    if config.get("AllowFunnel", {}).get(address):
        raise RuntimeError(f"{address} is exposed through Funnel. Disable Funnel "
                           "on this port before using it for Todo.")
    tcp = config.get("TCP", {}).get(str(HTTPS_PORT))
    if tcp and tcp != {"HTTPS": True}:
        raise RuntimeError(f"Tailscale port {HTTPS_PORT} is used by another service.")
    for name, site in config.get("Web", {}).items():
        if name.endswith(f":{HTTPS_PORT}"):
            if name != address or site.get("Handlers") != {"/": {"Proxy": LOCAL}}:
                raise RuntimeError(f"Tailscale port {HTTPS_PORT} already serves "
                                   "another app; its configuration was preserved.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-open", action="store_true", help="start without opening a browser")
    parser.add_argument("--stop", action="store_true", help="stop this folder's local server")
    args = parser.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    # Serialize double-clicks; the OS releases the lock even after a crash.
    with (LOG.parent / "todo-app-launch.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.stop:
            info = local_server()
            if info:
                os.kill(info["pid"], signal.SIGTERM)
                print("Todo stopped. Its Tailscale route remains configured.")
            else:
                print("Todo is not running in this folder.")
            return

        tailscale = shutil.which("tailscale")
        bundled = Path("/Applications/Tailscale.app/Contents/MacOS/tailscale")
        if not tailscale and bundled.exists():
            tailscale = str(bundled)
        if not tailscale:
            raise RuntimeError("Install Tailscale and connect this Mac to your tailnet first.")
        status = json.loads(run([tailscale, "status", "--json"]))
        if status.get("BackendState") != "Running" or not status.get("Self", {}).get("Online"):
            raise RuntimeError("Tailscale is disconnected. Connect or sign in in the Tailscale app, then retry.")
        suffix = status.get("CurrentTailnet", {}).get("MagicDNSSuffix")
        if not suffix:
            raise RuntimeError("Tailscale did not report a tailnet DNS suffix.")
        host_dns = f"{HOST}.{suffix}"
        url = f"https://{host_dns}:{HTTPS_PORT}"
        self_dns = status.get("Self", {}).get("DNSName", "").rstrip(".").lower()
        if self_dns == host_dns.lower():
            config = json.loads(run([tailscale, "serve", "status", "--json"]))
            check_serve_config(config, f"{host_dns}:{HTTPS_PORT}")
            start_server()
            print("Configuring private Tailscale access…", flush=True)
            run([tailscale, "serve", "--bg", f"--https={HTTPS_PORT}", LOCAL], timeout=45)
        else:
            print(f"Opening Todo hosted on {HOST}; no local server will be started.", flush=True)
        if health(url).get("app") != "todo":
            raise RuntimeError(f"Cannot reach Todo at {url}. Make sure {HOST} is "
                               "awake, connected to Tailscale, and running Todo. "
                               "Check Tailscale HTTPS setup and access rules if needed.")
        print(f"Todo → {url}", flush=True)
        if not args.no_open:
            subprocess.run(["/usr/bin/open", url], check=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Todo: {exc}", file=sys.stderr)
        sys.exit(1)
