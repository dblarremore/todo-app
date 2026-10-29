"""Run with python3 -B -m unittest -v test_runtime."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import launch
import todo


class LauncherTests(unittest.TestCase):
    def test_existing_other_port_is_preserved(self):
        config = {"TCP": {"443": {"HTTPS": True}}, "Web": {
            "a414.example.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8080"}}}}}
        launch.check_serve_config(config, "a414.example.ts.net:8443")

    def test_existing_todo_route_is_reusable(self):
        address = "a414.example.ts.net:8443"
        config = {"TCP": {"8443": {"HTTPS": True}}, "Web": {
            address: {"Handlers": {"/": {"Proxy": launch.LOCAL}}}}}
        launch.check_serve_config(config, address)

    def test_other_app_on_same_port_is_refused(self):
        address = "a414.example.ts.net:8443"
        config = {"Web": {address: {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8080"}}}}}
        with self.assertRaises(RuntimeError):
            launch.check_serve_config(config, address)

    def test_public_funnel_is_refused(self):
        address = "a414.example.ts.net:8443"
        with self.assertRaises(RuntimeError):
            launch.check_serve_config({"AllowFunnel": {address: True}}, address)

    def exercise_launch(self, local, connected=True):
        status = {"BackendState": "Running" if connected else "Stopped",
                  "Self": {"Online": connected, "DNSName":
                           "a414.example.ts.net." if local else "m5bp.example.ts.net."},
                  "CurrentTailnet": {"MagicDNSSuffix": "example.ts.net"}}
        def command(args, **kwargs):
            if args[1:3] == ["status", "--json"]:
                return json.dumps(status)
            if args[1:4] == ["serve", "status", "--json"]:
                return "{}"
            return ""
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(launch, "HOST", "a414"), \
                patch.object(launch, "LOG", Path(directory) / "todo.log"), \
                patch.object(launch.shutil, "which", return_value="tailscale"), \
                patch.object(launch, "run", side_effect=command) as run, \
                patch.object(launch, "start_server") as start, \
                patch.object(launch, "health", return_value={"app": "todo"}), \
                patch.object(launch.subprocess, "run") as browser, \
                patch("sys.argv", ["launch.py"]), \
                contextlib.redirect_stdout(io.StringIO()):
            if not connected:
                with self.assertRaises(RuntimeError):
                    launch.main()
                start.assert_not_called()
                browser.assert_not_called()
                return
            launch.main()
            browser.assert_called_once_with(
                ["/usr/bin/open", "https://a414.example.ts.net:8443"], check=True)
            if local:
                start.assert_called_once()
                self.assertIn(unittest.mock.call(
                    ["tailscale", "serve", "--bg", "--https=8443", launch.LOCAL],
                    timeout=45), run.call_args_list)
            else:
                start.assert_not_called()
                self.assertEqual(run.call_count, 1)

    def test_host_starts_and_opens(self):
        self.exercise_launch(local=True)

    def test_other_mac_only_opens_host(self):
        self.exercise_launch(local=False)

    def test_disconnected_tailnet_stops_launch(self):
        self.exercise_launch(local=True, connected=False)


class ServerTests(unittest.TestCase):
    def test_rapid_saves_have_distinct_revisions_and_reject_stale_write(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with patch.multiple(todo, HERE=folder, DATA=folder / "data.json",
                                BACKUPS=folder / "backups", _last_backup=0.0):
                todo.save_data({"tasks": []})
                server = todo.ThreadingHTTPServer(("127.0.0.1", 0), todo.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                url = f"http://127.0.0.1:{server.server_port}"
                def get(path):
                    with urlopen(url + path) as response:
                        return json.load(response)
                def put(base):
                    request = Request(url + "/api/data", method="PUT",
                                      data=b'{"tasks": []}',
                                      headers={"Content-Type": "application/json",
                                               "X-Base-Updated": base})
                    with urlopen(request) as response:
                        return json.load(response)["updated"]
                try:
                    info = get("/api/health")
                    self.assertEqual(info["app"], "todo")
                    self.assertEqual(info["directory"], str(folder))
                    first = get("/api/data")["updated"]
                    second = put(first)
                    third = put(second)
                    self.assertEqual(len({first, second, third}), 3)
                    with self.assertRaises(HTTPError) as caught:
                        put(second)
                    self.assertEqual(caught.exception.code, 409)
                    self.assertEqual(get("/api/data")["updated"], third)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()


if __name__ == "__main__":
    unittest.main()
